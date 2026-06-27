from __future__ import annotations

import base64
import importlib
import logging
import math
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.models import PodReading, TelemetryEvent

LOGGER = logging.getLogger(__name__)
METRIC_PREFIX = "senior_pomidor_"
PUBLIC_METRIC_FIELDS: tuple[str, ...] = (
    "soil_moisture_percent",
    "soil_temperature_c",
    "air_temperature_c",
    "air_humidity_percent",
    "air_pressure_hpa",
    "air_vpd_kpa",
    "light_lux",
    "leaf_temp_c",
    "leaf_vpd_kpa",
)
NON_EXPORTED_FLAT_FIELDS: tuple[str, ...] = (
    "adc_raw",
    "air_actual_vapor_pressure_kpa",
    "air_saturation_vapor_pressure_kpa",
    "ir_ambient_temp_c",
    "leaf_saturation_vapor_pressure_kpa",
)
MAX_LABEL_VALUE_LENGTH = 80
PRIVATE_LABEL_PATTERN = re.compile(r"[/\\]|(?:^|[^0-9])(?:\d{1,3}\.){3}\d{1,3}(?:[^0-9]|$)")
SAFE_LABEL_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


class ExporterConfigError(RuntimeError):
    pass


class RemoteWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetricSample:
    name: str
    labels: dict[str, str]
    value: float
    timestamp_ms: int


@dataclass(frozen=True)
class ExportRow:
    reading_id: int
    timestamp_utc: datetime
    device_id: str
    pod_key: str
    enabled: bool
    adc_raw: float | None = None
    soil_moisture_percent: float | None = None
    soil_temperature_c: float | None = None
    air_temperature_c: float | None = None
    air_humidity_percent: float | None = None
    air_pressure_hpa: float | None = None
    air_actual_vapor_pressure_kpa: float | None = None
    air_saturation_vapor_pressure_kpa: float | None = None
    air_vpd_kpa: float | None = None
    light_lux: float | None = None
    ir_ambient_temp_c: float | None = None
    leaf_temp_c: float | None = None
    leaf_saturation_vapor_pressure_kpa: float | None = None
    leaf_vpd_kpa: float | None = None
    metrics_jsonb: dict | None = None


@dataclass
class ExportState:
    since: datetime
    last_reading_id: int = 0

    @classmethod
    def initial(cls, now: datetime, lookback_minutes: int) -> ExportState:
        return cls(since=as_utc(now) - timedelta(minutes=lookback_minutes))


@dataclass(frozen=True)
class ExportResult:
    sent_samples: int
    plant_samples: int = 0
    freshness_samples: int = 0
    skipped_reason: str | None = None
    max_source_timestamp: datetime | None = None
    max_source_reading_id: int | None = None


class RemoteWriteSender(Protocol):
    def send(self, samples: list[MetricSample]) -> None:
        pass


class Compressor(Protocol):
    def compress(self, payload: bytes) -> bytes:
        pass


class UrlOpenResponse(Protocol):
    status: int

    def __enter__(self) -> UrlOpenResponse:
        pass

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        pass


class UrlOpener(Protocol):
    def open(self, request: urllib.request.Request, timeout: float) -> UrlOpenResponse:
        pass


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def timestamp_ms(value: datetime) -> int:
    return int(as_utc(value).timestamp() * 1000)


def sanitize_label_value(value: object) -> str:
    text = str(value).strip()
    if not text:
        return "unknown"
    if PRIVATE_LABEL_PATTERN.search(text):
        return "redacted"
    sanitized = SAFE_LABEL_CHARS.sub("_", text)
    sanitized = sanitized.strip("._-")
    if not sanitized:
        return "unknown"
    return sanitized[:MAX_LABEL_VALUE_LENGTH]


def public_labels(device_id: object, pod_key: object) -> dict[str, str]:
    return {
        "device_id": sanitize_label_value(device_id),
        "pod_key": sanitize_label_value(pod_key),
    }


