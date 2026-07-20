import uuid
from datetime import datetime

from pydantic import BaseModel


class ExecutionRead(BaseModel):
    id: uuid.UUID
    script_id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    output: str | None
    llm_output: str | None
    tokens_used: int
    error: str | None
    duration_ms: int | None
    # Joined fields for convenience
    prompt_name: str | None = None
    script_version: int | None = None

    model_config = {"from_attributes": True}


class ExecutionListParams(BaseModel):
    status: str | None = None
    prompt_id: uuid.UUID | None = None
    limit: int = 50
    offset: int = 0
