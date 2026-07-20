import uuid
from datetime import datetime

from pydantic import BaseModel


class PromptCreate(BaseModel):
    name: str
    description: str | None = None
    prompt_text: str
    cron_expr: str | None = None
    enabled: bool = True
    mcp_server_ids: list[uuid.UUID]  # which servers to use for script generation


class PromptRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    prompt_text: str
    cron_expr: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    latest_script_version: int | None = None
    needs_llm: bool | None = None

    model_config = {"from_attributes": True}


class PromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_text: str | None = None
    cron_expr: str | None = None
