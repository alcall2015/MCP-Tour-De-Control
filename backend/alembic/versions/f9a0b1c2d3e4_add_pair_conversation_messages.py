"""add OpenRouter-backed SIM pair conversation history

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("config", sa.Column("pairing_openrouter_api_key", sa.String(500), nullable=False, server_default=""))
    op.add_column("config", sa.Column("pairing_openrouter_model", sa.String(150), nullable=False, server_default="google/gemini-2.5-flash"))
    op.add_column("config", sa.Column("pairing_conversation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("config", sa.Column("pairing_conversation_interval_minutes", sa.Integer(), nullable=False, server_default="180"))
    op.alter_column("config", "pairing_openrouter_api_key", server_default=None)
    op.alter_column("config", "pairing_openrouter_model", server_default=None)
    op.alter_column("config", "pairing_conversation_enabled", server_default=None)
    op.alter_column("config", "pairing_conversation_interval_minutes", server_default=None)
    op.create_table(
        "sim_pair_message",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("pair_id", sa.UUID(), nullable=False),
        sa.Column("from_sim_id", sa.Integer(), nullable=False),
        sa.Column("to_sim_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sim_pair_message")
    op.drop_column("config", "pairing_conversation_interval_minutes")
    op.drop_column("config", "pairing_conversation_enabled")
    op.drop_column("config", "pairing_openrouter_model")
    op.drop_column("config", "pairing_openrouter_api_key")
