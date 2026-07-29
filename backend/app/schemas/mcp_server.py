import uuid
from datetime import datetime

from pydantic import BaseModel


class McpServerCreate(BaseModel):
    name: str
    transport: str  # "stdio" or "http"
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    api_key: str | None = None
    enabled: bool = True


class McpServerRead(BaseModel):
    id: uuid.UUID
    name: str
    transport: str
    command: str | None
    args: list[str] | None
    env: dict[str, str] | None
    url: str | None
    api_key_set: bool = False
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class McpServerUpdate(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None


class McpToolInfo(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict | None = None


class McpTestResult(BaseModel):
    success: bool
    tools: list[McpToolInfo] = []
    error: str | None = None