def _metric_name(field_name: str) -> str:
    return f"{METRIC_PREFIX}{field_name}"


def _numeric_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def row_to_metric_samples(row: ExportRow) -> list[MetricSample]:
    if not row.enabled:
        LOGGER.debug(
            "Skipping disabled pod for Grafana Cloud export: device_id=%s pod_key=%s",
            row.device_id,
            row.pod_key,
        )
        return []

    dropped = non_exported_fields(row)
    if dropped:
        LOGGER.debug(
            "Dropping non-public telemetry fields for Grafana Cloud export: device_id=%s pod_key=%s fields=%s",
            row.device_id,
            row.pod_key,
            ",".join(dropped),
        )

    labels = public_labels(row.device_id, row.pod_key)
    sample_timestamp_ms = timestamp_ms(row.timestamp_utc)
    samples: list[MetricSample] = []
    for field_name in PUBLIC_METRIC_FIELDS:
        value = _numeric_or_none(getattr(row, field_name))
        if value is None:
            continue
        samples.append(
            MetricSample(
                name=_metric_name(field_name),
                labels=labels,
                value=value,
                timestamp_ms=sample_timestamp_ms,
            )
        )
    return samples


def freshness_sample(row: ExportRow, exported_at: datetime) -> MetricSample | None:
    if not row.enabled:
        return None
    age_seconds = max(0.0, (as_utc(exported_at) - as_utc(row.timestamp_utc)).total_seconds())
    return MetricSample(
        name=f"{METRIC_PREFIX}telemetry_freshness_seconds",
        labels=public_labels(row.device_id, row.pod_key),
        value=age_seconds,
        timestamp_ms=timestamp_ms(exported_at),
    )


def non_exported_fields(row: ExportRow) -> list[str]:
    fields = [
        field_name for field_name in NON_EXPORTED_FLAT_FIELDS if _numeric_or_none(getattr(row, field_name)) is not None
    ]
    if row.metrics_jsonb:
        fields.extend(sorted(str(key) for key in row.metrics_jsonb))
    return fields


def _row_from_orm(reading: PodReading, timestamp_utc: datetime) -> ExportRow:
    return ExportRow(
        reading_id=reading.id,
        timestamp_utc=timestamp_utc,
        device_id=reading.device_id,
        pod_key=reading.pod_key,
        enabled=reading.enabled,
        adc_raw=reading.adc_raw,
        soil_moisture_percent=reading.soil_moisture_percent,
        soil_temperature_c=reading.soil_temperature_c,
        air_temperature_c=reading.air_temperature_c,
        air_humidity_percent=reading.air_humidity_percent,
        air_pressure_hpa=reading.air_pressure_hpa,
        air_actual_vapor_pressure_kpa=reading.air_actual_vapor_pressure_kpa,
        air_saturation_vapor_pressure_kpa=reading.air_saturation_vapor_pressure_kpa,
        air_vpd_kpa=reading.air_vpd_kpa,
        light_lux=reading.light_lux,
        ir_ambient_temp_c=reading.ir_ambient_temp_c,
        leaf_temp_c=reading.leaf_temp_c,
        leaf_saturation_vapor_pressure_kpa=reading.leaf_saturation_vapor_pressure_kpa,
        leaf_vpd_kpa=reading.leaf_vpd_kpa,
        metrics_jsonb=reading.metrics_jsonb,
    )


def fetch_export_rows(db: Session, since: datetime, until: datetime, last_reading_id: int = 0) -> list[ExportRow]:
    since_utc = as_utc(since)
    statement = (
        select(PodReading, TelemetryEvent.timestamp_utc)
        .join(TelemetryEvent, PodReading.telemetry_event_id == TelemetryEvent.id)
        .where(
            or_(
                TelemetryEvent.timestamp_utc > since_utc,
                (TelemetryEvent.timestamp_utc == since_utc) & (PodReading.id > last_reading_id),
            )
        )
        .where(TelemetryEvent.timestamp_utc <= as_utc(until))
        .order_by(TelemetryEvent.timestamp_utc, PodReading.id)
    )
    return [_row_from_orm(reading, event_timestamp) for reading, event_timestamp in db.execute(statement).all()]


