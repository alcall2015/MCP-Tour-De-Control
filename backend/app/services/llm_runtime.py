"""LLM and MCP primitives shared by the chat and the agent runner."""
import asyncio
import json
import re
from dataclasses import dataclass, field

import structlog

from app.config import settings
from app.models import McpServer
from app.services.mcp_service import McpService, _build_http_transport

log = structlog.get_logger()

MAX_TOOL_RESULT_LEN = 2000

# Keep only the portable JSON Schema subset accepted by every configured
# function-calling provider.  In particular, Gemini rejects validation and
# metadata keywords such as `$schema`, `minimum`, and `additionalProperties`.
_FUNCTION_SCHEMA_FIELDS = {"type", "description", "properties", "required", "items", "enum"}

# Google has no roles: the conversation is flattened into one text prompt whose
# turns are delimited by [System] / [User] / [Assistant] / [Tool result ...]
# markers. Any text that reaches the prompt from outside (a user message or an
# MCP tool result) could forge one of those markers and pass itself off as a
# system instruction, so every interpolated fragment gets its markers quoted.
_FRAME_MARKER = re.compile(r"\[(System|User|Assistant|Tool result[^\]]*)\]", re.IGNORECASE)

GOOGLE_STANDING_INSTRUCTION = (
    "If you already have tool results above that answer the user's question, "
    "use them directly. Do NOT call the same tool again."
)


def _quote_markers(text: str) -> str:
    """Defuse forged frame markers in untrusted text before it joins the prompt."""
    return _FRAME_MARKER.sub(lambda m: "[" + m.group(1) + " (quoted)]", text or "")


@dataclass
class LlmResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)  # [{"name": str, "args": dict}]
    tokens_in: int = 0
    tokens_out: int = 0


def clean_schema(schema: dict) -> dict:
    """Reduce an MCP schema to portable LLM function-calling fields."""
    cleaned = {}
    for k, v in schema.items():
        if k not in _FUNCTION_SCHEMA_FIELDS:
            continue
        if k == "properties" and isinstance(v, dict):
            # `properties` maps property name -> sub-schema; each value is a
            # nested schema to clean, but the names themselves are not JSON
            # Schema keywords and must not be filtered against the field set.
            cleaned[k] = {name: clean_schema(sub) if isinstance(sub, dict) else sub for name, sub in v.items()}
        elif isinstance(v, dict):
            cleaned[k] = clean_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [clean_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            cleaned[k] = v
    # A property can have been removed above when it was expressed through a
    # JSON Schema reference.  Gemini rejects a `required` entry without a
    # matching property definition.
    properties = cleaned.get("properties")
    if "required" in cleaned:
        if isinstance(properties, dict):
            cleaned["required"] = [name for name in cleaned["required"] if name in properties]
        else:
            cleaned.pop("required")
    return cleaned


async def build_tool_defs(servers: list[McpServer]) -> tuple[list[dict], dict[str, McpServer]]:
    """Discover the tools of the given servers as LLM function definitions.

    Names are flattened into one namespace; on a collision the first server
    wins and a warning is logged."""
    tools: list[dict] = []
    tool_server_map: dict[str, McpServer] = {}
    for server in servers:
        for t in await McpService.get_server_tools(server):
            name = t["name"]
            if name in tool_server_map:
                log.warning("Tool name collision, keeping first", tool=name,
                            kept=tool_server_map[name].name, dropped=server.name)
                continue
            params = clean_schema(t.get("input_schema") or {"type": "object", "properties": {}})
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"[{server.name}] {t.get('description') or ''}",
                    "parameters": params,
                },
            })
            tool_server_map[name] = server
    return tools, tool_server_map


async def call_mcp_tool(tool_name: str, args: dict, server: McpServer) -> str:
    """Execute an MCP tool and return the result as a string (truncated)."""
    try:
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        if server.transport == "http" and server.url:
            transport = _build_http_transport(server.url, server.api_key)
        elif server.transport == "stdio" and server.command:
            transport = StdioTransport(command=server.command, args=server.args or [])
        else:
            return json.dumps({"error": f"Server {server.name} not configured properly"})
        async with Client(transport) as client:
            result = await asyncio.wait_for(client.call_tool(tool_name, args),
                                            timeout=settings.MCP_TOOL_TIMEOUT_SECONDS)
        text = result[0].text if result else ""
        if len(text) > MAX_TOOL_RESULT_LEN:
            text = text[:MAX_TOOL_RESULT_LEN] + f"\n[truncated, {len(text)} chars total]"
        return text
    except asyncio.TimeoutError:
        # Reported like any other tool failure so the loop keeps its shape.
        log.error("MCP tool call timed out", tool=tool_name, timeout=settings.MCP_TOOL_TIMEOUT_SECONDS)
        return json.dumps({"error": f"tool timed out after {settings.MCP_TOOL_TIMEOUT_SECONDS}s"})
    except Exception as e:
        log.error("MCP tool call failed", tool=tool_name, error=str(e))
        return json.dumps({"error": str(e)})


