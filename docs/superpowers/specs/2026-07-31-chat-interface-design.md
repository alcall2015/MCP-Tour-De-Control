# Chat Interface — Design Spec

## Overview

Add a conversational chat interface to MCP Tour De Control. The chat allows users to interact with a LLM that can call MCP tools in real-time, generate and test Python scripts, and answer questions — all within a streaming conversation.

## Architecture

### Transport: Server-Sent Events (SSE)

The user sends a message via `POST`, the backend returns a `StreamingResponse` with SSE events. No WebSocket needed — SSE passes through Cloudflare/nginx without config changes.

### Models

**Conversation**
- `id`: UUID PK
- `title`: String(200), nullable (auto-generated from first message)
- `created_at`: DateTime(tz)
- `updated_at`: DateTime(tz)

**ChatMessage**
- `id`: UUID PK
- `conversation_id`: UUID FK → Conversation
- `role`: String(20) — "user", "assistant", "tool"
- `content`: Text — message text or tool result JSON
- `tool_calls`: JSON, nullable — list of tool calls made by assistant
- `created_at`: DateTime(tz)

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/chat/conversations` | List conversations (ordered by updated_at desc) |
| POST | `/api/v1/chat/conversations` | Create new conversation, returns Conversation |
| DELETE | `/api/v1/chat/conversations/{id}` | Delete conversation and its messages |
| GET | `/api/v1/chat/conversations/{id}/messages` | Get message history |
| POST | `/api/v1/chat/conversations/{id}/messages` | Send message, returns SSE stream |

### SSE Event Types

```
event: text
data: {"content": "partial text chunk"}

event: tool_call
data: {"tool": "list_gateways", "server": "TmLite", "args": {"limit": 10}}

event: tool_result
data: {"tool": "list_gateways", "data": {...}}

event: script
data: {"code": "import asyncio..."}

event: done
data: {}

event: error
data: {"message": "error description"}
```

## Backend

### Chat Service (`app/services/chat_service.py`)

Orchestrates the conversation:

1. Load conversation history from DB (last 20 messages max)
2. Build system prompt with available MCP server tools
3. Convert MCP tools to provider-native function calling format (OpenAI tools / Anthropic tool_use / Google function_calling)
4. Call LLM with `stream=True`
5. Parse streaming response:
   - Text chunks → yield `text` events
   - Function/tool calls → execute via `fastmcp.Client` with auth headers, yield `tool_call` + `tool_result`, feed result back to LLM
   - Python code blocks → yield `script` events
6. Save complete assistant message + tool calls to DB after stream ends
7. Auto-generate conversation title from first user message (ask LLM for 5-word summary, non-streaming)

### System Prompt

```
Tu es l'assistant de MCP Tour De Control, une plateforme de gestion
de serveurs MCP et de scripts automatises.

Tu peux :
1. Repondre aux questions de l'utilisateur
2. Appeler les outils MCP disponibles pour recuperer des donnees en direct
3. Generer des scripts Python quand l'utilisateur le demande

Quand tu appelles un outil MCP, analyse le resultat et presente-le
de maniere claire et lisible a l'utilisateur.

Quand tu generes un script, mets-le dans un bloc ```python.

Reponds en francais. Sois concis et professionnel.
```

MCP tools are injected dynamically as function definitions from all enabled MCP servers.

### Context Window Management

- Send last 20 messages max to LLM
- Tool results longer than 2000 chars are truncated with "[truncated, N chars total]"
- System prompt + tools definitions are always included

### LLM Provider Streaming

Each provider has its own streaming API:

- **OpenAI**: `client.chat.completions.create(stream=True)` → iterate `chunk.choices[0].delta`
- **Anthropic**: `client.messages.stream()` → iterate content blocks, handle `tool_use` blocks
- **Google**: `model.generate_content(stream=True)` → iterate chunks, handle function calls

The chat service abstracts this behind a common async generator that yields our SSE event types.

### MCP Tool Execution

When the LLM requests a tool call:
1. Find the McpServer that owns the tool (tracked during tool registration)
2. Connect via `StreamableHttpTransport` (with auth headers if `api_key` set) or `StdioTransport`
3. Call `client.call_tool(name, args)`
4. Parse `result[0].text` as JSON
5. Return to LLM as tool result for continued generation

### Script Actions

When the frontend receives a `script` event, it can:
- **Test**: `POST /api/v1/chat/conversations/{id}/run-script` with `{"code": "..."}` — runs via `ScriptExecutor` in a temporary context, returns execution result
- **Save as prompt**: frontend opens the prompt creation form pre-filled with the script context

Endpoint for testing scripts in chat:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/chat/conversations/{id}/run-script` | Execute script code, return result |

## Frontend

### New Tab: "Chat"

5th tab between "Stress Call" and "Config". Route: `/chat`.

### Layout

- **Sidebar** (250px, left): conversation list + "Nouvelle conversation" button at top. Each item shows title (or "Nouvelle conversation" if no title yet) and relative date. Active conversation highlighted.
- **Main area**: chat messages with auto-scroll to bottom.

### Message Components

- **User bubble**: text, right-aligned, accent dark background
- **Assistant bubble**: left-aligned, panel background. Content rendered as Markdown via `react-markdown` (new dependency). Supports bold, lists, inline code, code blocks.
- **Tool call indicator**: compact inline banner showing "Appel list_gateways sur TmLite..." with spinner during execution. Result shown in collapsible block (collapsed by default if > 5 lines).
- **Script block**: syntax-highlighted Python code block with two action buttons below:
  - "Tester" — runs the script, shows output/error inline below the block
  - "Sauvegarder" — navigates to Prompts tab with pre-filled form

### Input Area

- Textarea at bottom, auto-resize (1-5 lines)
- Send with Enter, Shift+Enter for newline
- Disabled during streaming with "..." typing indicator
- Placeholder: "Posez une question, demandez un rapport, ou creez un script..."

### Streaming Implementation

```typescript
const response = await fetch(`/api/v1/chat/conversations/${convId}/messages`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: message }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
// Parse SSE events line by line, update React state per chunk
```

No EventSource needed (POST not supported by EventSource API). Use fetch + ReadableStream.

### New Dependencies

- `react-markdown` — Markdown rendering in chat bubbles

## Alembic Migration

New migration adding `conversation` and `chat_message` tables.

## File Structure

```
backend/
  app/
    models/conversation.py      — Conversation + ChatMessage models
    schemas/chat.py             — Pydantic schemas
    routers/chat.py             — Chat endpoints
    services/chat_service.py    — LLM orchestration + streaming + tool calls
  alembic/versions/xxx_add_chat_tables.py

frontend/
  src/
    components/Chat/
      ChatPage.tsx              — Main layout (sidebar + chat area)
      ConversationList.tsx      — Sidebar conversation list
      MessageList.tsx           — Scrollable message area
      MessageBubble.tsx         — Single message rendering (text/tool/script)
      ChatInput.tsx             — Input textarea
      ToolCallBlock.tsx         — Tool call indicator + collapsible result
      ScriptBlock.tsx           — Code block + Test/Save buttons
    lib/api.ts                  — New chat API functions + types
```
