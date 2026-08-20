"""add telemetry record id

Revision ID: 0009_telemetry_record_id
Revises: 0008_story_environment
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_telemetry_record_id"
down_revision: str | None = "0008_story_environment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("telemetry_events", sa.Column("record_id", sa.String(length=128), nullable=True))
    op.create_index("ix_telemetry_events_record_id", "telemetry_events", ["record_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_telemetry_events_record_id", table_name="telemetry_events")
    op.drop_column("telemetry_events", "record_id")
