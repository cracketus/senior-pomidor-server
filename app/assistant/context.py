from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.assistant.context_types import AssistantContext
from app.models import (
    AnomalyRecord,
    Device,
    Photo,
    SensorHealthSnapshot,
    StateSnapshot,
    TelemetryEvent,
)
from app.validation import ValidationError, validate_device_id

_REDACTED = "[redacted]"
_SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential", "api_key")
_METRIC_FIELDS = (
    "adc_raw",
    "soil_moisture_percent",
    "soil_temperature_c",
    "air_temperature_c",
    "air_humidity_percent",
    "air_pressure_hpa",
    "air_actual_vapor_pressure_kpa",
    "air_saturation_vapor_pressure_kpa",
    "air_vpd_kpa",
    "light_lux",
    "ir_ambient_temp_c",
    "leaf_temp_c",
    "leaf_saturation_vapor_pressure_kpa",
    "leaf_vpd_kpa",
)


class AssistantContextError(ValueError):
    pass


class AssistantContextProvider(Protocol):
    def build_context(self, node_id: str) -> AssistantContext: ...


@dataclass(frozen=True)
class AssistantContextBounds:
    history_lookback: timedelta = timedelta(hours=24)
    max_history_items: int = 24
    max_anomaly_items: int = 20
    max_photo_items: int = 5
    max_context_bytes: int = 64 * 1024
    max_section_bytes: int = 16 * 1024
    max_collection_items: int = 50
    max_string_chars: int = 2_000
    max_depth: int = 8

    def __post_init__(self) -> None:
        positive = (
            self.max_history_items,
            self.max_anomaly_items,
            self.max_photo_items,
            self.max_context_bytes,
            self.max_section_bytes,
            self.max_collection_items,
            self.max_string_chars,
            self.max_depth,
        )
        if self.history_lookback <= timedelta(0) or any(value <= 0 for value in positive):
            raise ValueError("assistant context bounds must be positive")


