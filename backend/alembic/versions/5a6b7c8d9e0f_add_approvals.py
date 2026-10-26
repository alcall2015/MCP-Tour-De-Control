"""add tool policies, approvals, agent risk ceiling, waiting_approval

Revision ID: 5a6b7c8d9e0f
Revises: 4f5a6b7c8d9e
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "5a6b7c8d9e0f"
down_revision = "4f5a6b7c8d9e"
branch_labels = None
depends_on = None

OLD_STATUS = "status IN ('queued','running','completed','failed','cancelled')"
NEW_STATUS = "status IN ('queued','running','waiting_approval','completed','failed','cancelled')"
OLD_KIND = "kind IN ('plan','turn','tool_call','critique','report','error')"
NEW_KIND = "kind IN ('plan','turn','tool_call','critique','report','error','approval_requested')"
TEMPLATE = ("Approbation requise · {agent}\n{tool} sur {server}\n{args}\n"
            "Répondre OUI {code} ou NON {code}\nExpire à {expires} · {link}")


def upgrade():
    op.add_column("agent", sa.Column("max_auto_risk", sa.SmallInteger(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_agent_max_auto_risk", "agent", "max_auto_risk BETWEEN 0 AND 2")

    op.drop_constraint("ck_agent_task_status", "agent_task", type_="check")
    op.create_check_constraint("ck_agent_task_status", "agent_task", NEW_STATUS)
    op.drop_constraint("ck_agent_task_step_kind", "agent_task_step", type_="check")
    op.create_check_constraint("ck_agent_task_step_kind", "agent_task_step", NEW_KIND)

    op.add_column("config", sa.Column("approval_expiry_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column("config", sa.Column("approval_whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("config", sa.Column("approval_whatsapp_number", sa.String(length=32), nullable=False, server_default="+2250700003331"))
    op.add_column("config", sa.Column("approval_whatsapp_server_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("config", sa.Column("approval_whatsapp_session_id", sa.String(length=100), nullable=True))
    op.add_column("config", sa.Column("approval_whatsapp_template", sa.Text(), nullable=False, server_default=TEMPLATE))

    op.create_table(
        "tool_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mcp_server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("risk_level", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("mcp_server_id", "tool_name", name="uq_tool_policy_server_tool"),
        sa.CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_tool_policy_risk_level"),
    )
    op.create_table(
        "approval",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=False),
        sa.Column("call_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notify_error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending','approved','rejected','expired')", name="ck_approval_status"),
        sa.CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_approval_risk_level"),
    )
    op.create_index("ix_approval_pending", "approval", ["expires_at"], postgresql_where=sa.text("status = 'pending'"))
    op.create_index("ix_approval_task", "approval", ["task_id", "step_seq"])


def downgrade():
    op.drop_index("ix_approval_task", table_name="approval")
    op.drop_index("ix_approval_pending", table_name="approval")
    op.drop_table("approval")
    op.drop_table("tool_policy")
    for column in ("approval_whatsapp_template", "approval_whatsapp_session_id", "approval_whatsapp_server_id",
                   "approval_whatsapp_number", "approval_whatsapp_enabled", "approval_expiry_hours"):
        op.drop_column("config", column)
    op.drop_constraint("ck_agent_task_step_kind", "agent_task_step", type_="check")
    op.create_check_constraint("ck_agent_task_step_kind", "agent_task_step", OLD_KIND)
    op.drop_constraint("ck_agent_task_status", "agent_task", type_="check")
    op.create_check_constraint("ck_agent_task_status", "agent_task", OLD_STATUS)
    op.drop_constraint("ck_agent_max_auto_risk", "agent", type_="check")
    op.drop_column("agent", "max_auto_risk")
