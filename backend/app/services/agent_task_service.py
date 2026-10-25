"""Every write to agent_task / agent_task_step goes through here.

The table doubles as the work queue: `claim` uses FOR UPDATE SKIP LOCKED and
guarantees one running task per agent; every step and status change is
followed by a Postgres NOTIFY so the API can stream it."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentTask, AgentTaskStep
from app.models.agent_task import FINAL_STATUSES

log = structlog.get_logger()

EVENTS_CHANNEL = "agent_task_events"
QUEUED_CHANNEL = "agent_task_queued"


class TaskConflict(Exception):
    status_code = 409

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _notify(session: AsyncSession, channel: str, payload: str) -> None:
    # Delivered when the surrounding transaction commits.
    await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": channel, "payload": payload})


async def _notify_event(session: AsyncSession, task: AgentTask, seq: int | None) -> None:
    await _notify(session, EVENTS_CHANNEL, json.dumps({"task_id": str(task.id), "seq": seq, "status": task.status}))


class AgentTaskService:

    @staticmethod
    async def enqueue(session: AsyncSession, agent: Agent, *, objective: str | None, trigger: str) -> AgentTask:
        if agent.status != "active":
            raise TaskConflict(f"Agent is {agent.status}; only active agents can run")
        open_task = (await session.execute(
            select(AgentTask.id).where(AgentTask.agent_id == agent.id, AgentTask.status.in_(("queued", "running"))).limit(1)
        )).scalar_one_or_none()
        if open_task:
            raise TaskConflict("Agent already has a queued or running task")
        task = AgentTask(
            agent_id=agent.id, trigger=trigger,
            objective=(objective or "").strip() or agent.objective,
            instructions=agent.instructions, max_steps=agent.max_steps, timeout_seconds=agent.timeout_seconds,
        )
        session.add(task)
        await session.flush()
        await _notify(session, QUEUED_CHANNEL, str(task.id))
        await session.commit()
        await session.refresh(task)
        log.info("agent_task_queued", task_id=str(task.id), agent_id=str(agent.id), trigger=trigger)
        return task

    @staticmethod
    async def claim(session: AsyncSession, worker_id: str) -> AgentTask | None:
        row = (await session.execute(text("""
            UPDATE agent_task
            SET status = 'running', worker_id = :worker_id, started_at = now(), heartbeat_at = now()
            WHERE id = (
                SELECT t.id FROM agent_task t
                WHERE t.status = 'queued'
                  AND NOT EXISTS (SELECT 1 FROM agent_task r WHERE r.agent_id = t.agent_id AND r.status = 'running')
                ORDER BY t.created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1)
            RETURNING id
        """), {"worker_id": worker_id})).first()
        await session.commit()
        if not row:
            return None
        task = await session.get(AgentTask, row[0])
        await session.refresh(task)
        await _notify_event(session, task, None)
        await session.commit()
        return task

    @staticmethod
    async def heartbeat(session: AsyncSession, task_id: uuid.UUID) -> None:
        await session.execute(update(AgentTask).where(AgentTask.id == task_id).values(heartbeat_at=_now()))
        await session.commit()

    @staticmethod
    async def sweep_stale(session: AsyncSession, older_than_seconds: int) -> int:
        cutoff = _now() - timedelta(seconds=older_than_seconds)
        stale = (await session.execute(
            select(AgentTask).where(AgentTask.status == "running", AgentTask.heartbeat_at < cutoff)
        )).scalars().all()
        for task in stale:
            await AgentTaskService.record_step(session, task, "error", {"message": "worker lost", "phase": "claim"})
            await AgentTaskService.finish(session, task, "failed", error="worker lost")
            log.warning("agent_task_worker_lost", task_id=str(task.id), worker_id=task.worker_id)
        return len(stale)

    @staticmethod
    async def record_step(session: AsyncSession, task: AgentTask, kind: str, payload: dict, *,
                          prompt: list | None = None, tokens_in: int | None = None,
                          tokens_out: int | None = None, duration_ms: int | None = None) -> AgentTaskStep:
        next_seq = (await session.execute(
            select(func.coalesce(func.max(AgentTaskStep.seq), 0) + 1).where(AgentTaskStep.task_id == task.id)
        )).scalar_one()
        step = AgentTaskStep(task_id=task.id, seq=next_seq, kind=kind, payload=payload, prompt=prompt,
                             tokens_in=tokens_in, tokens_out=tokens_out, duration_ms=duration_ms)
        session.add(step)
        task.step_count = next_seq
        task.tokens_in = (task.tokens_in or 0) + (tokens_in or 0)
        task.tokens_out = (task.tokens_out or 0) + (tokens_out or 0)
        await session.flush()
        await _notify_event(session, task, next_seq)
        await session.commit()
        return step

    @staticmethod
    async def finish(session: AsyncSession, task: AgentTask, status: str, *, outcome: str | None = None,
                     error: str | None = None) -> None:
        task.status = status
        task.outcome = outcome
        task.error = error
        task.finished_at = _now()
        await session.flush()
        await _notify_event(session, task, None)
        await session.commit()
        log.info("agent_task_finished", task_id=str(task.id), status=status, outcome=outcome)

    @staticmethod
    async def request_cancel(session: AsyncSession, task: AgentTask) -> None:
        if task.status in FINAL_STATUSES:
            raise TaskConflict(f"Task is already {task.status}")
        if task.status == "queued":
            await AgentTaskService.finish(session, task, "cancelled")
            return
        task.cancel_requested = True
        await session.commit()

    @staticmethod
    async def is_cancel_requested(session: AsyncSession, task_id: uuid.UUID) -> bool:
        return bool((await session.execute(
            select(AgentTask.cancel_requested).where(AgentTask.id == task_id)
        )).scalar_one())
