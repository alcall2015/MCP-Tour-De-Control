import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Agent, AgentTask, AgentTaskStep


async def _agent(session) -> Agent:
    agent = Agent(name="a", objective="o")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_task_defaults_and_snapshots(session):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="do it", instructions="be nice",
                     max_steps=5, timeout_seconds=60)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    assert task.status == "queued"
    assert task.outcome is None
    assert task.cancel_requested is False
    assert task.step_count == 0 and task.tokens_in == 0 and task.tokens_out == 0
    assert task.created_at is not None and task.started_at is None


async def test_steps_are_unique_per_seq_and_cascade(session):
    agent = await _agent(session)
    agent_id = agent.id  # Capture ID before any potential expiration
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60)
    session.add(task)
    await session.commit()
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="plan", payload={"steps": []}, prompt=[{"role": "system", "content": "x"}]))
    await session.commit()
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="turn", payload={}))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    # Get a fresh agent from the DB and delete it to ensure cascading deletes work
    fresh_agent = await session.get(Agent, agent_id)
    await session.delete(fresh_agent)
    await session.commit()
    assert (await session.execute(select(AgentTask))).scalars().all() == []
    assert (await session.execute(select(AgentTaskStep))).scalars().all() == []


@pytest.mark.parametrize("field,value", [("status", "done"), ("outcome", "ok"), ("trigger", "api")])
async def test_task_check_constraints(session, field, value):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60)
    setattr(task, field, value)
    session.add(task)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_step_kind_check_constraint(session):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60)
    session.add(task)
    await session.commit()
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="thought", payload={}))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_agent_has_optional_cron(session):
    agent = Agent(name="a", objective="o", cron_expr="0 8 * * *")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    assert agent.cron_expr == "0 8 * * *"
