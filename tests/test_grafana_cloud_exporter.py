import urllib.request
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.grafana_cloud_exporter import (
    ExporterConfigError,
    ExportRow,
    ExportState,
    MetricSample,
    RemoteWriteTransport,
    encode_write_request,
    export_once,
    public_labels,
    row_to_metric_samples,
    sanitize_label_value,
    validate_export_settings,
)
from app.models import Base
from app.services import persist_telemetry
from app.validation import TELEMETRY_SCHEMA


class RecordingTransport:
    def __init__(self) -> None:
        self.samples: list[MetricSample] = []

    def send(self, samples: list[MetricSample]) -> None:
        self.samples.extend(samples)


class FailingTransport:
    def send(self, samples: list[MetricSample]) -> None:
        raise AssertionError("transport should not be called")


class FakeCompressor:
    def compress(self, payload: bytes) -> bytes:
        return b"snappy:" + payload


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class FakeOpener:
    def __init__(self) -> None:
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return FakeResponse()


def sample_row(**overrides) -> ExportRow:
    values = {
        "reading_id": 1,
        "timestamp_utc": datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        "device_id": "pi-001",
        "pod_key": "pod-1",
        "enabled": True,
        "adc_raw": 511.0,
        "soil_moisture_percent": 42.5,
        "soil_temperature_c": 20.1,
        "air_temperature_c": 21.2,
        "air_humidity_percent": 58.0,
        "air_pressure_hpa": 1008.5,
        "light_lux": 1234.0,
        "ir_ambient_temp_c": 19.8,
        "leaf_temp_c": 18.7,
        "metrics_jsonb": {"battery_mv": 5010.0, "sensor_error_message": "private"},
    }
    values.update(overrides)
    return ExportRow(**values)


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, SessionLocal()


def telemetry_payload(timestamp: str, *, enabled: bool = True, moisture: float | None = 42.5) -> dict:
    pod = {
        "enabled": enabled,
        "soil_temperature_c": 20.1,
        "air_temperature_c": 21.2,
        "air_humidity_percent": 58.0,
        "air_pressure_hpa": 1008.5,
        "light_lux": 1234.0,
        "leaf_temp_c": 18.7,
        "battery_mv": 5010.0,
    }
    if moisture is not None:
        pod["soil_moisture_percent"] = moisture
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": timestamp,
        "pods": {"pod-1": pod},
        "system_health": {
            "rpi_core": {"cpu_temp_c": 80.0},
            "errors": [{"sensor": "wifi", "message": "do not export"}],
        },
    }


def enabled_settings(**overrides) -> Settings:
    values = {
        "grafana_cloud_export_enabled": True,
        "grafana_cloud_remote_write_url": "https://prometheus-prod.example/api/prom/push",
        "grafana_cloud_instance_id": "12345",
        "grafana_cloud_api_token": "secret-token",
    }
    values.update(overrides)
    return Settings(**values)


def test_row_to_metric_samples_exports_only_public_allowlisted_metrics():
    samples = row_to_metric_samples(sample_row())

    names = {sample.name for sample in samples}
    assert names == {
        "senior_pomidor_soil_moisture_percent",
        "senior_pomidor_soil_temperature_c",
        "senior_pomidor_air_temperature_c",
        "senior_pomidor_air_humidity_percent",
        "senior_pomidor_air_pressure_hpa",
        "senior_pomidor_light_lux",
        "senior_pomidor_leaf_temp_c",
    }
    encoded = encode_write_request(samples)
    assert b"adc_raw" not in encoded
    assert b"ir_ambient_temp_c" not in encoded
    assert b"battery_mv" not in encoded
    assert b"sensor_error_message" not in encoded


def test_labels_are_limited_and_sanitized():
    labels = public_labels("senior-pomidor/pi-001/telemetry", "pod 1")

    assert labels == {"device_id": "redacted", "pod_key": "pod_1"}
    assert set(labels) == {"device_id", "pod_key"}
    assert sanitize_label_value("192.168.1.10") == "redacted"
    assert sanitize_label_value("x" * 120) == "x" * 80


def test_row_to_metric_samples_uses_row_timestamp_and_labels():
    samples = row_to_metric_samples(sample_row(soil_moisture_percent=41.0, leaf_temp_c=None))
    sample_by_name = {sample.name: sample for sample in samples}

    moisture = sample_by_name["senior_pomidor_soil_moisture_percent"]
    assert moisture.labels == {"device_id": "pi-001", "pod_key": "pod-1"}
    assert moisture.value == 41.0
    assert moisture.timestamp_ms == 1_780_833_600_000
    assert "senior_pomidor_leaf_temp_c" not in sample_by_name


def test_disabled_pods_and_null_metric_fields_are_not_exported():
    assert row_to_metric_samples(sample_row(enabled=False)) == []

    samples = row_to_metric_samples(
        sample_row(
            soil_moisture_percent=None,
            soil_temperature_c=None,
            air_temperature_c=None,
            air_humidity_percent=None,
            air_pressure_hpa=None,
            light_lux=None,
            leaf_temp_c=None,
        )
    )
    assert samples == []


