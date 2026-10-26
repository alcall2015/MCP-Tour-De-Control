"""Agent lifecycle (status transitions, cron synchronisation) and read helpers."""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Agent, AgentTask
from app.models.agent_task import OPEN_STATUSES
from app.schemas.agent import AgentUpdate
from app.services.agent_task_service import AgentTaskService, TaskConflict
from app.services.scheduler_service import scheduler_service

log = structlog.get_logger()

# from -> allowed targets. `archived` is terminal except for restore to draft.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": {"draft"},
}


class AgentStateError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AgentService:

    @staticmethod
    def sync_cron_job(agent: Agent) -> None:
        if agent.status == "active" and agent.cron_expr:
            scheduler_service.reschedule_agent_job(agent.id, agent.cron_expr)
        else:
            scheduler_service.remove_agent_job(agent.id)

    @staticmethod
    async def change_status(session: AsyncSession, agent: Agent, target: str) -> Agent:
        if target not in ALLOWED_TRANSITIONS[agent.status]:
            raise AgentStateError(409, f"Cannot move agent from {agent.status} to {target}")
        if target == "active" and not any(s.enabled for s in agent.mcp_servers):
            raise AgentStateError(400, "Agent needs at least one enabled MCP server to be activated")
        previous = agent.status
        agent.status = target
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(agent)
        AgentService.sync_cron_job(agent)
        log.info("agent_status_changed", agent_id=str(agent.id), previous=previous, status=target)
        return agent

    @staticmethod
    async def apply_update(session: AsyncSession, agent: Agent, data: AgentUpdate, servers_loader) -> Agent:
        if agent.status == "archived":
            raise AgentStateError(409, "Agent is archived; restore it before editing")
        for field in ("name", "objective", "instructions", "description", "max_steps", "timeout_seconds", "max_auto_risk"):
            value = getattr(data, field)
            if value is not None:
                setattr(agent, field, value)
        if "cron_expr" in data.model_fields_set:
            agent.cron_expr = data.cron_expr
        if data.mcp_server_ids is not None:
            agent.mcp_servers = await servers_loader(data.mcp_server_ids)
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(agent)
        if "cron_expr" in data.model_fields_set:
            AgentService.sync_cron_job(agent)
        log.info("agent_updated", agent_id=str(agent.id), fields=sorted(data.model_fields_set))
        return agent

    @staticmethod
    async def assert_no_open_task(session: AsyncSession, agent_id: uuid.UUID) -> None:
        """Refuse to delete an agent under a task: the cascade would delete the
        row a worker is mid-run on, and the run would only notice at its next
        write."""
        open_task = (await session.execute(
            select(AgentTask.id).where(AgentTask.agent_id == agent_id, AgentTask.status.in_(OPEN_STATUSES)).limit(1)
        )).scalar_one_or_none()
        if open_task:
            raise AgentStateError(409, "Agent has a queued or running task; cancel it first")

    @staticmethod
    async def task_summaries(session: AsyncSession, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        out = {aid: {"running_task_id": None, "last_task": None} for aid in agent_ids}
        if not agent_ids:
            return out
        # Two narrow queries instead of loading every task entity of every
        # agent: DISTINCT ON (agent_id) gives the newest task per agent in one
        # pass, and the open-task index answers the running lookup.
        last_rows = (await session.execute(
            select(AgentTask.agent_id, AgentTask.id, AgentTask.status, AgentTask.outcome, AgentTask.finished_at)
            .distinct(AgentTask.agent_id)
            .where(AgentTask.agent_id.in_(agent_ids))
            .order_by(AgentTask.agent_id, AgentTask.created_at.desc())
        )).all()
        for agent_id, task_id, status, outcome, finished_at in last_rows:
            out[agent_id]["last_task"] = {"id": task_id, "status": status, "outcome": outcome, "finished_at": finished_at}
        running_rows = (await session.execute(
            select(AgentTask.agent_id, AgentTask.id)
            .where(AgentTask.agent_id.in_(agent_ids), AgentTask.status == "running")
        )).all()
        for agent_id, task_id in running_rows:
            out[agent_id]["running_task_id"] = task_id
        return out

    @staticmethod
    async def enqueue_from_cron(agent_id: uuid.UUID) -> None:
        async with async_session() as session:
            agent = await session.get(Agent, agent_id)
            if not agent or agent.status != "active":
                log.info("agent_cron_skipped", agent_id=str(agent_id), reason="not active")
                return
            try:
                await AgentTaskService.enqueue(session, agent, objective=None, trigger="cron")
            except TaskConflict as exc:
                log.info("agent_cron_skipped", agent_id=str(agent_id), reason=exc.detail)
