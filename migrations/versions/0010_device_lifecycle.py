"""add additive device lifecycle state and audit events

Revision ID: 0010_device_lifecycle
Revises: 0009_telemetry_record_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010_device_lifecycle"
down_revision: str | None = "0009_telemetry_record_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column("devices", "lifecycle_state"):
        op.add_column(
            "devices",
            sa.Column("lifecycle_state", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        )
    if not _has_column("devices", "lifecycle_changed_at"):
        op.add_column("devices", sa.Column("lifecycle_changed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("devices", "lifecycle_reason_code"):
        op.add_column("devices", sa.Column("lifecycle_reason_code", sa.String(length=64), nullable=True))
    # Keep the server default: it is both a safe backfill for old rows and a
    # compatibility guard for writers that do not know the additive column.
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = {item["name"] for item in inspector.get_check_constraints("devices")}
    if "ck_devices_lifecycle_state" not in constraints:
        with op.batch_alter_table("devices") as batch_op:
            batch_op.create_check_constraint(
                "ck_devices_lifecycle_state",
                "lifecycle_state IN ('ACTIVE', 'DECOMMISSIONED')",
            )
    if "device_lifecycle_events" not in inspector.get_table_names():
        op.create_table(
            "device_lifecycle_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
            sa.Column("from_state", sa.String(length=32), nullable=False),
            sa.Column("to_state", sa.String(length=32), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason_code", sa.String(length=64), nullable=False),
            sa.CheckConstraint(
                "from_state IN ('ACTIVE', 'DECOMMISSIONED') AND to_state IN ('ACTIVE', 'DECOMMISSIONED')",
                name="ck_device_lifecycle_event_states",
            ),
        )
        op.create_index("ix_device_lifecycle_events_device_id", "device_lifecycle_events", ["device_id"])


def downgrade() -> None:
    # Deliberately retain additive lifecycle objects so a v0.3.0 application remains
    # ready after rollback and a later upgrade can validate/reuse the schema.
    pass
