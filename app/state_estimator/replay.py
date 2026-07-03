from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import PodReading
from app.state_estimator.adapters import observations_from_reading
from app.state_estimator.config import load_estimator_runtime
from app.state_estimator.estimator import estimate_state
from app.state_estimator.models import EstimatorContext, EstimatorHistory, RawObservation
from app.telemetry import iter_pods, pod_enabled, pod_key, pod_metrics
from app.validation import payload_device_id, payload_timestamp


def replay_observations(
    payload: dict[str, Any],
    *,
    timezone: str,
    config_path: str = "config/state_estimator_v1.yaml",
) -> list[dict[str, Any]]:
    history = EstimatorHistory()
    states: list[dict[str, Any]] = []
    config, calibration = load_estimator_runtime(config_path, timezone=timezone)
    for node_id, node_observations in _observation_batches(payload):
        if not node_observations:
            continue
        result = estimate_state(
            node_observations,
            context=EstimatorContext(node_id=node_id, timezone=timezone),
            config=config,
            calibration=calibration,
            history=history,
        )
        result.state["generated_ts"] = result.state["ts"]
        states.append(result.state)
    return states


def _observation_batches(payload: dict[str, Any]) -> list[tuple[str, list[RawObservation]]]:
    if isinstance(payload.get("observations"), list):
        observations = [_raw_observation(item) for item in payload.get("observations", []) if isinstance(item, dict)]
        by_node: dict[str, list[RawObservation]] = {}
        for observation in sorted(observations, key=lambda item: item.ts):
            by_node.setdefault(observation.node_id, []).append(observation)
        return sorted(by_node.items())
    raw_events = payload.get("telemetry")
    if raw_events is None:
        raw_events = payload.get("events")
    events = raw_events if isinstance(raw_events, list) else [payload]
    batches: list[tuple[str, list[RawObservation]]] = []
    accumulated: dict[str, list[RawObservation]] = {}
    for event in events:
        if isinstance(event, dict):
            event_observations = _observations_from_telemetry(event)
            if not event_observations:
                continue
            node_id = event_observations[0].node_id
            accumulated.setdefault(node_id, []).extend(event_observations)
            batches.append((node_id, list(accumulated[node_id])))
    return batches


def _observations_from_telemetry(payload: dict[str, Any]) -> list[RawObservation]:
    node_id = payload_device_id(payload)
    ts = payload_timestamp(payload)
    observations: list[RawObservation] = []
    for index, pod in enumerate(iter_pods(payload)):
        key = pod_key(pod, index)
        known, unknown = pod_metrics(pod)
        reading = PodReading(
            telemetry_event_id=0,
            device_id=node_id,
            pod_key=key,
            enabled=pod_enabled(pod),
            metrics_jsonb=unknown,
            **known,
        )
        observations.extend(observations_from_reading(reading, ts, ts))
    observations.append(
        RawObservation(
            node_id=node_id,
            sensor_id="device_status",
            sensor_type="device_status",
            ts=ts,
            received_ts=ts,
            values={"mcu_connected": True},
            read_ok=True,
        )
    )
    return observations


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
