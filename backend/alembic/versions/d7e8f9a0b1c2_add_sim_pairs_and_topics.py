"""add SIM pairs, history, runs and conversation topics

Revision ID: d7e8f9a0b1c2
Revises: c9d4e1f2a3b4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c9d4e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("sim_pairing_topic", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("name", sa.String(200), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("name"))
    op.create_table("sim_pair", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("sim_a_id", sa.Integer(), nullable=False), sa.Column("sim_b_id", sa.Integer(), nullable=False), sa.Column("country", sa.String(100), nullable=False), sa.Column("group_a", sa.String(200), nullable=False), sa.Column("group_b", sa.String(200), nullable=False), sa.Column("topic", sa.String(200), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("archived_reason", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.create_table("sim_pair_history", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("pair_id", sa.UUID(), nullable=False), sa.Column("event", sa.String(50), nullable=False), sa.Column("details", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("sim_pairing_run", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("status", sa.String(20), nullable=False), sa.Column("summary", sa.JSON()), sa.Column("error", sa.Text()), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_table("sim_pairing_run")
    op.drop_table("sim_pair_history")
    op.drop_table("sim_pair")
    op.drop_table("sim_pairing_topic")
