from app.utils.prompt_builder import build_generation_prompt


def test_build_prompt_includes_user_prompt():
    result = build_generation_prompt("Fetch open Jira tickets", [])
    assert "Fetch open Jira tickets" in result


def test_build_prompt_includes_mcp_server_tools():
    servers = [
        {
            "name": "jira-server",
            "transport": "stdio",
            "command": "python",
            "args": ["jira_mcp.py"],
            "tools": [
                {"name": "get_tickets", "description": "Get tickets", "input_schema": {"properties": {"status": {"type": "string"}}}}
            ],
        }
    ]
    result = build_generation_prompt("Fetch tickets", servers)
    assert "jira-server" in result
    assert "get_tickets" in result
    # The input schema must reach the LLM — McpService emits the key as `input_schema`
    assert '"status"' in result


def test_build_prompt_includes_hybrid_instructions():
    result = build_generation_prompt("Summarize data", [])
    assert "os.environ" in result
    assert "LLM_API_KEY" in result
