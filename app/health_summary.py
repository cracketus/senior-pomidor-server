from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.edge_reliability import EdgeReliabilityEvaluation, evaluate_edge_reliability
from app.models import SensorHealthSnapshot, TelemetryEvent
from app.readiness import check_readiness
from app.telemetry import health_alerts

TELEMETRY_STALE_SECONDS = 20 * 60
WORKER_STALE_SECONDS = 90
HEALTHY_WORKER_STATUSES = {"healthy", "state_estimator_healthy"}
SUMMARY_STATUSES = {"OK", "WARN", "ALERT", "UNKNOWN"}


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _age_seconds(timestamp: datetime, now: datetime) -> float | None:
    value = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    age = (now - value).total_seconds()
    return round(age, 3) if age >= 0 else None


def _component(status: str, *, age_seconds: float | None = None, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if age_seconds is not None:
        result["age_seconds"] = age_seconds
    result.update(details)
    return result


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _reliability_component(
    evaluation: EdgeReliabilityEvaluation,
    system_health: dict[str, Any],
    *,
    age_seconds: float,
) -> dict[str, Any]:
    watchdog = _object(system_health.get("watchdog"))
    spool = _object(system_health.get("spool"))
    application = _object(system_health.get("application"))
    watchdog_details = {
        field: watchdog[field] for field in ("state", "result", "suppression", "configured") if field in watchdog
    }
    spool_details = {
        target: spool[source]
        for source, target in (("status", "reported_status"), ("disk_status", "disk_status"))
        if source in spool
    }
    application_details = {
        field: application[field]
        for field in ("process_running", "systemd_available", "systemd_service_active")
        if field in application
    }
    return _component(
        evaluation.status,
        age_seconds=age_seconds,
        reason_codes=[finding.reason_code for finding in evaluation.findings],
        watchdog=_component(evaluation.watchdog_status, **watchdog_details),
        spool=_component(evaluation.spool_status, **spool_details),
        application=_component(evaluation.application_status, **application_details),
    )


def _unknown_reliability_component(reason_code: str) -> dict[str, Any]:
    return _component(
        "UNKNOWN",
        reason_codes=[reason_code],
        watchdog=_component("UNKNOWN"),
        spool=_component("UNKNOWN"),
        application=_component("UNKNOWN"),
    )


def _worker_component(path_value: str, now: datetime) -> tuple[dict[str, Any], list[dict[str, str]]]:
    path = Path(path_value)
    if not path.is_file():
        return _component("UNKNOWN", reason_code="worker_health_missing"), [
            {"code": "worker_health_missing", "message": "worker health is unavailable"}
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]).replace("Z", "+00:00"))
        worker_status = str(payload["status"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _component("UNKNOWN", reason_code="worker_health_invalid"), [
            {"code": "worker_health_invalid", "message": "worker health is malformed"}
        ]

    age = _age_seconds(updated_at, now)
    if age is None:
        return _component("UNKNOWN", reason_code="worker_health_timestamp_invalid"), [
            {"code": "worker_health_timestamp_invalid", "message": "worker health timestamp is invalid"}
        ]
    if age > WORKER_STALE_SECONDS:
        return _component("WARN", age_seconds=age, reason_code="worker_health_stale"), [
            {"code": "worker_health_stale", "message": "worker health is stale"}
        ]
    if worker_status not in HEALTHY_WORKER_STATUSES:
        return _component("ALERT", age_seconds=age, reason_code="worker_unhealthy"), [
            {"code": "worker_unhealthy", "message": "worker reported an unhealthy status"}
        ]
    return _component("OK", age_seconds=age), []


def _node_component(
    db: Session, node_id: str, now: datetime
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    reasons: list[dict[str, str]] = []
    telemetry = db.scalar(
        select(TelemetryEvent)
        .where(TelemetryEvent.device_id == node_id)
        .order_by(desc(TelemetryEvent.timestamp_utc), desc(TelemetryEvent.id))
    )
    sensor_health = db.scalar(
        select(SensorHealthSnapshot)
        .where(SensorHealthSnapshot.node_id == node_id)
        .order_by(desc(SensorHealthSnapshot.ts), desc(SensorHealthSnapshot.health_id))
    )

    if telemetry is None:
        telemetry_component = _component("UNKNOWN", reason_code="telemetry_missing")
        reasons.append({"code": "telemetry_missing", "message": "node telemetry is unavailable"})
        reliability_component = _unknown_reliability_component("edge_reliability_telemetry_missing")
        reasons.append(
            {
                "code": "edge_reliability_telemetry_missing",
                "message": "edge reliability telemetry is unavailable",
            }
        )
    else:
        age = _age_seconds(telemetry.timestamp_utc, now)
        if age is None:
            telemetry_component = _component("UNKNOWN", reason_code="telemetry_timestamp_invalid")
            reasons.append({"code": "telemetry_timestamp_invalid", "message": "node telemetry timestamp is invalid"})
            reliability_component = _unknown_reliability_component("edge_reliability_telemetry_unavailable")
            reasons.append(
                {
                    "code": "edge_reliability_telemetry_unavailable",
                    "message": "edge reliability telemetry is unavailable",
                }
            )
        elif age > TELEMETRY_STALE_SECONDS:
            telemetry_component = _component("WARN", age_seconds=age, reason_code="telemetry_stale")
            reasons.append({"code": "telemetry_stale", "message": "node telemetry is stale"})
            reliability_component = _unknown_reliability_component("edge_reliability_telemetry_stale")
            reliability_component["age_seconds"] = age
            reasons.append(
                {"code": "edge_reliability_telemetry_stale", "message": "edge reliability telemetry is stale"}
            )
        else:
            system_health = telemetry.system_health_jsonb if isinstance(telemetry.system_health_jsonb, dict) else {}
            evaluation = evaluate_edge_reliability(system_health)
            alerts = health_alerts(system_health, edge_reliability=evaluation)
            reliability_component = _reliability_component(evaluation, system_health, age_seconds=age)
            reasons.extend({"code": finding.reason_code, "message": finding.message} for finding in evaluation.findings)
            if any(alert.get("level") == "critical" for alert in alerts):
                telemetry_component = _component("ALERT", age_seconds=age, reason_code="telemetry_critical_alert")
                reasons.append({"code": "telemetry_critical_alert", "message": "node telemetry has a critical alert"})
            elif alerts:
                telemetry_component = _component("WARN", age_seconds=age, reason_code="telemetry_alert")
                reasons.append({"code": "telemetry_alert", "message": "node telemetry has an alert"})
            else:
                telemetry_component = _component("OK", age_seconds=age)

    if sensor_health is None:
        sensor_component = _component("UNKNOWN", reason_code="sensor_health_missing")
        reasons.append({"code": "sensor_health_missing", "message": "node sensor health is unavailable"})
    else:
        age = _age_seconds(sensor_health.ts, now)
        if age is None:
            sensor_component = _component("UNKNOWN", reason_code="sensor_health_timestamp_invalid")
            reasons.append({"code": "sensor_health_timestamp_invalid", "message": "sensor health timestamp is invalid"})
        elif age > TELEMETRY_STALE_SECONDS:
            sensor_component = _component("WARN", age_seconds=age, reason_code="sensor_health_stale")
            reasons.append({"code": "sensor_health_stale", "message": "sensor health is stale"})
        else:
            sensor_component = _component("OK", age_seconds=age)
    return telemetry_component, sensor_component, reliability_component, reasons


def _bounded_unique_reasons(reasons: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason["code"] in seen:
            continue
        result.append(reason)
        seen.add(reason["code"])
        if len(result) == 20:
            break
    return result


def build_health_summary(
    db: Session,
    *,
    worker_health_file: str,
    now: datetime | None = None,
    node_id: str | None = None,
    alembic_ini_path: str = "alembic.ini",
    readiness_engine: Any,
) -> dict[str, Any]:
    current_time = _utc_now(now)
    reasons: list[dict[str, str]] = []
    components: dict[str, dict[str, Any]] = {"api": _component("OK")}

    try:
        readiness = check_readiness(readiness_engine, alembic_ini_path)
        if readiness.ready:
            components["database"] = _component("OK", migration=readiness.migration)
        elif readiness.database == "unavailable":
            components["database"] = _component("ALERT", reason_code="database_unavailable")
            reasons.append({"code": "database_unavailable", "message": "database is unavailable"})
        else:
            components["database"] = _component("WARN", migration=readiness.migration, reason_code="migration_mismatch")
            reasons.append({"code": "migration_mismatch", "message": "database migration is not current"})
    except (OSError, RuntimeError, SQLAlchemyError):
        components["database"] = _component("UNKNOWN", reason_code="readiness_unavailable")
        reasons.append({"code": "readiness_unavailable", "message": "readiness state is unavailable"})

    worker, worker_reasons = _worker_component(worker_health_file, current_time)
    components["worker"] = worker
    reasons.extend(worker_reasons)

    if node_id:
        try:
            telemetry, sensor_health, edge_reliability, node_reasons = _node_component(db, node_id, current_time)
            components["telemetry"] = telemetry
            components["sensor_health"] = sensor_health
            components["edge_reliability"] = edge_reliability
            reasons.extend(node_reasons)
        except SQLAlchemyError:
            components["telemetry"] = _component("UNKNOWN", reason_code="telemetry_unavailable")
            components["sensor_health"] = _component("UNKNOWN", reason_code="sensor_health_unavailable")
            components["edge_reliability"] = _unknown_reliability_component("edge_reliability_telemetry_unavailable")
            reasons.append({"code": "node_health_unavailable", "message": "node health is unavailable"})
            reasons.append(
                {
                    "code": "edge_reliability_telemetry_unavailable",
                    "message": "edge reliability telemetry is unavailable",
                }
            )
    else:
        components["telemetry"] = _component("OK", scope="server")
        components["sensor_health"] = _component("OK", scope="server")

    status = "OK"
    for candidate in ("ALERT", "WARN", "UNKNOWN"):
        if any(component.get("status") == candidate for component in components.values()):
            status = candidate
            break
    return {
        "schema_version": "health_summary_v1",
        "status": status if status in SUMMARY_STATUSES else "UNKNOWN",
        "generated_at": current_time.isoformat().replace("+00:00", "Z"),
        "components": components,
        "reasons": _bounded_unique_reasons(reasons),
        "data_freshness": {
            "worker_max_age_seconds": WORKER_STALE_SECONDS,
            "telemetry_max_age_seconds": TELEMETRY_STALE_SECONDS,
            "node_id": node_id,
        },
    }
