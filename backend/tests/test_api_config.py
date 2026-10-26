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
    assert "activity_cron" in data


@pytest.mark.asyncio
async def test_update_config():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/v1/config", json={"llm_provider": "anthropic", "llm_model": "claude-3"})
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "anthropic"


@pytest.mark.asyncio
async def test_a_lookback_no_longer_than_the_job_interval_is_rejected():
    # The job runs every 15 minutes and APScheduler coalesces missed runs, so a
    # window equal to the interval never reads the gap left by a restart.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        too_short = await client.put("/api/v1/config", json={"sms_autoreply_lookback_minutes": 15})
        assert too_short.status_code == 422
        assert "30" in too_short.json()["detail"]
        ok = await client.put("/api/v1/config", json={"sms_autoreply_lookback_minutes": 30})
        assert ok.status_code == 200
        assert ok.json()["sms_autoreply_lookback_minutes"] == 30


@pytest.mark.asyncio
async def test_a_lookback_longer_than_the_recipient_cooldown_is_rejected():
    # A trigger held back by the cooldown is recorded nowhere, so it stays in
    # the lookback window and fires again as soon as the cooldown expires.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        both = await client.put("/api/v1/config", json={
            "sms_autoreply_lookback_minutes": 120,
            "sms_autoreply_recipient_cooldown_hours": 1,
        })
        assert both.status_code == 422
        assert "cooldown" in both.json()["detail"]

        # And on the effective pair: a request may carry only one of the two,
        # so the incoming value is checked against the stored one.
        stored = await client.put("/api/v1/config", json={"sms_autoreply_lookback_minutes": 1440})
        assert stored.status_code == 200
        alone = await client.put("/api/v1/config", json={"sms_autoreply_recipient_cooldown_hours": 1})
        assert alone.status_code == 422
        assert "1440" in alone.json()["detail"]


@pytest.mark.asyncio
async def test_approval_settings_round_trip(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        before = (await c.get("/api/v1/config")).json()
        assert before["approval_expiry_hours"] == 24 and before["approval_whatsapp_enabled"] is False
        assert before["approval_whatsapp_number"] == "+2250700003331" and before["approval_whatsapp_server_id"] is None
        resp = await c.put("/api/v1/config", json={"approval_expiry_hours": 48, "approval_whatsapp_enabled": True,
                                                   "approval_whatsapp_number": "+22501020304", "approval_whatsapp_session_id": "sess-1",
                                                   "approval_whatsapp_template": "Hi {agent} {code} {link}"})
        assert resp.status_code == 200, resp.text
        after = resp.json()
        assert after["approval_expiry_hours"] == 48 and after["approval_whatsapp_enabled"] is True
        assert after["approval_whatsapp_number"] == "+22501020304" and after["approval_whatsapp_session_id"] == "sess-1"
        assert (await c.put("/api/v1/config", json={"approval_expiry_hours": 0})).status_code == 422
        assert (await c.put("/api/v1/config", json={"approval_whatsapp_number": "abc"})).status_code == 422
        assert (await c.put("/api/v1/config", json={"approval_whatsapp_template": "no code here"})).status_code == 422
