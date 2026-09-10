from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.models import PodReading
from app.state_estimator.adapters import observations_from_reading
from app.state_estimator.config import load_estimator_runtime
from app.state_estimator.decisions import build_action_simulation, build_guardrails
from app.state_estimator.estimator import estimate_state
from app.state_estimator.models import EstimatorContext, EstimatorHistory, EstimatorResult, RawObservation
from app.telemetry import iter_pods, pod_enabled, pod_key, pod_metrics
from app.validation import payload_device_id, payload_timestamp


@dataclass(frozen=True)
class ReplayEvaluation:
    evaluation_ts: datetime
    result: EstimatorResult
    guardrails: dict[str, Any]
    action_simulation: dict[str, Any]


def replay_observations(
    payload: dict[str, Any],
    *,
    timezone: str,
    config_path: str = "config/state_estimator_v1.yaml",
) -> list[dict[str, Any]]:
    return [
        evaluation.result.state for evaluation in evaluate_replay(payload, timezone=timezone, config_path=config_path)
    ]


def evaluate_replay(
    payload: dict[str, Any],
    *,
    timezone: str,
    config_path: str = "config/state_estimator_v1.yaml",
    evaluation_at: datetime | None = None,
) -> list[ReplayEvaluation]:
    """Replay telemetry through production estimator and advisory decision logic.

    Fixture timestamps are the evaluation clock by default. ``evaluation_at`` is
    useful for deterministic freshness checks and never changes observation time.
    The returned diagnostics retain runtime-only timing; evidence serializers must
    omit ``processing_ms`` when byte stability is required.
    """

    history = EstimatorHistory()
    evaluations: list[ReplayEvaluation] = []
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
        frame_ts = max(_as_utc(observation.ts) for observation in node_observations)
        decision_ts = _as_utc(evaluation_at) if evaluation_at is not None else frame_ts
        result.state["generated_ts"] = decision_ts.astimezone(ZoneInfo(timezone)).isoformat()
        result.state["refs"]["anomaly_ids"] = sorted(result.state["refs"]["anomaly_ids"])
        anomalies = sorted(result.anomalies, key=lambda item: (str(item.get("type")), str(item.get("anomaly_id"))))
        guardrails = build_guardrails(
            node_id=node_id,
            state=result.state,
            sensor_health=result.sensor_health,
            active_anomalies=anomalies,
            now=decision_ts,
        )
        action_simulation = build_action_simulation(
            node_id=node_id,
            guardrails=guardrails,
            state=result.state,
            active_anomalies=anomalies,
            now=decision_ts,
        )
        evaluations.append(
            ReplayEvaluation(
                evaluation_ts=decision_ts,
                result=EstimatorResult(
                    state=result.state,
                    sensor_health=result.sensor_health,
                    anomalies=anomalies,
                    diagnostics=result.diagnostics,
                ),
                guardrails=guardrails,
                action_simulation=action_simulation,
            )
        )
    return evaluations


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
