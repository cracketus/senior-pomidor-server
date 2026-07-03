from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models import AnomalyRecord, EstimatorDiagnostic, SensorHealthSnapshot, StateSnapshot, TelemetryEvent
from app.state_estimator.adapters import observations_from_event
from app.state_estimator.estimator import estimate_state
from app.state_estimator.logging import append_jsonl, daily_name, monthly_name
from app.state_estimator.models import EstimatorConfig, EstimatorContext, EstimatorHistory, EstimatorResult
from app.validation import validate_device_id

logger = logging.getLogger(__name__)


def parse_state_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def persist_estimator_result(db: Session, result: EstimatorResult, *, private_log_dir: str | None = None) -> None:
    state_ts = parse_state_ts(result.state["ts"])
    generated_at = parse_state_ts(result.state["generated_ts"])
    current_anomalies = dedupe_and_clear_anomalies(
        db,
        result.anomalies,
        node_id=result.state["node_id"],
        state_ts=state_ts,
    )
    result.state["refs"]["anomaly_ids"] = [
        item["anomaly_id"] for item in current_anomalies if item.get("status") == "ACTIVE"
    ]
    db.merge(
        StateSnapshot(
            state_id=result.state["state_id"],
            node_id=result.state["node_id"],
            ts=state_ts,
            payload_jsonb=result.state,
            generated_at=generated_at,
        )
    )
    db.merge(
        SensorHealthSnapshot(
            health_id=result.sensor_health["health_id"],
            node_id=result.sensor_health["node_id"],
            ts=parse_state_ts(result.sensor_health["ts"]),
            payload_jsonb=result.sensor_health,
        )
    )
    for item in current_anomalies:
        db.merge(
            AnomalyRecord(
                anomaly_id=item["anomaly_id"],
                node_id=item["node_id"],
                type=item["type"],
                status=item["status"],
                severity=item["severity"],
                ts=parse_state_ts(item["ts"]),
                state_id=item.get("state_id"),
                payload_jsonb=item,
            )
        )
    db.merge(
        EstimatorDiagnostic(
            diagnostic_id=result.diagnostics["diagnostic_id"],
            node_id=result.diagnostics["node_id"],
            ts=parse_state_ts(result.diagnostics["ts"]),
            state_id=result.diagnostics.get("state_id"),
            payload_jsonb=result.diagnostics,
        )
    )
    db.commit()
    if private_log_dir:
        try:
            append_estimator_logs(private_log_dir, result, state_ts, anomalies=current_anomalies)
        except OSError:
            logger.exception("Failed to append state estimator JSONL logs")


def append_estimator_logs(
    private_log_dir: str,
    result: EstimatorResult,
    state_ts: datetime,
    *,
    anomalies: list[dict[str, Any]] | None = None,
) -> None:
    append_jsonl(private_log_dir, monthly_name("states", state_ts), result.state)
    append_jsonl(private_log_dir, monthly_name("sensor_health", state_ts), result.sensor_health)
    append_jsonl(private_log_dir, daily_name("estimator_diagnostics", state_ts), result.diagnostics)
    for item in anomalies if anomalies is not None else result.anomalies:
        append_jsonl(private_log_dir, monthly_name("anomalies", state_ts), item)


def dedupe_and_clear_anomalies(
    db: Session,
    anomalies: list[dict[str, Any]],
    *,
    node_id: str,
    state_ts: datetime,
) -> list[dict[str, Any]]:
    active_records = db.scalars(
        select(AnomalyRecord).where(AnomalyRecord.node_id == node_id, AnomalyRecord.status == "ACTIVE")
    ).all()
    active_by_type = {record.type: record for record in active_records}
    current_types = {item["type"] for item in anomalies}
    persisted: list[dict[str, Any]] = []
    for item in anomalies:
        existing = active_by_type.get(item["type"])
        if existing is not None:
            first_seen_ts = parse_state_ts(existing.payload_jsonb.get("first_seen_ts") or existing.payload_jsonb["ts"])
            item["anomaly_id"] = existing.anomaly_id
            item["first_seen_ts"] = existing.payload_jsonb.get("first_seen_ts") or existing.payload_jsonb["ts"]
            item["last_seen_ts"] = item["ts"]
            item["duration_seconds"] = max(0, int((state_ts - first_seen_ts).total_seconds()))
        else:
            item["first_seen_ts"] = item["ts"]
            item["last_seen_ts"] = item["ts"]
        persisted.append(item)

    for record in active_records:
        if record.type in current_types:
            continue
        payload = dict(record.payload_jsonb)
        payload["status"] = "CLEARED"
        payload["cleared_ts"] = state_ts.isoformat().replace("+00:00", "Z")
        record.status = "CLEARED"
        record.ts = state_ts
        record.payload_jsonb = payload
        persisted.append(payload)
    return persisted


def estimate_latest_from_telemetry(
    db: Session,
    *,
    node_id: str,
    timezone: str,
    private_log_dir: str | None = None,
    history: EstimatorHistory | None = None,
) -> EstimatorResult | None:
    node_id = validate_device_id(node_id)
    latest = db.scalar(
        select(TelemetryEvent)
        .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
        .where(TelemetryEvent.device_id == node_id)
        .order_by(desc(TelemetryEvent.timestamp_utc))
        .limit(1)
    )
    if latest is None:
        return None
    since = latest.timestamp_utc - timedelta(minutes=5)
    events = db.scalars(
        select(TelemetryEvent)
        .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
        .where(TelemetryEvent.device_id == node_id, TelemetryEvent.timestamp_utc >= since)
        .order_by(TelemetryEvent.timestamp_utc)
    ).all()
    observations = [observation for event in events for observation in observations_from_event(event)]
    result = estimate_state(
        observations,
        context=EstimatorContext(node_id=node_id, timezone=timezone),
        config=EstimatorConfig(timezone=timezone),
        history=history,
    )
    persist_estimator_result(db, result, private_log_dir=private_log_dir)
    return result


def latest_state_or_estimate(
    db: Session,
    *,
    node_id: str,
    timezone: str,
    private_log_dir: str | None = None,
) -> dict[str, Any] | None:
    node_id = validate_device_id(node_id)
    snapshot = db.scalar(
        select(StateSnapshot).where(StateSnapshot.node_id == node_id).order_by(desc(StateSnapshot.ts)).limit(1)
    )
    latest_event_ts = db.scalar(
        select(TelemetryEvent.timestamp_utc)
        .where(TelemetryEvent.device_id == node_id)
        .order_by(desc(TelemetryEvent.timestamp_utc))
        .limit(1)
    )
    if snapshot is not None and (latest_event_ts is None or snapshot.ts >= latest_event_ts):
        return snapshot.payload_jsonb
    result = estimate_latest_from_telemetry(
        db,
        node_id=node_id,
        timezone=timezone,
        private_log_dir=private_log_dir,
    )
    return result.state if result is not None else None
