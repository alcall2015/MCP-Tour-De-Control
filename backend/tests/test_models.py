import pytest
from app.models import Config, McpServer, Prompt, Script, Execution


@pytest.mark.asyncio
async def test_create_config(session):
    config = Config(llm_provider="openai", llm_model="gpt-4", api_key="test-key")
    session.add(config)
    await session.commit()
    await session.refresh(config)
    assert config.id is not None
    assert config.llm_provider == "openai"


@pytest.mark.asyncio
async def test_create_mcp_server(session):
    server = McpServer(name="test-server", transport="stdio", command="python", args=["server.py"])
    session.add(server)
    await session.commit()
    await session.refresh(server)
    assert server.id is not None
    assert server.enabled is True


@pytest.mark.asyncio
async def test_create_prompt_with_script(session):
    prompt = Prompt(name="Test Prompt", prompt_text="Do something", cron_expr="0 8 * * *")
    session.add(prompt)
    await session.commit()
    await session.refresh(prompt)

    script = Script(prompt_id=prompt.id, version=1, code="print('hello')", needs_llm=False)
    session.add(script)
    await session.commit()
    await session.refresh(script)
    assert script.prompt_id == prompt.id


@pytest.mark.asyncio
async def test_create_execution(session):
    prompt = Prompt(name="Test", prompt_text="Test", cron_expr="0 * * * *")
    session.add(prompt)
    await session.commit()

    script = Script(prompt_id=prompt.id, version=1, code="pass", needs_llm=False)
    session.add(script)
    await session.commit()

    execution = Execution(script_id=script.id, status="success", output="done", tokens_used=0, duration_ms=100)
    session.add(execution)
    await session.commit()
    await session.refresh(execution)
    assert execution.status == "success"
    assert execution.tokens_used == 0
