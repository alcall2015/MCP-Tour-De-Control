import asyncio
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.config import settings
from app.models import Agent, AgentTask, AgentTaskStep, McpServer
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

    with capture_logs() as logs:
        assert await worker.process_available() == 1
        await asyncio.sleep(0.1)

    assert any(e["event"] == "agent_task_run_crashed" for e in logs)
    assert worker._free_slots() == worker.concurrency
    await worker.close()


async def test_run_crash_marks_task_failed(setup_db, session):
    """Whatever escapes run_task is the worker's to record, phase `claim`."""
    async def crashing_run(task_id, **_):
        raise RuntimeError("boom")

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=1, run=crashing_run, session_factory=factory, worker_id="w-test")

    agent = await _agent(session, "crashmark")
    task = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")

    assert await worker.process_available() == 1
    await asyncio.sleep(0.1)

    async with factory() as s:
        refreshed = await s.get(AgentTask, task.id)
        assert refreshed.status == "failed"
        assert refreshed.error.startswith("claim:") and "boom" in refreshed.error
        steps = (await s.execute(
            select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq)
        )).scalars().all()
        assert [st.kind for st in steps] == ["error"]
        assert steps[0].payload == {"message": "boom", "phase": "claim"}
    await worker.close()


async def test_heartbeat_stops_after_hard_budget(setup_db, session, monkeypatch):
    """Past timeout + grace + one LLM call the beater gives up, so the sweep can reclaim."""
    agent = await _agent(session, "wedged")
    task = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    async with async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)() as s:
        t = await s.get(AgentTask, task.id)
        t.timeout_seconds = 0
        await s.commit()

    monkeypatch.setattr(settings, "AGENT_TASK_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(settings, "AGENT_TASK_FINAL_GRACE_SECONDS", 0)
    monkeypatch.setattr(settings, "LLM_CALL_TIMEOUT_SECONDS", 0)
    # With a zero budget everywhere it is already spent when the beater starts,
    # so the very first tick must stop it.

    calls: list = []

    async def counting_heartbeat(session, task_id):
        calls.append(task_id)

    monkeypatch.setattr(AgentTaskService, "heartbeat", counting_heartbeat)
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)

    async def slow_run(task_id, **_):
        await asyncio.sleep(0.2)

    worker = Worker(concurrency=1, run=slow_run, session_factory=factory, worker_id="w-test")
    with capture_logs() as logs:
        await worker._run_with_heartbeat(task.id)

    assert calls == []                                   # never heartbeats past the budget
    assert any(e["event"] == "agent_task_heartbeat_budget_exhausted" for e in logs)
    await worker.close()
