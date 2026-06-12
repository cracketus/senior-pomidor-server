"""add telemetry system health

Revision ID: 0002_system_health
Revises: 0001_initial
Create Date: 2026-06-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_system_health"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("telemetry_events", sa.Column("system_health_jsonb", json_type, nullable=True))


def downgrade() -> None:
    op.drop_column("telemetry_events", "system_health_jsonb")
