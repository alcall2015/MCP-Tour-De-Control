# Chat Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a streaming chat interface where users can converse with a LLM that calls MCP tools in real-time, generates scripts, and maintains persistent conversation history.

**Architecture:** SSE-based streaming via FastAPI `StreamingResponse`. Chat service orchestrates LLM streaming + MCP tool execution. React frontend with sidebar (conversation list) + main chat area with typed message bubbles.

**Tech Stack:** FastAPI SSE, OpenAI/Anthropic/Google streaming APIs, fastmcp.Client for tool calls, React + react-markdown, SQLAlchemy async models.

## Global Constraints

- Python 3.12, FastAPI 0.115, SQLAlchemy 2.0 async
- React 18 + TypeScript + Vite + Tailwind v4
- "Control Tower at Night" design system (CSS custom properties: `--bg-void`, `--bg-panel`, `--accent`, `--text-primary`, etc.)
- No emojis in navigation tabs
- All DB operations async via `async_session`
- Existing patterns: models in `app/models/`, schemas in `app/schemas/`, routers in `app/routers/`, services in `app/services/`
- `Base` imported from `app.models.config`
- Frontend API calls go through `request<T>()` helper in `lib/api.ts`

---

### Task 1: Database Models + Migration

**Files:**
- Create: `backend/app/models/conversation.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/b1c2d3e4f5a6_add_chat_tables.py`

**Interfaces:**
- Produces: `Conversation` model (id, title, created_at, updated_at), `ChatMessage` model (id, conversation_id, role, content, tool_calls, created_at)

- [ ] **Step 1: Create conversation models**

Create `backend/app/models/conversation.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # "user", "assistant", "tool"
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
```

- [ ] **Step 2: Export models in __init__.py**

Add to `backend/app/models/__init__.py`:

```python
from app.models.conversation import Conversation, ChatMessage
```

And add `"Conversation", "ChatMessage"` to the `__all__` list.

- [ ] **Step 3: Create Alembic migration**

Create `backend/alembic/versions/b1c2d3e4f5a6_add_chat_tables.py`:

```python
"""add chat tables

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversation',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'chat_message',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text, nullable=False, server_default=''),
        sa.Column('tool_calls', postgresql.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_chat_message_conversation_id', 'chat_message', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_chat_message_conversation_id')
    op.drop_table('chat_message')
    op.drop_table('conversation')
```

- [ ] **Step 4: Verify migration applies locally**

