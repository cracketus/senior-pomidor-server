from __future__ import annotations

from datetime import datetime
from typing import Any

from app.state_estimator.estimator import estimate_state
from app.state_estimator.models import EstimatorConfig, EstimatorContext, EstimatorHistory, RawObservation


def replay_observations(payload: dict[str, Any], *, timezone: str) -> list[dict[str, Any]]:
    history = EstimatorHistory()
    states: list[dict[str, Any]] = []
    observations = [_raw_observation(item) for item in payload.get("observations", []) if isinstance(item, dict)]
    by_node: dict[str, list[RawObservation]] = {}
    for observation in sorted(observations, key=lambda item: item.ts):
        by_node.setdefault(observation.node_id, []).append(observation)
    for node_id, node_observations in sorted(by_node.items()):
        result = estimate_state(
            node_observations,
            context=EstimatorContext(node_id=node_id, timezone=timezone),
            config=EstimatorConfig(timezone=timezone),
            history=history,
        )
        states.append(result.state)
    return states


def _raw_observation(item: dict[str, Any]) -> RawObservation:
    values: dict[str, float | bool | str | None] = {}
    raw_values = item.get("values")
    if isinstance(raw_values, dict):
        values = {
            str(key): value
            for key, value in raw_values.items()
            if isinstance(value, float | bool | str) or value is None
        }
    raw: dict[str, Any] = {}
    raw_item = item.get("raw")
    if isinstance(raw_item, dict):
        raw = raw_item
    return RawObservation(
        node_id=str(item["node_id"]),
        sensor_id=str(item["sensor_id"]),
        sensor_type=str(item["sensor_type"]),
        ts=datetime.fromisoformat(str(item["ts"])),
        received_ts=datetime.fromisoformat(str(item.get("received_ts") or item["ts"])),
        values=values,
        read_ok=bool(item.get("read_ok", True)),
        error=str(item["error"]) if item.get("error") is not None else None,
        raw=raw,
    )
