import os

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest

from app.services.script_executor import ScriptExecutor


@pytest.mark.asyncio
async def test_execute_simple_script(session):
    from app.models import Prompt, Script, Config
    from app.utils.crypto import encrypt_value

    # Create config
    config = Config(llm_provider="openai", llm_model="gpt-4", api_key=encrypt_value("sk-test"))
    session.add(config)

    prompt = Prompt(name="Test", prompt_text="Test", cron_expr="0 * * * *")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code='import json\nprint(json.dumps({"output": "hello", "llm_used": False, "tokens": 0}))',
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "success"
    assert "hello" in execution.output
    assert execution.tokens_used == 0


@pytest.mark.asyncio
async def test_execute_failing_script(session):
    from app.models import Prompt, Script, Config
    from app.utils.crypto import encrypt_value

    config = Config(llm_provider="openai", llm_model="gpt-4", api_key=encrypt_value("sk-test"))
    session.add(config)

    prompt = Prompt(name="Test", prompt_text="Test")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code="raise Exception('boom')",
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "failed"
    assert "boom" in execution.error


@pytest.mark.asyncio
async def test_execute_timeout_script(session):
    from app.models import Prompt, Script, Config
    from app.utils.crypto import encrypt_value

    config = Config(llm_provider="openai", llm_model="gpt-4", api_key=encrypt_value("sk-test"))
    session.add(config)

    prompt = Prompt(name="Timeout Test", prompt_text="Test")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code="import time\ntime.sleep(60)",
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session, timeout=1)
    assert execution.status == "timeout"
    assert "timed out" in execution.error


@pytest.mark.asyncio
async def test_execute_script_no_config(session):
    """Script should still run even without LLM config."""
    from app.models import Prompt, Script

    prompt = Prompt(name="No Config Test", prompt_text="Test")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code='import json\nprint(json.dumps({"output": "no config", "llm_used": False, "tokens": 0}))',
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "success"
    assert "no config" in execution.output


@pytest.mark.asyncio
async def test_execute_script_non_json_output(session):
    """Script that outputs non-JSON should still succeed."""
    from app.models import Prompt, Script

    prompt = Prompt(name="Non-JSON Test", prompt_text="Test")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code='print("plain text output")',
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "success"
    assert "plain text output" in execution.output


@pytest.mark.asyncio
async def test_execute_script_sets_duration(session):
    """Execution should record duration_ms and finished_at."""
    from app.models import Prompt, Script

    prompt = Prompt(name="Duration Test", prompt_text="Test")
    session.add(prompt)
    await session.commit()

    script = Script(
        prompt_id=prompt.id, version=1,
        code='import json\nprint(json.dumps({"output": "done", "llm_used": False, "tokens": 5}))',
        needs_llm=False,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)

    execution = await ScriptExecutor.run(script, session)
    assert execution.status == "success"
    assert execution.duration_ms is not None
    assert execution.duration_ms >= 0
    assert execution.finished_at is not None
    assert execution.tokens_used == 5
