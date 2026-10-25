import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base

TASK_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
FINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
OUTCOMES = ("success", "partial", "failed")
TRIGGERS = ("manual", "cron")
STEP_KINDS = ("plan", "turn", "tool_call", "critique", "report", "error")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentTask(Base):
    __tablename__ = "agent_task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(20))
    # Snapshots: editing the agent never changes a task already in flight.
    objective: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    max_steps: Mapped[int] = mapped_column(Integer)
    timeout_seconds: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(10), nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    critique: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)

    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["AgentTaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="AgentTaskStep.seq"
    )

    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_agent_task_status"),
        CheckConstraint("outcome IS NULL OR outcome IN ('success','partial','failed')", name="ck_agent_task_outcome"),
        CheckConstraint("trigger IN ('manual','cron')", name="ck_agent_task_trigger"),
        Index("ix_agent_task_agent_created", "agent_id", text("created_at DESC")),
        Index("ix_agent_task_queue", "created_at", postgresql_where=text("status = 'queued'")),
        Index("ix_agent_task_running", "agent_id", postgresql_where=text("status = 'running'")),
    )


class AgentTaskStep(Base):
    __tablename__ = "agent_task_step"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_task.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    prompt: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    task: Mapped[AgentTask] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("task_id", "seq", name="uq_agent_task_step_seq"),
        CheckConstraint("kind IN ('plan','turn','tool_call','critique','report','error')", name="ck_agent_task_step_kind"),
    )
