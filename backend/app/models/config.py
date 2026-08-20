import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
