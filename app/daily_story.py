from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai_analysis import ensure_utc, format_utc, reading_metrics
from app.models import AnomalyRecord, SensorHealthSnapshot, TelemetryEvent
from app.ollama import OllamaClient, OllamaError
from app.telemetry import health_alerts

REQUIRED_TEMPLATE_TOKENS = (
    "{{NODE_ID}}",
    "{{WINDOW_START_UTC}}",
    "{{WINDOW_END_UTC}}",
    "{{CONTEXT_JSON}}",
)
STORY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"story": {"type": "string", "minLength": 1, "maxLength": 280}},
    "required": ["story"],
    "additionalProperties": False,
}


class DailyStoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyStoryContext:
    summary: dict[str, Any]
    telemetry_event_count: int


@dataclass(frozen=True)
class GeneratedStory:
    story: str
    metrics: dict[str, Any]
    request_attempts: int


def _round(value: float) -> float:
    return round(value, 6)


def _metric_summary(samples: list[tuple[datetime, float]]) -> dict[str, float | int]:
    samples.sort(key=lambda item: item[0])
    values = [value for _timestamp, value in samples]
    first = values[0]
    last = values[-1]
    return {
        "count": len(values),
        "min": _round(min(values)),
        "max": _round(max(values)),
        "average": _round(sum(values) / len(values)),
        "first": _round(first),
        "last": _round(last),
        "change": _round(last - first),
    }