def fetch_latest_rows_by_pod(db: Session, until: datetime) -> list[ExportRow]:
    statement = (
        select(PodReading, TelemetryEvent.timestamp_utc)
        .join(TelemetryEvent, PodReading.telemetry_event_id == TelemetryEvent.id)
        .where(TelemetryEvent.timestamp_utc <= as_utc(until))
        .order_by(TelemetryEvent.timestamp_utc.desc(), PodReading.id.desc())
    )
    latest: dict[tuple[str, str], ExportRow] = {}
    for reading, event_timestamp in db.execute(statement).all():
        key = (reading.device_id, reading.pod_key)
        if key not in latest:
            latest[key] = _row_from_orm(reading, event_timestamp)
    return list(latest.values())


def validate_export_settings(export_settings: Settings) -> None:
    if not export_settings.grafana_cloud_export_enabled:
        return

    missing = [
        name
        for name, value in (
            ("GRAFANA_CLOUD_REMOTE_WRITE_URL", export_settings.grafana_cloud_remote_write_url),
            ("GRAFANA_CLOUD_INSTANCE_ID", export_settings.grafana_cloud_instance_id),
            ("GRAFANA_CLOUD_API_TOKEN", export_settings.grafana_cloud_api_token),
        )
        if not value
    ]
    if missing:
        raise ExporterConfigError(
            "Grafana Cloud export is enabled but required settings are missing: " + ", ".join(missing)
        )


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _key(field_number: int, wire_type: int) -> bytes:
    return _varint((field_number << 3) | wire_type)


def _length_delimited(field_number: int, payload: bytes) -> bytes:
    return _key(field_number, 2) + _varint(len(payload)) + payload


def _string_field(field_number: int, value: str) -> bytes:
    return _length_delimited(field_number, value.encode("utf-8"))


def _double_field(field_number: int, value: float) -> bytes:
    return _key(field_number, 1) + struct.pack("<d", value)


def _int64_field(field_number: int, value: int) -> bytes:
    return _key(field_number, 0) + _varint(value)


def _encode_label(name: str, value: str) -> bytes:
    return _string_field(1, name) + _string_field(2, value)


def _encode_sample(sample: MetricSample) -> bytes:
    return _double_field(1, sample.value) + _int64_field(2, sample.timestamp_ms)


def _encode_time_series(sample: MetricSample) -> bytes:
    labels = {"__name__": sample.name, **sample.labels}
    payload = b"".join(_length_delimited(1, _encode_label(name, labels[name])) for name in sorted(labels))
    payload += _length_delimited(2, _encode_sample(sample))
    return payload


def encode_write_request(samples: list[MetricSample]) -> bytes:
    return b"".join(_length_delimited(1, _encode_time_series(sample)) for sample in samples)