async def call_llm(provider: str, model: str, api_key: str, messages: list[dict], tools: list[dict] | None) -> LlmResult:
    """Call the configured provider once, in a worker thread (the SDKs block)."""
    return await asyncio.to_thread(_call_llm_sync, provider, model, api_key, messages, tools)


def _call_llm_sync(provider, model, api_key, messages, tools) -> LlmResult:
    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=settings.LLM_CALL_TIMEOUT_SECONDS)
        kwargs = {"model": model, "messages": messages, "stream": True,
                  "stream_options": {"include_usage": True}}
        if tools:
            kwargs["tools"] = tools
        text, acc, tokens_in, tokens_out = "", {}, 0, 0
        for chunk in client.chat.completions.create(**kwargs):
            if not chunk.choices:  # the trailing usage-only chunk
                usage = getattr(chunk, "usage", None)
                if usage:
                    tokens_in, tokens_out = usage.prompt_tokens or 0, usage.completion_tokens or 0
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text += delta.content
            for tc in delta.tool_calls or []:
                slot = acc.setdefault(tc.index, {"name": "", "args": ""})
                if tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function.arguments:
                    slot["args"] += tc.function.arguments
        calls = []
        for tc in acc.values():
            try:
                args = json.loads(tc["args"]) if tc["args"] else {}
            except json.JSONDecodeError:
                args = {}
            calls.append({"name": tc["name"], "args": args})
        return LlmResult(text, calls, tokens_in, tokens_out)

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=settings.LLM_CALL_TIMEOUT_SECONDS)
        anthropic_tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
                            "input_schema": t["function"]["parameters"]} for t in (tools or [])]
        system_text, msgs = "", []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            elif m["role"] == "tool":
                msgs.append({"role": "user", "content": [{"type": "tool_result",
                             "tool_use_id": m.get("tool_call_id", ""), "content": m["content"]}]})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                msgs.append({"role": "assistant", "content": [
                    {"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                     "input": json.loads(tc["function"]["arguments"])} for tc in m["tool_calls"]]})
            else:
                msgs.append({"role": m["role"], "content": m.get("content") or ""})
        kwargs = {"model": model, "max_tokens": 4096, "messages": msgs}
        if system_text:
            kwargs["system"] = system_text
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        with client.messages.stream(**kwargs) as stream:
            text = ""
            for event in stream:
                if getattr(event, "type", None) == "content_block_delta" and hasattr(event.delta, "text"):
                    text += event.delta.text
            response = stream.get_final_message()
        calls = [{"name": b.name, "args": b.input} for b in response.content if b.type == "tool_use"]
        usage = getattr(response, "usage", None)
        return LlmResult(text, calls, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)

    if provider == "google":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        google_tools = None
        if tools:
            decls = [genai.types.FunctionDeclaration(
                name=t["function"]["name"], description=t["function"]["description"],
                parameters=t["function"]["parameters"] if t["function"]["parameters"].get("properties") else None,
            ) for t in tools]
            google_tools = [genai.types.Tool(function_declarations=decls)]
        model_obj = genai.GenerativeModel(model, tools=google_tools)
        parts = []
        system_seen = False
        for m in messages:
            if m["role"] == "system":
                # The standing instruction rides with the real system text at the
                # top of the prompt, where no later turn can appear to override it.
                content = m["content"]
                if not system_seen:
                    content = f"{content}\n\n{GOOGLE_STANDING_INSTRUCTION}"
                    system_seen = True
                parts.append(f"[System] {content}")
            elif m["role"] == "user":
                parts.append(f"[User] {_quote_markers(m['content'])}")
            elif m["role"] == "assistant":
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        parts.append(f"[Assistant called tool: {tc.get('function', tc).get('name', 'unknown')}]")
                elif m.get("content"):
                    parts.append(f"[Assistant] {_quote_markers(m['content'])}")
            elif m["role"] == "tool":
                content = _quote_markers(m["content"])
                if len(content) > MAX_TOOL_RESULT_LEN:
                    content = content[:MAX_TOOL_RESULT_LEN] + f"\n[truncated, {len(m['content'])} chars total]"
                parts.append(f"[Tool result for {m.get('tool_call_id', '').replace('call_', '')}]\n{content}")
        if not system_seen:
            parts.insert(0, f"[System] {GOOGLE_STANDING_INSTRUCTION}")
        prompt = "\n\n".join(parts)
        text, calls, tokens_in, tokens_out = "", [], 0, 0
        for chunk in model_obj.generate_content(
                prompt, stream=True, request_options={"timeout": settings.LLM_CALL_TIMEOUT_SECONDS}):
            try:
                if chunk.text:
                    text += chunk.text
            except ValueError:
                pass
            for candidate in getattr(chunk, "candidates", None) or []:
                for part in getattr(candidate.content, "parts", None) or []:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        calls.append({"name": fc.name, "args": dict(fc.args)})
            usage = getattr(chunk, "usage_metadata", None)
            if usage:
                tokens_in = getattr(usage, "prompt_token_count", tokens_in) or tokens_in
                tokens_out = getattr(usage, "candidates_token_count", tokens_out) or tokens_out
        return LlmResult(text, calls, tokens_in, tokens_out)

    raise ValueError(f"Unsupported provider: {provider}")