def test_export_once_skips_when_disabled_without_requiring_cloud_config():
    engine, db = make_db()
    try:
        state = ExportState.initial(datetime(2026, 6, 7, 12, 0, tzinfo=UTC), lookback_minutes=10)
        result = export_once(
            db,
            Settings(grafana_cloud_export_enabled=False),
            state,
            transport=FailingTransport(),
            now=datetime(2026, 6, 7, 12, 1, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    assert result.skipped_reason == "disabled"
    assert result.sent_samples == 0


def test_enabled_export_requires_remote_write_config():
    with pytest.raises(ExporterConfigError, match="GRAFANA_CLOUD_API_TOKEN"):
        validate_export_settings(
            Settings(
                grafana_cloud_export_enabled=True,
                grafana_cloud_remote_write_url="https://example.test/push",
                grafana_cloud_instance_id="12345",
                grafana_cloud_api_token=None,
            )
        )


def test_export_once_reads_postgres_rows_sends_metrics_and_advances_state():
    engine, db = make_db()
    transport = RecordingTransport()
    try:
        persist_telemetry(db, telemetry_payload("2026-06-07T11:58:00Z"), source="mqtt")
        persist_telemetry(db, telemetry_payload("2026-06-07T12:00:30Z", moisture=None), source="mqtt")
        persist_telemetry(db, telemetry_payload("2026-06-07T12:01:00Z", enabled=False), source="mqtt")

        state = ExportState(since=datetime(2026, 6, 7, 12, 0, tzinfo=UTC))
        result = export_once(
            db,
            enabled_settings(),
            state,
            transport=transport,
            now=datetime(2026, 6, 7, 12, 2, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    names = {sample.name for sample in transport.samples}
    assert "senior_pomidor_soil_moisture_percent" not in names
    assert "senior_pomidor_soil_temperature_c" in names
    assert "senior_pomidor_telemetry_freshness_seconds" not in names
    assert result.plant_samples == 6
    assert result.freshness_samples == 0
    assert result.max_source_timestamp == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert result.max_source_reading_id is not None
    assert state.since == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert state.last_reading_id == result.max_source_reading_id


def test_export_once_does_not_skip_rows_inserted_later_at_checkpoint_timestamp():
    engine, db = make_db()
    first_transport = RecordingTransport()
    second_transport = RecordingTransport()
    try:
        persist_telemetry(db, telemetry_payload("2026-06-07T12:01:00Z", moisture=42.5), source="mqtt")
        state = ExportState(since=datetime(2026, 6, 7, 12, 0, tzinfo=UTC))

        first_result = export_once(
            db,
            enabled_settings(),
            state,
            transport=first_transport,
            now=datetime(2026, 6, 7, 12, 2, tzinfo=UTC),
        )

        late_payload = telemetry_payload("2026-06-07T12:01:00Z", moisture=35.0)
        late_payload["device_id"] = "pi-002"
        persist_telemetry(db, late_payload, source="mqtt")

        second_result = export_once(
            db,
            enabled_settings(),
            state,
            transport=second_transport,
            now=datetime(2026, 6, 7, 12, 3, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    assert first_result.max_source_timestamp == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert second_result.max_source_timestamp == datetime(2026, 6, 7, 12, 1, tzinfo=UTC)
    assert second_result.max_source_reading_id is not None
    assert second_result.max_source_reading_id > (first_result.max_source_reading_id or 0)
    late_moisture = [
        sample
        for sample in second_transport.samples
        if sample.name == "senior_pomidor_soil_moisture_percent" and sample.labels["device_id"] == "pi-002"
    ]
    assert len(late_moisture) == 1
    assert late_moisture[0].value == 35.0


def test_export_once_sends_freshness_for_latest_enabled_pod():
    engine, db = make_db()
    transport = RecordingTransport()
    try:
        persist_telemetry(db, telemetry_payload("2026-06-07T11:58:00Z"), source="mqtt")
        state = ExportState(since=datetime(2026, 6, 7, 12, 0, tzinfo=UTC))
        result = export_once(
            db,
            enabled_settings(),
            state,
            transport=transport,
            now=datetime(2026, 6, 7, 12, 2, tzinfo=UTC),
        )
    finally:
        db.close()
        engine.dispose()

    freshness = [sample for sample in transport.samples if sample.name == "senior_pomidor_telemetry_freshness_seconds"]
    assert len(freshness) == 1
    assert freshness[0].value == 240.0
    assert result.plant_samples == 0
    assert result.freshness_samples == 1


def test_remote_write_transport_posts_snappy_protobuf_with_basic_auth():
    opener = FakeOpener()
    transport = RemoteWriteTransport(
        url="https://prometheus-prod.example/api/prom/push",
        instance_id="12345",
        api_token="secret-token",
        compressor=FakeCompressor(),
        opener=opener,
    )

    transport.send(
        [
            MetricSample(
                name="senior_pomidor_soil_moisture_percent",
                labels={"device_id": "pi-001", "pod_key": "pod-1"},
                value=42.5,
                timestamp_ms=int((datetime(2026, 6, 7, 12, 0, tzinfo=UTC) + timedelta()).timestamp() * 1000),
            )
        ]
    )

    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == "https://prometheus-prod.example/api/prom/push"
    assert request.get_method() == "POST"
    assert timeout == 10.0
    assert request.headers["Authorization"] == "Basic MTIzNDU6c2VjcmV0LXRva2Vu"
    assert request.headers["Content-encoding"] == "snappy"
    assert request.headers["Content-type"] == "application/x-protobuf"
    payload = request.data
    assert isinstance(payload, bytes)
    assert payload.startswith(b"snappy:")
    assert b"senior_pomidor_soil_moisture_percent" in payload
    assert b"device_id" in payload
    assert b"pod_key" in payload
