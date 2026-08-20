import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class TrackedDocument(Base):
    __tablename__ = "tracked_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    web_url: Mapped[str] = mapped_column(Text)
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    content: Mapped["DocumentContent"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    activity: Mapped[list["DocumentActivity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentContent(Base):
    """The latest extraction only. Never a history — that is what bounds storage."""

    __tablename__ = "document_content"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracked_document.id", ondelete="CASCADE"), unique=True
    )
    text: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    document: Mapped["TrackedDocument"] = relationship(back_populates="content")


class DocumentActivity(Base):
    """One row per document per day that actually changed. Days with no change have no row."""

    __tablename__ = "document_activity"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracked_document.id", ondelete="CASCADE")
    )
    day: Mapped[date] = mapped_column(Date)
    added: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)

    document: Mapped["TrackedDocument"] = relationship(back_populates="activity")

    __table_args__ = (
        UniqueConstraint("document_id", "day", name="uq_document_activity_document_day"),
        Index("ix_document_activity_day", "day"),
    )
