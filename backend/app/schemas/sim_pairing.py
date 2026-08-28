import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SimPairingGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SimPairingGroupRead(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SimPairingTopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SimPairingTopicRead(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SimPairRead(BaseModel):
    id: uuid.UUID
    sim_a_id: int
    sim_b_id: int
    sim_a_name: str
    sim_b_name: str
    country: str
    group_a: str
    group_b: str
    topic: str
    target_messages: int
    sent_count: int
    status: str
    archived_reason: str | None
    created_at: datetime
    archived_at: datetime | None

    model_config = {"from_attributes": True}


class SimPairQueueStats(BaseModel):
    pending: int
    overdue: int
    failed: int
    pairs_under_target: int


class SimPairHistoryRead(BaseModel):
    id: uuid.UUID
    pair_id: uuid.UUID
    event: str
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SimPairMessageRead(BaseModel):
    id: uuid.UUID
    pair_id: uuid.UUID
    from_sim_id: int
    to_sim_id: int
    content: str
    provider: str
    model: str
    status: str
    error: str | None
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SimPairMessageQueueRead(BaseModel):
    id: uuid.UUID
    pair_id: uuid.UUID
    status: str
    due_at: datetime
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
