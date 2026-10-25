import asyncio
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models import Agent, AgentTask, McpServer
from app.services.agent_task_service import AgentTaskService
from app.worker import Worker


async def _agent(session, name):
    agent = Agent(name=name, objective="o", status="active",
                  mcp_servers=[McpServer(name=f"s-{name}", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_process_available_respects_concurrency_and_runs_tasks(setup_db, session):
    a, b, c = [await _agent(session, n) for n in "abc"]
    for agent in (a, b, c):
        await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    ran: list = []
    gate = asyncio.Event()

    async def fake_run(task_id, **_):
        ran.append(task_id)
        await gate.wait()
        async with factory() as s:
            await AgentTaskService.finish(s, await s.get(AgentTask, task_id), "completed", outcome="success")

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=2, run=fake_run, session_factory=factory, worker_id="w-test")

    assert await worker.process_available() == 2          # two slots, two tasks started
    assert await worker.process_available() == 0          # slots full
    gate.set()
    await asyncio.sleep(0.2)
    assert await worker.process_available() == 1          # third task once a slot frees up
    await asyncio.sleep(0.2)
    assert len(ran) == 3
    await worker.close()


async def test_sweep_delegates_to_service(setup_db, session):
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=1, session_factory=factory)
    assert await worker.sweep() == 0
    await worker.close()


async def test_heartbeat_keeps_going_after_a_db_error(setup_db, session, monkeypatch):
    original_heartbeat = settings.AGENT_TASK_HEARTBEAT_SECONDS
    monkeypatch.setattr(settings, "AGENT_TASK_HEARTBEAT_SECONDS", 0.01)

    calls: list = []

    async def flaky_heartbeat(session, task_id):
        calls.append(task_id)
        if len(calls) == 1:
            raise RuntimeError("transient db error")

    monkeypatch.setattr(AgentTaskService, "heartbeat", flaky_heartbeat)

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)

    async def slow_run(task_id, **_):
        await asyncio.sleep(0.1)

    worker = Worker(concurrency=1, run=slow_run, session_factory=factory, worker_id="w-test")
    await worker._run_with_heartbeat("task-1")

    assert len(calls) >= 2
    monkeypatch.setattr(settings, "AGENT_TASK_HEARTBEAT_SECONDS", original_heartbeat)
    await worker.close()


async def test_request_stop_closes_running_tasks_and_marks_them(setup_db, session):
    agent = await _agent(session, "stopme")
    task = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")

    never = asyncio.Event()

    async def hanging_run(task_id, **_):
        await never.wait()

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=1, run=hanging_run, session_factory=factory, worker_id="w-test")

    assert await worker.process_available() == 1
    worker.request_stop()
    await worker.close()

    async with factory() as s:
        refreshed = await s.get(AgentTask, task.id)
        assert refreshed.status == "failed"
        assert refreshed.error == "worker stopped"


async def test_run_crash_is_logged_and_slot_freed(setup_db, session):
    async def crashing_run(task_id, **_):
        raise RuntimeError("boom")

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=2, run=crashing_run, session_factory=factory, worker_id="w-test")

    agent = await _agent(session, "crashme")
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")

    assert await worker.process_available() == 1
    await asyncio.sleep(0.1)

    assert worker._free_slots() == worker.concurrency
    await worker.close()
