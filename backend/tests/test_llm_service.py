import ast
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.llm_service import LlmService


@pytest.mark.asyncio
async def test_generate_script_returns_valid_python():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = """import asyncio
import json

async def main():
    result = {"output": "test", "llm_used": False, "tokens": 0}
    print(json.dumps(result))

if __name__ == "__main__":
    asyncio.run(main())"""
    mock_response.usage.total_tokens = 150

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text="Test prompt",
            mcp_servers_info=[],
            api_key="sk-test",
            llm_provider="openai",
            llm_model="gpt-4",
        )

    # Must be valid Python
    ast.parse(code)
    assert isinstance(needs_llm, bool)
    assert isinstance(llm_steps, list)


@pytest.mark.asyncio
async def test_generate_script_detects_llm_usage():
    code_with_llm = """import asyncio
import json
import os
from openai import OpenAI

async def main():
    llm = OpenAI(api_key=os.environ["LLM_API_KEY"])
    print(json.dumps({"output": "done", "llm_used": True, "tokens": 100}))

if __name__ == "__main__":
    asyncio.run(main())"""

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = code_with_llm
    mock_response.usage.total_tokens = 200

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text="Summarize data",
            mcp_servers_info=[],
            api_key="sk-test",
            llm_provider="openai",
            llm_model="gpt-4",
        )

    assert needs_llm is True


@pytest.mark.asyncio
async def test_generate_script_strips_markdown_fences():
    code_in_fences = """```python
import asyncio
import json

async def main():
    print(json.dumps({"output": "ok", "llm_used": False, "tokens": 0}))

if __name__ == "__main__":
    asyncio.run(main())
```"""

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = code_in_fences
    mock_response.usage.total_tokens = 50

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text="Simple task",
            mcp_servers_info=[],
            api_key="sk-test",
            llm_provider="openai",
            llm_model="gpt-4",
        )

    # Code must NOT contain markdown fences
    assert "```" not in code
    ast.parse(code)


@pytest.mark.asyncio
async def test_generate_script_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        await LlmService.generate_script(
            prompt_text="Test",
            mcp_servers_info=[],
            api_key="key",
            llm_provider="groq",
            llm_model="some-model",
        )


@pytest.mark.asyncio
async def test_generate_script_no_llm_markers():
    pure_python_code = """import asyncio
import json

async def main():
    data = [1, 2, 3]
    result = sum(data)
    print(json.dumps({"output": result, "llm_used": False, "tokens": 0}))

if __name__ == "__main__":
    asyncio.run(main())"""

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = pure_python_code
    mock_response.usage.total_tokens = 80

    with patch("app.services.llm_service.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text="Sum a list",
            mcp_servers_info=[],
            api_key="sk-test",
            llm_provider="openai",
            llm_model="gpt-4",
        )

    assert needs_llm is False
    assert llm_steps == []
