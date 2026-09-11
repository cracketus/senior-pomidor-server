from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import case, desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models import AnomalyRecord, Device, Photo, PodReading, StateSnapshot, TelemetryEvent
from app.operator_edge_reliability import (
    EdgeApplicationReliability,
    EdgeReliabilityFreshness,
    EdgeReliabilityReason,
    EdgeSpoolReliability,
    EdgeWatchdogReliability,
    OperatorEdgeReliabilityV1,
    build_operator_edge_reliability,
)

SCHEMA_VERSION = "senior-pomidor.operator.v1"
MAX_AGE_SECONDS = 1200
MAX_REASONS = 20


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    ALERT = "ALERT"
    UNKNOWN = "UNKNOWN"


ANOMALY_STATUS_MAP = {
    "CRITICAL": Status.ALERT,
    "HIGH": Status.ALERT,
    "WARN": Status.WARN,
    "MEDIUM": Status.WARN,
    "LOW": Status.WARN,
    "INFO": Status.OK,
}


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Completeness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class Reason(Strict):
    code: str = Field(min_length=1, max_length=80)
    status: Status
    message: str = Field(min_length=1, max_length=200)


class Envelope(Strict):
    schema_version: Literal["senior-pomidor.operator.v1"] = "senior-pomidor.operator.v1"
    view: str = Field(min_length=1, max_length=40)
    request_id: str = Field(min_length=1, max_length=64)
    generated_at_utc: datetime
    status: Status
    availability: Availability
    freshness: Freshness
    completeness: Completeness
    reasons: list[Reason] = Field(default_factory=list, max_length=MAX_REASONS)


class Host(Strict):
    availability: Availability
    status: Status
    freshness: Freshness
    reason: str | None


class DecisionView(Strict):
    items: list[Any] = Field(default_factory=list, max_length=100)


def status_rank(value: Status | str) -> int:
    return {Status.OK: 0, Status.UNKNOWN: 1, Status.WARN: 2, Status.ALERT: 3}[Status(value)]


def anomaly_status(severity: str) -> Status:
    return ANOMALY_STATUS_MAP.get(severity.upper(), Status.UNKNOWN)


