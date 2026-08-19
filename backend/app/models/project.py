import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class Project(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    stale_days: Mapped[int] = mapped_column(Integer, default=14)
    budget_warn_pct: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    links: Mapped[list["ProjectLink"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectLink.position"
    )
    snapshots: Mapped[list["ProjectSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectLink(Base):
    __tablename__ = "project_link"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    file_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_kpi_source: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship(back_populates="links")


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("ix_project_snapshot_project_captured", "project_id", "captured_at"),
    )
