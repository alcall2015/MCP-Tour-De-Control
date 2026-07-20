import json


def build_generation_prompt(user_prompt: str, mcp_servers: list[dict]) -> str:
    servers_section = ""
    if mcp_servers:
        for server in mcp_servers:
            servers_section += f"\n### {server['name']} (transport: {server['transport']})\n"
            if server["transport"] == "stdio":
                servers_section += f"Command: {server['command']} {' '.join(server.get('args', []))}\n"
            else:
                servers_section += f"URL: {server.get('url', 'N/A')}\n"
            if server.get("tools"):
                servers_section += "Tools:\n"
                for tool in server["tools"]:
                    schema_str = json.dumps(tool.get("inputSchema", {}), indent=2)
                    servers_section += f"- `{tool['name']}`: {tool.get('description', '')} — input: {schema_str}\n"

    return f"""You are a Python script generator for MCP Tour De Control.

Generate a Python script that accomplishes the following task:
{user_prompt}

## Available MCP Servers
{servers_section if servers_section else "No MCP servers configured."}

## Rules

1. Use `fastmcp.Client` to connect to MCP servers. For stdio transport:
   ```python
   from fastmcp import Client
   async with Client("stdio", command="<command>", args=[...]) as client:
       result = await client.call_tool("<tool_name>", {{"arg": "value"}})
   ```

2. If a step requires reasoning (summarization, analysis, classification), use the LLM API:
   ```python
   import os
   from openai import OpenAI
   llm = OpenAI(api_key=os.environ["LLM_API_KEY"])
   ```
   Read the provider from `os.environ["LLM_PROVIDER"]` and model from `os.environ["LLM_MODEL"]`.

3. For steps that produce deterministic output (filtering, formatting, counting), use pure Python.

4. The script MUST print a single JSON line to stdout at the end:
   ```python
   import json
   print(json.dumps({{"output": "<result>", "llm_used": True/False, "tokens": <int>}}))
   ```

5. Wrap everything in an async main() and call asyncio.run(main()).

6. Handle errors gracefully — catch exceptions and include them in the output JSON.

Generate ONLY the Python code, no markdown fences, no explanation."""
