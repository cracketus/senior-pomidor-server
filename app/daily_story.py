from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai_analysis import ensure_utc, format_utc, reading_metrics
from app.models import AnomalyRecord, DailyStoryRun, SensorHealthSnapshot, TelemetryEvent
from app.ollama import OllamaClient, OllamaError
from app.telemetry import health_alerts

REQUIRED_TEMPLATE_TOKENS = (
    "{{NODE_ID}}",
    "{{WINDOW_START_UTC}}",
    "{{WINDOW_END_UTC}}",
    "{{ENVIRONMENT_CONTEXT_JSON}}",
    "{{CONTEXT_JSON}}",
)
STORY_MIN_CHARS = 280 * 6
STORY_MAX_CHARS = 32768
STORY_END_MARKER = "#SeniorPomidor"
STORY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    # Large grammar-enforced lengths make reasoning models pad the story with
    # internal analysis. Enforce the publication bounds in _parse_story.
    "properties": {"story": {"type": "string", "minLength": 1}},
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


def load_environment_context(path: str, max_chars: int) -> dict[str, Any]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        context = json.loads(raw)
    except OSError as exc:
        raise DailyStoryError(f"Unable to read daily story environment context: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DailyStoryError(f"Daily story environment context is invalid JSON: {exc}") from exc
    if not isinstance(context, dict):
        raise DailyStoryError("Daily story environment context must be a JSON object")
    if len(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) > max_chars:
        raise DailyStoryError("Daily story environment context exceeds its configured size limit")
    return context


def build_environment_context(
    db: Session,
    *,
    node_id: str,
    story_date: date,
    base_context: dict[str, Any],
    memory_entries: int,
    max_chars: int,
) -> dict[str, Any]:
    context = json.loads(json.dumps(base_context, ensure_ascii=False))
    configured_memories = context.get("running_memories")
    if isinstance(configured_memories, dict):
        memories = configured_memories
    elif isinstance(configured_memories, list):
        memories = {"notes": configured_memories}
    else:
        memories = {"notes": []}
    previous_runs = list(
        db.scalars(
            select(DailyStoryRun)
            .where(
                DailyStoryRun.node_id == node_id,
                DailyStoryRun.story_date < story_date,
                DailyStoryRun.status == "succeeded",
                DailyStoryRun.story.is_not(None),
            )
            .order_by(DailyStoryRun.story_date.desc(), DailyStoryRun.id.desc())
            .limit(memory_entries)
        ).all()
    )
    memories["previous_diary_entries"] = [
        {"story_date": run.story_date.isoformat(), "story": run.story} for run in reversed(previous_runs)
    ]
    context["running_memories"] = memories
    serialized = lambda: json.dumps(  # noqa: E731
        context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    while memories["previous_diary_entries"] and len(serialized()) > max_chars:
        memories["previous_diary_entries"].pop(0)
    if len(serialized()) > max_chars:
        raise DailyStoryError("Daily story environment context exceeds its configured size limit")
    return context


def render_user_prompt(
    template: str,
    *,
    node_id: str,
    window_start: datetime,
    window_end: datetime,
    environment_context: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    replacements = {
        "{{NODE_ID}}": node_id,
        "{{WINDOW_START_UTC}}": format_utc(window_start),
        "{{WINDOW_END_UTC}}": format_utc(window_end),
        "{{ENVIRONMENT_CONTEXT_JSON}}": json.dumps(
            environment_context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
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
    if len(story) < STORY_MIN_CHARS:
        raise DailyStoryError(f"Ollama returned a story shorter than {STORY_MIN_CHARS} characters (got {len(story)})")
    if len(story) > STORY_MAX_CHARS:
        raise DailyStoryError(f"Ollama returned a story longer than {STORY_MAX_CHARS} characters")
    if not story.endswith(STORY_END_MARKER):
        raise DailyStoryError(f"Ollama story must end with {STORY_END_MARKER} and contain no trailing analysis")
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
    request_prompt = user_prompt
    for attempt in range(1, retry_attempts + 1):
        response = None
        try:
            response = client.generate(
                model=model,
                system=system_prompt,
                prompt=request_prompt,
                format_schema=STORY_JSON_SCHEMA,
                options=options,
                keep_alive=keep_alive,
                think=False,
            )
            return GeneratedStory(story=_parse_story(response.text), metrics=response.metrics, request_attempts=attempt)
        except (DailyStoryError, OllamaError) as exc:
            last_error = exc
            if isinstance(exc, OllamaError) and not exc.retryable:
                break
            if isinstance(exc, DailyStoryError):
                short_draft = ""
                if response is not None:
                    try:
                        previous_payload = json.loads(response.text)
                        previous_story = previous_payload.get("story") if isinstance(previous_payload, dict) else None
                    except json.JSONDecodeError:
                        previous_story = None
                    if isinstance(previous_story, str) and 0 < len(previous_story.strip()) < STORY_MIN_CHARS:
                        short_draft = (
                            "\n\nPrevious short draft to rewrite and expand:\n"
                            "<draft>\n"
                            f"{previous_story.strip()}\n"
                            "</draft>"
                        )
                request_prompt = (
                    f"{user_prompt}\n\n"
                    f"Correction for generation attempt {attempt + 1}: the previous response was invalid because "
                    f"{exc}. Return one complete JSON story of at least {STORY_MIN_CHARS} characters. "
                    "Rewrite the whole diary as 7-10 clearly separated thread posts of 240-280 characters each. "
                    "Expand the observations and biological interpretation without inventing facts; do not merely "
                    "continue after the existing ending. Return only the publishable diary, with no planning, "
                    "reasoning, prompt discussion, or commentary."
                    f"{short_draft}"
                )
    raise DailyStoryError(str(last_error or "Daily story generation failed")) from last_error
