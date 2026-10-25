import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, Config, Conversation, McpServer
from app.services.llm_runtime import MAX_TOOL_RESULT_LEN, build_tool_defs, call_llm, call_mcp_tool
from app.utils.crypto import decrypt_value
from app.utils.sse import sse_frame as _sse

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
MAX_TOOL_ROUNDS = 8


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
        servers = (await session.execute(select(McpServer).where(McpServer.enabled == True))).scalars().all()
        return await build_tool_defs(list(servers))

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

        # Stream from LLM with tool call loop (bounded to prevent infinite loops)
        full_response = ""
        all_tool_calls = []

        try:
            for _round in range(MAX_TOOL_ROUNDS):
                result = await call_llm(provider, model, api_key, messages, tools)
                text_chunk, tool_calls_batch = result.text, result.tool_calls

                # Yield text as SSE event
                if text_chunk:
                    full_response += text_chunk
                    yield _sse("text", {"content": text_chunk})

                if not tool_calls_batch:
                    break

                # Process tool calls
                for tc in tool_calls_batch:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    server = tool_server_map.get(tool_name)

                    yield _sse("tool_call", {"tool": tool_name, "server": server.name if server else "unknown", "args": tool_args})

                    if server:
                        result_text = await call_mcp_tool(tool_name, tool_args, server)
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
            else:
                # Loop exhausted MAX_TOOL_ROUNDS without ever breaking, i.e. the model
                # still wanted to call tools on the very last round. Force one more,
                # tool-less turn so it must write an answer instead of going silent.
                result = await call_llm(provider, model, api_key, messages, None)
                text_chunk, dropped_tool_calls = result.text, result.tool_calls
                if dropped_tool_calls:
                    log.warning("Synthesis turn discarded tool calls", count=len(dropped_tool_calls))
                if text_chunk:
                    full_response += text_chunk
                    yield _sse("text", {"content": text_chunk})

            if not full_response:
                fallback_text = (
                    "Desole, j'ai atteint la limite d'appels d'outils sans parvenir a une reponse. "
                    "Peux-tu reformuler ou preciser ta question ?"
                )
                full_response = fallback_text
                yield _sse("text", {"content": fallback_text})

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
