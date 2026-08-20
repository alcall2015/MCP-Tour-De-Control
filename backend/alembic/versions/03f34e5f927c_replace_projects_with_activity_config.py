"""replace projects with activity config

Revision ID: 03f34e5f927c
Revises: aa2d4bae63d4
Create Date: 2026-08-20 12:22:06.999929
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '03f34e5f927c'
down_revision: Union[str, None] = 'aa2d4bae63d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("project_snapshot")
    op.drop_table("project_link")
    op.drop_table("project")
    op.alter_column("config", "projects_cron", new_column_name="activity_cron")
    op.add_column(
        "config",
        sa.Column("drive_folder_id", sa.String(length=100), nullable=False, server_default=""),
    )
    op.alter_column("config", "drive_folder_id", server_default=None)


def downgrade() -> None:
    # Deliberately does NOT recreate the project/project_link/project_snapshot
    # tables: the Projects feature is gone for good, and a half-restored
    # schema (empty tables, no app code that reads or writes them) would be
    # worse than no schema at all.
    op.drop_column("config", "drive_folder_id")
    op.alter_column("config", "activity_cron", new_column_name="projects_cron")
