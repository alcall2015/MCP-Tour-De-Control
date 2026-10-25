import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, AgentTaskStep, McpServer
from app.services.agent_task_service import AgentTaskService, TaskConflict


async def make_agent(session, name="a", status="active") -> Agent:
    server = McpServer(name=f"srv-{name}", transport="http", url="http://x", enabled=True)
    agent = Agent(name=name, objective="objective", instructions="rules", status=status, mcp_servers=[server])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_enqueue_snapshots_and_notifies(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    assert task.status == "queued" and task.trigger == "manual"
    assert task.objective == "objective" and task.instructions == "rules"
    assert task.max_steps == agent.max_steps and task.timeout_seconds == agent.timeout_seconds
    assert task.started_at is None and task.worker_id is None


async def test_enqueue_rejects_inactive_agent_and_duplicates(session):
    draft = await make_agent(session, "d", status="draft")
    with pytest.raises(TaskConflict):
        await AgentTaskService.enqueue(session, draft, objective=None, trigger="manual")
    active = await make_agent(session, "x")
    await AgentTaskService.enqueue(session, active, objective="first", trigger="manual")
    with pytest.raises(TaskConflict):
        await AgentTaskService.enqueue(session, active, objective="second", trigger="cron")


async def test_claim_is_exclusive_per_agent_and_across_workers(setup_db, session):
    a1 = await make_agent(session, "a1")
    a2 = await make_agent(session, "a2")
    t1 = await AgentTaskService.enqueue(session, a1, objective="1", trigger="manual")
    t2 = await AgentTaskService.enqueue(session, a2, objective="2", trigger="manual")
    # a second task of a1 cannot be enqueued while t1 is queued, so insert it directly
    t3 = AgentTask(agent_id=a1.id, trigger="manual", objective="3", instructions="", max_steps=5, timeout_seconds=60)
    session.add(t3)
    await session.commit()

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s1, factory() as s2, factory() as s3:
        c1, c2, c3 = await asyncio.gather(
            AgentTaskService.claim(s1, "w1"), AgentTaskService.claim(s2, "w2"), AgentTaskService.claim(s3, "w3"))
    claimed = {c.id for c in (c1, c2, c3) if c}
    assert claimed == {t1.id, t2.id}           # t3 waits: its agent already has a running task
    assert {c.worker_id for c in (c1, c2, c3) if c} == {"w1", "w2"} or len(claimed) == 2
    for c in (c1, c2, c3):
        if c:
            assert c.status == "running" and c.started_at is not None and c.heartbeat_at is not None

    await AgentTaskService.finish(session, await session.get(AgentTask, t1.id), "completed", outcome="success")
    assert (await AgentTaskService.claim(session, "w4")).id == t3.id
    assert await AgentTaskService.claim(session, "w5") is None


async def test_sweep_marks_only_stale_running_tasks(session):
    agent = await make_agent(session)
    fresh = await AgentTaskService.enqueue(session, agent, objective="f", trigger="manual")
    fresh = await AgentTaskService.claim(session, "w")
    stale = AgentTask(agent_id=(await make_agent(session, "b")).id, trigger="manual", objective="s", instructions="",
                      max_steps=5, timeout_seconds=60, status="running", worker_id="dead",
                      started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                      heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    session.add(stale)
    await session.commit()

    assert await AgentTaskService.sweep_stale(session, older_than_seconds=90) == 1
    await session.refresh(stale)
    await session.refresh(fresh)
    assert stale.status == "failed" and stale.error == "worker lost" and stale.finished_at is not None
    assert fresh.status == "running"
    steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == stale.id))).scalars().all()
    assert [s.kind for s in steps] == ["error"] and steps[0].payload["phase"] == "claim"


async def test_record_step_increments_seq_and_totals(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
    s1 = await AgentTaskService.record_step(session, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "p"}], tokens_in=10, tokens_out=5)
    s2 = await AgentTaskService.record_step(session, task, "tool_call", {"tool": "t"}, duration_ms=12)
    assert (s1.seq, s2.seq) == (1, 2)
    await session.refresh(task)
    assert task.step_count == 2 and task.tokens_in == 10 and task.tokens_out == 5
    assert s1.prompt == [{"role": "system", "content": "p"}] and s2.prompt is None


async def test_heartbeat_and_cancel(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
    await AgentTaskService.request_cancel(session, task)       # queued -> cancelled immediately
    await session.refresh(task)
    assert task.status == "cancelled" and task.finished_at is not None
    with pytest.raises(TaskConflict):
        await AgentTaskService.request_cancel(session, task)   # already final

    agent2 = await make_agent(session, "b")
    running = await AgentTaskService.enqueue(session, agent2, objective="o", trigger="manual")
    running = await AgentTaskService.claim(session, "w")
    before = running.heartbeat_at
    await asyncio.sleep(0.01)
    await AgentTaskService.heartbeat(session, running.id)
    await session.refresh(running)
    assert running.heartbeat_at > before
    await AgentTaskService.request_cancel(session, running)
    assert await AgentTaskService.is_cancel_requested(session, running.id) is True
    await session.refresh(running)
    assert running.status == "running"                         # the runner turns it into cancelled


async def test_notifications_are_emitted(setup_db, session):
    """LISTEN on a raw asyncpg connection and check enqueue + step + finish notify."""
    agent = await make_agent(session)
    received: list[tuple[str, str]] = []
    async with setup_db.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        await raw.add_listener("agent_task_queued", lambda c, pid, ch, payload: received.append((ch, payload)))
        await raw.add_listener("agent_task_events", lambda c, pid, ch, payload: received.append((ch, payload)))
        task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
        await AgentTaskService.record_step(session, task, "plan", {"steps": []})
        await AgentTaskService.finish(session, task, "completed", outcome="success")
        for _ in range(50):
            if len(received) >= 3:
                break
            await asyncio.sleep(0.05)
    channels = [c for c, _ in received]
    assert channels[0] == "agent_task_queued" and received[0][1] == str(task.id)
    assert channels.count("agent_task_events") >= 2
    assert all(str(task.id) in p for _, p in received[1:])
