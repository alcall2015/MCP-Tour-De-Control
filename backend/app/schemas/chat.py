import uuid
from datetime import datetime

from pydantic import BaseModel


class ConversationRead(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ChatMessageRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    tool_calls: list | dict | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    content: str
