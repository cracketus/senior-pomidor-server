"""add action simulation table

Revision ID: 0006_action_simulations
Revises: 0005_state_estimator_v1
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models import JSON_TYPE

revision: str = "0006_action_simulations"
down_revision: str | None = "0005_state_estimator_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_simulations",
        sa.Column("simulation_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_id", sa.String(length=256), nullable=True),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("payload_jsonb", JSON_TYPE, nullable=False),
        sa.PrimaryKeyConstraint("simulation_id"),
    )
    op.create_index(op.f("ix_action_simulations_decision"), "action_simulations", ["decision"])
    op.create_index(op.f("ix_action_simulations_node_id"), "action_simulations", ["node_id"])
    op.create_index(op.f("ix_action_simulations_state_id"), "action_simulations", ["state_id"])
    op.create_index(op.f("ix_action_simulations_ts"), "action_simulations", ["ts"])


def downgrade() -> None:
    op.drop_index(op.f("ix_action_simulations_ts"), table_name="action_simulations")
    op.drop_index(op.f("ix_action_simulations_state_id"), table_name="action_simulations")
    op.drop_index(op.f("ix_action_simulations_node_id"), table_name="action_simulations")
    op.drop_index(op.f("ix_action_simulations_decision"), table_name="action_simulations")
    op.drop_table("action_simulations")
