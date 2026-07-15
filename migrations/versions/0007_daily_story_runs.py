"""add daily story runs

Revision ID: 0007_daily_story_runs
Revises: 0006_action_simulations
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models import JSON_TYPE

revision: str = "0007_daily_story_runs"
down_revision: str | None = "0006_action_simulations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_story_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("story_date", sa.Date(), nullable=False),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("story", sa.String(length=280), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("ollama_options_jsonb", JSON_TYPE, nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("user_prompt", sa.Text(), nullable=True),
        sa.Column("input_summary_jsonb", JSON_TYPE, nullable=True),
        sa.Column("runtime_metrics_jsonb", JSON_TYPE, nullable=True),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt_count >= 1", name="ck_daily_story_run_attempt_count"),
        sa.CheckConstraint(
            "(status = 'succeeded' AND story IS NOT NULL) OR (status <> 'succeeded' AND story IS NULL)",
            name="ck_daily_story_run_story_status",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'skipped_no_data', 'failed')",
            name="ck_daily_story_run_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", "story_date", name="uq_daily_story_run_node_date"),
    )
    op.create_index(op.f("ix_daily_story_runs_node_id"), "daily_story_runs", ["node_id"])
    op.create_index(op.f("ix_daily_story_runs_status"), "daily_story_runs", ["status"])
    op.create_index(op.f("ix_daily_story_runs_story_date"), "daily_story_runs", ["story_date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_story_runs_story_date"), table_name="daily_story_runs")
    op.drop_index(op.f("ix_daily_story_runs_status"), table_name="daily_story_runs")
    op.drop_index(op.f("ix_daily_story_runs_node_id"), table_name="daily_story_runs")
    op.drop_table("daily_story_runs")
