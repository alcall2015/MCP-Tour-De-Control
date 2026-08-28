"""add persistent local names for paired SIMs

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sim_pairing_sim",
        sa.Column("sim_id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("display_name"),
    )
    op.add_column("sim_pair", sa.Column("sim_a_name", sa.String(100), nullable=False, server_default=""))
    op.add_column("sim_pair", sa.Column("sim_b_name", sa.String(100), nullable=False, server_default=""))
    op.alter_column("sim_pair", "sim_a_name", server_default=None)
    op.alter_column("sim_pair", "sim_b_name", server_default=None)


def downgrade() -> None:
    op.drop_column("sim_pair", "sim_b_name")
    op.drop_column("sim_pair", "sim_a_name")
    op.drop_table("sim_pairing_sim")
