import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Agent, McpServer


async def _server(session, name="tm", enabled=True) -> McpServer:
    server = McpServer(name=name, transport="http", url="http://example.test/mcp", enabled=enabled)
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


async def test_agent_defaults(session):
    agent = Agent(name="a", objective="o")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    assert agent.status == "draft"
    assert agent.instructions == ""
    assert agent.description is None
    assert agent.max_steps == 20
    assert agent.timeout_seconds == 300
    assert agent.created_at is not None
    assert agent.mcp_servers == []


async def test_agent_links_servers(session):
    s1 = await _server(session, "one")
    s2 = await _server(session, "two")
    agent = Agent(name="a", objective="o", mcp_servers=[s1, s2])
    session.add(agent)
    await session.commit()
    session.expunge_all()

    loaded = (await session.execute(select(Agent))).scalar_one()
    assert sorted(s.name for s in loaded.mcp_servers) == ["one", "two"]


async def test_deleting_server_unlinks_it(session):
    s1 = await _server(session, "one")
    agent = Agent(name="a", objective="o", mcp_servers=[s1])
    session.add(agent)
    await session.commit()
    session.expunge_all()

    server = await session.get(McpServer, s1.id)
    await session.delete(server)
    await session.commit()
    session.expunge_all()

    loaded = (await session.execute(select(Agent))).scalar_one()
    assert loaded.mcp_servers == []


@pytest.mark.parametrize("field,value", [
    ("status", "running"),
    ("max_steps", 0),
    ("max_steps", 101),
    ("timeout_seconds", 9),
    ("timeout_seconds", 3601),
])
async def test_check_constraints(session, field, value):
    agent = Agent(name="a", objective="o")
    setattr(agent, field, value)
    session.add(agent)
    with pytest.raises(IntegrityError):
        await session.commit()
