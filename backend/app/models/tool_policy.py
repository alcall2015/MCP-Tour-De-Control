import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base

DEFAULT_RISK_LEVEL = 2


class ToolPolicy(Base):
    """Risk level of one tool on one MCP server. Rows are created on discovery
    with the default level and only ever edited by an operator."""
    __tablename__ = "tool_policy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mcp_server.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(200))
    risk_level: Mapped[int] = mapped_column(SmallInteger, default=DEFAULT_RISK_LEVEL)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("mcp_server_id", "tool_name", name="uq_tool_policy_server_tool"),
        CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_tool_policy_risk_level"),
    )
