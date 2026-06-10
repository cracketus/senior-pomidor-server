from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Device, Photo, PodReading, TelemetryEvent
from app.services import persist_photo, persist_telemetry
from app.validation import ValidationError, parse_utc_z

router = APIRouter(prefix="/api/v1")


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat().replace("+00:00", "Z")


def event_to_dict(event: TelemetryEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "device_id": event.device_id,
        "timestamp_utc": format_utc(event.timestamp_utc),
        "schema_version": event.schema_version,
        "source": event.source,
        "received_at": format_utc(event.received_at),
        "readings": [
            {
                "pod_key": reading.pod_key,
                "enabled": reading.enabled,
                "metrics": {
                    key: value
                    for key, value in {
                        "adc_raw": reading.adc_raw,
                        "soil_moisture_percent": reading.soil_moisture_percent,
                        "soil_temperature_c": reading.soil_temperature_c,
                        "air_temperature_c": reading.air_temperature_c,
                        "air_humidity_percent": reading.air_humidity_percent,
                        "air_pressure_hpa": reading.air_pressure_hpa,
                        "light_lux": reading.light_lux,
                        "ir_ambient_temp_c": reading.ir_ambient_temp_c,
                        "leaf_temp_c": reading.leaf_temp_c,
                        **reading.metrics_jsonb,
                    }.items()
                    if value is not None
                },
            }
            for reading in event.readings
        ],
        "errors": [
            {"pod_key": error.pod_key, "sensor": error.sensor, "message": error.message}
            for error in event.errors
        ],
    }


def photo_to_dict(photo: Photo) -> dict[str, Any]:
    return {
        "photo_id": photo.photo_id,
        "device_id": photo.device_id,
        "captured_at_utc": format_utc(photo.captured_at_utc),
        "schema_version": photo.schema_version,
        "sharpness_score": photo.sharpness_score,
        "content_type": photo.content_type,
        "file_size_bytes": photo.file_size_bytes,
        "sha256": photo.sha256,
        "received_at": format_utc(photo.received_at),
    }


@router.post("/edge/telemetry", status_code=status.HTTP_202_ACCEPTED)
def ingest_telemetry(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        event = persist_telemetry(db, payload, source="http")
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"accepted": True, "event_id": event.id}


@router.post("/edge/photos")
async def upload_photo(
    response: Response,
    photo_id: Annotated[str, Form()],
    device_id: Annotated[str, Form()],
    captured_at_utc: Annotated[str, Form()],
    schema_version: Annotated[str, Form()],
    photo: Annotated[UploadFile, File()],
    sharpness_score: Annotated[float | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if settings.photo_upload_token:
        expected = f"Bearer {settings.photo_upload_token}"
        if authorization != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid photo upload token")
    if photo.content_type not in {"image/jpeg", "image/pjpeg"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="photo must be JPEG")
    content = await photo.read()
    if len(content) > settings.photo_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="photo exceeds size limit")
    if not content.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="photo must be JPEG")
    try:
        stored, created = persist_photo(
            db,
            photo_id=photo_id,
            device_id=device_id,
            captured_at_utc=captured_at_utc,
            schema_version=schema_version,
            sharpness_score=sharpness_score,
            content_type=photo.content_type or "image/jpeg",
            content=content,
            storage_dir=settings.photo_storage_dir,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return {"accepted": True, "created": created, "photo": photo_to_dict(stored)}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    devices = db.scalars(select(Device).order_by(Device.device_id)).all()
    return [
        {
            "device_id": device.device_id,
            "first_seen_at": format_utc(device.first_seen_at),
            "last_seen_at": format_utc(device.last_seen_at),
            "last_payload_at": format_utc(device.last_payload_at),
        }
        for device in devices
    ]


@router.get("/devices/{device_id}/latest")
def latest_telemetry(device_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    event = db.scalar(
        select(TelemetryEvent)
        .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
        .where(TelemetryEvent.device_id == device_id)
        .order_by(desc(TelemetryEvent.timestamp_utc))
        .limit(1)
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device telemetry not found")
    return event_to_dict(event)


@router.get("/devices/{device_id}/telemetry")
def telemetry_history(
    device_id: str,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    pod: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = (
        select(TelemetryEvent)
        .options(selectinload(TelemetryEvent.readings), selectinload(TelemetryEvent.errors))
        .where(TelemetryEvent.device_id == device_id)
        .order_by(TelemetryEvent.timestamp_utc)
    )
    try:
        if from_:
            query = query.where(TelemetryEvent.timestamp_utc >= parse_utc_z(from_))
        if to:
            query = query.where(TelemetryEvent.timestamp_utc <= parse_utc_z(to))
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    events = db.scalars(query).all()
    if pod:
        event_ids = db.scalars(
            select(PodReading.telemetry_event_id).where(PodReading.device_id == device_id, PodReading.pod_key == pod)
        ).all()
        event_id_set = set(event_ids)
        events = [event for event in events if event.id in event_id_set]
    return [event_to_dict(event) for event in events]


@router.get("/devices/{device_id}/photos")
def list_photos(device_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    photos = db.scalars(select(Photo).where(Photo.device_id == device_id).order_by(desc(Photo.captured_at_utc))).all()
    return [photo_to_dict(photo) for photo in photos]


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, db: Session = Depends(get_db)) -> FileResponse:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="photo not found")
    path = Path(photo.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="photo file not found")
    return FileResponse(path, media_type=photo.content_type, filename=path.name)
