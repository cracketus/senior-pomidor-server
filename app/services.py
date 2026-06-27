import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Device, Photo, PodError, PodReading, TelemetryEvent
from app.telemetry import (
    iter_pod_errors,
    iter_pods,
    iter_unmatched_pod_errors,
    normalize_system_health,
    pod_enabled,
    pod_key,
    pod_metrics,
)
from app.validation import (
    PHOTO_SCHEMA,
    ValidationError,
    parse_utc_z,
    validate_device_id,
    validate_photo_id,
    validate_pod_key,
    validate_telemetry_payload,
)


def resolve_photo_storage_dir(storage_dir: str) -> Path:
    return Path(storage_dir).expanduser().resolve()


def resolve_photo_target_path(storage_dir: str, device_id: str, photo_id: str) -> Path:
    base_dir = resolve_photo_storage_dir(storage_dir)
    target_path = (base_dir / device_id / f"{photo_id}.jpg").resolve()
    if not target_path.is_relative_to(base_dir):
        raise ValidationError("photo storage path escapes storage directory")
    return target_path


def resolve_stored_photo_path(storage_dir: str, storage_path: str) -> Path:
    base_dir = resolve_photo_storage_dir(storage_dir)
    path = Path(storage_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if not resolved.is_relative_to(base_dir):
        raise ValidationError("photo storage path escapes storage directory")
    return resolved


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def upsert_device(db: Session, device_id: str, payload_at: datetime, received_at: datetime) -> Device:
    device_id = validate_device_id(device_id)
    device = db.get(Device, device_id)
    if device is None:
        device = Device(
            device_id=device_id,
            first_seen_at=received_at,
            last_seen_at=received_at,
            last_payload_at=payload_at,
        )
        db.add(device)
    else:
        device.last_seen_at = received_at
        if payload_at > as_utc(device.last_payload_at):
            device.last_payload_at = payload_at
    return device


def persist_telemetry(db: Session, payload: dict[str, Any], source: str) -> TelemetryEvent:
    device_id, timestamp = validate_telemetry_payload(payload)
    schema_version = payload.get("schema_version") or payload.get("schema")
    received_at = now_utc()
    upsert_device(db, device_id, timestamp, received_at)

    event = TelemetryEvent(
        device_id=device_id,
        timestamp_utc=timestamp,
        schema_version=schema_version,
        source=source,
        raw_payload_jsonb=payload,
        system_health_jsonb=normalize_system_health(payload),
        received_at=received_at,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(TelemetryEvent).where(
                TelemetryEvent.device_id == device_id,
                TelemetryEvent.timestamp_utc == timestamp,
                TelemetryEvent.schema_version == schema_version,
            )
        )
        if existing is None:
            raise
        return existing

    pod_keys: set[str] = set()
    for index, pod in enumerate(iter_pods(payload)):
        key = pod_key(pod, index)
        pod_keys.add(key)
        known, unknown = pod_metrics(pod)
        db.add(
            PodReading(
                telemetry_event_id=event.id,
                device_id=device_id,
                pod_key=key,
                enabled=pod_enabled(pod),
                metrics_jsonb=unknown,
                **known,
            )
        )
        for error in iter_pod_errors(payload, pod, key):
            db.add(
                PodError(
                    telemetry_event_id=event.id,
                    device_id=device_id,
                    pod_key=validate_pod_key(error["pod_key"]),
                    sensor=error["sensor"],
                    message=str(error["message"]),
                )
            )
    for error in iter_unmatched_pod_errors(payload, pod_keys):
        key = validate_pod_key(error["pod_key"])
        db.add(
            PodError(
                telemetry_event_id=event.id,
                device_id=device_id,
                pod_key=key,
                sensor=error["sensor"],
                message=str(error["message"]),
            )
        )
    db.commit()
    db.refresh(event)
    return event


def persist_photo(
    db: Session,
    *,
    photo_id: str,
    device_id: str,
    captured_at_utc: str,
    schema_version: str,
    sharpness_score: float | None,
    content_type: str,
    content: bytes,
    storage_dir: str,
) -> tuple[Photo, bool]:
    if schema_version != PHOTO_SCHEMA:
        raise ValidationError(f"unsupported photo schema: {schema_version}")
    captured_at = parse_utc_z(captured_at_utc)
    photo_id = validate_photo_id(photo_id)
    device_id = validate_device_id(device_id)
    existing = db.get(Photo, photo_id)
    if existing is not None:
        return existing, False

    received_at = now_utc()
    upsert_device(db, device_id, captured_at, received_at)
    digest = hashlib.sha256(content).hexdigest()
    target_path = resolve_photo_target_path(storage_dir, device_id, photo_id)
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)

    photo = Photo(
        photo_id=photo_id,
        device_id=device_id,
        captured_at_utc=captured_at,
        schema_version=schema_version,
        sharpness_score=sharpness_score,
        content_type=content_type,
        file_size_bytes=len(content),
        storage_path=str(target_path),
        sha256=digest,
        received_at=received_at,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo, True
