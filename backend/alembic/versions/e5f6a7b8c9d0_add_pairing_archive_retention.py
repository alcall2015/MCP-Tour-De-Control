"""add pairing archive retention

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("config", sa.Column("pairing_archive_retention_days", sa.Integer(),
                                      nullable=False, server_default="90"))


def downgrade() -> None:
    op.drop_column("config", "pairing_archive_retention_days")
