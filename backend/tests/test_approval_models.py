import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config, McpServer, ToolPolicy
from app.models.agent_task import OPEN_STATUSES, STEP_KINDS


async def _agent_and_task(session):
    server = McpServer(name="srv", transport="http", url="http://x", enabled=True)
    agent = Agent(name="a", objective="o", status="active", mcp_servers=[server])
    session.add(agent)
    await session.commit()
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60, status="running")
    session.add(task)
    await session.commit()
    return server, agent, task


async def test_constants_include_the_new_states():
    assert "waiting_approval" in OPEN_STATUSES
    assert "approval_requested" in STEP_KINDS


async def test_agent_max_auto_risk_default_and_bounds(session):
    agent = Agent(name="a", objective="o")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    assert agent.max_auto_risk == 1
    agent.max_auto_risk = 3
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_task_accepts_waiting_approval_and_keeps_one_open_per_agent(session):
    _, agent, task = await _agent_and_task(session)
    task.status = "waiting_approval"
    await session.commit()
    session.add(AgentTask(agent_id=agent.id, trigger="manual", objective="o2", instructions="", max_steps=5, timeout_seconds=60))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_step_kind_approval_requested(session):
    _, _, task = await _agent_and_task(session)
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="approval_requested", payload={"code": "ABC234"}))
    await session.commit()


async def test_tool_policy_unique_and_default_level(session):
    server, _, _ = await _agent_and_task(session)
    session.add(ToolPolicy(mcp_server_id=server.id, tool_name="list_x"))
    await session.commit()
    p = (await session.execute(select(ToolPolicy))).scalar_one()
    assert p.risk_level == 2 and p.first_seen_at is not None
    session.add(ToolPolicy(mcp_server_id=server.id, tool_name="list_x"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_approval_defaults_and_checks(session):
    _, agent, task = await _agent_and_task(session)
    a = Approval(task_id=task.id, agent_id=agent.id, step_seq=2, call_index=0, tool_name="write_x", server_name="srv",
                 args={"a": 1}, args_hash="h", risk_level=2, code="ABC234", expires_at=task.created_at)
    session.add(a)
    await session.commit()
    await session.refresh(a)
    assert a.status == "pending" and a.consumed_at is None and a.requested_at is not None
    task_id = task.id  # captured before the rollback below expires `task`
    a.status = "maybe"
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    await session.delete(await session.get(AgentTask, task_id))
    await session.commit()
    assert (await session.execute(select(Approval))).scalars().all() == []


async def test_config_approval_defaults(session):
    c = Config(llm_provider="openai", llm_model="m", api_key="")
    session.add(c)
    await session.commit()
    await session.refresh(c)
    assert c.approval_expiry_hours == 24 and c.approval_whatsapp_enabled is False
    assert c.approval_whatsapp_number == "+2250700003331"
    assert c.approval_whatsapp_server_id is None and c.approval_whatsapp_session_id is None
    assert "{code}" in c.approval_whatsapp_template and "{link}" in c.approval_whatsapp_template
