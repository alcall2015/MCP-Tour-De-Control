import json


def build_generation_prompt(user_prompt: str, mcp_servers: list[dict], llm_provider: str = "openai") -> str:
    servers_section = ""
    if mcp_servers:
        for server in mcp_servers:
            servers_section += f"\n### {server['name']} (transport: {server['transport']})\n"
            if server["transport"] == "stdio":
                servers_section += f"Command: {server['command']} {' '.join(server.get('args', []))}\n"
            else:
                servers_section += f"URL: {server.get('url', 'N/A')}\n"
                if server.get("has_api_key"):
                    servers_section += "Authentication: API key required (available in env var `MCP_API_KEY_<SERVER_NAME>`)\n"
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
   from fastmcp.client.transports import StdioTransport
   transport = StdioTransport(command="<command>", args=[...])
   async with Client(transport) as client:
       result = await client.call_tool("<tool_name>", {{"arg": "value"}})
   ```
   For http transport (no auth):
   ```python
   from fastmcp import Client
   async with Client("<url>") as client:
       result = await client.call_tool("<tool_name>", {{"arg": "value"}})
   ```
   For http transport WITH API key authentication:
   ```python
   import os
   from fastmcp import Client
   from fastmcp.client.transports import StreamableHttpTransport
   api_key = os.environ["MCP_API_KEY_<SERVER_NAME>"]
   transport = StreamableHttpTransport("<url>", headers={{"Authorization": f"Bearer {{api_key}}", "X-API-Key": api_key}})
   async with Client(transport) as client:
       result = await client.call_tool("<tool_name>", {{"arg": "value"}})
   ```
   IMPORTANT: If a server has "Authentication: API key required", you MUST use StreamableHttpTransport with headers. The env var name is MCP_API_KEY_ followed by the server name in uppercase with non-alphanumeric chars replaced by underscores.

2. If a step requires reasoning (summarization, analysis, classification), use the LLM API.
   The current LLM provider is: {llm_provider}

   For provider "openai" or "anthropic", use the OpenAI-compatible API:
   ```python
   import os
   from openai import OpenAI
   llm = OpenAI(api_key=os.environ["LLM_API_KEY"])
   response = llm.chat.completions.create(model=os.environ["LLM_MODEL"], messages=[...])
   ```

   For provider "google", use the Google GenAI SDK:
   ```python
   import os
   import google.generativeai as genai
   genai.configure(api_key=os.environ["LLM_API_KEY"])
   model = genai.GenerativeModel(os.environ["LLM_MODEL"])
   response = model.generate_content("your prompt here")
   summary = response.text
   # Set tokens = 0 (Google SDK does not return token counts the same way)
   ```

   IMPORTANT: Use the correct SDK for the current provider "{llm_provider}". Do NOT mix them.

3. For steps that produce deterministic output (filtering, formatting, counting), use pure Python.

4. The script MUST print a single JSON line to stdout at the end:
   ```python
   import json
   print(json.dumps({{"output": "<result>", "llm_used": True/False, "tokens": <int>}}))
   ```

5. Wrap everything in an async main() and call asyncio.run(main()).

6. Handle errors gracefully — catch exceptions and include them in the output JSON.

7. IMPORTANT: `client.call_tool()` returns a list of content blocks, NOT an object with `.content`.
   Always parse tool results like this:
   ```python
   result = await client.call_tool("tool_name", {{}})
   # result is a list of TextContent objects
   text = result[0].text if result else ""
   data = json.loads(text)
   ```
   NEVER use `result.content` — use `result[0].text` directly.

Generate ONLY the Python code, no markdown fences, no explanation."""
