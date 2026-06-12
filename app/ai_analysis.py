from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
import base64
import json
import urllib.error
import urllib.request

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models import Photo, PodReading, TelemetryEvent
from app.telemetry import health_alerts


DEFAULT_AI_ANALYSIS_MODEL = "llama3.2-vision"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_AI_ANALYSIS_OUTPUT = "data/ai-analysis/results.jsonl"


class AnalysisError(RuntimeError):
    pass


class VisionAnalyzer(Protocol):
    def analyze(self, image_path: Path, prompt: str) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class PhotoTelemetryContext:
    photo: Photo
    telemetry_events: list[TelemetryEvent]


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def select_photo_contexts(
    db: Session,
    *,
    limit: int,
    device_id: str | None = None,
    since_hours: float | None = None,
    telemetry_window: timedelta = timedelta(minutes=30),
    now: datetime | None = None,
) -> list[PhotoTelemetryContext]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if since_hours is not None and since_hours < 0:
        raise ValueError("since_hours must be non-negative")
    if telemetry_window.total_seconds() < 0:
        raise ValueError("telemetry_window must be non-negative")

    query = select(Photo).order_by(desc(Photo.captured_at_utc)).limit(limit)
    if device_id:
        query = query.where(Photo.device_id == device_id)
    if since_hours is not None:
        cutoff = ensure_utc(now or datetime.now(UTC)) - timedelta(hours=since_hours)
        query = query.where(Photo.captured_at_utc >= cutoff)

    photos = db.scalars(query).all()
    contexts: list[PhotoTelemetryContext] = []
    for photo in photos:
        captured_at = ensure_utc(photo.captured_at_utc)
        window_start = captured_at - telemetry_window
        window_end = captured_at + telemetry_window
        telemetry_events = db.scalars(
            select(TelemetryEvent)
            .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
            .where(
                TelemetryEvent.device_id == photo.device_id,
                TelemetryEvent.timestamp_utc >= window_start,
                TelemetryEvent.timestamp_utc <= window_end,
            )
            .order_by(TelemetryEvent.timestamp_utc)
        ).all()
        contexts.append(PhotoTelemetryContext(photo=photo, telemetry_events=list(telemetry_events)))
    return contexts


def reading_metrics(reading: PodReading) -> dict[str, Any]:
    metrics = {
        "adc_raw": reading.adc_raw,
        "soil_moisture_percent": reading.soil_moisture_percent,
        "soil_temperature_c": reading.soil_temperature_c,
        "air_temperature_c": reading.air_temperature_c,
        "air_humidity_percent": reading.air_humidity_percent,
        "air_pressure_hpa": reading.air_pressure_hpa,
        "light_lux": reading.light_lux,
        "ir_ambient_temp_c": reading.ir_ambient_temp_c,
        "leaf_temp_c": reading.leaf_temp_c,
    }
    metrics.update(reading.metrics_jsonb or {})
    return {key: value for key, value in metrics.items() if value is not None}


def telemetry_event_summary(event: TelemetryEvent) -> dict[str, Any]:
    system_health = event.system_health_jsonb
    return {
        "id": event.id,
        "device_id": event.device_id,
        "timestamp_utc": format_utc(event.timestamp_utc),
        "schema_version": event.schema_version,
        "source": event.source,
        "readings": [
            {
                "pod_key": reading.pod_key,
                "enabled": reading.enabled,
                "metrics": reading_metrics(reading),
            }
            for reading in event.readings
        ],
        "errors": [
            {"pod_key": error.pod_key, "sensor": error.sensor, "message": error.message}
            for error in event.errors
        ],
        "system_health": system_health,
        "health_alerts": health_alerts(system_health),
    }


def build_prompt_inputs(context: PhotoTelemetryContext) -> dict[str, Any]:
    photo = context.photo
    return {
        "photo": {
            "photo_id": photo.photo_id,
            "device_id": photo.device_id,
            "captured_at_utc": format_utc(photo.captured_at_utc),
            "sharpness_score": photo.sharpness_score,
            "content_type": photo.content_type,
            "file_size_bytes": photo.file_size_bytes,
            "sha256": photo.sha256,
        },
        "telemetry": [telemetry_event_summary(event) for event in context.telemetry_events],
    }


def render_prompt(prompt_inputs: dict[str, Any]) -> str:
    return (
        "Analyze this Senior Pomidor tomato monitoring photo using the image and the matching telemetry.\n"
        "Focus on visible plant condition, watering stress, heat or cold stress, sensor-error clues, "
        "and practical follow-up checks. Do not invent facts that are not visible or present in telemetry.\n"
        "Return concise JSON with keys: visible_condition, likely_issues, telemetry_correlations, "
        "recommended_follow_up, confidence.\n\n"
        "Prompt inputs:\n"
        f"{json.dumps(prompt_inputs, indent=2, sort_keys=True)}"
    )


class OllamaVisionAnalyzer:
    def __init__(
        self,
        *,
        model: str = DEFAULT_AI_ANALYSIS_MODEL,
        host: str = DEFAULT_OLLAMA_HOST,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_path: Path, prompt: str) -> str:
        if not self.host:
            raise AnalysisError("Ollama host is required")
        image_bytes = image_path.read_bytes()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise AnalysisError(f"Ollama HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise AnalysisError(f"Ollama request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AnalysisError("Ollama request timed out") from exc

        analysis = response_payload.get("response")
        if not isinstance(analysis, str):
            raise AnalysisError("Ollama response did not include a text response")
        return analysis


def analyze_context(
    context: PhotoTelemetryContext,
    analyzer: VisionAnalyzer,
    *,
    model: str,
    ollama_host: str,
    analyzed_at: datetime | None = None,
) -> dict[str, Any]:
    start = perf_counter()
    prompt_inputs = build_prompt_inputs(context)
    prompt = render_prompt(prompt_inputs)
    image_path = Path(context.photo.storage_path)
    analysis: str | None = None
    error: str | None = None
    try:
        analysis = analyzer.analyze(image_path, prompt)
    except Exception as exc:  # noqa: BLE001 - per-photo report output should capture prototype failures.
        error = str(exc)

    return {
        "photo_id": context.photo.photo_id,
        "device_id": context.photo.device_id,
        "captured_at_utc": format_utc(context.photo.captured_at_utc),
        "model": model,
        "analyzed_at": format_utc(analyzed_at or datetime.now(UTC)),
        "telemetry_event_ids": [event.id for event in context.telemetry_events],
        "prompt_inputs": prompt_inputs,
        "analysis": analysis,
        "runtime": {
            "elapsed_seconds": round(perf_counter() - start, 3),
            "ollama_host": ollama_host,
        },
        "error": error,
    }


def write_jsonl(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def analyze_contexts(
    contexts: list[PhotoTelemetryContext],
    analyzer: VisionAnalyzer,
    *,
    output_path: Path,
    model: str,
    ollama_host: str,
    analyzed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    records = [
        analyze_context(context, analyzer, model=model, ollama_host=ollama_host, analyzed_at=analyzed_at)
        for context in contexts
    ]
    if records:
        write_jsonl(records, output_path)
    return records
