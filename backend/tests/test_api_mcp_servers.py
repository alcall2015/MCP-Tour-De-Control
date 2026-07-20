import os

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Base

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
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_mcp_server():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/mcp-servers", json={
            "name": "test-server",
            "transport": "stdio",
            "command": "python",
            "args": ["server.py"],
        })
        assert resp.status_code == 201
        server_id = resp.json()["id"]

        resp = await client.get("/api/v1/mcp-servers")
        assert resp.status_code == 200
        assert any(s["id"] == server_id for s in resp.json())


@pytest.mark.asyncio
async def test_update_mcp_server():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/mcp-servers", json={
            "name": "old-name",
            "transport": "stdio",
            "command": "python",
        })
        server_id = resp.json()["id"]

        resp = await client.put(f"/api/v1/mcp-servers/{server_id}", json={"name": "new-name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"


@pytest.mark.asyncio
async def test_delete_mcp_server():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/mcp-servers", json={
            "name": "to-delete",
            "transport": "stdio",
            "command": "python",
        })
        server_id = resp.json()["id"]

        resp = await client.delete(f"/api/v1/mcp-servers/{server_id}")
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/mcp-servers/{server_id}")
        assert resp.status_code == 404
