from __future__ import annotations

from datetime import datetime
from typing import Any


def sensor_entry(
    *,
    sensor_id: str,
    sensor_type: str,
    status: str,
    confidence: float,
    last_seen_ts: str | None,
    age_seconds: float | None,
    flags: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "sensor_id": sensor_id,
        "sensor_type": sensor_type,
        "status": status,
        "confidence": round(confidence, 3),
        "last_seen_ts": last_seen_ts,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "flags": flags or [],
        "reason": reason,
    }


def overall_status(entries: list[dict[str, Any]]) -> str:
    statuses = {entry["status"] for entry in entries}
    if statuses & {"DISCONNECTED", "OUT_OF_RANGE", "STALE"}:
        return "WARN"
    if statuses & {"WARN", "JUMP", "UNCALIBRATED", "UNKNOWN"}:
        return "WARN"
    return "OK"


def age_seconds(now: datetime, then: datetime | None) -> float | None:
    if then is None:
        return None
    return max(0.0, (now - then).total_seconds())
