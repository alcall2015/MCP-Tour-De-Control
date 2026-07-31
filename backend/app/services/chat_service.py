import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, Config, Conversation, McpServer
from app.services.mcp_service import McpService, _build_http_transport
from app.utils.crypto import decrypt_value

log = structlog.get_logger()

SYSTEM_PROMPT = """Tu es l'assistant de MCP Tour De Control, une plateforme de gestion de serveurs MCP et de scripts automatises.

Tu peux :
1. Repondre aux questions de l'utilisateur
2. Appeler les outils MCP disponibles pour recuperer des donnees en direct
3. Generer des scripts Python quand l'utilisateur le demande

Quand tu appelles un outil MCP, analyse le resultat et presente-le de maniere claire et lisible a l'utilisateur.

Quand tu generes un script, mets-le dans un bloc ```python.

Reponds en francais. Sois concis et professionnel."""

MAX_HISTORY = 20
MAX_TOOL_RESULT_LEN = 2000

# Fields not supported by all LLM providers in function calling schemas
_UNSUPPORTED_SCHEMA_FIELDS = {"default", "additionalProperties", "anyOf"}


def _clean_schema(schema: dict) -> dict:
    """Strip fields unsupported by LLM function calling (e.g. Google Gemini rejects 'default')."""
    cleaned = {}
    for k, v in schema.items():
        if k in _UNSUPPORTED_SCHEMA_FIELDS:
            continue
        if isinstance(v, dict):
            cleaned[k] = _clean_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [_clean_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            cleaned[k] = v
    return cleaned


class ChatService:

    @staticmethod
    async def _load_context(conversation_id, session: AsyncSession) -> list[dict]:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(MAX_HISTORY)
        )
        messages = list(reversed(result.scalars().all()))
        context = []
        for msg in messages:
            entry = {"role": msg.role, "content": msg.content}
            if msg.role == "assistant" and msg.tool_calls:
                entry["tool_calls_data"] = msg.tool_calls
            context.append(entry)
        return context

    @staticmethod
    async def _get_mcp_tools(session: AsyncSession) -> tuple[list[dict], dict[str, McpServer]]:
        """Return LLM tool definitions and a map of tool_name -> McpServer."""
        servers_result = await session.execute(
            select(McpServer).where(McpServer.enabled == True)
        )
        tools = []
        tool_server_map = {}
        for server in servers_result.scalars().all():
            server_tools = await McpService.get_server_tools(server)
            for t in server_tools:
                params = _clean_schema(t.get("input_schema") or {"type": "object", "properties": {}})
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": f"[{server.name}] {t.get('description', '')}",
                        "parameters": params,
                    },
                }
                tools.append(tool_def)
                tool_server_map[t["name"]] = server
        return tools, tool_server_map

    @staticmethod
    async def _call_mcp_tool(tool_name: str, args: dict, server: McpServer) -> str:
        """Execute an MCP tool and return the result as a string."""
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StdioTransport

            if server.transport == "http" and server.url:
                transport = _build_http_transport(server.url, server.api_key)
                async with Client(transport) as client:
                    result = await client.call_tool(tool_name, args)
            elif server.transport == "stdio" and server.command:
                transport = StdioTransport(command=server.command, args=server.args or [])
                async with Client(transport) as client:
                    result = await client.call_tool(tool_name, args)
            else:
                return json.dumps({"error": f"Server {server.name} not configured properly"})

            text = result[0].text if result else ""
            if len(text) > MAX_TOOL_RESULT_LEN:
                text = text[:MAX_TOOL_RESULT_LEN] + f"\n[truncated, {len(text)} chars total]"
            return text
        except Exception as e:
            log.error("MCP tool call failed", tool=tool_name, error=str(e))
            return json.dumps({"error": str(e)})

    @staticmethod
    async def stream_response(
        conversation_id: str,
        user_content: str,
        session: AsyncSession,
    ):
        """Async generator yielding SSE event strings."""
        # Load config
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.api_key:
            yield _sse("error", {"message": "LLM not configured. Set API key in Config."})
            return

        api_key = decrypt_value(config.api_key)
        provider = config.llm_provider
        model = config.llm_model

        # Save user message
        user_msg = ChatMessage(conversation_id=conversation_id, role="user", content=user_content)
        session.add(user_msg)
        await session.commit()

        # Load context + tools
        context = await ChatService._load_context(conversation_id, session)
        tools, tool_server_map = await ChatService._get_mcp_tools(session)

        # Build messages for LLM
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for entry in context:
            messages.append({"role": entry["role"], "content": entry["content"]})

        # Stream from LLM with tool call loop
        full_response = ""
        all_tool_calls = []

        try:
            while True:
                text_chunk, tool_calls_batch = await _stream_llm(
                    provider, model, api_key, messages, tools, stream_callback=lambda chunk: None
                )

                # Stream text
                if text_chunk:
                    # We yield text in one block since provider-level streaming
                    # is handled inside _stream_llm via callback
                    full_response += text_chunk

                if not tool_calls_batch:
                    break

                # Process tool calls
                for tc in tool_calls_batch:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    server = tool_server_map.get(tool_name)

                    yield _sse("tool_call", {"tool": tool_name, "server": server.name if server else "unknown", "args": tool_args})

                    if server:
                        result_text = await ChatService._call_mcp_tool(tool_name, tool_args, server)
                    else:
                        result_text = json.dumps({"error": f"Unknown tool: {tool_name}"})

                    try:
                        result_data = json.loads(result_text)
                    except json.JSONDecodeError:
                        result_data = result_text

                    yield _sse("tool_result", {"tool": tool_name, "data": result_data})
                    all_tool_calls.append({"name": tool_name, "args": tool_args, "result": result_text})

                    # Add tool interaction to messages for next LLM turn
                    messages.append({"role": "assistant", "content": None, "tool_calls": [
                        {"id": f"call_{tool_name}", "type": "function", "function": {"name": tool_name, "arguments": json.dumps(tool_args)}}
                    ]})
                    messages.append({"role": "tool", "tool_call_id": f"call_{tool_name}", "content": result_text})

        except Exception as e:
            log.error("Chat stream error", error=str(e))
            yield _sse("error", {"message": str(e)})
            return

        # Save assistant message
        assistant_msg = ChatMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
            tool_calls=all_tool_calls if all_tool_calls else None,
        )
        session.add(assistant_msg)

        # Update conversation timestamp + auto-title
        conv = await session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.now(timezone.utc)
            if not conv.title and user_content:
                conv.title = user_content[:80]
        await session.commit()

        yield _sse("done", {})