def unknown_edge_reliability(
    event: TelemetryEvent | None,
    now: datetime,
    *,
    device_id: str | None = None,
    reason_code: str = "edge_reliability_malformed",
    reason_message: str = "Edge reliability telemetry is malformed",
) -> OperatorEdgeReliabilityV1:
    raw_device_id = event.device_id if event is not None else device_id
    projected_device_id = (
        raw_device_id
        if isinstance(raw_device_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", raw_device_id)
        else "unknown"
    )
    record_id = (
        event.record_id
        if event is not None
        and isinstance(event.record_id, str)
        and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", event.record_id)
        else None
    )
    generated_at = utc(now) or datetime.now(UTC)
    return OperatorEdgeReliabilityV1(
        schema_version="senior-pomidor.operator.edge-reliability.v1",
        device_id=projected_device_id,
        record_id=record_id,
        generated_at_utc=generated_at,
        observed_at_utc=None,
        received_at_utc=None,
        status="UNKNOWN",
        freshness=EdgeReliabilityFreshness(status="UNKNOWN", age_seconds=None, max_age_seconds=1200),
        reasons=[
            EdgeReliabilityReason(
                code=reason_code,
                status="UNKNOWN",
                message=reason_message,
            )
        ],
        watchdog=EdgeWatchdogReliability(
            status="UNKNOWN",
            state=None,
            result=None,
            suppression=None,
            configured=None,
            attempt_count=None,
            restart_count=None,
            reboot_count=None,
            last_healthy_heartbeat_at_utc=None,
        ),
        spool=EdgeSpoolReliability(
            status="UNKNOWN",
            reported_status=None,
            disk_status=None,
            pending_count=None,
            backlog_count=None,
            in_flight_count=None,
            dead_letter_count=None,
            oldest_pending_age_seconds=None,
            outage_duration_seconds=None,
            disk_usage_percent=None,
            last_delivery_result=None,
            last_successful_delivery_at_utc=None,
            last_error_code=None,
            worker_state=None,
            worker_last_heartbeat_at_utc=None,
        ),
        application=EdgeApplicationReliability(
            status="UNKNOWN",
            process_running=None,
            process_uptime_seconds=None,
            systemd_available=None,
            systemd_active_state=None,
            systemd_sub_state=None,
            systemd_service_active=None,
        ),
    )


class MetricSnapshot(Strict):
    soil_moisture_percent: float | None = Field(default=None, ge=0, le=100)
    soil_temperature_c: float | None = None
    air_temperature_c: float | None = None
    air_humidity_percent: float | None = Field(default=None, ge=0, le=100)
    air_vpd_kpa: float | None = Field(default=None, ge=0)
    light_lux: float | None = Field(default=None, ge=0, le=150000)


class PodView(Strict):
    pod_key: str
    plant_id: str | None
    plant_identity_status: Literal["UNKNOWN"]
    enabled: bool | None
    observed_at_utc: datetime | None
    metrics: MetricSnapshot


class PlantView(Strict):
    node_id: str
    observed_at_utc: datetime | None
    state_id: str | None
    pods: list[PodView] = Field(default_factory=list, max_length=100)


class PlantsData(Strict):
    items: list[PlantView] = Field(default_factory=list, max_length=100)
    returned_count: int = Field(ge=0, le=100)
    has_more: bool


class StateEnvironment(Strict):
    air_temp_c: float | None
    rh_pct: float | None = Field(default=None, ge=0, le=100)
    vpd_kpa: float | None = Field(default=None, ge=0)
    lux: float | None = Field(default=None, ge=0, le=150000)


class StateSoil(Strict):
    temp_c: float | None
    probes: list[StateProbe] = Field(default_factory=list, max_length=100)


class StateProbe(Strict):
    id: str
    position: str
    moisture_pct: float | None = Field(default=None, ge=0, le=100)
    dry_threshold_pct: float | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: str


class StatePlant(Strict):
    leaf_temp_c: float | None


class StateView(Strict):
    state_id: str
    node_id: str
    observed_at_utc: datetime
    status: Status
    confidence: float | None = Field(default=None, ge=0, le=1)
    env: StateEnvironment
    soil: StateSoil
    plant: StatePlant


class StatusData(Strict):
    host: Host
    nodes: list[PlantView] = Field(default_factory=list, max_length=100)
    state: StateView | None
    edge: list[OperatorEdgeReliabilityV1] = Field(default_factory=list, max_length=100)
    decisions: Availability


class EdgeData(Strict):
    items: list[OperatorEdgeReliabilityV1] = Field(default_factory=list, max_length=100)
    returned_count: int = Field(ge=0, le=100)
    has_more: bool


class AnomalyView(Strict):
    anomaly_id: str
    node_id: str
    type: str
    status: str
    severity: Status
    observed_at_utc: datetime
    state_id: str | None


class AnomalyData(Strict):
    items: list[AnomalyView] = Field(default_factory=list, max_length=100)
    returned_count: int = Field(ge=0, le=100)
    has_more: bool


class PhotoView(Strict):
    photo_id: str
    node_id: str
    captured_at_utc: datetime
    content_type: str
    file_size_bytes: int = Field(ge=0)
    sha256: str
    sharpness_score: float | None


class PhotoData(Strict):
    items: list[PhotoView] = Field(default_factory=list, max_length=100)
    returned_count: int = Field(ge=0, le=100)
    has_more: bool


class StatusResponse(Envelope):
    view: Literal["status"] = "status"
    data: StatusData


class PlantsResponse(Envelope):
    view: Literal["plants"] = "plants"
    data: PlantsData


class EdgesResponse(Envelope):
    view: Literal["edges"] = "edges"
    data: EdgeData


class AnomaliesResponse(Envelope):
    view: Literal["anomalies"] = "anomalies"
    data: AnomalyData


class PhotosResponse(Envelope):
    view: Literal["photos"] = "photos"
    data: PhotoData


class DecisionsResponse(Envelope):
    view: Literal["decisions"] = "decisions"
    data: DecisionView


class OperatorError(Strict):
    schema_version: Literal["senior-pomidor.operator.v1"] = "senior-pomidor.operator.v1"
    error_code: str
    request_id: str
    message: str


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)


def _reason(code: str, status: Status, message: str) -> Reason:
    return Reason(code=code, status=status, message=message)


def _freshness(observed: datetime | None, now: datetime) -> Freshness:
    observed = utc(observed)
    if observed is None:
        return Freshness.UNKNOWN
    age = (now - observed).total_seconds()
    if age < 0:
        return Freshness.UNKNOWN
    return Freshness.FRESH if age <= MAX_AGE_SECONDS else Freshness.STALE


def _status(values: list[Status]) -> Status:
    for candidate in (Status.ALERT, Status.WARN, Status.UNKNOWN, Status.OK):
        if candidate in values:
            return candidate
    return Status.UNKNOWN


def _request_id() -> str:
    return uuid4().hex


