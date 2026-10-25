import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session, engine, get_async_session
from app.models import AgentTask, AgentTaskStep
from app.models.agent_task import FINAL_STATUSES
from app.schemas import AgentTaskDetail, AgentTaskRead, AgentTaskStepDetail, AgentTaskStepRead
from app.services.agent_task_service import AgentTaskService, EVENTS_CHANNEL, TaskConflict
from app.utils.sse import sse_frame

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


KEEPALIVE_SECONDS = 20

# Module-level so tests can point the stream at the test database.
session_factory = async_session
db_engine = engine


def _status_payload(task: AgentTask) -> dict:
    return {"status": task.status, "outcome": task.outcome, "error": task.error,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None}


async def _steps_after(task_id: uuid.UUID, last_seq: int) -> list[AgentTaskStep]:
    async with session_factory() as session:
        return (await session.execute(
            select(AgentTaskStep).where(AgentTaskStep.task_id == task_id, AgentTaskStep.seq > last_seq).order_by(AgentTaskStep.seq)
        )).scalars().all()


async def _task_snapshot(task_id: uuid.UUID) -> AgentTask | None:
    async with session_factory() as session:
        return await session.get(AgentTask, task_id)


async def _event_stream(task_id: uuid.UUID):
    last_seq = 0
    last_status = None
    try:
        # Backlog first, so a reconnecting client never misses a step.
        for step in await _steps_after(task_id, 0):
            last_seq = step.seq
            yield sse_frame("step", AgentTaskStepRead.model_validate(step).model_dump(mode="json"))
        task = await _task_snapshot(task_id)
        last_status = task.status
        yield sse_frame("status", _status_payload(task))
        if task.status in FINAL_STATUSES:
            yield sse_frame("done", {})
            return

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_notify(_conn, _pid, _channel, payload):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return
            if data.get("task_id") == str(task_id):
                loop.call_soon_threadsafe(queue.put_nowait, data)

        async with db_engine.connect() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.add_listener(EVENTS_CHANNEL, on_notify)
            try:
                # Anything written between the backlog read and the LISTEN registration.
                queue.put_nowait({"task_id": str(task_id), "seq": None, "status": None})
                while True:
                    try:
                        await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    for step in await _steps_after(task_id, last_seq):
                        last_seq = step.seq
                        yield sse_frame("step", AgentTaskStepRead.model_validate(step).model_dump(mode="json"))
                    task = await _task_snapshot(task_id)
                    if task.status != last_status or task.status in FINAL_STATUSES:
                        last_status = task.status
                        yield sse_frame("status", _status_payload(task))
                    if task.status in FINAL_STATUSES:
                        yield sse_frame("done", {})
                        return
            finally:
                await raw.remove_listener(EVENTS_CHANNEL, on_notify)
    except Exception as exc:  # noqa: BLE001
        yield sse_frame("error", {"message": str(exc)})


@router.get("/{task_id}/events")
async def task_events(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    await _get_task(session, task_id)
    return StreamingResponse(_event_stream(task_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
