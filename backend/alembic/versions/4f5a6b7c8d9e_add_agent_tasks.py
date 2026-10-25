"""add agent tasks, steps and agent cron

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "4f5a6b7c8d9e"
down_revision = "3e4f5a6b7c8d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent", sa.Column("cron_expr", sa.String(length=100), nullable=True))
    op.create_table(
        "agent_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("outcome", sa.String(length=10), nullable=True),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("critique", postgresql.JSONB(), nullable=True),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_agent_task_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('success','partial','failed')", name="ck_agent_task_outcome"),
        sa.CheckConstraint("trigger IN ('manual','cron')", name="ck_agent_task_trigger"),
    )
    op.create_index("ix_agent_task_agent_created", "agent_task", ["agent_id", sa.text("created_at DESC")])
    op.create_index("ix_agent_task_queue", "agent_task", ["created_at"], postgresql_where=sa.text("status = 'queued'"))
    op.create_index("ix_agent_task_running", "agent_task", ["agent_id"], postgresql_where=sa.text("status = 'running'"))
    # Phrased as NOT IN the final states so a future open state (waiting_approval)
    # stays covered without another migration.
    op.create_index("uq_agent_task_open_per_agent", "agent_task", ["agent_id"], unique=True,
                     postgresql_where=sa.text("status NOT IN ('completed','failed','cancelled')"))
    op.create_table(
        "agent_task_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("prompt", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "seq", name="uq_agent_task_step_seq"),
        sa.CheckConstraint("kind IN ('plan','turn','tool_call','critique','report','error')", name="ck_agent_task_step_kind"),
    )


def downgrade():
    op.drop_table("agent_task_step")
    op.drop_index("uq_agent_task_open_per_agent", table_name="agent_task")
    op.drop_index("ix_agent_task_running", table_name="agent_task")
    op.drop_index("ix_agent_task_queue", table_name="agent_task")
    op.drop_index("ix_agent_task_agent_created", table_name="agent_task")
    op.drop_table("agent_task")
    op.drop_column("agent", "cron_expr")
