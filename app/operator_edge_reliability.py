from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.edge_reliability import evaluate_edge_reliability
from app.models import TelemetryEvent

EDGE_RELIABILITY_SCHEMA_VERSION: Literal["senior-pomidor.operator.edge-reliability.v1"] = (
    "senior-pomidor.operator.edge-reliability.v1"
)
EDGE_RELIABILITY_MAX_AGE_SECONDS = 20 * 60

ReliabilityStatus = Literal["OK", "WARN", "ALERT", "UNKNOWN"]
FreshnessStatus = Literal["FRESH", "STALE", "UNKNOWN"]
NonNegativeInt = Annotated[int, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, le=100)]
DeviceId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
RecordId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EdgeReliabilityFreshness(StrictResponseModel):
    status: FreshnessStatus
    age_seconds: int | float | None
    max_age_seconds: int


class EdgeReliabilityReason(StrictResponseModel):
    code: str
    status: ReliabilityStatus
    message: str


class EdgeWatchdogReliability(StrictResponseModel):
    status: ReliabilityStatus
    state: str | None
    result: str | None
    suppression: bool | None
    configured: bool | None
    attempt_count: NonNegativeInt | None
    restart_count: NonNegativeInt | None
    reboot_count: NonNegativeInt | None
    last_healthy_heartbeat_at_utc: datetime | None


class EdgeSpoolReliability(StrictResponseModel):
    status: ReliabilityStatus
    reported_status: str | None
    disk_status: str | None
    pending_count: NonNegativeInt | None
    backlog_count: NonNegativeInt | None
    in_flight_count: NonNegativeInt | None
    dead_letter_count: NonNegativeInt | None
    oldest_pending_age_seconds: NonNegativeInt | None
    outage_duration_seconds: NonNegativeInt | None
    disk_usage_percent: Percent | None
    last_delivery_result: str | None
    last_successful_delivery_at_utc: datetime | None
    last_error_code: str | None
    worker_state: str | None
    worker_last_heartbeat_at_utc: datetime | None


class EdgeApplicationReliability(StrictResponseModel):
    status: ReliabilityStatus
    process_running: bool | None
    process_uptime_seconds: NonNegativeInt | None
    systemd_available: bool | None
    systemd_active_state: str | None
    systemd_sub_state: str | None
    systemd_service_active: bool | None


class OperatorEdgeReliabilityV1(StrictResponseModel):
    schema_version: Literal["senior-pomidor.operator.edge-reliability.v1"]
    device_id: DeviceId
    record_id: RecordId | None
    generated_at_utc: datetime
    observed_at_utc: datetime | None
    received_at_utc: datetime | None
    status: ReliabilityStatus
    freshness: EdgeReliabilityFreshness
    reasons: list[EdgeReliabilityReason]
    watchdog: EdgeWatchdogReliability
    spool: EdgeSpoolReliability
    application: EdgeApplicationReliability


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_value(age: float) -> int | float:
    rounded = round(age, 3)
    return int(rounded) if rounded.is_integer() else rounded


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value(block: dict[str, Any], field: str, *, project: bool) -> Any:
    return block.get(field) if project else None


def _watchdog(block: dict[str, Any], status: ReliabilityStatus, *, project: bool) -> EdgeWatchdogReliability:
    return EdgeWatchdogReliability(
        status=status,
        state=_value(block, "state", project=project),
        result=_value(block, "result", project=project),
        suppression=_value(block, "suppression", project=project),
        configured=_value(block, "configured", project=project),
        attempt_count=_value(block, "attempt_count", project=project),
        restart_count=_value(block, "restart_count", project=project),
        reboot_count=_value(block, "reboot_count", project=project),
        last_healthy_heartbeat_at_utc=_value(block, "last_healthy_heartbeat_at_utc", project=project),
    )


def _spool(block: dict[str, Any], status: ReliabilityStatus, *, project: bool) -> EdgeSpoolReliability:
    return EdgeSpoolReliability(
        status=status,
        reported_status=_value(block, "status", project=project),
        disk_status=_value(block, "disk_status", project=project),
        pending_count=_value(block, "pending_count", project=project),
        backlog_count=_value(block, "backlog_count", project=project),
        in_flight_count=_value(block, "in_flight_count", project=project),
        dead_letter_count=_value(block, "dead_letter_count", project=project),
        oldest_pending_age_seconds=_value(block, "oldest_pending_age_seconds", project=project),
        outage_duration_seconds=_value(block, "outage_duration_seconds", project=project),
        disk_usage_percent=_value(block, "disk_usage_percent", project=project),
        last_delivery_result=_value(block, "last_delivery_result", project=project),
        last_successful_delivery_at_utc=_value(block, "last_successful_delivery_at_utc", project=project),
        last_error_code=_value(block, "last_error_code", project=project),
        worker_state=_value(block, "worker_state", project=project),
        worker_last_heartbeat_at_utc=_value(block, "worker_last_heartbeat_at_utc", project=project),
    )


