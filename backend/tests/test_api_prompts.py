import os
import uuid

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import patch, AsyncMock, MagicMock

from app.main import app
from app.database import get_async_session
from app.models import Base, Config, McpServer
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


async def create_config(async_session):
    """Helper to create a Config with an encrypted API key."""
    async with async_session() as session:
        config = Config(
            llm_provider="openai",
            llm_model="gpt-4",
            api_key=encrypt_value("sk-test-key"),
        )
        session.add(config)
        await session.commit()


def make_mock_llm_response(code: str):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = code
    mock_response.usage.total_tokens = 100
    return mock_response


SIMPLE_SCRIPT = """import asyncio
import json

async def main():
    print(json.dumps({"output": "done", "llm_used": False, "tokens": 0}))

if __name__ == "__main__":
    asyncio.run(main())"""


@pytest.mark.asyncio
async def test_list_prompts_empty(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/prompts")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_create_prompt_no_config(setup_test_db):
    """Creating a prompt without LLM config should return 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/prompts", json={
            "name": "test prompt",
            "prompt_text": "do something",
            "mcp_server_ids": [],
        })
        assert resp.status_code == 400
        assert "LLM not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_prompt_with_llm_mock(setup_test_db):
    """Create a prompt with mocked LLM — script should be generated."""
    await create_config(setup_test_db)

    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)
    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "my prompt",
                "prompt_text": "list files",
                "mcp_server_ids": [],
            })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my prompt"
    assert data["latest_script_version"] == 1
    assert data["needs_llm"] is False


@pytest.mark.asyncio
async def test_get_prompt_not_found(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/prompts/{uuid.uuid4()}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_prompt(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "get test",
                "prompt_text": "do something",
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]

            resp = await client.get(f"/api/v1/prompts/{prompt_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == prompt_id


@pytest.mark.asyncio
async def test_update_prompt(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "old name",
                "prompt_text": "original text",
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]

            resp = await client.put(f"/api/v1/prompts/{prompt_id}", json={"name": "new name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new name"


@pytest.mark.asyncio
async def test_delete_prompt(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "to delete",
                "prompt_text": "delete me",
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]

            resp = await client.delete(f"/api/v1/prompts/{prompt_id}")
            assert resp.status_code == 204

            resp = await client.get(f"/api/v1/prompts/{prompt_id}")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_toggle_prompt(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "toggle test",
                "prompt_text": "toggle me",
                "enabled": True,
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]
            assert resp.json()["enabled"] is True

            resp = await client.put(f"/api/v1/prompts/{prompt_id}/toggle")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_regenerate_script(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "regen test",
                "prompt_text": "do the thing",
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]
            assert resp.json()["latest_script_version"] == 1

            resp = await client.post(f"/api/v1/prompts/{prompt_id}/regenerate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 2
    assert data["prompt_id"] == prompt_id


@pytest.mark.asyncio
async def test_list_prompt_scripts(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "script list test",
                "prompt_text": "list scripts",
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]

            # Regenerate to get a second script
            await client.post(f"/api/v1/prompts/{prompt_id}/regenerate")

            resp = await client.get(f"/api/v1/prompts/{prompt_id}/scripts")
    assert resp.status_code == 200
    scripts = resp.json()
    assert len(scripts) == 2
    # Should be ordered descending by version
    assert scripts[0]["version"] > scripts[1]["version"]


@pytest.mark.asyncio
async def test_get_script_by_id(setup_test_db):
    await create_config(setup_test_db)
    mock_response = make_mock_llm_response(SIMPLE_SCRIPT)

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/prompts", json={
                "name": "script get test",
                "prompt_text": "get a script",
                "mcp_server_ids": [],
            })
            prompt_id = resp.json()["id"]

            resp = await client.get(f"/api/v1/prompts/{prompt_id}/scripts")
            script_id = resp.json()[0]["id"]

            resp = await client.get(f"/api/v1/scripts/{script_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == script_id


@pytest.mark.asyncio
async def test_get_script_not_found(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/scripts/{uuid.uuid4()}")
        assert resp.status_code == 404
