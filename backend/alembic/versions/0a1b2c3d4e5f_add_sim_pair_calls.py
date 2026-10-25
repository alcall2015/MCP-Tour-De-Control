"""add internal SIM pair calls

Revision ID: 0a1b2c3d4e5f
Revises: d4e5f6a7b8c9
"""
import sqlalchemy as sa
from alembic import op

revision = "0a1b2c3d4e5f"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("config", sa.Column("pairing_call_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("config", sa.Column("pairing_call_interval_minutes", sa.Integer(), nullable=False, server_default="360"))
    op.add_column("config", sa.Column("pairing_call_min_seconds", sa.Integer(), nullable=False, server_default="45"))
    op.add_column("config", sa.Column("pairing_call_max_seconds", sa.Integer(), nullable=False, server_default="75"))
    op.add_column("config", sa.Column("pairing_call_max_per_run", sa.Integer(), nullable=False, server_default="5"))
    op.create_table("sim_pair_call", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("pair_id", sa.UUID(), nullable=False), sa.Column("from_sim_id", sa.Integer(), nullable=False), sa.Column("to_sim_id", sa.Integer(), nullable=False), sa.Column("hold_seconds", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("error", sa.Text(), nullable=True), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table("sim_pair_call")
    for column in ("pairing_call_max_per_run", "pairing_call_max_seconds", "pairing_call_min_seconds", "pairing_call_interval_minutes", "pairing_call_enabled"):
        op.drop_column("config", column)
