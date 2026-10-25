import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_session
from app.models import AgentTask, AgentTaskStep
from app.schemas import AgentTaskDetail, AgentTaskRead, AgentTaskStepDetail
from app.services.agent_task_service import AgentTaskService, TaskConflict

router = APIRouter(prefix="/api/v1/agent-tasks", tags=["agent-tasks"])


async def _get_task(session: AsyncSession, task_id: uuid.UUID, *, with_steps: bool = False) -> AgentTask:
    stmt = select(AgentTask).where(AgentTask.id == task_id)
    if with_steps:
        stmt = stmt.options(selectinload(AgentTask.steps))
    task = (await session.execute(stmt)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}", response_model=AgentTaskDetail)
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return AgentTaskDetail.model_validate(await _get_task(session, task_id, with_steps=True))


@router.get("/{task_id}/steps/{seq}", response_model=AgentTaskStepDetail)
async def get_step(task_id: uuid.UUID, seq: int, session: AsyncSession = Depends(get_async_session)):
    await _get_task(session, task_id)
    step = (await session.execute(
        select(AgentTaskStep).where(AgentTaskStep.task_id == task_id, AgentTaskStep.seq == seq)
    )).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return AgentTaskStepDetail.model_validate(step)


@router.post("/{task_id}/cancel", response_model=AgentTaskRead, status_code=202)
async def cancel_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    task = await _get_task(session, task_id)
    try:
        await AgentTaskService.request_cancel(session, task)
    except TaskConflict as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    await session.refresh(task)
    return AgentTaskRead.model_validate(task)
