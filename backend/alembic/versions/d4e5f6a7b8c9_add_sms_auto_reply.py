"""add sms auto-reply

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE = "Salut, j'essaye de te joindre. Ecris-moi sur WhatsApp au {whatsapp}."


def upgrade() -> None:
    op.create_table(
        "sms_reply",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("trigger_kind", sa.String(20), nullable=False),
        sa.Column("trigger_ref", sa.String(200), nullable=False, unique=True),
        sa.Column("sim_id", sa.Integer(), nullable=False),
        sa.Column("to_number", sa.String(40), nullable=False),
        sa.Column("whatsapp_number", sa.String(40), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sms_reply_created", "sms_reply", ["created_at"])
    # The per-recipient cooldown queries by number and date on every run.
    op.create_index("ix_sms_reply_recipient", "sms_reply", ["to_number", "created_at"])
    op.add_column("config", sa.Column("sms_autoreply_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("config", sa.Column("sms_autoreply_template", sa.Text(), nullable=False, server_default=TEMPLATE))
    op.add_column("config", sa.Column("sms_autoreply_max_per_run", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("config", sa.Column("sms_autoreply_lookback_minutes", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("config", sa.Column("sms_autoreply_recipient_cooldown_hours", sa.Integer(), nullable=False, server_default="24"))


def downgrade() -> None:
    for column in ("sms_autoreply_recipient_cooldown_hours", "sms_autoreply_lookback_minutes",
                   "sms_autoreply_max_per_run", "sms_autoreply_template", "sms_autoreply_enabled"):
        op.drop_column("config", column)
    op.drop_index("ix_sms_reply_recipient", table_name="sms_reply")
    op.drop_index("ix_sms_reply_created", table_name="sms_reply")
    op.drop_table("sms_reply")
