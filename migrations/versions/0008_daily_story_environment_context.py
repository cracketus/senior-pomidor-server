"""add daily story environment context

Revision ID: 0008_story_environment
Revises: 0007_daily_story_runs
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models import JSON_TYPE

revision: str = "0008_story_environment"
down_revision: str | None = "0007_daily_story_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("daily_story_runs", sa.Column("environment_context_jsonb", JSON_TYPE, nullable=True))


def downgrade() -> None:
    op.drop_column("daily_story_runs", "environment_context_jsonb")
