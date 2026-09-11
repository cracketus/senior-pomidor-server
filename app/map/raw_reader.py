from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.map.raw_evidence import (
    MAX_HEALTH_FACTS_PER_EVENT,
    MAX_QUERY_ROWS,
    ChannelSelector,
    EvidenceFidelity,
    EvidenceKind,
    EvidenceMode,
    EvidenceReason,
    EvidenceValidity,
    HealthFact,
    ProfileIdentity,
    RawEvidenceBatch,
    RawEvidenceItem,
    RawEvidenceRequest,
    bounded_detail_digest,
    compute_evidence_digest,
)
from app.telemetry import normalize_system_health

logger = logging.getLogger(__name__)


class RawEvidenceErrorCode(StrEnum):
    QUERY_LIMIT_EXCEEDED = "QUERY_LIMIT_EXCEEDED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    UNSUPPORTED_BACKEND = "UNSUPPORTED_BACKEND"


class RawEvidenceReadError(RuntimeError):
    def __init__(self, code: RawEvidenceErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


RAW_EVIDENCE_SQL = """
WITH selectors AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:selectors AS jsonb)) AS s(
        source_id text,
        storage_device_id text,
        channel_id text,
        pod_key text,
        metric_name text,
        error_sensors jsonb
    )
), selected_sources AS (
    SELECT DISTINCT source_id, storage_device_id FROM selectors
), selected_pods AS (
    SELECT DISTINCT storage_device_id, pod_key FROM selectors
), base_events AS (
    SELECT e.*, ss.source_id
    FROM telemetry_events e
    JOIN selected_sources ss
      ON ss.storage_device_id = e.device_id
    WHERE e.received_at <= :receipt_cutoff
      AND (
        (e.timestamp_utc >= :coverage_start AND e.timestamp_utc < :window_end)
        OR e.timestamp_utc > :evaluation_time
      )
), raw_rows AS (
    SELECT
        'event'::text AS row_type,
        e.id AS row_id,
        e.id AS event_id,
        e.record_id,
        e.source_id,
        e.timestamp_utc AS observation_at,
        e.received_at,
        e.schema_version AS source_schema_version,
        NULL::text AS pod_key,
        NULL::boolean AS enabled,
        e.system_health_jsonb AS values_jsonb,
        NULL::text AS sensor,
        NULL::text AS error_detail
    FROM base_events e
    UNION ALL
    SELECT
        'reading'::text,
        r.id,
        e.id,
        e.record_id,
        e.source_id,
        e.timestamp_utc,
        e.received_at,
        e.schema_version,
        r.pod_key,
        r.enabled,
        jsonb_build_object(
            'adc_raw', r.adc_raw,
            'soil_moisture_percent', r.soil_moisture_percent,
            'soil_temperature_c', r.soil_temperature_c,
            'air_temperature_c', r.air_temperature_c,
            'air_humidity_percent', r.air_humidity_percent,
            'air_pressure_hpa', r.air_pressure_hpa,
            'air_actual_vapor_pressure_kpa', r.air_actual_vapor_pressure_kpa,
            'air_saturation_vapor_pressure_kpa', r.air_saturation_vapor_pressure_kpa,
            'air_vpd_kpa', r.air_vpd_kpa,
            'light_lux', r.light_lux,
            'ir_ambient_temp_c', r.ir_ambient_temp_c,
            'leaf_temp_c', r.leaf_temp_c,
            'leaf_saturation_vapor_pressure_kpa', r.leaf_saturation_vapor_pressure_kpa,
            'leaf_vpd_kpa', r.leaf_vpd_kpa
        ),
        NULL::text,
        NULL::text
    FROM pod_readings r
    JOIN base_events e ON e.id = r.telemetry_event_id
    JOIN selected_pods p ON p.storage_device_id = r.device_id AND p.pod_key = r.pod_key
    UNION ALL
    SELECT
        'error'::text,
        pe.id,
        e.id,
        e.record_id,
        e.source_id,
        e.timestamp_utc,
        e.received_at,
        e.schema_version,
        pe.pod_key,
        NULL::boolean,
        NULL::jsonb,
        pe.sensor,
        pe.message
    FROM pod_errors pe
    JOIN base_events e ON e.id = pe.telemetry_event_id
    JOIN selected_pods p ON p.storage_device_id = pe.device_id AND p.pod_key = pe.pod_key
    WHERE pe.sensor IS NULL OR EXISTS (
        SELECT 1 FROM selectors s
        WHERE s.storage_device_id = pe.device_id
          AND s.pod_key = pe.pod_key
          AND s.error_sensors ? pe.sensor
    )
)
SELECT * FROM raw_rows
ORDER BY observation_at, received_at, event_id, row_type, row_id
LIMIT 100001
"""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("database and clock timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _event_identity(row: Mapping[str, Any]) -> tuple[str, str | None]:
    record_id = row.get("record_id")
    if isinstance(record_id, str) and record_id:
        return f"record:{record_id}", record_id
    return f"legacy:{row['source_id']}:event:{row['event_id']}", None


def _health_facts(value: Any) -> tuple[HealthFact, ...]:
    normalized = normalize_system_health({"system_health": value}) if isinstance(value, dict) else None
    if not normalized:
        return ()
    facts: list[HealthFact] = []

    def walk(path: str, item: Any) -> None:
        if len(facts) >= MAX_HEALTH_FACTS_PER_EVENT:
            return
        if isinstance(item, dict):
            for key in sorted(item):
                walk(f"{path}.{key}" if path else key, item[key])
            return
        if isinstance(item, list):
            for index, child in enumerate(item[:32]):
                if isinstance(child, dict) and "message" in child:
                    sensor = child.get("sensor")
                    sensor_name = sensor if isinstance(sensor, str) and sensor else "unknown"
                    facts.append(
                        HealthFact(
                            path=f"{path}.{index}.{sensor_name}"[:256],
                            validity=EvidenceValidity.INVALID,
                            warning_level="warning",
                            detail_digest=bounded_detail_digest(str(child["message"])),
                        )
                    )
                else:
                    walk(f"{path}.{index}", child)
            return
        if isinstance(item, bool | int | str) or item is None:
            facts.append(HealthFact(path=path[:256], value=item))
        elif isinstance(item, float):
            if math.isfinite(item):
                facts.append(HealthFact(path=path[:256], value=0.0 if item == 0 else item))
            else:
                facts.append(HealthFact(path=path[:256], validity=EvidenceValidity.INVALID))

    walk("system_health", normalized)
    return tuple(facts)


def _base_item(row: Mapping[str, Any], *, kind: EvidenceKind, child_identity: str, **values: Any) -> RawEvidenceItem:
    event_identity, record_id = _event_identity(row)
    observation_at = _as_utc(row["observation_at"])
    received_at = _as_utc(row["received_at"])
    return RawEvidenceItem(
        observation_at=observation_at,
        received_at=received_at,
        event_identity=event_identity,
        record_id=record_id,
        evidence_kind=kind,
        child_identity=child_identity,
        source_id=row["source_id"],
        source_schema_version=row["source_schema_version"],
        **values,
    )


def _reading_items(
    row: Mapping[str, Any],
    selectors_by_pod: Mapping[tuple[str, str], tuple[ChannelSelector, ...]],
    evaluation_time: datetime,
) -> list[RawEvidenceItem]:
    selectors = selectors_by_pod.get((row["source_id"], row["pod_key"]), ())
    stored_values = row.get("values_jsonb")
    values = stored_values if isinstance(stored_values, dict) else {}
    result: list[RawEvidenceItem] = []
    for selector in selectors:
        observation_at = _as_utc(row["observation_at"])
        if not selector.effective_interval.contains(observation_at):
            continue
        common = {
            "channel_id": selector.channel_id,
            "pod_key": selector.pod_key,
            "metric_name": selector.metric_name,
            "unit": selector.unit,
        }
        child_identity = f"reading:{row['row_id']}:{selector.metric_name.value}"
        if row.get("enabled") is False:
            result.append(
                _base_item(
                    row,
                    kind=EvidenceKind.DISABLED_CHANNEL,
                    child_identity=child_identity,
                    validity=EvidenceValidity.INVALID,
                    reason=EvidenceReason.DISABLED,
                    **common,
                )
            )
            continue
        value = values.get(selector.metric_name.value)
        if value is None:
            continue
        if observation_at > evaluation_time:
            validity = EvidenceValidity.CLOCK_INVALID
            reason = EvidenceReason.CLOCK_INVALID
            normalized_value = (
                float(value)
                if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
                else None
            )
        elif isinstance(value, bool) or not isinstance(value, int | float):
            validity = EvidenceValidity.INVALID
            reason = EvidenceReason.INVALID_TYPE
            normalized_value = None
        elif not math.isfinite(float(value)):
            validity = EvidenceValidity.INVALID
            reason = EvidenceReason.NON_FINITE
            normalized_value = None
        elif not selector.minimum <= float(value) <= selector.maximum:
            validity = EvidenceValidity.INVALID
            reason = EvidenceReason.OUT_OF_RANGE
            normalized_value = float(value)
        else:
            validity = EvidenceValidity.VALID
            reason = None
            normalized_value = 0.0 if float(value) == 0 else float(value)
        result.append(
            _base_item(
                row,
                kind=EvidenceKind.CHANNEL_VALUE
                if validity == EvidenceValidity.VALID
                else EvidenceKind.CHANNEL_INVALID_VALUE,
                child_identity=child_identity,
                value=normalized_value,
                validity=validity,
                reason=reason,
                **common,
            )
        )
    return result


def _error_items(
    row: Mapping[str, Any],
    selectors_by_pod: Mapping[tuple[str, str], tuple[ChannelSelector, ...]],
    evaluation_time: datetime,
) -> list[RawEvidenceItem]:
    selectors = selectors_by_pod.get((row["source_id"], row["pod_key"]), ())
    sensor = row.get("sensor")
    bounded_sensor = sensor[:128] if isinstance(sensor, str) and sensor else None
    detail_digest = bounded_detail_digest(str(row.get("error_detail", "")))
    result: list[RawEvidenceItem] = []
    for selector in selectors:
        observation_at = _as_utc(row["observation_at"])
        if not selector.effective_interval.contains(observation_at):
            continue
        if bounded_sensor is not None and bounded_sensor not in selector.error_sensors:
            continue
        clock_invalid = observation_at > evaluation_time
        result.append(
            _base_item(
                row,
                kind=EvidenceKind.EXPLICIT_ERROR,
                child_identity=f"error:{row['row_id']}:{selector.channel_id}",
                channel_id=selector.channel_id,
                pod_key=selector.pod_key,
                metric_name=selector.metric_name,
                unit=selector.unit,
                validity=EvidenceValidity.CLOCK_INVALID if clock_invalid else EvidenceValidity.INVALID,
                reason=EvidenceReason.CLOCK_INVALID if clock_invalid else EvidenceReason.EXPLICIT_ERROR,
                sensor=bounded_sensor,
                detail_digest=detail_digest,
            )
        )
    return result


def normalize_evidence_rows(
    request: RawEvidenceRequest,
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_time: datetime,
    data_cutoff: datetime,
) -> RawEvidenceBatch:
    evaluation_time = _as_utc(evaluation_time)
    data_cutoff = _as_utc(data_cutoff)
    row_list = list(rows)
    if len(row_list) > MAX_QUERY_ROWS:
        raise RawEvidenceReadError(RawEvidenceErrorCode.QUERY_LIMIT_EXCEEDED)
    selectors_by_pod: dict[tuple[str, str], tuple[ChannelSelector, ...]] = {}
    for selector in request.selectors:
        key = (selector.source_id, selector.pod_key)
        selectors_by_pod[key] = (*selectors_by_pod.get(key, ()), selector)

    candidates: list[RawEvidenceItem] = []
    for row in row_list:
        row_type = row["row_type"]
        if row_type == "event":
            candidates.append(
                _base_item(
                    row,
                    kind=EvidenceKind.SOURCE_RECEIPT,
                    child_identity="event",
                    validity=(
                        EvidenceValidity.CLOCK_INVALID
                        if _as_utc(row["observation_at"]) > evaluation_time
                        else EvidenceValidity.VALID
                    ),
                    reason=(EvidenceReason.CLOCK_INVALID if _as_utc(row["observation_at"]) > evaluation_time else None),
                    health_facts=_health_facts(row.get("values_jsonb")),
                )
            )
        elif row_type == "reading":
            candidates.extend(_reading_items(row, selectors_by_pod, evaluation_time))
        elif row_type == "error":
            candidates.extend(_error_items(row, selectors_by_pod, evaluation_time))
        else:
            raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE)

    # Keep every in-window/future-invalid fact, but only the latest relevant pre-window
    # channel fact as lookback seed. Source receipts are retained for omission evidence.
    seed_by_channel: dict[str, RawEvidenceItem] = {}
    selectors_by_channel = {selector.channel_id: selector for selector in request.selectors}
    selected: list[RawEvidenceItem] = []
    for item in candidates:
        if item.evidence_kind == EvidenceKind.SOURCE_RECEIPT or item.observation_at >= request.window_start:
            selected.append(item)
        elif item.channel_id is not None:
            selector = selectors_by_channel[item.channel_id]
            if item.observation_at < request.window_start - timedelta(seconds=selector.max_age_seconds):
                continue
            previous = seed_by_channel.get(item.channel_id)
            if previous is None or _sort_key(previous) < _sort_key(item):
                seed_by_channel[item.channel_id] = item
    selected.extend(seed_by_channel.values())

    unique: dict[tuple[str, str, str], RawEvidenceItem] = {}
    for item in selected:
        unique[(item.event_identity, item.evidence_kind.value, item.child_identity)] = item
    items = tuple(sorted(unique.values(), key=_sort_key))
    coverage_start = (
        min(request.window_start - timedelta(seconds=selector.max_age_seconds) for selector in request.selectors)
        if request.selectors
        else request.window_start
    )
    profiles = tuple(
        ProfileIdentity(profile_id=profile_id, version=version)
        for profile_id, version in sorted({(item.profile_id, item.profile_version) for item in request.selectors})
    )
    provisional = RawEvidenceBatch(
        mode=request.mode,
        window_start=request.window_start,
        window_end=request.window_end,
        evaluation_time=evaluation_time,
        data_cutoff=data_cutoff,
        coverage_start=coverage_start,
        coverage_end=request.window_end,
        topology_revision_id=request.topology_revision_id,
        topology_digest=request.topology_digest,
        profile_identities=profiles,
        fidelity=EvidenceFidelity.INGEST_TIME_PROXY,
        row_count=len(row_list),
        items=items,
        digest="0" * 64,
    )
    return provisional.model_copy(update={"digest": compute_evidence_digest(provisional)})


def _sort_key(item: RawEvidenceItem) -> tuple[datetime, datetime, str, str, str]:
    return (
        item.observation_at,
        item.received_at,
        item.event_identity,
        item.evidence_kind.value,
        item.child_identity,
    )


class RawEvidenceReader:
    def __init__(self, engine: Engine, *, clock: Callable[[], datetime]) -> None:
        self._engine = engine
        self._clock = clock

    def read(self, request: RawEvidenceRequest) -> RawEvidenceBatch:
        started = time.monotonic()
        result_code = "COMPLETE"
        row_count = 0
        batch: RawEvidenceBatch | None = None
        if self._engine.dialect.name != "postgresql":
            self._log(request, started, RawEvidenceErrorCode.UNSUPPORTED_BACKEND.value, 0, None)
            raise RawEvidenceReadError(RawEvidenceErrorCode.UNSUPPORTED_BACKEND)
        evaluation_time = _as_utc(self._clock())
        if evaluation_time < request.window_end:
            raise ValueError("evaluation clock must not precede window_end")
        data_cutoff = request.data_cutoff or evaluation_time
        if data_cutoff > evaluation_time:
            raise ValueError("data_cutoff must not be in the future relative to the evaluation clock")
        receipt_cutoff = (
            request.receipt_cutoff
            if request.mode == EvidenceMode.AS_KNOWN_CORE and request.receipt_cutoff is not None
            else min(data_cutoff, request.window_end)
            if request.mode == EvidenceMode.AS_KNOWN_CORE
            else data_cutoff
        )
        coverage_start = (
            min(request.window_start - timedelta(seconds=selector.max_age_seconds) for selector in request.selectors)
            if request.selectors
            else request.window_start
        )
        selector_json = json.dumps(
            [
                {
                    "source_id": item.source_id,
                    "storage_device_id": item.storage_device_id,
                    "channel_id": item.channel_id,
                    "pod_key": item.pod_key,
                    "metric_name": item.metric_name.value,
                    "error_sensors": list(item.error_sensors),
                }
                for item in request.selectors
            ],
            separators=(",", ":"),
        )
        try:
            with self._engine.connect() as connection:
                transaction = connection.begin()
                try:
                    rows = self._extract_rows(
                        connection,
                        selector_json=selector_json,
                        receipt_cutoff=receipt_cutoff,
                        coverage_start=coverage_start,
                        window_end=request.window_end,
                        evaluation_time=evaluation_time,
                    )
                finally:
                    transaction.rollback()
            row_count = len(rows)
            batch = normalize_evidence_rows(
                request,
                cast(Iterable[Mapping[str, Any]], rows),
                evaluation_time=evaluation_time,
                data_cutoff=data_cutoff,
            )
        except RawEvidenceReadError as exc:
            result_code = exc.code.value
            raise
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            code = (
                RawEvidenceErrorCode.QUERY_TIMEOUT if sqlstate == "57014" else RawEvidenceErrorCode.BACKEND_UNAVAILABLE
            )
            result_code = code.value
            raise RawEvidenceReadError(code) from None
        except SQLAlchemyError:
            result_code = RawEvidenceErrorCode.BACKEND_UNAVAILABLE.value
            raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE) from None
        except (KeyError, TypeError, ValueError):
            result_code = RawEvidenceErrorCode.BACKEND_UNAVAILABLE.value
            raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE) from None
        finally:
            self._log(
                request, started, result_code, batch.row_count if batch else row_count, batch.digest if batch else None
            )
        return batch

    def read_many(self, requests: tuple[RawEvidenceRequest, ...]) -> tuple[RawEvidenceBatch, ...]:
        """Read bounded segments from one repeatable-read, read-only transaction."""
        if not requests:
            return ()
        if self._engine.dialect.name != "postgresql":
            raise RawEvidenceReadError(RawEvidenceErrorCode.UNSUPPORTED_BACKEND)
        evaluation_time = _as_utc(self._clock())
        cutoff = requests[0].data_cutoff or evaluation_time
        if any((request.data_cutoff or evaluation_time) != cutoff for request in requests):
            raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE)
        batches: list[RawEvidenceBatch] = []
        aggregate_rows = 0
        try:
            with self._engine.connect() as connection:
                transaction = connection.begin()
                try:
                    for index, request in enumerate(requests):
                        if evaluation_time < request.window_end or cutoff > evaluation_time:
                            raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE)
                        receipt_cutoff = (
                            request.receipt_cutoff
                            if request.mode == EvidenceMode.AS_KNOWN_CORE and request.receipt_cutoff is not None
                            else min(cutoff, request.window_end)
                            if request.mode == EvidenceMode.AS_KNOWN_CORE
                            else cutoff
                        )
                        coverage_start = (
                            min(
                                request.window_start - timedelta(seconds=selector.max_age_seconds)
                                for selector in request.selectors
                            )
                            if request.selectors
                            else request.window_start
                        )
                        selector_json = json.dumps(
                            [
                                {
                                    "source_id": item.source_id,
                                    "storage_device_id": item.storage_device_id,
                                    "channel_id": item.channel_id,
                                    "pod_key": item.pod_key,
                                    "metric_name": item.metric_name.value,
                                    "error_sensors": list(item.error_sensors),
                                }
                                for item in request.selectors
                            ],
                            separators=(",", ":"),
                        )
                        rows = self._extract_rows(
                            connection,
                            selector_json=selector_json,
                            receipt_cutoff=receipt_cutoff,
                            coverage_start=coverage_start,
                            window_end=request.window_end,
                            evaluation_time=evaluation_time,
                            configure=index == 0,
                        )
                        aggregate_rows += len(rows)
                        if aggregate_rows > MAX_QUERY_ROWS:
                            raise RawEvidenceReadError(RawEvidenceErrorCode.QUERY_LIMIT_EXCEEDED)
                        batches.append(
                            normalize_evidence_rows(
                                request,
                                cast(Iterable[Mapping[str, Any]], rows),
                                evaluation_time=evaluation_time,
                                data_cutoff=cutoff,
                            )
                        )
                finally:
                    transaction.rollback()
        except RawEvidenceReadError:
            raise
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            code = (
                RawEvidenceErrorCode.QUERY_TIMEOUT if sqlstate == "57014" else RawEvidenceErrorCode.BACKEND_UNAVAILABLE
            )
            raise RawEvidenceReadError(code) from None
        except SQLAlchemyError:
            raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE) from None
        return tuple(batches)

    @staticmethod
    def _extract_rows(
        connection: Any,
        *,
        selector_json: str,
        receipt_cutoff: datetime,
        coverage_start: datetime,
        window_end: datetime,
        evaluation_time: datetime,
        configure: bool = True,
    ) -> Any:
        if configure:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            settings = (
                connection.execute(
                    text(
                        "SELECT current_setting('transaction_isolation') AS isolation, "
                        "current_setting('transaction_read_only') AS read_only, "
                        "current_setting('statement_timeout') AS statement_timeout"
                    )
                )
                .mappings()
                .one()
            )
            if dict(settings) != {
                "isolation": "repeatable read",
                "read_only": "on",
                "statement_timeout": "5s",
            }:
                raise RawEvidenceReadError(RawEvidenceErrorCode.BACKEND_UNAVAILABLE)
        return (
            connection.execute(
                text(RAW_EVIDENCE_SQL),
                {
                    "selectors": selector_json,
                    "receipt_cutoff": receipt_cutoff,
                    "coverage_start": coverage_start,
                    "window_end": window_end,
                    "evaluation_time": evaluation_time,
                },
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _log(request: RawEvidenceRequest, started: float, result_code: str, row_count: int, digest: str | None) -> None:
        logger.info(
            "map_raw_reader mode=%s source_count=%s row_count=%s elapsed_ms=%s result_code=%s digest=%s",
            request.mode.value,
            len({item.source_id for item in request.selectors}),
            min(row_count, MAX_QUERY_ROWS + 1),
            max(0, round((time.monotonic() - started) * 1000)),
            result_code,
            digest,
        )
