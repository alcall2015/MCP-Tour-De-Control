import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

AgentTaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
AgentOutcome = Literal["success", "partial", "failed"]
StepKind = Literal["plan", "turn", "tool_call", "critique", "report", "error"]


class AgentTaskCreate(BaseModel):
    objective: str | None = None


class AgentTaskRead(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    trigger: Literal["manual", "cron"]
    objective: str
    instructions: str
    max_steps: int
    timeout_seconds: int
    status: AgentTaskStatus
    outcome: AgentOutcome | None
    plan: dict[str, Any] | None
    critique: dict[str, Any] | None
    report: dict[str, Any] | None
    error: str | None
    cancel_requested: bool
    step_count: int
    tokens_in: int
    tokens_out: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class AgentTaskStepRead(BaseModel):
    seq: int
    kind: StepKind
    payload: dict[str, Any]
    tokens_in: int | None
    tokens_out: int | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentTaskStepDetail(AgentTaskStepRead):
    prompt: list[dict[str, Any]] | None


class AgentTaskDetail(AgentTaskRead):
    steps: list[AgentTaskStepRead]
