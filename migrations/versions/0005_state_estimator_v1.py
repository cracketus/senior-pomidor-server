"""add state estimator v1 tables

Revision ID: 0005_state_estimator_v1
Revises: 0004_vpd_metrics
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models import JSON_TYPE

revision: str = "0005_state_estimator_v1"
down_revision: str | None = "0004_vpd_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "state_snapshots",
        sa.Column("state_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_jsonb", JSON_TYPE, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state_id"),
    )
    op.create_index(op.f("ix_state_snapshots_node_id"), "state_snapshots", ["node_id"])
    op.create_index(op.f("ix_state_snapshots_ts"), "state_snapshots", ["ts"])

    op.create_table(
        "sensor_health_snapshots",
        sa.Column("health_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_jsonb", JSON_TYPE, nullable=False),
        sa.PrimaryKeyConstraint("health_id"),
    )
    op.create_index(op.f("ix_sensor_health_snapshots_node_id"), "sensor_health_snapshots", ["node_id"])
    op.create_index(op.f("ix_sensor_health_snapshots_ts"), "sensor_health_snapshots", ["ts"])

    op.create_table(
        "anomaly_records",
        sa.Column("anomaly_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_id", sa.String(length=256), nullable=True),
        sa.Column("payload_jsonb", JSON_TYPE, nullable=False),
        sa.PrimaryKeyConstraint("anomaly_id"),
    )
    op.create_index(op.f("ix_anomaly_records_node_id"), "anomaly_records", ["node_id"])
    op.create_index(op.f("ix_anomaly_records_state_id"), "anomaly_records", ["state_id"])
    op.create_index(op.f("ix_anomaly_records_status"), "anomaly_records", ["status"])
    op.create_index(op.f("ix_anomaly_records_ts"), "anomaly_records", ["ts"])
    op.create_index(op.f("ix_anomaly_records_type"), "anomaly_records", ["type"])

    op.create_table(
        "estimator_diagnostics",
        sa.Column("diagnostic_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_id", sa.String(length=256), nullable=True),
        sa.Column("payload_jsonb", JSON_TYPE, nullable=False),
        sa.PrimaryKeyConstraint("diagnostic_id"),
    )
    op.create_index(op.f("ix_estimator_diagnostics_node_id"), "estimator_diagnostics", ["node_id"])
    op.create_index(op.f("ix_estimator_diagnostics_state_id"), "estimator_diagnostics", ["state_id"])
    op.create_index(op.f("ix_estimator_diagnostics_ts"), "estimator_diagnostics", ["ts"])


def downgrade() -> None:
    op.drop_index(op.f("ix_estimator_diagnostics_ts"), table_name="estimator_diagnostics")
    op.drop_index(op.f("ix_estimator_diagnostics_state_id"), table_name="estimator_diagnostics")
    op.drop_index(op.f("ix_estimator_diagnostics_node_id"), table_name="estimator_diagnostics")
    op.drop_table("estimator_diagnostics")
    op.drop_index(op.f("ix_anomaly_records_type"), table_name="anomaly_records")
    op.drop_index(op.f("ix_anomaly_records_ts"), table_name="anomaly_records")
    op.drop_index(op.f("ix_anomaly_records_status"), table_name="anomaly_records")
    op.drop_index(op.f("ix_anomaly_records_state_id"), table_name="anomaly_records")
    op.drop_index(op.f("ix_anomaly_records_node_id"), table_name="anomaly_records")
    op.drop_table("anomaly_records")
    op.drop_index(op.f("ix_sensor_health_snapshots_ts"), table_name="sensor_health_snapshots")
    op.drop_index(op.f("ix_sensor_health_snapshots_node_id"), table_name="sensor_health_snapshots")
    op.drop_table("sensor_health_snapshots")
    op.drop_index(op.f("ix_state_snapshots_ts"), table_name="state_snapshots")
    op.drop_index(op.f("ix_state_snapshots_node_id"), table_name="state_snapshots")
    op.drop_table("state_snapshots")