Run: `cd backend && alembic upgrade head`
Expected: Tables `conversation` and `chat_message` created.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/conversation.py backend/app/models/__init__.py backend/alembic/versions/b1c2d3e4f5a6_add_chat_tables.py
git commit -m "feat(chat): add Conversation and ChatMessage models + migration"
```

---

### Task 2: Pydantic Schemas + Chat Router (CRUD)

**Files:**
- Create: `backend/app/schemas/chat.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `backend/app/routers/chat.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `Conversation`, `ChatMessage` models from Task 1
- Produces: REST endpoints `GET/POST/DELETE /api/v1/chat/conversations`, `GET /api/v1/chat/conversations/{id}/messages`, `POST /api/v1/chat/conversations/{id}/messages` (SSE placeholder — streaming added in Task 3)

- [ ] **Step 1: Create chat schemas**

Create `backend/app/schemas/chat.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ConversationRead(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ChatMessageRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    tool_calls: list | dict | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    content: str
```

- [ ] **Step 2: Export schemas in __init__.py**

Add to `backend/app/schemas/__init__.py`:

```python
from app.schemas.chat import ConversationRead, ChatMessageRead, ChatMessageCreate
```

And add `"ConversationRead", "ChatMessageRead", "ChatMessageCreate"` to the `__all__` list.

- [ ] **Step 3: Create chat router with CRUD endpoints**

Create `backend/app/routers/chat.py`:

```python
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Conversation, ChatMessage
from app.schemas import ConversationRead, ChatMessageRead, ChatMessageCreate

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Conversation).order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/conversations", response_model=ConversationRead, status_code=201)
async def create_conversation(session: AsyncSession = Depends(get_async_session)):
    conv = Conversation()
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await session.delete(conv)
    await session.commit()


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageRead])
async def list_messages(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()
```

- [ ] **Step 4: Register router in main.py**

Add to `backend/app/main.py` imports:

```python
from app.routers import chat as chat_router
```

Add after the last `app.include_router(...)`:

```python
app.include_router(chat_router.router)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/chat.py backend/app/schemas/__init__.py backend/app/routers/chat.py backend/app/main.py
git commit -m "feat(chat): add chat schemas, CRUD router, register in app"
```

---

### Task 3: Chat Service — LLM Streaming + MCP Tool Calls

**Files:**
- Create: `backend/app/services/chat_service.py`
- Modify: `backend/app/routers/chat.py` (add SSE message endpoint)

**Interfaces:**
- Consumes: `Conversation`, `ChatMessage` models; `McpServer` model; `Config` model; `McpService` for tool listing; `decrypt_value` from crypto; `_build_http_transport` from mcp_service
- Produces: `ChatService.stream_response()` async generator yielding SSE events; `POST /api/v1/chat/conversations/{id}/messages` returning `StreamingResponse`

- [ ] **Step 1: Create chat service**

Create `backend/app/services/chat_service.py`:

```python
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
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": f"[{server.name}] {t.get('description', '')}",
                        "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
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
```

- [ ] **Step 2: Add SSE message endpoint to chat router**

Add to the end of `backend/app/routers/chat.py`:

```python
from fastapi.responses import StreamingResponse
from app.services.chat_service import ChatService
from app.schemas import ChatMessageCreate


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    data: ChatMessageCreate,
    session: AsyncSession = Depends(get_async_session),
):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        async for event in ChatService.stream_response(
            str(conversation_id), data.content, session
        ):
            yield event

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 3: Add run-script endpoint to chat router**

Add to `backend/app/routers/chat.py`:

```python
from pydantic import BaseModel
from app.services.script_executor import ScriptExecutor
from app.models import Execution

class RunScriptRequest(BaseModel):
    code: str

@router.post("/conversations/{conversation_id}/run-script")
async def run_script_in_chat(
    conversation_id: uuid.UUID,
    data: RunScriptRequest,
    session: AsyncSession = Depends(get_async_session),
):
    conv = await session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    from app.models import Script
    # Create a temporary script object (not saved to DB as a prompt script)
    temp_script = Script.__new__(Script)
    temp_script.id = uuid.uuid4()
    temp_script.code = data.code

    execution = await ScriptExecutor.run(temp_script, session, timeout=60)
    return {
        "status": execution.status,
        "output": execution.output,
        "error": execution.error,
        "duration_ms": execution.duration_ms,
    }
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/chat_service.py backend/app/routers/chat.py
git commit -m "feat(chat): add ChatService with SSE streaming, tool calls, and run-script endpoint"
```

---

### Task 4: Frontend — API Types + Chat Functions

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: TypeScript types `Conversation`, `ChatMessageData`, `SSEEvent`; API functions `listConversations`, `createConversation`, `deleteConversation`, `listMessages`, `sendMessage` (returns `Response` for SSE), `runScriptInChat`, `parseSSEStream`

- [ ] **Step 1: Add chat types and API functions**

Add to the end of `frontend/src/lib/api.ts`:

```typescript
// Chat
export const listConversations = () => request<Conversation[]>("/chat/conversations");
export const createConversation = () =>
  request<Conversation>("/chat/conversations", { method: "POST" });
export const deleteConversation = (id: string) =>
  request<void>(`/chat/conversations/${id}`, { method: "DELETE" });
export const listMessages = (conversationId: string) =>
  request<ChatMessageData[]>(`/chat/conversations/${conversationId}/messages`);
export const sendMessageSSE = async (conversationId: string, content: string): Promise<Response> => {
  const res = await fetch(`${BASE}/chat/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
  return res;
};
export const runScriptInChat = (conversationId: string, code: string) =>
  request<{ status: string; output: string | null; error: string | null; duration_ms: number | null }>(
    `/chat/conversations/${conversationId}/run-script`,
    { method: "POST", body: JSON.stringify({ code }) }
  );

