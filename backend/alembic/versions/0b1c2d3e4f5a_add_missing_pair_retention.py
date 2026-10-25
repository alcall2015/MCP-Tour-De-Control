"""add missing pairing archive retention column on production chain

Revision ID: 0b1c2d3e4f5a
Revises: 0a1b2c3d4e5f
"""
import sqlalchemy as sa
from alembic import op

revision = "0b1c2d3e4f5a"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None

def _has_column(table: str, column: str) -> bool:
    """True when the column already exists, so a DB that took the other
    branch of the pairing-retention fork can be upgraded through this one."""
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if _has_column("config", "pairing_archive_retention_days"):
        return
    op.add_column("config", sa.Column("pairing_archive_retention_days", sa.Integer(), nullable=False, server_default="90"))

def downgrade():
    if _has_column("config", "pairing_archive_retention_days"):
        op.drop_column("config", "pairing_archive_retention_days")
