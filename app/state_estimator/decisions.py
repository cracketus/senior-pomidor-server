from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

STALE_STATE_SECONDS = 20 * 60
NORMAL_SAMPLING_SECONDS = 600
ANOMALY_WATCH_SECONDS = 120
CRITICAL_SAMPLING_SECONDS = 60
ANOMALY_WATCH_DURATION_SECONDS = 30 * 60

BLOCKING_ANOMALY_TYPES = {
    "REQUIRED_SENSOR_UNAVAILABLE",
    "DEVICE_DISCONNECTED",
    "LOW_STATE_CONFIDENCE",
}
BLOCKING_SENSOR_STATUSES = {"OUT_OF_RANGE", "JUMP", "STALE", "DISCONNECTED"}
REQUIRED_SENSOR_TYPES = {"air_temp_rh", "soil_moisture"}
OPTIONAL_SENSOR_TYPES = {"co2", "leaf_ir", "light_lux"}
NOTIFY_SEVERITIES = {"HIGH", "CRITICAL"}
SAMPLING_ANOMALY_TYPES = {
    "SENSOR_STALE",
    "SENSOR_JUMP",
    "HIGH_VPD",
    "HIGH_TEMP",
    "CRITICAL_HEAT",
    "LOW_STATE_CONFIDENCE",
    "REQUIRED_SENSOR_UNAVAILABLE",
    "DEVICE_DISCONNECTED",
}


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_ts(value: datetime) -> str:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def build_guardrails(
    *,
    node_id: str,
    state: dict[str, Any] | None,
    sensor_health: dict[str, Any] | None,
    active_anomalies: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    blocking: list[str] = []
    caution: list[str] = []
    state_id: str | None = None

    if state is None:
        blocking.append("missing_state")
    else:
        state_id = str(state.get("state_id") or "")
        state_ts = parse_ts(state.get("ts"))
        if state_ts is None:
            blocking.append("missing_state_timestamp")
        elif now - state_ts > timedelta(seconds=STALE_STATE_SECONDS):
            blocking.append("stale_state")
        quality_level = str(state.get("quality", {}).get("level") or "")
        if quality_level == "UNSAFE_FOR_AUTONOMY":
            blocking.append("unsafe_for_autonomy")
        elif quality_level in {"LOW_CONFIDENCE", "DEGRADED"}:
            caution.append(f"state_quality_{quality_level.lower()}")

    for anomaly in active_anomalies:
        type_ = str(anomaly.get("type") or "")
        severity = str(anomaly.get("severity") or "").upper()
        if type_ in BLOCKING_ANOMALY_TYPES:
            blocking.append(f"active_anomaly_{type_.lower()}")
        elif severity == "WARN":
            caution.append(f"warning_anomaly_{type_.lower()}")

    for sensor in (sensor_health or {}).get("sensors", []):
        sensor_type = str(sensor.get("sensor_type") or "")
        status = str(sensor.get("status") or "")
        if sensor_type in REQUIRED_SENSOR_TYPES and status in BLOCKING_SENSOR_STATUSES:
            blocking.append(f"required_sensor_{sensor_type.lower()}_{status.lower()}")
        if sensor_type in OPTIONAL_SENSOR_TYPES and status in {"NOT_PRESENT", "DISCONNECTED", "STALE"}:
            caution.append(f"optional_sensor_{sensor_type.lower()}_{status.lower()}")

    blocking = sorted(set(blocking))
    caution = sorted(set(caution))
    level = "BLOCKED" if blocking else "CAUTION" if caution else "ALLOW"
    return {
        "schema_version": "guardrails_v1",
        "node_id": node_id,
        "state_id": state_id,
        "generated_ts": format_ts(now),
        "allowed": not blocking,
        "level": level,
        "blocking_reasons": blocking,
        "caution_reasons": caution,
    }


def build_action_simulation(
    *,
    node_id: str,
    guardrails: dict[str, Any],
    state: dict[str, Any] | None,
    active_anomalies: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    state_id = state.get("state_id") if state else None
    reasons: list[str] = []
    sampling_seconds = NORMAL_SAMPLING_SECONDS
    sampling_until_ts: str | None = None

    if not guardrails.get("allowed"):
        decision = "BLOCKED_BY_GUARDRAIL"
        reasons = list(guardrails.get("blocking_reasons") or [])
        if "active_anomaly_device_disconnected" in reasons:
            sampling_seconds = CRITICAL_SAMPLING_SECONDS
        else:
            sampling_seconds = ANOMALY_WATCH_SECONDS
            sampling_until_ts = format_ts(now + timedelta(seconds=ANOMALY_WATCH_DURATION_SECONDS))
    else:
        notify_anomalies = [
            item for item in active_anomalies if str(item.get("severity") or "").upper() in NOTIFY_SEVERITIES
        ]
        sampling_anomalies = [
            item for item in active_anomalies if str(item.get("type") or "") in SAMPLING_ANOMALY_TYPES
        ]
        if notify_anomalies:
            decision = "WOULD_NOTIFY"
            reasons = [f"active_anomaly_{item.get('type')}" for item in notify_anomalies]
        elif sampling_anomalies:
            decision = "WOULD_INCREASE_SAMPLING"
            reasons = [f"active_anomaly_{item.get('type')}" for item in sampling_anomalies]
        else:
            decision = "NO_ACTION"

        if sampling_anomalies:
            severe_sampling = any(
                str(item.get("type") or "") in {"CRITICAL_HEAT", "DEVICE_DISCONNECTED"} for item in sampling_anomalies
            )
            sampling_seconds = CRITICAL_SAMPLING_SECONDS if severe_sampling else ANOMALY_WATCH_SECONDS
            sampling_until_ts = (
                None if severe_sampling else format_ts(now + timedelta(seconds=ANOMALY_WATCH_DURATION_SECONDS))
            )

    simulation_id = f"action_sim_{format_ts(now)}_{node_id}_{state_id or 'no_state'}".replace(":", "").replace("+", "")
    return {
        "schema_version": "action_simulation_v1",
        "simulation_id": simulation_id,
        "node_id": node_id,
        "state_id": state_id,
        "generated_ts": format_ts(now),
        "decision": decision,
        "reasons": sorted(set(reasons)),
        "guardrails": {
            "allowed": bool(guardrails.get("allowed")),
            "level": guardrails.get("level"),
            "blocking_reasons": list(guardrails.get("blocking_reasons") or []),
            "caution_reasons": list(guardrails.get("caution_reasons") or []),
        },
        "sampling_recommendation": {
            "recommended_poll_seconds": sampling_seconds,
            "normal_poll_seconds": NORMAL_SAMPLING_SECONDS,
            "until_ts": sampling_until_ts,
            "advisory_only": True,
        },
        "actuation": {
            "physical_actuation": False,
            "watering_proposed": False,
        },
    }
