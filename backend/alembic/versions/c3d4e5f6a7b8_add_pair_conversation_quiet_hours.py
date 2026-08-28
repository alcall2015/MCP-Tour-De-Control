"""add fleet-wide quiet hours for pair conversations

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enabled by default: overnight SMS is the one remaining way this traffic
    # does not look like a conversation between two people.
    op.add_column("config", sa.Column("pairing_quiet_hours_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("config", sa.Column("pairing_quiet_start_hour", sa.Integer(), nullable=False, server_default="22"))
    op.add_column("config", sa.Column("pairing_quiet_end_hour", sa.Integer(), nullable=False, server_default="7"))


def downgrade() -> None:
    op.drop_column("config", "pairing_quiet_end_hour")
    op.drop_column("config", "pairing_quiet_start_hour")
    op.drop_column("config", "pairing_quiet_hours_enabled")
