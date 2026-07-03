from __future__ import annotations

from typing import Any


def anomaly(
    *,
    node_id: str,
    ts: str,
    state_id: str,
    type_: str,
    severity: str,
    signals: dict[str, Any],
    confidence: float,
    required_response: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "anomaly_v1",
        "anomaly_id": f"anom_{ts}_{node_id}_{type_}".replace(":", "").replace("+", ""),
        "node_id": node_id,
        "ts": ts,
        "state_id": state_id,
        "severity": severity,
        "type": type_,
        "status": "ACTIVE",
        "signals": signals,
        "duration_seconds": 0,
        "expected_effects": [],
        "required_response": required_response,
        "confidence": round(confidence, 3),
    }
