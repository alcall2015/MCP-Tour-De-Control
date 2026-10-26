import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class ApprovalRead(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None = None
    task_objective: str | None = None
    step_seq: int
    call_index: int
    tool_name: str
    server_name: str
    args: dict[str, Any]
    risk_level: int
    code: str
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime
    seconds_left: int
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    notified_at: datetime | None
    notify_error: str | None
    consumed_at: datetime | None

    @classmethod
    def from_model(cls, approval, *, agent_name: str | None = None, task_objective: str | None = None) -> "ApprovalRead":
        left = int((approval.expires_at - datetime.now(timezone.utc)).total_seconds())
        return cls(
            id=approval.id, task_id=approval.task_id, agent_id=approval.agent_id, agent_name=agent_name, task_objective=task_objective,
            step_seq=approval.step_seq, call_index=approval.call_index, tool_name=approval.tool_name, server_name=approval.server_name,
            args=approval.args, risk_level=approval.risk_level, code=approval.code, status=approval.status,
            requested_at=approval.requested_at, expires_at=approval.expires_at, seconds_left=max(0, left),
            decided_at=approval.decided_at, decided_by=approval.decided_by, decision_reason=approval.decision_reason,
            notified_at=approval.notified_at, notify_error=approval.notify_error, consumed_at=approval.consumed_at,
        )


class ApprovalDecision(BaseModel):
    reason: str | None = None
