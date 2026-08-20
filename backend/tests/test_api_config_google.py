import json
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
from app.services.scheduler_service import is_valid_cron
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


async def test_invalid_cron_leaves_a_valid_google_key_unwritten(client, setup_test_db):
    # Validation happens before any assignment, so a PUT carrying BOTH a
    # valid google_sa_key AND an invalid activity_cron must reject the whole
    # request (422) and must not persist the pasted credential either.
    with patch("app.routers.config.scheduler_service") as scheduler:
        response = await client.put(
            "/api/v1/config",
            json={
                "google_sa_key": '{"type": "service_account"}',
                "activity_cron": "not a cron",
            },
        )

    assert response.status_code == 422
    scheduler.set_activity_job.assert_not_called()

    async with setup_test_db() as session:
        config = (await session.execute(select(Config))).scalar_one_or_none()
        assert config is None or not config.google_sa_key


async def test_default_activity_cron_is_exposed(client):
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["activity_cron"] == "0 6 * * *"
    assert response.json()["google_sa_key_set"] is False
    assert response.json()["google_sa_email"] is None


async def test_google_sa_email_is_exposed_but_no_other_key_material_is(client, setup_test_db):
    key_json = json.dumps(
        {
            "type": "service_account",
            "project_id": "proj-123",
            "private_key_id": "abc123",
            "private_key": "-----BEGIN PRIVATE KEY-----\nSUPER-SECRET\n-----END PRIVATE KEY-----\n",
            "client_email": "svc@proj-123.iam.gserviceaccount.com",
            "client_id": "999999",
        }
    )
    with patch("app.routers.config.scheduler_service"):
        response = await client.put("/api/v1/config", json={"google_sa_key": key_json})

    assert response.status_code == 200
    body = response.json()
    assert body["google_sa_email"] == "svc@proj-123.iam.gserviceaccount.com"
    assert body["google_sa_key_set"] is True

    serialized = json.dumps(body)
    for secret in ["SUPER-SECRET", "private_key", "private_key_id", "abc123", "999999"]:
        assert secret not in serialized

    # A follow-up GET must keep exposing only the email, never the raw key.
    get_response = await client.get("/api/v1/config")
    assert get_response.json()["google_sa_email"] == "svc@proj-123.iam.gserviceaccount.com"
    assert "google_sa_key" not in get_response.json()


async def test_google_sa_email_is_none_for_unparsable_key(client, setup_test_db):
    with patch("app.routers.config.scheduler_service"):
        response = await client.put("/api/v1/config", json={"google_sa_key": "not valid json"})

    assert response.status_code == 200
    assert response.json()["google_sa_email"] is None


async def test_google_sa_email_is_none_when_client_email_absent(client, setup_test_db):
    key_json = json.dumps({"type": "service_account", "project_id": "proj-123"})
    with patch("app.routers.config.scheduler_service"):
        response = await client.put("/api/v1/config", json={"google_sa_key": key_json})

    assert response.status_code == 200
    assert response.json()["google_sa_email"] is None


async def test_changing_cron_reschedules_the_job(client):
    with patch("app.routers.config.scheduler_service") as scheduler:
        response = await client.put("/api/v1/config", json={"activity_cron": "30 7 * * 1-5"})

    assert response.status_code == 200
    assert response.json()["activity_cron"] == "30 7 * * 1-5"
    scheduler.set_activity_job.assert_called_once_with("30 7 * * 1-5")


async def test_unchanged_cron_does_not_reschedule(client):
    with patch("app.routers.config.scheduler_service") as scheduler:
        # First set the cron to a known value.
        first = await client.put("/api/v1/config", json={"activity_cron": "30 7 * * 1-5"})
        assert first.status_code == 200
        scheduler.set_activity_job.assert_called_once_with("30 7 * * 1-5")
        scheduler.reset_mock()

        # PUT the exact same value again: no reschedule should happen.
        second = await client.put("/api/v1/config", json={"activity_cron": "30 7 * * 1-5"})

    assert second.status_code == 200
    assert second.json()["activity_cron"] == "30 7 * * 1-5"
    scheduler.set_activity_job.assert_not_called()


async def test_invalid_cron_is_rejected_before_persisting(client, setup_test_db):
    with patch("app.routers.config.scheduler_service") as scheduler:
        # Establish a known-good stored value first.
        setup_response = await client.put("/api/v1/config", json={"activity_cron": "30 7 * * 1-5"})
        assert setup_response.status_code == 200
        scheduler.reset_mock()

        response = await client.put("/api/v1/config", json={"activity_cron": "not a cron"})

    assert response.status_code == 422
    scheduler.set_activity_job.assert_not_called()

    async with setup_test_db() as session:
        config = (await session.execute(select(Config))).scalar_one()
        assert config.activity_cron == "30 7 * * 1-5"


@pytest.mark.parametrize(
    "cron_expr",
    [
        "0 6 * * *",
        "30 7 * * 1-5",
        "*/15 * * * *",
    ],
)
def test_is_valid_cron_accepts_valid_expressions(cron_expr):
    assert is_valid_cron(cron_expr) is True


@pytest.mark.parametrize(
    "cron_expr",
    [
        "not a cron",
        "99 99 * * *",
        "",
    ],
)
def test_is_valid_cron_rejects_invalid_expressions(cron_expr):
    assert is_valid_cron(cron_expr) is False
