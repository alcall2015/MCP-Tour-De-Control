"""add agents and agent_mcp_server

Revision ID: 1c2d3e4f5a6b
Revises: f6a7b8c9d0e1
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "1c2d3e4f5a6b"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','active','paused','archived')", name="ck_agent_status"),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 100", name="ck_agent_max_steps"),
        sa.CheckConstraint("timeout_seconds BETWEEN 10 AND 3600", name="ck_agent_timeout_seconds"),
    )
    op.create_table(
        "agent_mcp_server",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mcp_server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_server.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade():
    op.drop_table("agent_mcp_server")
    op.drop_table("agent")