// Chat types
export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
export interface ChatMessageData {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls: Array<{ name: string; args: Record<string, unknown>; result: string }> | null;
  created_at: string;
}
export interface SSEEvent {
  event: "text" | "tool_call" | "tool_result" | "script" | "done" | "error";
  data: Record<string, unknown>;
}

export function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";

  return reader.read().then(function process({ done, value }): Promise<void> {
    if (done) return Promise.resolve();
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ event: currentEvent as SSEEvent["event"], data });
        } catch { /* skip malformed */ }
        currentEvent = "";
      }
    }

    return reader.read().then(process);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(chat): add chat API functions, types, and SSE parser"
```

---

### Task 5: Frontend — Chat Page + Conversation Sidebar

**Files:**
- Create: `frontend/src/components/Chat/ChatPage.tsx`
- Create: `frontend/src/components/Chat/ConversationList.tsx`
- Create: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: `frontend/src/components/Layout/TabNav.tsx` (add tab)

**Interfaces:**
- Consumes: `listConversations`, `createConversation`, `deleteConversation` from api.ts
- Produces: Chat page layout with sidebar + placeholder main area

- [ ] **Step 1: Create ConversationList component**

Create `frontend/src/components/Chat/ConversationList.tsx`:

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listConversations, createConversation, deleteConversation } from "../../lib/api";
import type { Conversation } from "../../lib/api";

interface Props {
  activeId: string | null;
  onSelect: (id: string) => void;
}

export function ConversationList({ activeId, onSelect }: Props) {
  const queryClient = useQueryClient();
  const { data: conversations = [] } = useQuery({
    queryKey: ["conversations"],
    queryFn: listConversations,
  });

  const createMut = useMutation({
    mutationFn: createConversation,
    onSuccess: (conv) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onSelect(conv.id);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

  const formatDate = (d: string) => {
    const date = new Date(d);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    if (diff < 86400000) return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
  };

  return (
    <div
      className="flex flex-col h-full"
      style={{ borderRight: "1px solid var(--border)", backgroundColor: "var(--bg-void)" }}
    >
      <div className="p-3">
        <button
          onClick={() => createMut.mutate()}
          className="btn-primary w-full text-xs py-2"
        >
          + Nouvelle conversation
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {conversations.map((conv: Conversation) => (
          <div
            key={conv.id}
            onClick={() => onSelect(conv.id)}
            className="px-3 py-2.5 cursor-pointer transition-all duration-150 flex items-center justify-between group"
            style={{
              backgroundColor: activeId === conv.id ? "var(--bg-panel)" : "transparent",
              borderLeft: activeId === conv.id ? "2px solid var(--accent)" : "2px solid transparent",
            }}
          >
            <div className="min-w-0 flex-1">
              <p
                className="text-sm truncate"
                style={{ color: activeId === conv.id ? "var(--text-primary)" : "var(--text-secondary)" }}
              >
                {conv.title || "Nouvelle conversation"}
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {formatDate(conv.updated_at)}
              </p>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Supprimer cette conversation ?")) deleteMut.mutate(conv.id);
              }}
              className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 rounded transition-opacity"
              style={{ color: "var(--error)" }}
            >
              x
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create ChatPage layout component**

Create `frontend/src/components/Chat/ChatPage.tsx`:

```typescript
import { useState } from "react";
import { ConversationList } from "./ConversationList";

