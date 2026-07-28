import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, Float, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class StressTestMetrics(Base):
    __tablename__ = "stress_test_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stress_test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stress_test.id", ondelete="CASCADE")
    )

    # SIP metrics
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    successful_calls: Mapped[int] = mapped_column(Integer, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0)
    asr_percent: Mapped[float] = mapped_column(Float, default=0)
    pdd_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    pdd_p95_ms: Mapped[float] = mapped_column(Float, default=0)
    setup_time_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    cps_achieved: Mapped[float] = mapped_column(Float, default=0)
    retransmissions: Mapped[int] = mapped_column(Integer, default=0)
    failed_by_code: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # RTP metrics
    packets_sent: Mapped[int] = mapped_column(Integer, default=0)
    packets_received: Mapped[int] = mapped_column(Integer, default=0)
    packet_loss_pct: Mapped[float] = mapped_column(Float, default=0)
    jitter_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    jitter_max_ms: Mapped[float] = mapped_column(Float, default=0)
    rtt_avg_ms: Mapped[float] = mapped_column(Float, default=0)
    rtt_max_ms: Mapped[float] = mapped_column(Float, default=0)
    mos_score: Mapped[float] = mapped_column(Float, default=0)
    out_of_order: Mapped[int] = mapped_column(Integer, default=0)
    throughput_kbps: Mapped[float] = mapped_column(Float, default=0)

    # System metrics
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=0)
    ramp_up_curve: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    stress_test: Mapped["StressTest"] = relationship(back_populates="metrics")
