"""add durable SIM pair message queue

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sim_pair_message_queue",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("pair_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sim_pair_message_queue_due", "sim_pair_message_queue", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_sim_pair_message_queue_due", table_name="sim_pair_message_queue")
    op.drop_table("sim_pair_message_queue")
