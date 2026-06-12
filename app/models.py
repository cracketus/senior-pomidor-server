from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_payload_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"
    __table_args__ = (
        UniqueConstraint("device_id", "timestamp_utc", "schema_version", name="uq_telemetry_event_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), index=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_payload_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    system_health_jsonb: Mapped[dict | None] = mapped_column(JSON_TYPE)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    readings: Mapped[list["PodReading"]] = relationship(cascade="all, delete-orphan")
    errors: Mapped[list["PodError"]] = relationship(cascade="all, delete-orphan")


class PodReading(Base):
    __tablename__ = "pod_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telemetry_event_id: Mapped[int] = mapped_column(ForeignKey("telemetry_events.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    pod_key: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adc_raw: Mapped[float | None] = mapped_column(Float)
    soil_moisture_percent: Mapped[float | None] = mapped_column(Float)
    soil_temperature_c: Mapped[float | None] = mapped_column(Float)
    air_temperature_c: Mapped[float | None] = mapped_column(Float)
    air_humidity_percent: Mapped[float | None] = mapped_column(Float)
    air_pressure_hpa: Mapped[float | None] = mapped_column(Float)
    light_lux: Mapped[float | None] = mapped_column(Float)
    ir_ambient_temp_c: Mapped[float | None] = mapped_column(Float)
    leaf_temp_c: Mapped[float | None] = mapped_column(Float)
    metrics_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)


class PodError(Base):
    __tablename__ = "pod_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telemetry_event_id: Mapped[int] = mapped_column(ForeignKey("telemetry_events.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    pod_key: Mapped[str] = mapped_column(String(64), index=True)
    sensor: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text, nullable=False)


class Photo(Base):
    __tablename__ = "photos"

    photo_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), index=True)
    captured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    sharpness_score: Mapped[float | None] = mapped_column(Float)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
