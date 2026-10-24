import os
import uuid

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Base, McpServer

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_async_session
    yield async_session
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def create_server(async_session, name="tm", enabled=True) -> str:
    async with async_session() as session:
        server = McpServer(name=name, transport="http", url="http://example.test/mcp", enabled=enabled)
        session.add(server)
        await session.commit()
        return str(server.id)


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def create_agent(c: AsyncClient, **overrides) -> dict:
    payload = {"name": "Log analyst", "objective": "Find the root cause", "mcp_server_ids": []}
    payload.update(overrides)
    resp = await c.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---- list / create / get -------------------------------------------------

async def test_list_agents_empty():
    async with client() as c:
        resp = await c.get("/api/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_agent_defaults_to_draft(setup_test_db):
    sid = await create_server(setup_test_db, "TmLite")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[sid], instructions="Be terse")
    assert data["status"] == "draft"
    assert data["max_steps"] == 20
    assert data["timeout_seconds"] == 300
    assert data["instructions"] == "Be terse"
    assert data["description"] is None
    assert data["mcp_servers"] == [{"id": sid, "name": "TmLite", "enabled": True}]


async def test_create_agent_ignores_client_status():
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={
            "name": "x", "objective": "y", "mcp_server_ids": [], "status": "active",
        })
    assert resp.status_code == 201
    assert resp.json()["status"] == "draft"


async def test_create_agent_unknown_server_404():
    missing = str(uuid.uuid4())
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={"name": "x", "objective": "y", "mcp_server_ids": [missing]})
    assert resp.status_code == 404
    assert missing in resp.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"name": "", "objective": "y"},
    {"name": "x", "objective": ""},
    {"name": "x", "objective": "y", "max_steps": 0},
    {"name": "x", "objective": "y", "max_steps": 101},
    {"name": "x", "objective": "y", "timeout_seconds": 9},
    {"name": "x", "objective": "y", "timeout_seconds": 5000},
])
async def test_create_agent_validation_422(payload):
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={**payload, "mcp_server_ids": []})
    assert resp.status_code == 422


async def test_get_agent_and_not_found():
    async with client() as c:
        data = await create_agent(c)
        resp = await c.get(f"/api/v1/agents/{data['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Log analyst"
        resp = await c.get(f"/api/v1/agents/{uuid.uuid4()}")
        assert resp.status_code == 404


async def test_list_orders_newest_first():
    async with client() as c:
        await create_agent(c, name="first")
        await create_agent(c, name="second")
        resp = await c.get("/api/v1/agents")
    assert [a["name"] for a in resp.json()] == ["second", "first"]


async def test_create_agent_dedupes_server_ids(setup_test_db):
    sid = await create_server(setup_test_db, "TmLite")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[sid, sid])
    assert [s["id"] for s in data["mcp_servers"]] == [sid]


# ---- update / delete -----------------------------------------------------

async def set_status(async_session, agent_id: str, status: str) -> None:
    from app.models import Agent
    async with async_session() as session:
        agent = await session.get(Agent, uuid.UUID(agent_id))
        agent.status = status
        await session.commit()


async def test_update_fields_and_replace_servers(setup_test_db):
    s1 = await create_server(setup_test_db, "one")
    s2 = await create_server(setup_test_db, "two")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[s1])
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={
            "name": "Renamed", "max_steps": 5, "mcp_server_ids": [s2],
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["max_steps"] == 5
    assert body["objective"] == "Find the root cause"          # untouched
    assert [s["id"] for s in body["mcp_servers"]] == [s2]        # replaced, not merged
    assert body["updated_at"] > data["updated_at"]


async def test_update_without_server_ids_keeps_servers(setup_test_db):
    s1 = await create_server(setup_test_db, "one")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[s1])
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"description": "note"})
    assert resp.status_code == 200
    assert [s["id"] for s in resp.json()["mcp_servers"]] == [s1]
    assert resp.json()["description"] == "note"


async def test_update_unknown_server_404_and_not_found():
    async with client() as c:
        data = await create_agent(c)
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"mcp_server_ids": [str(uuid.uuid4())]})
        assert resp.status_code == 404
        resp = await c.put(f"/api/v1/agents/{uuid.uuid4()}", json={"name": "x"})
        assert resp.status_code == 404


async def test_update_archived_409(setup_test_db):
    async with client() as c:
        data = await create_agent(c)
        await set_status(setup_test_db, data["id"], "archived")
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"name": "x"})
    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"]


async def test_update_validation_422():
    async with client() as c:
        data = await create_agent(c)
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"timeout_seconds": 5000})
    assert resp.status_code == 422


@pytest.mark.parametrize("status", ["draft", "archived"])
async def test_delete_allowed_statuses(setup_test_db, status):
    async with client() as c:
        data = await create_agent(c)
        await set_status(setup_test_db, data["id"], status)
        resp = await c.delete(f"/api/v1/agents/{data['id']}")
        assert resp.status_code == 204
        resp = await c.get(f"/api/v1/agents/{data['id']}")
        assert resp.status_code == 404


@pytest.mark.parametrize("status", ["active", "paused"])
async def test_delete_blocked_statuses(setup_test_db, status):
    async with client() as c:
        data = await create_agent(c)
        await set_status(setup_test_db, data["id"], status)
        resp = await c.delete(f"/api/v1/agents/{data['id']}")
    assert resp.status_code == 409


async def test_delete_not_found():
    async with client() as c:
        resp = await c.delete(f"/api/v1/agents/{uuid.uuid4()}")
    assert resp.status_code == 404
