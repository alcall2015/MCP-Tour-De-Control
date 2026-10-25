import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Integer, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Config(Base):
    __tablename__ = "config"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    llm_provider: Mapped[str] = mapped_column(String(50), default="openai")
    llm_model: Mapped[str] = mapped_column(String(100), default="gpt-4")
    api_key: Mapped[str] = mapped_column(String(500), default="")
    google_sa_key: Mapped[str] = mapped_column(Text, default="")
    drive_folder_id: Mapped[str] = mapped_column(String(100), default="")
    activity_cron: Mapped[str] = mapped_column(String(100), default="0 6 * * *")
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pairing_openrouter_api_key: Mapped[str] = mapped_column(String(500), default="")
    pairing_openrouter_model: Mapped[str] = mapped_column(String(150), default="google/gemini-2.5-flash")
    pairing_conversation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pairing_conversation_interval_minutes: Mapped[int] = mapped_column(Integer, default=180)
    pairing_target_messages: Mapped[int] = mapped_column(Integer, default=10)
    # A per-run ceiling that protects run duration, not a cadence knob: the
    # queue's due_at is what paces each pair.
    pairing_max_messages_per_run: Mapped[int] = mapped_column(Integer, default=10)
    pairing_sim_cooldown_minutes: Mapped[int] = mapped_column(Integer, default=20)
    # Quiet hours are fleet-wide and expressed in UTC. The SIMs span several
    # countries; one window for all of them is a deliberate simplification.
    pairing_quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pairing_quiet_start_hour: Mapped[int] = mapped_column(Integer, default=22)
    pairing_quiet_end_hour: Mapped[int] = mapped_column(Integer, default=7)
    sms_autoreply_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_autoreply_template: Mapped[str] = mapped_column(
        Text,
        default=(
            "Salut, j'essaie de te joindre. Ecris-moi sur WhatsApp au {whatsapp}.\n---\n"
            "Bonjour, je n'ai pas pu te joindre. Ecris-moi sur WhatsApp au {whatsapp}.\n---\n"
            "Salut, rappelle-moi ou ecris-moi sur WhatsApp au {whatsapp}.\n---\n"
            "Bonjour, contacte-moi sur WhatsApp au {whatsapp}."
        ),
    )
    sms_autoreply_max_per_run: Mapped[int] = mapped_column(Integer, default=10)
    sms_autoreply_lookback_minutes: Mapped[int] = mapped_column(Integer, default=60)
    # The same person is called several times in a row by the same caller, each
    # attempt being a distinct CDR row. Uniqueness on trigger_ref would let all
    # of them through, so a recipient is also silenced for a while.
    sms_autoreply_recipient_cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
    # 0 keeps archived pairs forever. Deleting one removes its messages,
    # history and queue rows too — there is no foreign key to cascade.
    pairing_archive_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    pairing_call_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pairing_call_interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    pairing_call_min_seconds: Mapped[int] = mapped_column(Integer, default=45)
    pairing_call_max_seconds: Mapped[int] = mapped_column(Integer, default=75)
    pairing_call_max_per_run: Mapped[int] = mapped_column(Integer, default=5)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
