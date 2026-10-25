import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
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


async def test_enqueue_reraises_unrelated_integrity_errors(session):
    """Only the partial unique index means "already has an open task"; any other
    IntegrityError (here: a foreign key to an agent row that doesn't exist) must
    propagate unchanged, and the savepoint rollback must leave the session usable."""
    ghost = Agent(id=uuid.uuid4(), name="ghost", objective="o", status="active")
    with pytest.raises(IntegrityError):
        await AgentTaskService.enqueue(session, ghost, objective=None, trigger="manual")
    assert (await session.execute(select(AgentTask))).scalars().all() == []


async def test_enqueue_conflict_keeps_session_usable(session):
    agent = await make_agent(session)
    await AgentTaskService.enqueue(session, agent, objective="first", trigger="manual")
    with pytest.raises(TaskConflict):
        await AgentTaskService.enqueue(session, agent, objective="second", trigger="cron")
    # The conflict rolls back only the nested savepoint, not the whole session.
    assert agent.name == "a"
    rows = (await session.execute(select(AgentTask).where(AgentTask.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1


async def test_second_open_task_per_agent_is_rejected_by_the_database(session):
    """The partial unique index, not just the enqueue() pre-check, is what makes this impossible."""
    agent = await make_agent(session)
    agent_id = agent.id  # captured before the rollback below expires `agent`
    t1 = AgentTask(agent_id=agent_id, trigger="manual", objective="1", instructions="", max_steps=5, timeout_seconds=60)
    session.add(t1)
    await session.commit()
    t1_id = t1.id  # captured before the rollback below expires t1

    t2 = AgentTask(agent_id=agent_id, trigger="manual", objective="2", instructions="", max_steps=5, timeout_seconds=60)
    session.add(t2)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    await AgentTaskService.finish(session, await session.get(AgentTask, t1_id), "completed", outcome="success")
    t3 = AgentTask(agent_id=agent_id, trigger="manual", objective="3", instructions="", max_steps=5, timeout_seconds=60)
    session.add(t3)
    await session.commit()  # the agent's only open task is gone now, so this succeeds


async def test_claim_under_real_overlap_never_runs_two_tasks_of_one_agent(setup_db, session):
    """Reproduces the real race: a claimer holds its transaction open (uncommitted) while
    a second, independent session claims concurrently. The agent-row lock in the claim SQL
    (FOR UPDATE OF t, a) must let the second claimer skip straight to a different agent's
    task rather than block forever or double-claim."""
    a1 = await make_agent(session, "a1")
    a2 = await make_agent(session, "a2")
    a3 = await make_agent(session, "a3")
    await AgentTaskService.enqueue(session, a1, objective="1", trigger="manual")
    await AgentTaskService.enqueue(session, a2, objective="2", trigger="manual")
    await AgentTaskService.enqueue(session, a3, objective="3", trigger="manual")

    claim_sql = text("""
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
    """)

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    async with setup_db.connect() as conn:
        held_row = (await conn.execute(claim_sql, {"worker_id": "holder"})).first()
        assert held_row is not None
        held_agent_id = (await conn.execute(
            text("SELECT agent_id FROM agent_task WHERE id = :id"), {"id": held_row[0]}
        )).scalar_one()
        # conn's transaction is still open (no commit yet): this is the uncommitted running
        # row that a buggy NOT EXISTS check would not see.

        async with factory() as s2:
            second = await asyncio.wait_for(AgentTaskService.claim(s2, "w2"), timeout=5)
        assert second is not None
        assert second.agent_id != held_agent_id

        await conn.commit()

    rows = (await session.execute(select(AgentTask.agent_id).where(AgentTask.status == "running"))).scalars().all()
    assert len(rows) == 2
    assert len(set(rows)) == 2  # exactly one running row per agent, never two for the same one


async def test_concurrent_enqueue_only_one_wins(setup_db, session):
    agent = await make_agent(session)
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s1, factory() as s2:
        a1, a2 = await s1.get(Agent, agent.id), await s2.get(Agent, agent.id)
        results = await asyncio.gather(
            AgentTaskService.enqueue(s1, a1, objective="x", trigger="manual"),
            AgentTaskService.enqueue(s2, a2, objective="y", trigger="cron"),
            return_exceptions=True,
        )
    successes = [r for r in results if isinstance(r, AgentTask)]
    failures = [r for r in results if isinstance(r, TaskConflict)]
    assert len(successes) == 1 and len(failures) == 1

    rows = (await session.execute(select(AgentTask).where(AgentTask.agent_id == agent.id))).scalars().all()
    assert len(rows) == 1


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


async def test_sweep_handles_null_heartbeat_and_skips_locked(setup_db, session):
    a1 = await make_agent(session, "a1")
    a2 = await make_agent(session, "a2")
    null_hb = AgentTask(agent_id=a1.id, trigger="manual", objective="n", instructions="", max_steps=5, timeout_seconds=60,
                        status="running", worker_id="dead", heartbeat_at=None,
                        started_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    locked = AgentTask(agent_id=a2.id, trigger="manual", objective="l", instructions="", max_steps=5, timeout_seconds=60,
                       status="running", worker_id="dead2",
                       started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                       heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    session.add_all([null_hb, locked])
    await session.commit()

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    async with factory() as holder:
        await holder.execute(select(AgentTask.id).where(AgentTask.id == locked.id).with_for_update())
        # holder's transaction stays open, holding the row lock on `locked`.

        swept = await AgentTaskService.sweep_stale(session, older_than_seconds=90)
        assert swept == 1

        await holder.rollback()

    await session.refresh(null_hb)
    await session.refresh(locked)
    assert null_hb.status == "failed" and null_hb.error == "worker lost"
    assert locked.status == "running"


async def test_sweep_survives_a_failing_candidate(session, monkeypatch):
    """A failure on one candidate (e.g. a transient error inside record_step) must not
    expire the ORM objects of the other candidates and abort the whole sweep: it must
    roll back just that candidate's work and keep going."""
    agent1 = await make_agent(session, "a1")
    agent2 = await make_agent(session, "a2")
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    task1 = AgentTask(agent_id=agent1.id, trigger="manual", objective="1", instructions="",
                      max_steps=5, timeout_seconds=60, status="running", worker_id="dead1",
                      started_at=old, heartbeat_at=old)
    task2 = AgentTask(agent_id=agent2.id, trigger="manual", objective="2", instructions="",
                      max_steps=5, timeout_seconds=60, status="running", worker_id="dead2",
                      started_at=old, heartbeat_at=old)
    session.add_all([task1, task2])
    await session.commit()
    task1_id, task2_id = task1.id, task2.id

    original_record_step = AgentTaskService.record_step
    calls = {"n": 0}

    async def flaky_record_step(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return await original_record_step(*args, **kwargs)

    monkeypatch.setattr(AgentTaskService, "record_step", flaky_record_step)

    count = await AgentTaskService.sweep_stale(session, older_than_seconds=90)
    assert count == 1

    # The DB query has no ORDER BY, so which of the two stale rows is handed to the
    # first (failing) record_step call is unspecified; what must hold regardless is
    # that exactly one survives untouched (still running) and the other was carried
    # through to failed once record_step started working again.
    task1 = await session.get(AgentTask, task1_id)
    task2 = await session.get(AgentTask, task2_id)
    statuses = {task1.status, task2.status}
    assert statuses == {"running", "failed"}
    failed_task = task1 if task1.status == "failed" else task2
    assert failed_task.error == "worker lost"


async def test_record_step_increments_seq_and_totals(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
    s1 = await AgentTaskService.record_step(session, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "p"}], tokens_in=10, tokens_out=5)
    assert task.step_count == 1 and task.tokens_in == 10 and task.tokens_out == 5  # record_step refreshes task itself
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
