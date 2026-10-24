import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentStatus = Literal["draft", "active", "paused", "archived"]


class AgentServerRef(BaseModel):
    """Denormalised server summary so the agent list needs no second request."""
    id: uuid.UUID
    name: str
    enabled: bool


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    instructions: str = ""
    description: str | None = None
    max_steps: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    mcp_server_ids: list[uuid.UUID] = []


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, min_length=1)
    instructions: str | None = None
    description: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=100)
    timeout_seconds: int | None = Field(default=None, ge=10, le=3600)
    mcp_server_ids: list[uuid.UUID] | None = None  # replaces the whole set when present


class AgentStatusUpdate(BaseModel):
    status: AgentStatus


class AgentRead(BaseModel):
    id: uuid.UUID
    name: str
    objective: str
    instructions: str
    description: str | None
    status: AgentStatus
    max_steps: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime
    mcp_servers: list[AgentServerRef]

    model_config = {"from_attributes": True}
