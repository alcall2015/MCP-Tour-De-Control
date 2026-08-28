import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base


class SmsReply(Base):
    """One automatic reply.

    `trigger_ref` is unique on purpose: the 15-minute job re-reads an
    overlapping window, and this constraint is what stops a second reply.
    The row is committed as "sending" before the SMS leaves, so a crash
    mid-send leaves the trigger claimed rather than free to be answered again.
    """

    __tablename__ = "sms_reply"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_kind: Mapped[str] = mapped_column(String(20))  # "sms" | "missed_call"
    trigger_ref: Mapped[str] = mapped_column(String(200), unique=True)
    sim_id: Mapped[int] = mapped_column(Integer)
    to_number: Mapped[str] = mapped_column(String(40))
    whatsapp_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sending | sent | failed | skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
