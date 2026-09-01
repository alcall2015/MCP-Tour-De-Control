"""add pair_id indexes on the sim_pair child tables

The retention purge deletes from all three child tables by pair_id, and none of
them carried an index on that column: every purge was a sequential scan.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_sim_pair_message_pair_id", "sim_pair_message", ["pair_id"])
    op.create_index("ix_sim_pair_history_pair_id", "sim_pair_history", ["pair_id"])
    op.create_index("ix_sim_pair_message_queue_pair_id", "sim_pair_message_queue", ["pair_id"])


def downgrade() -> None:
    op.drop_index("ix_sim_pair_message_queue_pair_id", table_name="sim_pair_message_queue")
    op.drop_index("ix_sim_pair_history_pair_id", table_name="sim_pair_history")
    op.drop_index("ix_sim_pair_message_pair_id", table_name="sim_pair_message")
