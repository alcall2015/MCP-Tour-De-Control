"""add mcp_server api_key column

Revision ID: a1b2c3d4e5f6
Revises: 47a0603e908a
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '47a0603e908a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mcp_server', sa.Column('api_key', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('mcp_server', 'api_key')