class RemoteWriteTransport:
    def __init__(
        self,
        *,
        url: str,
        instance_id: str,
        api_token: str,
        timeout_seconds: float = 10.0,
        compressor: Compressor | None = None,
        opener: UrlOpener | None = None,
    ) -> None:
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ExporterConfigError("Grafana Cloud remote write URL must be an HTTP(S) URL")
        self.url = url
        self.instance_id = instance_id
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds
        self._compressor = compressor
        self._opener = opener or urllib.request.build_opener()

    def _compress(self, payload: bytes) -> bytes:
        if self._compressor is not None:
            return self._compressor.compress(payload)
        try:
            snappy = importlib.import_module("snappy")
        except ImportError as exc:
            raise ExporterConfigError("python-snappy is required for Grafana Cloud remote write export") from exc
        return cast(Compressor, snappy).compress(payload)

    def send(self, samples: list[MetricSample]) -> None:
        if not samples:
            return

        payload = self._compress(encode_write_request(samples))
        credentials = f"{self.instance_id}:{self.api_token}".encode()
        request = urllib.request.Request(  # noqa: S310 - URL scheme is validated in __init__.
            self.url,
            data=payload,
            headers={
                "Authorization": f"Basic {base64.b64encode(credentials).decode('ascii')}",
                "Content-Encoding": "snappy",
                "Content-Type": "application/x-protobuf",
                "User-Agent": "senior-pomidor-server/0.1",
                "X-Prometheus-Remote-Write-Version": "0.1.0",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status < 200 or response.status >= 300:
                    raise RemoteWriteError(f"Grafana Cloud remote write returned HTTP {response.status}")
        except OSError as exc:
            raise RemoteWriteError(f"Grafana Cloud remote write failed: {exc}") from exc


def build_transport(export_settings: Settings) -> RemoteWriteTransport:
    validate_export_settings(export_settings)
    if (
        export_settings.grafana_cloud_remote_write_url is None
        or export_settings.grafana_cloud_instance_id is None
        or export_settings.grafana_cloud_api_token is None
    ):
        raise ExporterConfigError("Grafana Cloud remote write transport cannot be built without credentials")
    return RemoteWriteTransport(
        url=export_settings.grafana_cloud_remote_write_url,
        instance_id=export_settings.grafana_cloud_instance_id,
        api_token=export_settings.grafana_cloud_api_token,
    )


def export_once(
    db: Session,
    export_settings: Settings,
    state: ExportState,
    *,
    transport: RemoteWriteSender | None = None,
    now: datetime | None = None,
) -> ExportResult:
    if not export_settings.grafana_cloud_export_enabled:
        LOGGER.info("Grafana Cloud export is disabled")
        return ExportResult(sent_samples=0, skipped_reason="disabled")

    validate_export_settings(export_settings)
    exporter_transport = transport or build_transport(export_settings)
    exported_at = as_utc(now or datetime.now(UTC))
    rows = fetch_export_rows(db, state.since, exported_at, state.last_reading_id)
    plant_samples = [sample for row in rows for sample in row_to_metric_samples(row)]
    freshness_samples = [
        sample
        for row in fetch_latest_rows_by_pod(db, exported_at)
        if (sample := freshness_sample(row, exported_at)) is not None
    ]
    samples = plant_samples + freshness_samples
    exporter_transport.send(samples)

    max_source_timestamp = max((as_utc(row.timestamp_utc) for row in rows), default=None)
    if max_source_timestamp is not None:
        state.since = max_source_timestamp
        state.last_reading_id = max(row.reading_id for row in rows if as_utc(row.timestamp_utc) == max_source_timestamp)

    LOGGER.info(
        "Exported %s Grafana Cloud samples: plant=%s freshness=%s",
        len(samples),
        len(plant_samples),
        len(freshness_samples),
    )
    return ExportResult(
        sent_samples=len(samples),
        plant_samples=len(plant_samples),
        freshness_samples=len(freshness_samples),
        max_source_timestamp=max_source_timestamp,
        max_source_reading_id=state.last_reading_id if max_source_timestamp is not None else None,
    )


def run_forever() -> None:
    configure_logging()
    if not settings.grafana_cloud_export_enabled:
        LOGGER.info("Grafana Cloud export is disabled; exiting")
        return

    validate_export_settings(settings)
    state = ExportState.initial(datetime.now(UTC), settings.grafana_cloud_export_lookback_minutes)
    transport = build_transport(settings)
    while True:
        try:
            with SessionLocal() as db:
                export_once(db, settings, state, transport=transport)
        except RemoteWriteError:
            LOGGER.exception("Grafana Cloud export attempt failed; retrying on next interval")
        except Exception:
            LOGGER.exception("Unexpected Grafana Cloud export attempt failure; retrying on next interval")
        time.sleep(settings.grafana_cloud_export_interval_seconds)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
