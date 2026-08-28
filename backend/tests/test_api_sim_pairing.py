import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def api_session_override():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_session
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_manage_sim_pairing_groups():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/sim-pairing/groups", json={"name": "love"})
        assert created.status_code == 201
        group_id = created.json()["id"]

        listed = await client.get("/api/v1/sim-pairing/groups")
        assert listed.status_code == 200
        assert [group["name"] for group in listed.json()] == ["love"]

        duplicate = await client.post("/api/v1/sim-pairing/groups", json={"name": "love"})
        assert duplicate.status_code == 409

        deleted = await client.delete(f"/api/v1/sim-pairing/groups/{group_id}")
        assert deleted.status_code == 204