def _grouped_counts(items: Sequence[tuple[str, ...]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    counts = Counter(items)
    return [
        {**dict(zip(fields, key, strict=True)), "count": count}
        for key, count in sorted(counts.items(), key=lambda item: item[0])
    ]


def _coverage(events: list[TelemetryEvent], window_start: datetime, window_end: datetime) -> dict[str, Any]:
    if not events:
        return {
            "start_utc": None,
            "end_utc": None,
            "window_start_gap_seconds": int((window_end - window_start).total_seconds()),
            "window_end_gap_seconds": int((window_end - window_start).total_seconds()),
            "expected_interval_seconds": None,
            "data_gaps": [],
        }
    timestamps = [ensure_utc(event.timestamp_utc) for event in events]
    intervals = [(right - left).total_seconds() for left, right in pairwise(timestamps)]
    expected = median(intervals) if intervals else None
    threshold = max(120.0, expected * 2) if expected is not None else None
    gaps = [
        {
            "start_utc": format_utc(left),
            "end_utc": format_utc(right),
            "seconds": int((right - left).total_seconds()),
        }
        for left, right in pairwise(timestamps)
        if threshold is not None and (right - left).total_seconds() > threshold
    ]
    return {
        "start_utc": format_utc(timestamps[0]),
        "end_utc": format_utc(timestamps[-1]),
        "window_start_gap_seconds": max(0, int((timestamps[0] - window_start).total_seconds())),
        "window_end_gap_seconds": max(0, int((window_end - timestamps[-1]).total_seconds())),
        "expected_interval_seconds": _round(expected) if expected is not None else None,
        "data_gaps": gaps[:50],
    }


def _anomaly_summary(records: list[AnomalyRecord]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
    for record in records:
        grouped[(record.type, record.severity, record.status)].append(ensure_utc(record.ts))
    return [
        {
            "type": key[0],
            "severity": key[1],
            "status": key[2],
            "count": len(timestamps),
            "first_utc": format_utc(min(timestamps)),
            "last_utc": format_utc(max(timestamps)),
        }
        for key, timestamps in sorted(grouped.items())
    ][:100]


def _sensor_health_summary(snapshots: list[SensorHealthSnapshot]) -> dict[str, Any]:
    histories: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    overall: list[tuple[datetime, str]] = []
    for snapshot in snapshots:
        timestamp = ensure_utc(snapshot.ts)
        payload = snapshot.payload_jsonb or {}
        overall_status = payload.get("overall_status") or payload.get("status")
        if overall_status is not None:
            overall.append((timestamp, str(overall_status)))
        sensors = payload.get("sensors")
        if not isinstance(sensors, list):
            continue
        for index, sensor in enumerate(sensors):
            if not isinstance(sensor, dict) or sensor.get("status") is None:
                continue
            sensor_id = (
                sensor.get("sensor_id") or sensor.get("id") or sensor.get("sensor_type") or f"sensor-{index + 1}"
            )
            histories[str(sensor_id)].append((timestamp, str(sensor["status"])))

    def summarized(history: list[tuple[datetime, str]]) -> dict[str, Any]:
        changes: list[dict[str, str]] = []
        previous: str | None = None
        for timestamp, status in history:
            if previous is not None and status != previous:
                changes.append({"at_utc": format_utc(timestamp), "from": previous, "to": status})
            previous = status
        return {"latest_status": history[-1][1], "changes": changes[:50]}

    return {
        "snapshot_count": len(snapshots),
        "overall": summarized(overall) if overall else {"latest_status": None, "changes": []},
        "sensors": {key: summarized(histories[key]) for key in sorted(histories)},
    }


def _bounded(summary: dict[str, Any], max_chars: int) -> dict[str, Any]:
    if max_chars < 512:
        raise ValueError("max_chars must be at least 512")
    serialized = lambda: json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))  # noqa: E731
    if len(serialized()) <= max_chars:
        return summary
    summary["truncated"] = True
    removable_lists = [
        summary["errors"]["pod"],
        summary["errors"]["system_health"],
        summary["errors"]["system_health_alerts"],
        summary["anomalies"],
        summary["coverage"]["data_gaps"],
    ]
    for items in removable_lists:
        while items and len(serialized()) > max_chars:
            items.pop()
    sensor_map = summary["sensor_health"]["sensors"]
    while sensor_map and len(serialized()) > max_chars:
        sensor_map.pop(next(reversed(sensor_map)))
    pods = summary["pods"]
    for pod_key in reversed(list(pods)):
        metrics = pods[pod_key]
        while metrics and len(serialized()) > max_chars:
            metrics.pop(next(reversed(metrics)))
        if not metrics and len(serialized()) > max_chars:
            pods.pop(pod_key)
    if len(serialized()) <= max_chars:
        return summary
    return {
        "node_id": summary["node_id"],
        "window_start_utc": summary["window_start_utc"],
        "window_end_utc": summary["window_end_utc"],
        "event_count": summary["event_count"],
        "coverage": summary["coverage"],
        "truncated": True,
    }


def build_daily_story_context(
    db: Session,
    *,
    node_id: str,
    window_start: datetime,
    window_end: datetime,
    max_chars: int = 16_000,
) -> DailyStoryContext:
    window_start = ensure_utc(window_start)
    window_end = ensure_utc(window_end)
    if window_start >= window_end:
        raise ValueError("window_start must be before window_end")
    events = list(
        db.scalars(
            select(TelemetryEvent)
            .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
            .where(
                TelemetryEvent.device_id == node_id,
                TelemetryEvent.timestamp_utc >= window_start,
                TelemetryEvent.timestamp_utc < window_end,
            )
            .order_by(TelemetryEvent.timestamp_utc, TelemetryEvent.id)
        ).all()
    )
    anomalies = list(
        db.scalars(
            select(AnomalyRecord)
            .where(
                AnomalyRecord.node_id == node_id,
                AnomalyRecord.ts >= window_start,
                AnomalyRecord.ts < window_end,
            )
            .order_by(AnomalyRecord.ts, AnomalyRecord.anomaly_id)
        ).all()
    )
    health = list(
        db.scalars(
            select(SensorHealthSnapshot)
            .where(
                SensorHealthSnapshot.node_id == node_id,
                SensorHealthSnapshot.ts >= window_start,
                SensorHealthSnapshot.ts < window_end,
            )
            .order_by(SensorHealthSnapshot.ts, SensorHealthSnapshot.health_id)
        ).all()
    )

    metric_samples: dict[str, dict[str, list[tuple[datetime, float]]]] = defaultdict(lambda: defaultdict(list))
    pod_errors: list[tuple[str, str, str]] = []
    system_errors: list[tuple[str, str]] = []
    system_alerts: list[tuple[str, str, str]] = []
    for event in events:
        timestamp = ensure_utc(event.timestamp_utc)
        for reading in sorted(event.readings, key=lambda item: item.pod_key):
            for metric, value in sorted(reading_metrics(reading).items()):
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                metric_samples[reading.pod_key][metric].append((timestamp, float(value)))
        for error in event.errors:
            pod_errors.append((error.pod_key, error.sensor or "", error.message))
        system_health = event.system_health_jsonb or {}
        raw_errors = system_health.get("errors") if isinstance(system_health, dict) else None
        if isinstance(raw_errors, list):
            for error in raw_errors:
                if isinstance(error, dict) and error.get("message"):
                    system_errors.append((str(error.get("sensor") or ""), str(error["message"])))
        for alert in health_alerts(event.system_health_jsonb):
            system_alerts.append(
                (str(alert.get("metric") or ""), str(alert.get("level") or ""), str(alert.get("message") or ""))
            )

    summary = {
        "node_id": node_id,
        "window_start_utc": format_utc(window_start),
        "window_end_utc": format_utc(window_end),
        "event_count": len(events),
        "coverage": _coverage(events, window_start, window_end),
        "pods": {
            pod_key: {metric: _metric_summary(samples) for metric, samples in sorted(metrics.items())}
            for pod_key, metrics in sorted(metric_samples.items())
        },
        "errors": {
            "pod": _grouped_counts(pod_errors, ("pod_key", "sensor", "message"))[:100],
            "system_health": _grouped_counts(system_errors, ("sensor", "message"))[:100],
            "system_health_alerts": _grouped_counts(system_alerts, ("metric", "level", "message"))[:100],
        },
        "anomalies": _anomaly_summary(anomalies),
        "sensor_health": _sensor_health_summary(health),
    }
    return DailyStoryContext(summary=_bounded(summary, max_chars), telemetry_event_count=len(events))


def load_prompts(system_path: str, user_path: str) -> tuple[str, str]:
    try:
        system_prompt = Path(system_path).read_text(encoding="utf-8").strip()
        user_template = Path(user_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DailyStoryError(f"Unable to read daily story prompt: {exc}") from exc
    if not system_prompt:
        raise DailyStoryError("Daily story system prompt is empty")
    if not user_template:
        raise DailyStoryError("Daily story user prompt is empty")
    missing = [token for token in REQUIRED_TEMPLATE_TOKENS if token not in user_template]
    if missing:
        raise DailyStoryError(f"Daily story user prompt is missing required tokens: {', '.join(missing)}")
    return system_prompt, user_template


def render_user_prompt(
    template: str, *, node_id: str, window_start: datetime, window_end: datetime, summary: dict[str, Any]
) -> str:
    replacements = {
        "{{NODE_ID}}": node_id,
        "{{WINDOW_START_UTC}}": format_utc(window_start),
        "{{WINDOW_END_UTC}}": format_utc(window_end),
        "{{CONTEXT_JSON}}": json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }
    rendered = template
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def _parse_story(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DailyStoryError("Ollama returned malformed story JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"story"}:
        raise DailyStoryError("Ollama story JSON must contain only the story field")
    story = payload.get("story")
    if not isinstance(story, str) or not story.strip():
        raise DailyStoryError("Ollama returned an empty story")
    story = story.strip()
    if len(story) > 280:
        raise DailyStoryError("Ollama returned a story longer than 280 characters")
    return story


def generate_story(
    client: OllamaClient,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    options: dict[str, Any],
    keep_alive: str | int,
    retry_attempts: int = 3,
) -> GeneratedStory:
    if retry_attempts < 1:
        raise ValueError("retry_attempts must be at least 1")
    last_error: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = client.generate(
                model=model,
                system=system_prompt,
                prompt=user_prompt,
                format_schema=STORY_JSON_SCHEMA,
                options=options,
                keep_alive=keep_alive,
            )
            return GeneratedStory(story=_parse_story(response.text), metrics=response.metrics, request_attempts=attempt)
        except (DailyStoryError, OllamaError) as exc:
            last_error = exc
            if isinstance(exc, OllamaError) and not exc.retryable:
                break
    raise DailyStoryError(str(last_error or "Daily story generation failed")) from last_error