async def _stream_llm(provider, model, api_key, messages, tools, stream_callback):
    """Call LLM with streaming, return (text, tool_calls).
    Uses OpenAI-compatible format for all providers."""

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        kwargs = {"model": model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
        stream = client.chat.completions.create(**kwargs)

        text = ""
        tool_calls_acc = {}
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                text += delta.content
                stream_callback(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"name": "", "args": ""}
                    if tc.function.name:
                        tool_calls_acc[idx]["name"] = tc.function.name
                    if tc.function.arguments:
                        tool_calls_acc[idx]["args"] += tc.function.arguments

        parsed_calls = []
        for tc in tool_calls_acc.values():
            try:
                args = json.loads(tc["args"]) if tc["args"] else {}
            except json.JSONDecodeError:
                args = {}
            parsed_calls.append({"name": tc["name"], "args": args})

        return text, parsed_calls if parsed_calls else None

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        # Convert OpenAI tool format to Anthropic
        anthropic_tools = []
        for t in (tools or []):
            anthropic_tools.append({
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            })
        # Convert messages: extract system, handle tool messages
        system_text = ""
        anthropic_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            elif m["role"] == "tool":
                anthropic_msgs.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m["content"]}
                ]})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                content_blocks = []
                for tc in m["tool_calls"]:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    })
                anthropic_msgs.append({"role": "assistant", "content": content_blocks})
            else:
                anthropic_msgs.append({"role": m["role"], "content": m.get("content") or ""})

        kwargs = {"model": model, "max_tokens": 4096, "messages": anthropic_msgs}
        if system_text:
            kwargs["system"] = system_text
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        with client.messages.stream(**kwargs) as stream:
            text = ""
            tool_calls = []
            for event in stream:
                if hasattr(event, 'type'):
                    if event.type == 'content_block_delta':
                        if hasattr(event.delta, 'text'):
                            text += event.delta.text
                            stream_callback(event.delta.text)
            # Check final message for tool use
            response = stream.get_final_message()
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls.append({"name": block.name, "args": block.input})

        return text, tool_calls if tool_calls else None

    elif provider == "google":
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # Convert tools to Google format
        google_tools = None
        if tools:
            function_declarations = []
            for t in tools:
                params = t["function"]["parameters"]
                # Google requires specific format
                function_declarations.append(genai.types.FunctionDeclaration(
                    name=t["function"]["name"],
                    description=t["function"]["description"],
                    parameters=params if params.get("properties") else None,
                ))
            google_tools = [genai.types.Tool(function_declarations=function_declarations)]

        model_obj = genai.GenerativeModel(model, tools=google_tools)

        # Build Google-format messages
        history = []
        system_text = ""
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            elif m["role"] == "user":
                history.append({"role": "user", "parts": [m["content"]]})
            elif m["role"] == "assistant":
                if m.get("content"):
                    history.append({"role": "model", "parts": [m["content"]]})
            elif m["role"] == "tool":
                history.append({"role": "function", "parts": [
                    genai.types.Part(function_response=genai.types.FunctionResponse(
                        name=m.get("tool_call_id", "").replace("call_", ""),
                        response={"result": m["content"]},
                    ))
                ]})

        # Add system as first user context if needed
        if system_text and history and history[0]["role"] == "user":
            history[0]["parts"][0] = system_text + "\n\n" + history[0]["parts"][0]

        chat = model_obj.start_chat(history=history[:-1] if history else [])
        last_msg = history[-1]["parts"][0] if history else ""

        response = chat.send_message(last_msg, stream=True)
        text = ""
        tool_calls = []
        for chunk in response:
            if chunk.text:
                text += chunk.text
                stream_callback(chunk.text)
            if hasattr(chunk, 'candidates') and chunk.candidates:
                for candidate in chunk.candidates:
                    if hasattr(candidate, 'content') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                fc = part.function_call
                                tool_calls.append({"name": fc.name, "args": dict(fc.args)})

        return text, tool_calls if tool_calls else None

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