def _application(block: dict[str, Any], status: ReliabilityStatus, *, project: bool) -> EdgeApplicationReliability:
    return EdgeApplicationReliability(
        status=status,
        process_running=_value(block, "process_running", project=project),
        process_uptime_seconds=_value(block, "process_uptime_seconds", project=project),
        systemd_available=_value(block, "systemd_available", project=project),
        systemd_active_state=_value(block, "systemd_active_state", project=project),
        systemd_sub_state=_value(block, "systemd_sub_state", project=project),
        systemd_service_active=_value(block, "systemd_service_active", project=project),
    )


def build_operator_edge_reliability(event: TelemetryEvent, *, now: datetime) -> OperatorEdgeReliabilityV1:
    generated_at = _utc(now)
    observed_at = _utc(event.timestamp_utc) if isinstance(event.timestamp_utc, datetime) else None
    received_at = _utc(event.received_at) if isinstance(event.received_at, datetime) else None
    age = (generated_at - observed_at).total_seconds() if observed_at is not None else None
    health = event.system_health_jsonb if isinstance(event.system_health_jsonb, dict) else {}
    watchdog = _object(health.get("watchdog"))
    spool = _object(health.get("spool"))
    application = _object(health.get("application"))

    if age is None or age < 0:
        overall_status: ReliabilityStatus = "UNKNOWN"
        freshness_status: FreshnessStatus = "UNKNOWN"
        age_seconds: int | float | None = None
        reasons = [
            EdgeReliabilityReason(
                code="edge_reliability_telemetry_unavailable",
                status="UNKNOWN",
                message="Edge reliability telemetry is unavailable",
            )
        ]
        subsystem_status: ReliabilityStatus = "UNKNOWN"
        project = False
    elif age > EDGE_RELIABILITY_MAX_AGE_SECONDS:
        overall_status = "UNKNOWN"
        freshness_status = "STALE"
        age_seconds = _age_value(age)
        reasons = [
            EdgeReliabilityReason(
                code="edge_reliability_telemetry_stale",
                status="UNKNOWN",
                message="Edge reliability telemetry is stale",
            )
        ]
        subsystem_status = "UNKNOWN"
        project = True
    else:
        evaluation = evaluate_edge_reliability(health)
        overall_status = cast(ReliabilityStatus, evaluation.status)
        freshness_status = "FRESH"
        age_seconds = _age_value(age)
        reasons = [
            EdgeReliabilityReason(
                code=finding.reason_code,
                status=cast(ReliabilityStatus, finding.status),
                message=finding.message,
            )
            for finding in evaluation.findings
        ]
        project = True
        return OperatorEdgeReliabilityV1(
            schema_version=EDGE_RELIABILITY_SCHEMA_VERSION,
            device_id=event.device_id,
            record_id=event.record_id,
            generated_at_utc=generated_at,
            observed_at_utc=observed_at,
            received_at_utc=received_at,
            status=overall_status,
            freshness=EdgeReliabilityFreshness(
                status=freshness_status,
                age_seconds=age_seconds,
                max_age_seconds=EDGE_RELIABILITY_MAX_AGE_SECONDS,
            ),
            reasons=reasons,
            watchdog=_watchdog(watchdog, cast(ReliabilityStatus, evaluation.watchdog_status), project=project),
            spool=_spool(spool, cast(ReliabilityStatus, evaluation.spool_status), project=project),
            application=_application(
                application,
                cast(ReliabilityStatus, evaluation.application_status),
                project=project,
            ),
        )

    return OperatorEdgeReliabilityV1(
        schema_version=EDGE_RELIABILITY_SCHEMA_VERSION,
        device_id=event.device_id,
        record_id=event.record_id,
        generated_at_utc=generated_at,
        observed_at_utc=observed_at,
        received_at_utc=received_at,
        status=overall_status,
        freshness=EdgeReliabilityFreshness(
            status=freshness_status,
            age_seconds=age_seconds,
            max_age_seconds=EDGE_RELIABILITY_MAX_AGE_SECONDS,
        ),
        reasons=reasons,
        watchdog=_watchdog(watchdog, subsystem_status, project=project),
        spool=_spool(spool, subsystem_status, project=project),
        application=_application(application, subsystem_status, project=project),
    )
