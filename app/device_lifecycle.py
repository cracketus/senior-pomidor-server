from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_analysis import format_utc
from app.models import Device, DeviceLifecycleEvent, DeviceLifecycleState
from app.validation import ValidationError, validate_device_id

MAX_REASON_CODE_LENGTH = 64


def validate_reason_code(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_REASON_CODE_LENGTH:
        raise ValidationError("reason_code must be a non-empty string of at most 64 characters")
    if not all(character.isalnum() or character in {"_", "-", "."} for character in value):
        raise ValidationError("reason_code contains unsupported characters")
    return value


def set_device_lifecycle(
    db: Session,
    *,
    device_id: str,
    target_state: DeviceLifecycleState | str,
    reason_code: str,
    expected_state: DeviceLifecycleState | str,
    apply: bool = False,
    changed_at: datetime | None = None,
) -> dict[str, object]:
    if not apply:
        raise ValidationError("--apply is required for lifecycle changes")
    device_id = validate_device_id(device_id)
    reason_code = validate_reason_code(reason_code)
    try:
        target = DeviceLifecycleState(target_state)
        expected = DeviceLifecycleState(expected_state)
    except ValueError as exc:
        raise ValidationError("unsupported lifecycle state") from exc

    device = db.scalar(select(Device).where(Device.device_id == device_id).with_for_update())
    if device is None:
        raise ValidationError("device not found")
    try:
        current = DeviceLifecycleState(device.lifecycle_state)
    except ValueError as exc:
        raise ValidationError("device has an unsupported persisted lifecycle state") from exc
    if current != expected:
        raise ValidationError(f"expected state {expected.value}, actual state {current.value}")
    if current == target:
        return {"device_id": device_id, "state": current.value, "changed": False, "reason_code": reason_code}

    timestamp = changed_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    db.add(
        DeviceLifecycleEvent(
            device_id=device_id,
            from_state=current.value,
            to_state=target.value,
            changed_at=timestamp,
            reason_code=reason_code,
        )
    )
    device.lifecycle_state = target.value
    device.lifecycle_changed_at = timestamp
    device.lifecycle_reason_code = reason_code
    db.commit()
    return {"device_id": device_id, "state": target.value, "changed": True, "reason_code": reason_code}


def show_device_lifecycle(db: Session, device_id: str) -> dict[str, object]:
    device_id = validate_device_id(device_id)
    device = db.get(Device, device_id)
    if device is None:
        raise ValidationError("device not found")
    events = db.scalars(
        select(DeviceLifecycleEvent)
        .where(DeviceLifecycleEvent.device_id == device_id)
        .order_by(DeviceLifecycleEvent.changed_at, DeviceLifecycleEvent.id)
    ).all()
    return {
        "device_id": device.device_id,
        "state": device.lifecycle_state,
        "changed_at": format_utc(device.lifecycle_changed_at) if device.lifecycle_changed_at else None,
        "reason_code": device.lifecycle_reason_code,
        "events": [
            {
                "from_state": event.from_state,
                "to_state": event.to_state,
                "changed_at": format_utc(event.changed_at),
                "reason_code": event.reason_code,
            }
            for event in events
        ],
    }
