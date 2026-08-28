"""add conversation target and pacing settings

Revision ID: b2c3d4e5f6a7
Revises: a0b1c2d3e4f5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sim_pair", sa.Column("target_messages", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("sim_pair", sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"))
    # Existing pairs keep the progress they already made; recounting from the
    # message table avoids restarting every conversation at zero.
    op.execute(
        "UPDATE sim_pair SET sent_count = ("
        " SELECT count(*) FROM sim_pair_message m"
        " WHERE m.pair_id = sim_pair.id AND m.status = 'sent')"
    )
    op.create_index("ix_sim_pair_progress", "sim_pair", ["status", "sent_count"])

    op.add_column("config", sa.Column("pairing_target_messages", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("config", sa.Column("pairing_max_messages_per_run", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("config", sa.Column("pairing_sim_cooldown_minutes", sa.Integer(), nullable=False, server_default="20"))


def downgrade() -> None:
    op.drop_column("config", "pairing_sim_cooldown_minutes")
    op.drop_column("config", "pairing_max_messages_per_run")
    op.drop_column("config", "pairing_target_messages")
    op.drop_index("ix_sim_pair_progress", table_name="sim_pair")
    op.drop_column("sim_pair", "sent_count")
    op.drop_column("sim_pair", "target_messages")
