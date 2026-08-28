import uuid
from datetime import datetime

from pydantic import BaseModel


class SmsReplyRead(BaseModel):
    id: uuid.UUID
    trigger_kind: str
    trigger_ref: str
    sim_id: int
    to_number: str
    whatsapp_number: str | None
    content: str
    status: str
    error: str | None
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SmsAutoReplyStats(BaseModel):
    sent: int
    failed: int
    skipped: int
    # Claimed but never resolved: the send outcome was not written back.
    sending: int
    last_sent_at: datetime | None