class SqlAlchemyAssistantContextProvider:
    """Read-only projection over existing persistence models.

    It deliberately does not call ``latest_state_or_estimate`` because that helper may
    create estimator records. Assistant reads must never mutate canonical storage.
    """

    def __init__(
        self,
        db: Session,
        *,
        bounds: AssistantContextBounds | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._bounds = bounds or AssistantContextBounds()
        self._clock = clock or (lambda: datetime.now(UTC))

    def build_context(self, node_id: str) -> AssistantContext:
        try:
            node_id = validate_device_id(node_id)
        except ValidationError as exc:
            raise AssistantContextError(str(exc)) from exc
        if self._db.get(Device, node_id) is None:
            raise AssistantContextError("device not found")

        now = _as_utc(self._clock())
        cutoff = now - self._bounds.history_lookback
        state = self._db.scalar(
            select(StateSnapshot).where(StateSnapshot.node_id == node_id).order_by(desc(StateSnapshot.ts)).limit(1)
        )
        health = self._db.scalar(
            select(SensorHealthSnapshot)
            .where(SensorHealthSnapshot.node_id == node_id)
            .order_by(desc(SensorHealthSnapshot.ts))
            .limit(1)
        )
        events = self._db.scalars(
            select(TelemetryEvent)
            .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
            .where(TelemetryEvent.device_id == node_id, TelemetryEvent.timestamp_utc >= cutoff)
            .order_by(desc(TelemetryEvent.timestamp_utc))
            .limit(self._bounds.max_history_items)
        ).all()
        anomalies = self._db.scalars(
            select(AnomalyRecord)
            .where(AnomalyRecord.node_id == node_id, AnomalyRecord.status == "ACTIVE")
            .order_by(desc(AnomalyRecord.ts))
            .limit(self._bounds.max_anomaly_items)
        ).all()
        photos = self._db.scalars(
            select(Photo)
            .where(Photo.device_id == node_id, Photo.captured_at_utc >= cutoff)
            .order_by(desc(Photo.captured_at_utc))
            .limit(self._bounds.max_photo_items)
        ).all()

        context = AssistantContext(
            node_id=node_id,
            generated_at=now,
            current_state=self._bounded_section(state.payload_jsonb) if state else None,
            recent_history=tuple(self._bounded_section(_telemetry_summary(event)) for event in events),
            active_anomalies=tuple(self._bounded_section(record.payload_jsonb) for record in anomalies),
            sensor_health=self._bounded_section(health.payload_jsonb) if health else None,
            recent_photos=tuple(_photo_summary(photo) for photo in photos),
        )
        return _fit_context(context, self._bounds.max_context_bytes)

    def _bounded_section(self, value: Any) -> dict[str, Any]:
        sanitized = _sanitize(
            value,
            max_depth=self._bounds.max_depth,
            max_items=self._bounds.max_collection_items,
            max_string_chars=self._bounds.max_string_chars,
        )
        if not isinstance(sanitized, dict):
            return {"value": sanitized}
        if _json_size(sanitized) > self._bounds.max_section_bytes:
            return {"truncated": True, "reason": "section_size_limit"}
        return sanitized


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _is_path_key(key: str) -> bool:
    normalized = key.casefold()
    return normalized == "path" or normalized.endswith("_path")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize(value: Any, *, max_depth: int, max_items: int, max_string_chars: int, _depth: int = 0) -> Any:
    if _depth >= max_depth:
        return "[truncated:depth]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= max_items:
                result["_truncated"] = True
                break
            key = str(raw_key)
            if _is_path_key(key):
                continue
            result[key] = (
                _REDACTED
                if _is_sensitive_key(key)
                else _sanitize(
                    item,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_string_chars=max_string_chars,
                    _depth=_depth + 1,
                )
            )
        return result
    if isinstance(value, list | tuple):
        items = [
            _sanitize(
                item,
                max_depth=max_depth,
                max_items=max_items,
                max_string_chars=max_string_chars,
                _depth=_depth + 1,
            )
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append("[truncated:items]")
        return items
    if isinstance(value, datetime):
        return _format_utc(value)
    if isinstance(value, str):
        return value if len(value) <= max_string_chars else value[:max_string_chars] + "[truncated]"
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:max_string_chars]


def _telemetry_summary(event: TelemetryEvent) -> dict[str, Any]:
    readings: list[dict[str, Any]] = []
    for reading in event.readings:
        metrics = {name: getattr(reading, name) for name in _METRIC_FIELDS if getattr(reading, name) is not None}
        metrics.update(reading.metrics_jsonb or {})
        readings.append({"pod_key": reading.pod_key, "enabled": reading.enabled, "metrics": metrics})
    return {
        "event_id": event.id,
        "node_id": event.device_id,
        "timestamp_utc": _format_utc(event.timestamp_utc),
        "readings": readings,
        "errors": [
            {"pod_key": error.pod_key, "sensor": error.sensor, "message": error.message} for error in event.errors
        ],
        "system_health": event.system_health_jsonb,
    }


def _photo_summary(photo: Photo) -> dict[str, Any]:
    return {
        "photo_id": photo.photo_id,
        "node_id": photo.device_id,
        "captured_at_utc": _format_utc(photo.captured_at_utc),
        "content_type": photo.content_type,
        "file_size_bytes": photo.file_size_bytes,
        "sharpness_score": photo.sharpness_score,
    }


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _fit_context(context: AssistantContext, max_bytes: int) -> AssistantContext:
    if _json_size(context.as_dict()) <= max_bytes:
        return context
    history = list(context.recent_history)
    anomalies = list(context.active_anomalies)
    photos = list(context.recent_photos)
    while history or anomalies or photos:
        largest = max(
            (("history", history), ("anomalies", anomalies), ("photos", photos)),
            key=lambda pair: _json_size(pair[1]),
        )[1]
        largest.pop()
        candidate = AssistantContext(
            node_id=context.node_id,
            generated_at=context.generated_at,
            current_state=context.current_state,
            recent_history=tuple(history),
            active_anomalies=tuple(anomalies),
            sensor_health=context.sensor_health,
            recent_photos=tuple(photos),
        )
        if _json_size(candidate.as_dict()) <= max_bytes:
            return candidate
    minimal = AssistantContext(
        node_id=context.node_id,
        generated_at=context.generated_at,
        current_state=None,
        recent_history=(),
        active_anomalies=(),
        sensor_health=None,
        recent_photos=(),
    )
    if _json_size(minimal.as_dict()) > max_bytes:
        raise AssistantContextError("max_context_bytes is too small for context envelope")
    return minimal
