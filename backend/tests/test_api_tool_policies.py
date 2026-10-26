import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Base, McpServer
from app.schemas import McpTestResult, McpToolInfo

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_async_session] = override
    yield factory
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


DISCOVERED = McpTestResult(success=True, tools=[McpToolInfo(name="list_x", description="list"), McpToolInfo(name="write_x", description="write")])


async def make_server(factory) -> str:
    async with factory() as s:
        server = McpServer(name="srv", transport="http", url="http://x", enabled=True)
        s.add(server)
        await s.commit()
        return str(server.id)


async def test_list_tools_discovers_and_merges_policies(setup_test_db):
    sid = await make_server(setup_test_db)
    with patch("app.services.tool_policy_service.McpService.test_connection", AsyncMock(return_value=DISCOVERED)):
        async with client() as c:
            resp = await c.get(f"/api/v1/mcp-servers/{sid}/tools")
            assert resp.status_code == 200, resp.text
            assert resp.json() == [{"name": "list_x", "description": "list", "risk_level": 2},
                                   {"name": "write_x", "description": "write", "risk_level": 2}]
            resp = await c.put(f"/api/v1/mcp-servers/{sid}/tools/list_x", json={"risk_level": 0})
            assert resp.status_code == 200 and resp.json()["risk_level"] == 0
            resp = await c.get(f"/api/v1/mcp-servers/{sid}/tools")
            assert [t["risk_level"] for t in resp.json()] == [0, 2]


async def test_put_validates_and_404s(setup_test_db):
    sid = await make_server(setup_test_db)
    async with client() as c:
        assert (await c.put(f"/api/v1/mcp-servers/{sid}/tools/list_x", json={"risk_level": 4})).status_code == 422
        assert (await c.put(f"/api/v1/mcp-servers/{sid}/tools/unknown", json={"risk_level": 1})).status_code == 404
        assert (await c.put(f"/api/v1/mcp-servers/{uuid.uuid4()}/tools/x", json={"risk_level": 1})).status_code == 404


async def test_discovery_failure_is_502(setup_test_db):
    sid = await make_server(setup_test_db)
    with patch("app.services.tool_policy_service.McpService.test_connection", AsyncMock(return_value=McpTestResult(success=False, error="down"))):
        async with client() as c:
            resp = await c.get(f"/api/v1/mcp-servers/{sid}/tools")
    assert resp.status_code == 502 and "down" in resp.json()["detail"]


async def test_test_endpoint_syncs_policies(setup_test_db):
    sid = await make_server(setup_test_db)
    with patch("app.routers.mcp_servers.McpService.test_connection", AsyncMock(return_value=DISCOVERED)):
        async with client() as c:
            assert (await c.post(f"/api/v1/mcp-servers/{sid}/test")).status_code == 200
    from sqlalchemy import select
    from app.models import ToolPolicy
    async with setup_test_db() as s:
        names = sorted(p.tool_name for p in (await s.execute(select(ToolPolicy))).scalars().all())
    assert names == ["list_x", "write_x"]
