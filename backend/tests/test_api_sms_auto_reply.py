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
async def test_the_endpoints_answer_before_anything_is_configured():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/sms-autoreply/replies")).status_code == 200
        stats = await client.get("/api/v1/sms-autoreply/stats")
        assert stats.status_code == 200
        assert stats.json() == {"sent": 0, "failed": 0, "skipped": 0, "sending": 0, "last_sent_at": None}
        run = await client.post("/api/v1/sms-autoreply/run")
        assert run.status_code == 200
        assert run.json()["reason"] == "SMS auto-reply is disabled"
