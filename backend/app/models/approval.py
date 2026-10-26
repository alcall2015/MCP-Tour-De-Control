import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base

APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class Approval(Base):
    """One operator decision bound to one exact tool call of one task."""
    __tablename__ = "approval"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_task.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"))
    step_seq: Mapped[int] = mapped_column(Integer)
    call_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(200))
    server_name: Mapped[str] = mapped_column(String(200))
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    args_hash: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[int] = mapped_column(SmallInteger)
    code: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notify_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','expired')", name="ck_approval_status"),
        CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_approval_risk_level"),
        Index("ix_approval_pending", "expires_at", postgresql_where=text("status = 'pending'")),
        Index("ix_approval_task", "task_id", "step_seq"),
        Index("uq_approval_code_pending", "code", unique=True, postgresql_where=text("status = 'pending'")),
    )
