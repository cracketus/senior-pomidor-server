"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(length=128), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_payload_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("raw_payload_jsonb", json_type, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("device_id", "timestamp_utc", "schema_version", name="uq_telemetry_event_identity"),
    )
    op.create_index("ix_telemetry_device_timestamp", "telemetry_events", ["device_id", "timestamp_utc"])
    op.create_table(
        "pod_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "telemetry_event_id", sa.Integer(), sa.ForeignKey("telemetry_events.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("pod_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("adc_raw", sa.Float(), nullable=True),
        sa.Column("soil_moisture_percent", sa.Float(), nullable=True),
        sa.Column("soil_temperature_c", sa.Float(), nullable=True),
        sa.Column("air_temperature_c", sa.Float(), nullable=True),
        sa.Column("air_humidity_percent", sa.Float(), nullable=True),
        sa.Column("air_pressure_hpa", sa.Float(), nullable=True),
        sa.Column("light_lux", sa.Float(), nullable=True),
        sa.Column("ir_ambient_temp_c", sa.Float(), nullable=True),
        sa.Column("leaf_temp_c", sa.Float(), nullable=True),
        sa.Column("metrics_jsonb", json_type, nullable=False),
    )
    op.create_table(
        "pod_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "telemetry_event_id", sa.Integer(), sa.ForeignKey("telemetry_events.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("pod_key", sa.String(length=64), nullable=False),
        sa.Column("sensor", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_table(
        "photos",
        sa.Column("photo_id", sa.String(length=128), primary_key=True),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("captured_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=128), nullable=False),
        sa.Column("sharpness_score", sa.Float(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_photos_device_captured", "photos", ["device_id", "captured_at_utc"])


def downgrade() -> None:
    op.drop_index("ix_photos_device_captured", table_name="photos")
    op.drop_table("photos")
    op.drop_table("pod_errors")
    op.drop_table("pod_readings")
    op.drop_index("ix_telemetry_device_timestamp", table_name="telemetry_events")
    op.drop_table("telemetry_events")
    op.drop_table("devices")
