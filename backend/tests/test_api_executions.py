import os
import uuid

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Base, Config, Prompt, Script, Execution
from app.utils.crypto import encrypt_value

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


async def create_test_data(async_session):
    """Create a prompt + script + execution for testing."""
    async with async_session() as session:
        config = Config(
            llm_provider="openai",
            llm_model="gpt-4",
            api_key=encrypt_value("sk-test-key"),
        )
        session.add(config)

        prompt = Prompt(name="Test Prompt", prompt_text="Test prompt text")
        session.add(prompt)
        await session.commit()

        script = Script(
            prompt_id=prompt.id,
            version=1,
            code='import json\nprint(json.dumps({"output": "test", "llm_used": False, "tokens": 0}))',
            needs_llm=False,
        )
        session.add(script)
        await session.commit()

        execution = Execution(
            script_id=script.id,
            status="success",
            output="test output",
            tokens_used=10,
            duration_ms=100,
        )
        session.add(execution)
        await session.commit()

        return {
            "prompt_id": str(prompt.id),
            "script_id": str(script.id),
            "execution_id": str(execution.id),
        }


@pytest.mark.asyncio
async def test_list_executions_empty(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/executions")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_list_executions(setup_test_db):
    data = await create_test_data(setup_test_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/executions")
        assert resp.status_code == 200
        executions = resp.json()
        assert len(executions) == 1
        assert executions[0]["id"] == data["execution_id"]
        assert executions[0]["status"] == "success"
        assert executions[0]["prompt_name"] == "Test Prompt"
        assert executions[0]["script_version"] == 1


@pytest.mark.asyncio
async def test_list_executions_filter_by_status(setup_test_db):
    await create_test_data(setup_test_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Filter by matching status
        resp = await client.get("/api/v1/executions?status=success")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Filter by non-matching status
        resp = await client.get("/api/v1/executions?status=failed")
        assert resp.status_code == 200
        assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_get_execution_by_id(setup_test_db):
    data = await create_test_data(setup_test_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/executions/{data['execution_id']}")
        assert resp.status_code == 200
        result = resp.json()
        assert result["id"] == data["execution_id"]
        assert result["status"] == "success"
        assert result["output"] == "test output"
        assert result["prompt_name"] == "Test Prompt"
        assert result["tokens_used"] == 10


@pytest.mark.asyncio
async def test_get_execution_not_found(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/executions/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_prompt_executions(setup_test_db):
    data = await create_test_data(setup_test_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/prompts/{data['prompt_id']}/executions")
        assert resp.status_code == 200
        executions = resp.json()
        assert len(executions) == 1
        assert executions[0]["id"] == data["execution_id"]


@pytest.mark.asyncio
async def test_list_prompt_executions_empty_for_unknown_prompt(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/prompts/{uuid.uuid4()}/executions")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_run_script_via_api(setup_test_db):
    """Test POST /scripts/:id/run endpoint."""
    data = await create_test_data(setup_test_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/scripts/{data['script_id']}/run")
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "success"
        assert result["script_id"] == data["script_id"]


@pytest.mark.asyncio
async def test_run_script_not_found(setup_test_db):
    """Test POST /scripts/:id/run with invalid script ID."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/v1/scripts/{uuid.uuid4()}/run")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_executions_pagination(setup_test_db):
    """Test limit/offset pagination on executions list."""
    await create_test_data(setup_test_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/executions?limit=1&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = await client.get("/api/v1/executions?limit=1&offset=1")
        assert resp.status_code == 200
        assert len(resp.json()) == 0
