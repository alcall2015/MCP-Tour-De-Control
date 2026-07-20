import uuid
from datetime import datetime

from pydantic import BaseModel


class ScriptRead(BaseModel):
    id: uuid.UUID
    prompt_id: uuid.UUID
    version: int
    code: str
    needs_llm: bool
    llm_steps: list | dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