def _safe_number(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        return None
    return value


def project_state(snapshot: StateSnapshot | None) -> StateView | None:
    if snapshot is None or not isinstance(snapshot.payload_jsonb, dict):
        return None
    payload = snapshot.payload_jsonb
    env_raw = payload.get("env") if isinstance(payload.get("env"), dict) else {}
    soil_raw = payload.get("soil") if isinstance(payload.get("soil"), dict) else {}
    plant_raw = payload.get("plant") if isinstance(payload.get("plant"), dict) else {}
    quality_raw = cast(dict[str, Any], payload.get("quality")) if isinstance(payload.get("quality"), dict) else {}
    confidence = _safe_number(quality_raw.get("state_confidence"), minimum=0, maximum=1)
    quality_level: str | None = None
    if isinstance(quality_raw.get("level"), str):
        quality_level = str(quality_raw["level"])
    state_status = Status.UNKNOWN
    if quality_level is not None:
        state_status = {
            "GOOD": Status.OK,
            "DEGRADED": Status.WARN,
            "LOW_CONFIDENCE": Status.WARN,
            "UNSAFE_FOR_AUTONOMY": Status.ALERT,
        }.get(quality_level, Status.UNKNOWN)
    probes: list[StateProbe] = []
    probes_raw = cast(dict[str, Any], soil_raw).get("probes")
    if isinstance(probes_raw, list):
        for raw_probe in probes_raw[:100]:
            if not isinstance(raw_probe, dict) or not isinstance(raw_probe.get("id"), str):
                continue
            probes.append(
                StateProbe(
                    id=raw_probe["id"],
                    position=str(raw_probe.get("position") or "unknown"),
                    moisture_pct=_safe_number(raw_probe.get("moisture_pct"), minimum=0, maximum=100),
                    dry_threshold_pct=_safe_number(raw_probe.get("dry_threshold_pct"), minimum=0, maximum=100),
                    confidence=_safe_number(raw_probe.get("confidence"), minimum=0, maximum=1),
                    status=str(raw_probe.get("status") or "UNKNOWN"),
                )
            )
    observed_at = utc(snapshot.ts)
    if observed_at is None:
        return None
    return StateView(
        state_id=snapshot.state_id,
        node_id=snapshot.node_id,
        observed_at_utc=observed_at,
        status=state_status,
        confidence=confidence,
        env=StateEnvironment(
            air_temp_c=_safe_number(cast(dict[str, Any], env_raw).get("air_temp_c"), minimum=-100),
            rh_pct=_safe_number(cast(dict[str, Any], env_raw).get("rh_pct"), minimum=0, maximum=100),
            vpd_kpa=_safe_number(cast(dict[str, Any], env_raw).get("vpd_kpa"), minimum=0),
            lux=_safe_number(cast(dict[str, Any], env_raw).get("lux"), minimum=0, maximum=150000),
        ),
        soil=StateSoil(temp_c=_safe_number(cast(dict[str, Any], soil_raw).get("temp_c"), minimum=-100), probes=probes),
        plant=StatePlant(leaf_temp_c=_safe_number(cast(dict[str, Any], plant_raw).get("leaf_temp_c"), minimum=-100)),
    )


def pod_view(reading: PodReading, observed_at: datetime) -> PodView:
    def metric(name: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
        value = getattr(reading, name, None)
        if value is None and isinstance(reading.metrics_jsonb, dict):
            value = reading.metrics_jsonb.get(name)
        return _safe_number(value, minimum=minimum, maximum=maximum)

    return PodView(
        pod_key=reading.pod_key,
        plant_id=None,
        plant_identity_status="UNKNOWN",
        enabled=reading.enabled if isinstance(reading.enabled, bool) else None,
        observed_at_utc=utc(observed_at),
        metrics=MetricSnapshot(
            soil_moisture_percent=metric("soil_moisture_percent", 0, 100),
            soil_temperature_c=metric("soil_temperature_c", -100),
            air_temperature_c=metric("air_temperature_c", -100),
            air_humidity_percent=metric("air_humidity_percent", 0, 100),
            air_vpd_kpa=metric("air_vpd_kpa", 0),
            light_lux=metric("light_lux", 0, 150000),
        ),
    )


class OperatorSummaryService:
    def __init__(self, db: Session, *, now: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.now = now or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return utc(self.now()) or datetime.now(UTC)

    def _latest_event(self, node_id: str) -> TelemetryEvent | None:
        return self.db.scalar(
            select(TelemetryEvent)
            .options(selectinload(TelemetryEvent.readings))
            .where(TelemetryEvent.device_id == node_id)
            .order_by(desc(TelemetryEvent.timestamp_utc), desc(TelemetryEvent.id))
            .limit(1)
        )

    def _plant(self, device: Device) -> PlantView:
        event = self._latest_event(device.device_id)
        state = self.db.scalar(
            select(StateSnapshot)
            .where(StateSnapshot.node_id == device.device_id)
            .order_by(desc(StateSnapshot.ts), desc(StateSnapshot.state_id))
            .limit(1)
        )
        readings = event.readings if event is not None else []
        observed = event.timestamp_utc if event is not None else None
        return PlantView(
            node_id=device.device_id,
            observed_at_utc=utc(observed),
            state_id=state.state_id if state is not None else None,
            pods=[pod_view(reading, observed) for reading in readings] if observed else [],
        )

    def plants(self, limit: int = 100) -> tuple[list[PlantView], bool]:
        devices = self.db.scalars(select(Device).order_by(Device.device_id).limit(limit + 1)).all()
        has_more = len(devices) > limit
        return [self._plant(device) for device in devices[:limit]], has_more

    def edges(self, limit: int = 100) -> tuple[list[OperatorEdgeReliabilityV1], bool]:
        devices = self.db.scalars(select(Device).order_by(Device.device_id).limit(limit + 1)).all()
        has_more = len(devices) > limit
        now = self._now()
        result: list[OperatorEdgeReliabilityV1] = []
        for device in devices[:limit]:
            event = self._latest_event(device.device_id)
            if event is not None:
                try:
                    result.append(build_operator_edge_reliability(event, now=now))
                except (PydanticValidationError, TypeError, ValueError, OverflowError):
                    result.append(unknown_edge_reliability(event, now))
            else:
                result.append(
                    unknown_edge_reliability(
                        None,
                        now,
                        device_id=device.device_id,
                        reason_code="edge_reliability_telemetry_unavailable",
                        reason_message="Edge reliability telemetry is unavailable",
                    )
                )
        return result, has_more

    def anomalies(self, *, node_id: str | None, since_hours: int, limit: int) -> tuple[list[AnomalyView], bool]:
        cutoff = self._now() - timedelta(hours=since_hours)
        query = select(AnomalyRecord).where((AnomalyRecord.status == "ACTIVE") | (AnomalyRecord.ts >= cutoff))
        if node_id:
            query = query.where(AnomalyRecord.node_id == node_id)
        records = self.db.scalars(
            query.order_by(desc(AnomalyRecord.ts), desc(AnomalyRecord.anomaly_id)).limit(limit + 1)
        ).all()
        items: list[AnomalyView] = []
        for record in records[:limit]:
            severity = anomaly_status(record.severity)
            observed_at = utc(record.ts)
            if observed_at is None:
                continue
            items.append(
                AnomalyView(
                    anomaly_id=record.anomaly_id,
                    node_id=record.node_id,
                    type=record.type,
                    status=record.status,
                    severity=severity,
                    observed_at_utc=observed_at,
                    state_id=record.state_id,
                )
            )
        return items, len(records) > limit

    def photos(self, *, node_id: str | None, since_hours: int, limit: int) -> tuple[list[PhotoView], bool]:
        query = select(Photo)
        if node_id:
            query = query.where(Photo.device_id == node_id)
        query = query.where(Photo.captured_at_utc >= self._now() - timedelta(hours=since_hours))
        rows = self.db.scalars(query.order_by(desc(Photo.captured_at_utc), desc(Photo.photo_id)).limit(limit + 1)).all()
        items: list[PhotoView] = []
        for row in rows[:limit]:
            captured_at = utc(row.captured_at_utc)
            if captured_at is None:
                continue
            try:
                items.append(
                    PhotoView(
                        photo_id=row.photo_id,
                        node_id=row.device_id,
                        captured_at_utc=captured_at,
                        content_type=row.content_type,
                        file_size_bytes=row.file_size_bytes,
                        sha256=row.sha256,
                        sharpness_score=_safe_number(row.sharpness_score),
                    )
                )
            except (PydanticValidationError, TypeError, ValueError, OverflowError):
                continue
        return items, len(rows) > limit

    def status(self) -> tuple[list[PlantView], list[OperatorEdgeReliabilityV1], StateView | None, list[Reason], bool]:
        failures = False
        try:
            plants, plants_have_more = self.plants()
        except SQLAlchemyError:
            self.db.rollback()
            plants, plants_have_more = [], False
            failures = True
            plants_reason: Reason | None = _reason("nodes_unavailable", Status.UNKNOWN, "Node data is unavailable")
        else:
            plants_reason = None
        try:
            edges, edges_have_more = self.edges()
        except SQLAlchemyError:
            self.db.rollback()
            edges, edges_have_more = [], False
            failures = True
            edges_reason: Reason | None = _reason(
                "edges_unavailable", Status.UNKNOWN, "Edge reliability is unavailable"
            )
        else:
            edges_reason = None
        state = None
        try:
            if plants:
                state = project_state(
                    self.db.scalar(
                        select(StateSnapshot).order_by(desc(StateSnapshot.ts), desc(StateSnapshot.state_id)).limit(1)
                    )
                )
        except SQLAlchemyError:
            self.db.rollback()
            failures = True
        reasons: list[Reason] = []
        if not plants:
            reasons.append(_reason("nodes_unavailable", Status.UNKNOWN, "No persisted nodes are available"))
        if plants_reason:
            reasons.append(plants_reason)
        if edges_reason:
            reasons.append(edges_reason)
        if not state:
            reasons.append(_reason("state_unavailable", Status.UNKNOWN, "Persisted state is unavailable"))
        try:
            active_status_rank = self.db.scalar(
                select(
                    func.max(
                        case(
                            (AnomalyRecord.severity.in_(("CRITICAL", "HIGH")), 3),
                            (AnomalyRecord.severity.in_(("WARN", "MEDIUM", "LOW")), 2),
                            (AnomalyRecord.severity.not_in(("INFO",)), 1),
                            else_=0,
                        )
                    )
                ).where(AnomalyRecord.status == "ACTIVE")
            )
            if active_status_rank == 3:
                reasons.append(_reason("active_anomaly_alert", Status.ALERT, "An active alert anomaly is present"))
            elif active_status_rank == 2:
                reasons.append(_reason("active_anomaly_warn", Status.WARN, "An active warning anomaly is present"))
            elif active_status_rank == 1:
                reasons.append(_reason("active_anomaly_unknown", Status.UNKNOWN, "An active anomaly is unclassified"))
        except SQLAlchemyError:
            self.db.rollback()
            failures = True
            reasons.append(_reason("anomalies_unavailable", Status.UNKNOWN, "Active anomalies are unavailable"))
        return plants, edges, state, reasons, failures or plants_have_more or edges_have_more


def aggregate_freshness(
    state: StateView | None,
    plants: list[PlantView],
    edges: list[OperatorEdgeReliabilityV1],
    now: datetime,
) -> Freshness:
    values = [_freshness(state.observed_at_utc, now) if state else Freshness.UNKNOWN]
    values.extend(_freshness(plant.observed_at_utc, now) for plant in plants)
    values.extend(Freshness(edge.freshness.status) for edge in edges)
    return combine_freshness(values)


def combine_freshness(values: Iterable[Freshness]) -> Freshness:
    values = list(values)
    if Freshness.UNKNOWN in values:
        return Freshness.UNKNOWN
    if Freshness.STALE in values:
        return Freshness.STALE
    return Freshness.FRESH if Freshness.FRESH in values else Freshness.UNKNOWN


def collection_freshness(timestamps: Iterable[datetime | None], now: datetime) -> Freshness:
    values = [_freshness(timestamp, now) for timestamp in timestamps]
    return combine_freshness(values)


def plants_status(items: list[PlantView], now: datetime) -> Status:
    if not items:
        return Status.UNKNOWN
    if any(
        not any(
            value is not None
            for value in (
                metric
                for pod in item.pods
                for metric in (
                    pod.metrics.soil_moisture_percent,
                    pod.metrics.soil_temperature_c,
                    pod.metrics.air_temperature_c,
                    pod.metrics.air_humidity_percent,
                    pod.metrics.air_vpd_kpa,
                    pod.metrics.light_lux,
                )
            )
        )
        for item in items
    ):
        return Status.UNKNOWN
    freshness = [_freshness(item.observed_at_utc, now) for item in items]
    if Freshness.UNKNOWN in freshness:
        return Status.UNKNOWN
    if Freshness.STALE in freshness:
        return Status.WARN
    return Status.OK


def envelope_kwargs(
    view: str,
    *,
    now: datetime,
    status: Status,
    availability: Availability,
    freshness: Freshness,
    completeness: Completeness,
    reasons: list[Reason] | None = None,
) -> dict[str, Any]:
    return {
        "view": view,
        "request_id": _request_id(),
        "generated_at_utc": now,
        "status": status,
        "availability": availability,
        "freshness": freshness,
        "completeness": completeness,
        "reasons": (reasons or [])[:MAX_REASONS],
    }
