from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AnomalyRecord, StateSnapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize recent state estimator outputs.")
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()
    since = datetime.now(UTC) - timedelta(hours=args.hours)
    with SessionLocal() as db:
        states_query = select(StateSnapshot).where(StateSnapshot.ts >= since).order_by(StateSnapshot.ts)
        anomalies_query = select(AnomalyRecord).where(AnomalyRecord.status == "ACTIVE").order_by(AnomalyRecord.ts)
        if args.node_id:
            states_query = states_query.where(StateSnapshot.node_id == args.node_id)
            anomalies_query = anomalies_query.where(AnomalyRecord.node_id == args.node_id)
        states = db.scalars(states_query).all()
        anomalies = db.scalars(anomalies_query).all()
    summary = summarize(states, anomalies, since=since)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def summarize(
    states: Sequence[StateSnapshot], anomalies: Sequence[AnomalyRecord], *, since: datetime
) -> dict[str, Any]:
    confidences: list[float] = []
    null_counts: dict[str, int] = {"env.vpd_kpa": 0, "soil.avg_moisture_pct": 0}
    probe_values: dict[str, list[float]] = {}
    for snapshot in states:
        payload = snapshot.payload_jsonb
        confidence = _number(_path(payload, "quality", "state_confidence"))
        if confidence is not None:
            confidences.append(confidence)
        if _path(payload, "env", "vpd_kpa") is None:
            null_counts["env.vpd_kpa"] += 1
        if _path(payload, "soil", "avg_moisture_pct") is None:
            null_counts["soil.avg_moisture_pct"] += 1
        for probe in _path(payload, "soil", "probes") or []:
            if not isinstance(probe, dict):
                continue
            moisture = _number(probe.get("moisture_pct"))
            if moisture is not None:
                probe_values.setdefault(str(probe.get("id")), []).append(moisture)
    total = len(states)
    return {
        "since": since.isoformat().replace("+00:00", "Z"),
        "state_snapshot_count": total,
        "active_anomaly_count": len(anomalies),
        "active_anomalies": [
            {"node_id": item.node_id, "type": item.type, "severity": item.severity, "ts": item.ts.isoformat()}
            for item in anomalies
        ],
        "state_confidence": {
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
        },
        "null_rates": {key: (count / total if total else None) for key, count in null_counts.items()},
        "probe_values": {
            key: {"min": min(values), "max": max(values), "latest": values[-1], "count": len(values)}
            for key, values in probe_values.items()
        },
    }


def _path(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
