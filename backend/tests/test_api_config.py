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
async def test_get_config_returns_default():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm_provider" in data
    assert "api_key_set" in data
    assert "api_key" not in data  # key must never be exposed
    assert "google_sa_key_set" in data
    assert "google_sa_key" not in data  # key must never be exposed
    assert "projects_cron" in data


@pytest.mark.asyncio
async def test_update_config():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/v1/config", json={"llm_provider": "anthropic", "llm_model": "claude-3"})
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "anthropic"
