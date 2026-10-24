import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base
from app.models.mcp_server import McpServer

AGENT_STATUSES = ("draft", "active", "paused", "archived")

agent_mcp_server = Table(
    "agent_mcp_server",
    Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"), primary_key=True),
    Column("mcp_server_id", UUID(as_uuid=True), ForeignKey("mcp_server.id", ondelete="CASCADE"), primary_key=True),
)


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    max_steps: Mapped[int] = mapped_column(Integer, default=20)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Authorised MCP servers. Rows in agent_mcp_server vanish with either side (DB cascade).
    mcp_servers: Mapped[list[McpServer]] = relationship(McpServer, secondary=agent_mcp_server, lazy="selectin")

    __table_args__ = (
        CheckConstraint("status IN ('draft','active','paused','archived')", name="ck_agent_status"),
        CheckConstraint("max_steps BETWEEN 1 AND 100", name="ck_agent_max_steps"),
        CheckConstraint("timeout_seconds BETWEEN 10 AND 3600", name="ck_agent_timeout_seconds"),
    )
