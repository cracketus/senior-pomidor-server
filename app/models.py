from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    air_actual_vapor_pressure_kpa: Mapped[float | None] = mapped_column(Float)
    air_saturation_vapor_pressure_kpa: Mapped[float | None] = mapped_column(Float)
    air_vpd_kpa: Mapped[float | None] = mapped_column(Float)
    light_lux: Mapped[float | None] = mapped_column(Float)
    ir_ambient_temp_c: Mapped[float | None] = mapped_column(Float)
    leaf_temp_c: Mapped[float | None] = mapped_column(Float)
    leaf_saturation_vapor_pressure_kpa: Mapped[float | None] = mapped_column(Float)
    leaf_vpd_kpa: Mapped[float | None] = mapped_column(Float)
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


class StateSnapshot(Base):
    __tablename__ = "state_snapshots"

    state_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SensorHealthSnapshot(Base):
    __tablename__ = "sensor_health_snapshots"

    health_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)


class AnomalyRecord(Base):
    __tablename__ = "anomaly_records"

    anomaly_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    type: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state_id: Mapped[str | None] = mapped_column(String(256), index=True)
    payload_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)


class EstimatorDiagnostic(Base):
    __tablename__ = "estimator_diagnostics"

    diagnostic_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state_id: Mapped[str | None] = mapped_column(String(256), index=True)
    payload_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)


class ActionSimulation(Base):
    __tablename__ = "action_simulations"

    simulation_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state_id: Mapped[str | None] = mapped_column(String(256), index=True)
    decision: Mapped[str] = mapped_column(String(64), index=True)
    payload_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)


class DailyStoryRun(Base):
    __tablename__ = "daily_story_runs"
    __table_args__ = (
        UniqueConstraint("node_id", "story_date", name="uq_daily_story_run_node_date"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'skipped_no_data', 'failed')",
            name="ck_daily_story_run_status",
        ),
        CheckConstraint("attempt_count >= 1", name="ck_daily_story_run_attempt_count"),
        CheckConstraint(
            "(status = 'succeeded' AND story IS NOT NULL) OR (status <> 'succeeded' AND story IS NULL)",
            name="ck_daily_story_run_story_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    story_date: Mapped[date] = mapped_column(Date, index=True)
    window_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    story: Mapped[str | None] = mapped_column(String(280))
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    ollama_options_jsonb: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    user_prompt: Mapped[str | None] = mapped_column(Text)
    input_summary_jsonb: Mapped[dict | None] = mapped_column(JSON_TYPE)
    runtime_metrics_jsonb: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error_details: Mapped[str | None] = mapped_column(Text)