export function ChatPage() {
  const [activeConvId, setActiveConvId] = useState<string | null>(null);

  return (
    <div className="flex" style={{ height: "calc(100vh - 57px)" }}>
      <div style={{ width: "250px", flexShrink: 0 }}>
        <ConversationList activeId={activeConvId} onSelect={setActiveConvId} />
      </div>
      <div className="flex-1 flex items-center justify-center">
        {activeConvId ? (
          <p style={{ color: "var(--text-muted)" }}>Chat area — Task 6</p>
        ) : (
          <div className="text-center">
            <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              Selectionnez ou creez une conversation
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Posez des questions, appelez des outils MCP, ou generez des scripts.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create page wrapper**

Create `frontend/src/pages/ChatPage.tsx`:

```typescript
import { ChatPage as ChatPageComponent } from "../components/Chat/ChatPage";

export function ChatPage() {
  return <ChatPageComponent />;
}
```

- [ ] **Step 4: Add route in App.tsx**

Add import at top of `frontend/src/App.tsx`:

```typescript
import { ChatPage } from "./pages/ChatPage";
```

Add route after `stress-call`:

```typescript
<Route path="chat" element={<ChatPage />} />
```

- [ ] **Step 5: Add Chat tab in TabNav.tsx**

In `frontend/src/components/Layout/TabNav.tsx`, update the `tabs` array:

```typescript
const tabs = [
  { to: "/", label: "Prompts" },
  { to: "/reports", label: "Reports" },
  { to: "/stress-call", label: "Stress Call" },
  { to: "/chat", label: "Chat" },
  { to: "/config", label: "Config" },
];
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/ChatPage.tsx frontend/src/components/Chat/ConversationList.tsx frontend/src/pages/ChatPage.tsx frontend/src/App.tsx frontend/src/components/Layout/TabNav.tsx
git commit -m "feat(chat): add Chat tab with conversation sidebar"
```

---

### Task 6: Frontend — Message List, Bubbles, Input + SSE Streaming

**Files:**
- Install: `react-markdown` npm dependency
- Create: `frontend/src/components/Chat/MessageList.tsx`
- Create: `frontend/src/components/Chat/MessageBubble.tsx`
- Create: `frontend/src/components/Chat/ChatInput.tsx`
- Create: `frontend/src/components/Chat/ToolCallBlock.tsx`
- Create: `frontend/src/components/Chat/ScriptBlock.tsx`
- Modify: `frontend/src/components/Chat/ChatPage.tsx` (wire everything together)

**Interfaces:**
- Consumes: `listMessages`, `sendMessageSSE`, `parseSSEStream`, `runScriptInChat` from api.ts
- Produces: Complete interactive chat with streaming messages, tool call display, script blocks with Test/Save

- [ ] **Step 1: Install react-markdown**

Run: `cd frontend && npm install react-markdown`

- [ ] **Step 2: Create ToolCallBlock component**

Create `frontend/src/components/Chat/ToolCallBlock.tsx`:

```typescript
import { useState } from "react";

interface Props {
  tool: string;
  server: string;
  args?: Record<string, unknown>;
  result?: unknown;
  loading?: boolean;
}

export function ToolCallBlock({ tool, server, args, result, loading }: Props) {
  const [expanded, setExpanded] = useState(false);
  const resultStr = typeof result === "string" ? result : JSON.stringify(result, null, 2);
  const isLong = resultStr && resultStr.split("\n").length > 5;

  return (
    <div
      className="my-2 rounded-lg text-xs"
      style={{ border: "1px solid rgba(96, 165, 250, 0.2)", backgroundColor: "rgba(96, 165, 250, 0.05)" }}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" style={{ color: "var(--running)" }} />}
        <span style={{ color: "var(--running)" }}>Appel</span>
        <code className="font-mono" style={{ color: "var(--accent)" }}>{tool}</code>
        <span style={{ color: "var(--text-muted)" }}>sur {server}</span>
      </div>
      {result !== undefined && (
        <div className="px-3 pb-2">
          {isLong && !expanded ? (
            <>
              <pre className="text-xs overflow-x-auto font-mono" style={{ color: "var(--text-secondary)", maxHeight: "80px", overflow: "hidden" }}>
                {resultStr?.slice(0, 300)}...
              </pre>
              <button onClick={() => setExpanded(true)} className="text-xs mt-1" style={{ color: "var(--running)" }}>
                Voir tout
              </button>
            </>
          ) : (
            <pre className="text-xs overflow-x-auto font-mono" style={{ color: "var(--text-secondary)", maxHeight: expanded ? "400px" : "200px", overflow: "auto" }}>
              {resultStr}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create ScriptBlock component**

Create `frontend/src/components/Chat/ScriptBlock.tsx`:

```typescript
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { runScriptInChat } from "../../lib/api";

interface Props {
  code: string;
  conversationId: string;
}

export function ScriptBlock({ code, conversationId }: Props) {
  const navigate = useNavigate();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ status: string; output: string | null; error: string | null } | null>(null);

  const handleTest = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await runScriptInChat(conversationId, code);
      setResult(res);
    } catch (e: unknown) {
      setResult({ status: "failed", output: null, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="my-2">
      <pre
        className="rounded-lg p-3 text-xs font-mono overflow-x-auto"
        style={{ backgroundColor: "rgba(0,0,0,0.3)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
      >
        {code}
      </pre>
      <div className="flex gap-2 mt-2">
        <button
          onClick={handleTest}
          disabled={running}
          className="rounded-lg px-3 py-1 text-xs font-medium transition-all disabled:opacity-50"
          style={{ backgroundColor: "rgba(96, 165, 250, 0.1)", color: "var(--running)", border: "1px solid rgba(96, 165, 250, 0.2)" }}
        >
          {running ? "Execution..." : "Tester"}
        </button>
        <button
          onClick={() => navigate("/?prefill=" + encodeURIComponent(code))}
          className="rounded-lg px-3 py-1 text-xs font-medium transition-all"
          style={{ backgroundColor: "rgba(226, 179, 64, 0.1)", color: "var(--accent)", border: "1px solid rgba(226, 179, 64, 0.2)" }}
        >
          Sauvegarder
        </button>
      </div>
      {result && (
        <div
          className="mt-2 rounded-lg p-3 text-xs font-mono"
          style={{
            backgroundColor: result.status === "success" ? "rgba(74, 222, 128, 0.05)" : "rgba(248, 113, 113, 0.05)",
            border: `1px solid ${result.status === "success" ? "rgba(74, 222, 128, 0.2)" : "rgba(248, 113, 113, 0.2)"}`,
            color: "var(--text-secondary)",
          }}
        >
          <div className="font-medium mb-1" style={{ color: result.status === "success" ? "var(--success)" : "var(--error)" }}>
            {result.status === "success" ? "Succes" : "Erreur"}
          </div>
          <pre className="whitespace-pre-wrap">{result.output || result.error || "Pas de sortie"}</pre>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create MessageBubble component**

Create `frontend/src/components/Chat/MessageBubble.tsx`:

```typescript
import Markdown from "react-markdown";
import { ToolCallBlock } from "./ToolCallBlock";
import { ScriptBlock } from "./ScriptBlock";

interface Props {
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: Array<{ name: string; args: Record<string, unknown>; result: string }> | null;
  pendingToolCall?: { tool: string; server: string; args?: Record<string, unknown> } | null;
  pendingToolResult?: { tool: string; data: unknown } | null;
  conversationId: string;
}

export function MessageBubble({ role, content, toolCalls, pendingToolCall, pendingToolResult, conversationId }: Props) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-3">
        <div
          className="rounded-xl px-4 py-2.5 max-w-[75%] text-sm"
          style={{ backgroundColor: "rgba(226, 179, 64, 0.15)", color: "var(--text-primary)" }}
        >
          {content}
        </div>
      </div>
    );
  }

  // Extract python code blocks for ScriptBlock treatment
  const parts = splitContentWithScripts(content);

  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[85%]">
        <div
          className="rounded-xl px-4 py-2.5 text-sm chat-markdown"
          style={{ backgroundColor: "var(--bg-panel)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
        >
          {parts.map((part, i) =>
            part.type === "script" ? (
              <ScriptBlock key={i} code={part.content} conversationId={conversationId} />
            ) : (
              <Markdown key={i}>{part.content}</Markdown>
            )
          )}
        </div>
        {/* Saved tool calls from history */}
        {toolCalls?.map((tc, i) => (
          <ToolCallBlock key={i} tool={tc.name} server="" args={tc.args} result={tc.result} />
        ))}
        {/* Live streaming tool call */}
        {pendingToolCall && (
          <ToolCallBlock
            tool={pendingToolCall.tool}
            server={pendingToolCall.server}
            args={pendingToolCall.args}
            loading={!pendingToolResult}
            result={pendingToolResult?.data}
          />
        )}
      </div>
    </div>
  );
}

function splitContentWithScripts(content: string): Array<{ type: "text" | "script"; content: string }> {
  const parts: Array<{ type: "text" | "script"; content: string }> = [];
  const regex = /```python\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", content: content.slice(lastIndex, match.index) });
    }
    parts.push({ type: "script", content: match[1].trim() });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push({ type: "text", content: content.slice(lastIndex) });
  }

  return parts.length ? parts : [{ type: "text", content }];
}
```

- [ ] **Step 5: Create MessageList component**

Create `frontend/src/components/Chat/MessageList.tsx`:

```typescript
import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: Array<{ name: string; args: Record<string, unknown>; result: string }> | null;
  pendingToolCall?: { tool: string; server: string; args?: Record<string, unknown> } | null;
  pendingToolResult?: { tool: string; data: unknown } | null;
}

interface Props {
  messages: DisplayMessage[];
  conversationId: string;
  streaming?: boolean;
}

export function MessageList({ messages, conversationId, streaming }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          role={msg.role}
          content={msg.content}
          toolCalls={msg.toolCalls}
          pendingToolCall={msg.pendingToolCall}
          pendingToolResult={msg.pendingToolResult}
          conversationId={conversationId}
        />
      ))}
      {streaming && (
        <div className="flex justify-start mb-3">
          <div
            className="rounded-xl px-4 py-2.5 text-sm"
            style={{ backgroundColor: "var(--bg-panel)", color: "var(--text-muted)", border: "1px solid var(--border)" }}
          >
            <span className="animate-pulse">...</span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
```

- [ ] **Step 6: Create ChatInput component**

Create `frontend/src/components/Chat/ChatInput.tsx`:

```typescript
import { useState, useRef, useEffect } from "react";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px";
    }
  }, [text]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (text.trim() && !disabled) {
        onSend(text.trim());
        setText("");
      }
    }
  };

  return (
    <div className="px-6 py-3" style={{ borderTop: "1px solid var(--border)", backgroundColor: "var(--bg-void)" }}>
      <div className="flex gap-2 items-end">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Posez une question, demandez un rapport, ou creez un script..."
          rows={1}
          className="input-field flex-1 resize-none font-sans text-sm"
          style={{ minHeight: "40px", maxHeight: "120px" }}
        />
        <button
          onClick={() => { if (text.trim() && !disabled) { onSend(text.trim()); setText(""); } }}
          disabled={disabled || !text.trim()}
          className="btn-primary px-4 py-2 text-sm disabled:opacity-50"
        >
          Envoyer
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Wire up ChatPage with streaming logic**

Replace `frontend/src/components/Chat/ChatPage.tsx`:

```typescript
import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ConversationList } from "./ConversationList";
import { MessageList, type DisplayMessage } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { listMessages, sendMessageSSE, parseSSEStream } from "../../lib/api";
import type { ChatMessageData } from "../../lib/api";

export function ChatPage() {
  const queryClient = useQueryClient();
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamingMessages, setStreamingMessages] = useState<DisplayMessage[]>([]);

  const { data: historyMessages = [] } = useQuery({
    queryKey: ["chat-messages", activeConvId],
    queryFn: () => (activeConvId ? listMessages(activeConvId) : Promise.resolve([])),
    enabled: !!activeConvId,
  });

  const toDisplayMessages = (msgs: ChatMessageData[]): DisplayMessage[] =>
    msgs
      .filter((m) => m.role !== "tool")
      .map((m) => ({
        id: m.id,
        role: m.role as "user" | "assistant",
        content: m.content,
        toolCalls: m.tool_calls,
      }));

  const displayMessages = streaming ? streamingMessages : toDisplayMessages(historyMessages);

  const handleSend = useCallback(
    async (content: string) => {
      if (!activeConvId || streaming) return;

      setStreaming(true);
      const userMsg: DisplayMessage = { id: "user-" + Date.now(), role: "user", content, toolCalls: null };
      const assistantMsg: DisplayMessage = { id: "assistant-" + Date.now(), role: "assistant", content: "", toolCalls: null };

      const currentHistory = toDisplayMessages(historyMessages);
      setStreamingMessages([...currentHistory, userMsg, assistantMsg]);

      try {
        const response = await sendMessageSSE(activeConvId, content);
        if (!response.body) throw new Error("No response body");

        const reader = response.body.getReader();
        let currentText = "";
        let currentToolCall: DisplayMessage["pendingToolCall"] = null;
        let currentToolResult: DisplayMessage["pendingToolResult"] = null;

        await parseSSEStream(reader, (event) => {
          if (event.event === "text") {
            currentText += (event.data as { content: string }).content;
            setStreamingMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, content: currentText };
              return updated;
            });
          } else if (event.event === "tool_call") {
            currentToolCall = event.data as DisplayMessage["pendingToolCall"];
            currentToolResult = null;
            setStreamingMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, pendingToolCall: currentToolCall, pendingToolResult: null };
              return updated;
            });
          } else if (event.event === "tool_result") {
            currentToolResult = event.data as DisplayMessage["pendingToolResult"];
            setStreamingMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, pendingToolResult: currentToolResult };
              return updated;
            });
          }
        });
      } catch (e) {
        console.error("Chat stream error:", e);
      } finally {
        setStreaming(false);
        setStreamingMessages([]);
        queryClient.invalidateQueries({ queryKey: ["chat-messages", activeConvId] });
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }
    },
    [activeConvId, streaming, historyMessages, queryClient],
  );

  return (
    <div className="flex" style={{ height: "calc(100vh - 57px)" }}>
      <div style={{ width: "250px", flexShrink: 0 }}>
        <ConversationList activeId={activeConvId} onSelect={setActiveConvId} />
      </div>
      <div className="flex-1 flex flex-col">
        {activeConvId ? (
          <>
            <MessageList messages={displayMessages} conversationId={activeConvId} streaming={streaming && displayMessages[displayMessages.length - 1]?.content === ""} />
            <ChatInput onSend={handleSend} disabled={streaming} />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                Selectionnez ou creez une conversation
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Posez des questions, appelez des outils MCP, ou generez des scripts.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Chat/ frontend/package.json frontend/package-lock.json
git commit -m "feat(chat): add message list, bubbles, input, streaming, tool call and script blocks"
```

---

### Task 7: Deploy + E2E Test

**Files:**
- No new files — deploy existing code to production

- [ ] **Step 1: Build frontend locally to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 2: Push to remote**

```bash
git push origin main
```

- [ ] **Step 3: Deploy to production**

```bash
ssh root@46.225.115.154 "cd /opt/mcp-tour-de-control && git pull && docker compose up -d --build backend frontend"
```

- [ ] **Step 4: Verify migration ran**

```bash
ssh root@46.225.115.154 "docker exec mcp-tour-de-control-backend-1 alembic current"
```

Expected: `b1c2d3e4f5a6 (head)`

- [ ] **Step 5: E2E test via curl**

```bash
# Create conversation
curl -s -X POST -u keffa:telemanager# https://tour.alcall.net/api/v1/chat/conversations | python3 -m json.tool

# Send message (SSE stream)
curl -s -N -X POST -u keffa:telemanager# https://tour.alcall.net/api/v1/chat/conversations/<CONV_ID>/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Liste les gateways actives via TmLite"}'
```

Expected: SSE events streaming with text + tool_call + tool_result + done.

- [ ] **Step 6: Test in browser**

Open https://tour.alcall.net/chat, create a conversation, send a message, verify streaming response.

- [ ] **Step 7: Commit any fixes if needed**

```bash
git add -A && git commit -m "fix(chat): post-deploy fixes" && git push origin main
```
