import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, Config
from app.utils.crypto import decrypt_value

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


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_google_key_is_encrypted_and_never_returned(client, setup_test_db):
    with patch("app.routers.config.scheduler_service"):
        response = await client.put(
            "/api/v1/config", json={"google_sa_key": '{"type": "service_account"}'}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["google_sa_key_set"] is True
    assert "google_sa_key" not in body

    async with setup_test_db() as session:
        config = (await session.execute(select(Config))).scalar_one()
        assert config.google_sa_key != '{"type": "service_account"}'
        assert decrypt_value(config.google_sa_key) == '{"type": "service_account"}'


async def test_default_projects_cron_is_exposed(client):
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["projects_cron"] == "0 6 * * *"
    assert response.json()["google_sa_key_set"] is False


async def test_changing_cron_reschedules_the_job(client):
    with patch("app.routers.config.scheduler_service") as scheduler:
        response = await client.put("/api/v1/config", json={"projects_cron": "30 7 * * 1-5"})

    assert response.status_code == 200
    assert response.json()["projects_cron"] == "30 7 * * 1-5"
    scheduler.set_projects_job.assert_called_once_with("30 7 * * 1-5")
