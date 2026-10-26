import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Agent, AgentTask, Approval
from app.schemas import ApprovalDecision, ApprovalRead
from app.schemas.approval import ApprovalStatus
from app.services.approval_service import ApprovalConflict, ApprovalService

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


async def _enrich(session: AsyncSession, approvals: list[Approval]) -> list[ApprovalRead]:
    if not approvals:
        return []
    agents = {a.id: a.name for a in (await session.execute(select(Agent).where(Agent.id.in_({x.agent_id for x in approvals})))).scalars().all()}
    tasks = {t.id: t.objective for t in (await session.execute(select(AgentTask).where(AgentTask.id.in_({x.task_id for x in approvals})))).scalars().all()}
    return [ApprovalRead.from_model(a, agent_name=agents.get(a.agent_id), task_objective=tasks.get(a.task_id)) for a in approvals]


@router.get("", response_model=list[ApprovalRead])
async def list_approvals(status: ApprovalStatus = Query(default="pending"),
                         session: AsyncSession = Depends(get_async_session)):
    rows = (await session.execute(select(Approval).where(Approval.status == status).order_by(Approval.requested_at.desc()).limit(200))).scalars().all()
    return await _enrich(session, list(rows))


async def _decide(approval_id: uuid.UUID, approve: bool, data: ApprovalDecision, session: AsyncSession) -> ApprovalRead:
    approval = await session.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    try:
        approval = await ApprovalService.decide(session, approval, approve=approve, decided_by="ui", reason=data.reason)
    except ApprovalConflict as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return (await _enrich(session, [approval]))[0]


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
async def approve(approval_id: uuid.UUID, data: ApprovalDecision, session: AsyncSession = Depends(get_async_session)):
    return await _decide(approval_id, True, data, session)


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
async def reject(approval_id: uuid.UUID, data: ApprovalDecision, session: AsyncSession = Depends(get_async_session)):
    return await _decide(approval_id, False, data, session)
