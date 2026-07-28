import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class StressTest(Base):
    __tablename__ = "stress_test"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(String(50))
    target_host: Mapped[str] = mapped_column(String(200))
    target_port: Mapped[int] = mapped_column(Integer, default=5060)
    transport: Mapped[str] = mapped_column(String(10), default="udp")
    cps: Mapped[int] = mapped_column(Integer)
    max_calls: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    call_duration: Mapped[int] = mapped_column(Integer, default=10)
    ramp_up: Mapped[int] = mapped_column(Integer, default=0)
    ramp_step: Mapped[int] = mapped_column(Integer, default=1)
    caller_id: Mapped[str] = mapped_column(String(100), default="sipp")
    media_type: Mapped[str] = mapped_column(String(20), default="random")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    remote_test_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    metrics: Mapped[list["StressTestMetrics"]] = relationship(
        back_populates="stress_test", cascade="all, delete-orphan"
    )
