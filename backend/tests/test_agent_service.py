import os
from unittest.mock import patch

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest

from app.models import Agent, AgentTask, McpServer
from app.schemas.agent import AgentUpdate
from app.services import agent_service
from app.services.agent_service import AgentService, AgentStateError
from app.services.agent_task_service import AgentTaskService
from app.services.scheduler_service import SchedulerService, _execute_agent_cron


async def _agent(session, *, status="draft", cron=None, enabled=True):
    agent = Agent(name="a", objective="o", status=status, cron_expr=cron,
                  mcp_servers=[McpServer(name="s", transport="http", url="http://x", enabled=enabled)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_activation_adds_cron_job_and_pause_removes_it(session):
    agent = await _agent(session, cron="0 8 * * *")
    service = SchedulerService(use_db_jobstore=False)
    service.start()
    with patch.object(agent_service, "scheduler_service", service):
        await AgentService.change_status(session, agent, "active")
        assert service.scheduler.get_job(f"agent_{agent.id}") is not None
        await AgentService.change_status(session, agent, "paused")
        assert service.scheduler.get_job(f"agent_{agent.id}") is None
    service.shutdown()


async def test_update_cron_on_active_agent_reschedules(session):
    agent = await _agent(session, status="active", cron="0 8 * * *")
    service = SchedulerService(use_db_jobstore=False)
    service.start()
    with patch.object(agent_service, "scheduler_service", service):
        async def loader(ids):
            return []
        await AgentService.apply_update(session, agent, AgentUpdate(cron_expr="0 9 * * *"), loader)
        job = service.scheduler.get_job(f"agent_{agent.id}")
        assert job is not None and "hour='9'" in str(job.trigger)
        await AgentService.apply_update(session, agent, AgentUpdate(cron_expr=None, name="renamed"), loader)
        assert service.scheduler.get_job(f"agent_{agent.id}") is None  # cron removed when cleared
    service.shutdown()


async def test_change_status_errors_are_typed(session):
    agent = await _agent(session, enabled=False)
    with pytest.raises(AgentStateError) as exc:
        await AgentService.change_status(session, agent, "active")
    assert exc.value.status_code == 400
    with pytest.raises(AgentStateError) as exc:
        await AgentService.change_status(session, agent, "paused")
    assert exc.value.status_code == 409


async def test_task_summaries(session):
    agent = await _agent(session, status="active")
    other = await _agent(session, status="active")
    done = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    await AgentTaskService.finish(session, done, "completed", outcome="partial")
    running = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    running = await AgentTaskService.claim(session, "w")
    summaries = await AgentService.task_summaries(session, [agent.id, other.id])
    assert summaries[agent.id]["running_task_id"] == running.id
    assert summaries[agent.id]["last_task"]["id"] == running.id and summaries[agent.id]["last_task"]["status"] == "running"
    assert summaries[other.id] == {"running_task_id": None, "last_task": None}


async def test_cron_tick_enqueues_once(setup_db, session):
    agent = await _agent(session, status="active", cron="* * * * *")
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    with patch("app.services.agent_service.async_session", factory):
        await _execute_agent_cron(str(agent.id))
        await _execute_agent_cron(str(agent.id))      # second tick skips: one is already queued
    from sqlalchemy import select, func
    count = (await session.execute(select(func.count()).select_from(AgentTask).where(AgentTask.agent_id == agent.id))).scalar_one()
    assert count == 1
    assert (await session.execute(select(AgentTask.trigger).where(AgentTask.agent_id == agent.id))).scalar_one() == "cron"
