"""Every write to agent_task / agent_task_step goes through here.

The table doubles as the work queue: `claim` uses FOR UPDATE SKIP LOCKED and
locks the agent row too, but the storage invariant that actually guarantees
one open task per agent is the partial unique index
`uq_agent_task_open_per_agent`. Every step and status change is followed by a
Postgres NOTIFY so the API can stream it."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
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
        # The pre-check above is a friendly 409 for the common case; the partial
        # unique index (uq_agent_task_open_per_agent) is what actually prevents
        # a cron tick racing a manual Run from inserting two open tasks.
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise TaskConflict("Agent already has a queued or running task")
        await _notify(session, QUEUED_CHANNEL, str(task.id))
        await session.commit()
        await session.refresh(task)
        log.info("agent_task_queued", task_id=str(task.id), agent_id=str(agent.id), trigger=trigger)
        return task

    @staticmethod
    async def claim(session: AsyncSession, worker_id: str) -> AgentTask | None:
        # The agent row is locked too (FOR UPDATE OF t, a) as defense in depth:
        # NOT EXISTS alone cannot see another claimer's uncommitted running row
        # under READ COMMITTED. Single transaction, notify included.
        row = (await session.execute(text("""
            UPDATE agent_task
            SET status = 'running', worker_id = :worker_id, started_at = now(), heartbeat_at = now()
            WHERE id = (
                SELECT t.id FROM agent_task t
                JOIN agent a ON a.id = t.agent_id
                WHERE t.status = 'queued'
                  AND NOT EXISTS (SELECT 1 FROM agent_task r WHERE r.agent_id = t.agent_id AND r.status = 'running')
                ORDER BY t.created_at
                FOR UPDATE OF t, a SKIP LOCKED
                LIMIT 1)
            RETURNING id
        """), {"worker_id": worker_id})).first()
        if not row:
            await session.commit()
            return None
        task = await session.get(AgentTask, row[0])
        await session.refresh(task)
        await _notify_event(session, task, None)
        await session.commit()
        return task

    @staticmethod
    async def heartbeat(session: AsyncSession, task_id: uuid.UUID) -> None:
        await session.execute(update(AgentTask).where(AgentTask.id == task_id).values(heartbeat_at=func.now()))
        await session.commit()

    @staticmethod
    async def sweep_stale(session: AsyncSession, older_than_seconds: int) -> int:
        cutoff = func.now() - timedelta(seconds=older_than_seconds)
        stale = (await session.execute(
            select(AgentTask).where(
                AgentTask.status == "running",
                or_(
                    AgentTask.heartbeat_at < cutoff,
                    and_(AgentTask.heartbeat_at.is_(None), AgentTask.started_at < cutoff),
                ),
            ).with_for_update(skip_locked=True)
        )).scalars().all()
        count = 0
        for task in stale:
            try:
                await AgentTaskService.record_step(session, task, "error", {"message": "worker lost", "phase": "claim"})
                await AgentTaskService.finish(session, task, "failed", error="worker lost")
                log.warning("agent_task_worker_lost", task_id=str(task.id), worker_id=task.worker_id)
                count += 1
            except Exception:
                log.exception("agent_task_sweep_failed", task_id=str(task.id))
                await session.rollback()
        return count

    @staticmethod
    async def record_step(session: AsyncSession, task: AgentTask, kind: str, payload: dict, *,
                          prompt: list | None = None, tokens_in: int | None = None,
                          tokens_out: int | None = None, duration_ms: int | None = None) -> AgentTaskStep:
        # Lock the task row first so two writers racing on the same task cannot
        # both read the same max(seq) or clobber each other's totals.
        await session.execute(select(AgentTask.id).where(AgentTask.id == task.id).with_for_update())
        next_seq = (await session.execute(
            select(func.coalesce(func.max(AgentTaskStep.seq), 0) + 1).where(AgentTaskStep.task_id == task.id)
        )).scalar_one()
        step = AgentTaskStep(task_id=task.id, seq=next_seq, kind=kind, payload=payload, prompt=prompt,
                             tokens_in=tokens_in, tokens_out=tokens_out, duration_ms=duration_ms)
        session.add(step)
        await session.execute(update(AgentTask).where(AgentTask.id == task.id).values(
            step_count=next_seq,
            tokens_in=AgentTask.tokens_in + (tokens_in or 0),
            tokens_out=AgentTask.tokens_out + (tokens_out or 0),
        ))
        await session.flush()
        await _notify_event(session, task, next_seq)
        await session.commit()
        await session.refresh(task)
        return step

    @staticmethod
    async def finish(session, task, status, *, outcome=None, error=None) -> bool:
        assert status in FINAL_STATUSES, status
        result = await session.execute(
            update(AgentTask)
            .where(AgentTask.id == task.id, AgentTask.status.in_(("queued", "running")))
            .values(status=status, outcome=outcome, error=error, finished_at=func.now())
        )
        if result.rowcount == 0:
            await session.rollback()
            await session.refresh(task)
            log.warning("agent_task_finish_skipped", task_id=str(task.id), current=task.status, wanted=status)
            return False
        await session.refresh(task)
        await _notify_event(session, task, None)
        await session.commit()
        log.info("agent_task_finished", task_id=str(task.id), status=status, outcome=outcome)
        return True

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
        result = (await session.execute(
            select(AgentTask.cancel_requested).where(AgentTask.id == task_id)
        )).scalar_one_or_none()
        # A deleted task must stop, not spin forever waiting for a cancel flag
        # that no longer has a row to live on.
        return True if result is None else bool(result)
