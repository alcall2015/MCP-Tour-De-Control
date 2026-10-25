# Agent Execution (2a, backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an `active` agent be run: tasks are queued in Postgres, claimed by a separate worker process, executed as plan → tool loop → critique → report, journaled step by step with full prompts, exposed over a REST API and an SSE stream, and schedulable by cron.

**Architecture:** The chat's LLM/tool primitives move to `services/llm_runtime.py` and are shared. Two new tables (`agent_task`, `agent_task_step`) form both the journal and the queue; `services/agent_task_service.py` owns every write to them (enqueue, claim with `FOR UPDATE SKIP LOCKED`, heartbeat, steps, finish, `NOTIFY`). `services/agent_runner.py` is a pure orchestration of injected `llm` and `tool` callables; `app/worker.py` is a thin loop around claim + runner. `services/agent_service.py` takes the agent lifecycle out of the router and syncs per-agent cron jobs with APScheduler.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 + asyncpg (`LISTEN`/`NOTIFY`), Alembic, Pydantic v2, APScheduler 3, pytest-asyncio on a live Postgres, structlog.

Spec: `docs/superpowers/specs/2026-10-25-agent-execution-design.md`. Frontend is plan 2b.

## Global Constraints

- Branch `feat/agent-execution` from `main` (the main checkout is clean; no worktree needed). Conventional Commits `feat(agents): ...` / `refactor(chat): ...`, every commit ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Stage named paths only; never `git add -A`.
- Backend commands from `backend/` with `venv/bin/python`; tests need the test Postgres (`mcp_control_test`) on localhost:5432; add `-p no:cacheprovider`. One pre-existing `AuthlibDeprecationWarning` from `fastmcp` is known.
- Alembic revision `4f5a6b7c8d9e`, chained on `3e4f5a6b7c8d` (single head). Hand-written; never apply autogenerate's spurious drops (see CLAUDE.md).
- Task status values exactly `queued`, `running`, `completed`, `failed`, `cancelled`; outcome values `success`, `partial`, `failed`; trigger values `manual`, `cron`; step kinds `plan`, `turn`, `tool_call`, `critique`, `report`, `error`. All CHECK-constrained.
- Snapshots on the task: `objective`, `instructions`, `max_steps`, `timeout_seconds`.
- Settings with defaults: `AGENT_WORKER_CONCURRENCY=2`, `AGENT_TASK_HEARTBEAT_SECONDS=15`, `AGENT_TASK_STALE_SECONDS=90`, `AGENT_TASK_FINAL_GRACE_SECONDS=90`.
- Verdict by code: criterion met iff `met is True and confidence >= 0.5`; all met → `success`, none → `failed`, else `partial`. `max_steps` counts loop rounds only.
- Tool results truncated to `MAX_TOOL_RESULT_LEN = 2000` like the chat. Prompts stored verbatim on `plan`/`turn`/`critique`/`report` steps and never contain API keys.
- Every mutating write to `agent_task` / `agent_task_step` goes through `AgentTaskService`; it emits `NOTIFY agent_task_events` (`{"task_id","seq","status"}`) after step inserts and status changes, and `NOTIFY agent_task_queued` after enqueue.
- Claim SQL guarantees one `running` task per agent (`NOT EXISTS` on running tasks of the same agent).
- Routers stay thin: lifecycle and cron sync live in `services/agent_service.py`, task writes in `services/agent_task_service.py`. One file per entity in `models/`, `schemas/`, `routers/`; export every new model and schema from the package `__init__`s.
- Chat behaviour must not change; its tests remain the regression proof after the extraction.
- Code, comments and messages in English.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/app/services/llm_runtime.py` | `clean_schema`, `build_tool_defs`, `call_llm` → `LlmResult`, `call_mcp_tool` (extracted from chat) |
| `backend/app/utils/sse.py` | `sse_frame(event, data)` shared by chat and task streaming |
| `backend/app/services/chat_service.py` | delegates to `llm_runtime`; no behaviour change |
| `backend/app/config.py` | four `AGENT_*` settings |
| `backend/app/models/agent.py` | `+ cron_expr` |
| `backend/app/models/agent_task.py` | `AgentTask`, `AgentTaskStep` |
| `backend/alembic/versions/4f5a6b7c8d9e_add_agent_tasks.py` | migration |
| `backend/app/schemas/agent_task.py` | task/step schemas |
| `backend/app/schemas/agent.py` | `cron_expr`, `running_task_id`, `last_task` |
| `backend/app/services/agent_task_service.py` | enqueue, cancel, claim, heartbeat, sweep, steps, finish, notify |
| `backend/app/services/agent_runner.py` | `run_task()` phases, prompts, JSON parsing, verdict |
| `backend/app/worker.py` | worker loop (`python -m app.worker`) |
| `backend/app/services/agent_service.py` | transitions, cron sync, task summaries |
| `backend/app/services/scheduler_service.py` | `add_agent_job` / `remove_agent_job` / `reschedule_agent_job`, `_execute_agent_cron` |
| `backend/app/routers/agents.py` | thin; `+ POST/GET /{id}/tasks` |
| `backend/app/routers/agent_tasks.py` | detail, step detail, SSE, cancel |
| `backend/app/main.py` | include router, restore agent cron jobs |
| `docker-compose.yml` | `worker` service |
| `CLAUDE.md` | Agents section update |
| tests | `test_llm_runtime.py`, `test_agent_task_models.py`, `test_agent_task_service.py`, `test_agent_runner.py`, `test_worker.py`, `test_agent_service.py`, `test_api_agent_tasks.py`, updated `test_chat_service.py`, `test_api_agents.py` |

---

### Task 1: Extract the shared LLM runtime from the chat

**Files:**
- Create: `backend/app/services/llm_runtime.py`
- Create: `backend/app/utils/sse.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/tests/test_chat_service.py`
- Test: `backend/tests/test_llm_runtime.py`

**Interfaces:**
- Produces:
  ```python
  MAX_TOOL_RESULT_LEN = 2000
  @dataclass
  class LlmResult: text: str; tool_calls: list[dict]; tokens_in: int = 0; tokens_out: int = 0
  def clean_schema(schema: dict) -> dict
  async def build_tool_defs(servers: list[McpServer]) -> tuple[list[dict], dict[str, McpServer]]
  async def call_llm(provider: str, model: str, api_key: str, messages: list[dict], tools: list[dict] | None) -> LlmResult
  async def call_mcp_tool(tool_name: str, args: dict, server: McpServer) -> str
  def sse_frame(event: str, data: dict) -> str          # app/utils/sse.py
  ```
  `call_llm` runs the blocking SDK code in a thread (`asyncio.to_thread`) so callers can `asyncio.wait_for` it. `tool_calls` is always a list (empty when none).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm_runtime.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models import McpServer
from app.services import llm_runtime
from app.services.llm_runtime import LlmResult, build_tool_defs, call_llm, clean_schema


def test_clean_schema_keeps_portable_fields_and_prunes_required():
    schema = {
        "$schema": "x", "type": "object", "additionalProperties": False,
        "properties": {"a": {"type": "string", "minimum": 1}, "b": {"$ref": "#/x"}},
        "required": ["a", "b"],
    }
    assert clean_schema(schema) == {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {}},
        "required": ["a", "b"],
    }


def test_clean_schema_drops_required_without_properties():
    assert clean_schema({"type": "object", "required": ["a"]}) == {"type": "object"}


async def test_build_tool_defs_flattens_and_keeps_first_on_collision():
    s1 = McpServer(name="one", transport="http", url="http://a", enabled=True)
    s2 = McpServer(name="two", transport="http", url="http://b", enabled=True)

    async def fake_tools(server):
        return [{"name": "shared", "description": "d", "input_schema": {"type": "object", "properties": {}}},
                {"name": f"only_{server.name}", "description": "", "input_schema": None}]

    with patch("app.services.llm_runtime.McpService.get_server_tools", side_effect=fake_tools):
        defs, server_map = await build_tool_defs([s1, s2])

    assert [d["function"]["name"] for d in defs] == ["shared", "only_one", "only_two"]
    assert server_map["shared"] is s1
    assert defs[0]["function"]["description"] == "[one] d"
    assert defs[1]["function"]["parameters"] == {"type": "object", "properties": {}}


async def test_call_llm_openai_returns_text_calls_and_usage():
    def chunk(content=None, tool=None, usage=None):
        delta = SimpleNamespace(content=content, tool_calls=tool)
        choices = [SimpleNamespace(delta=delta)] if usage is None else []
        return SimpleNamespace(choices=choices, usage=usage)

    tc = SimpleNamespace(index=0, function=SimpleNamespace(name="list_x", arguments='{"a": 1}'))
    stream = [chunk("Hel"), chunk("lo"), chunk(tool=[tc]),
              chunk(usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3))]
    client = MagicMock()
    client.chat.completions.create.return_value = iter(stream)

    with patch("openai.OpenAI", return_value=client):
        result = await call_llm("openai", "gpt-x", "sk", [{"role": "user", "content": "hi"}], None)

    assert result == LlmResult(text="Hello", tool_calls=[{"name": "list_x", "args": {"a": 1}}], tokens_in=12, tokens_out=3)
    assert client.chat.completions.create.call_args.kwargs["stream_options"] == {"include_usage": True}


async def test_call_llm_unknown_provider_raises():
    with pytest.raises(ValueError):
        await call_llm("nope", "m", "k", [], None)


def test_sse_frame():
    from app.utils.sse import sse_frame
    assert sse_frame("step", {"a": "é"}) == 'event: step\ndata: {"a": "é"}\n\n'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_llm_runtime.py -q -p no:cacheprovider`
Expected: FAIL at import, `ModuleNotFoundError: No module named 'app.services.llm_runtime'`.

- [ ] **Step 3: Create `app/utils/sse.py`**

```python
import json


def sse_frame(event: str, data: dict) -> str:
    """One Server-Sent Events frame, UTF-8 kept readable."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: Create `app/services/llm_runtime.py`**

Move the bodies of `_clean_schema`, `_get_mcp_tools` (generalised), `_call_mcp_tool` and `_stream_llm` from `chat_service.py` here. The provider code is the existing code with three changes: it runs in a thread, it returns `LlmResult`, and it reads usage.

```python
"""LLM and MCP primitives shared by the chat and the agent runner."""
import asyncio
import json
from dataclasses import dataclass, field

import structlog

from app.models import McpServer
from app.services.mcp_service import McpService, _build_http_transport

log = structlog.get_logger()

MAX_TOOL_RESULT_LEN = 2000

# Keep only the portable JSON Schema subset accepted by every configured
# function-calling provider.  In particular, Gemini rejects validation and
# metadata keywords such as `$schema`, `minimum`, and `additionalProperties`.
_FUNCTION_SCHEMA_FIELDS = {"type", "description", "properties", "required", "items", "enum"}


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
        if isinstance(v, dict):
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
            result = await client.call_tool(tool_name, args)
        text = result[0].text if result else ""
        if len(text) > MAX_TOOL_RESULT_LEN:
            text = text[:MAX_TOOL_RESULT_LEN] + f"\n[truncated, {len(text)} chars total]"
        return text
    except Exception as e:
        log.error("MCP tool call failed", tool=tool_name, error=str(e))
        return json.dumps({"error": str(e)})


async def call_llm(provider: str, model: str, api_key: str, messages: list[dict], tools: list[dict] | None) -> LlmResult:
    """Call the configured provider once, in a worker thread (the SDKs block)."""
    return await asyncio.to_thread(_call_llm_sync, provider, model, api_key, messages, tools)


def _call_llm_sync(provider, model, api_key, messages, tools) -> LlmResult:
    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
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
        client = anthropic.Anthropic(api_key=api_key)
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
        for m in messages:
            if m["role"] == "system":
                parts.append(f"[System] {m['content']}")
            elif m["role"] == "user":
                parts.append(f"[User] {m['content']}")
            elif m["role"] == "assistant":
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        parts.append(f"[Assistant called tool: {tc.get('function', tc).get('name', 'unknown')}]")
                elif m.get("content"):
                    parts.append(f"[Assistant] {m['content']}")
            elif m["role"] == "tool":
                content = m["content"]
                if len(content) > MAX_TOOL_RESULT_LEN:
                    content = content[:MAX_TOOL_RESULT_LEN] + f"\n[truncated, {len(m['content'])} chars total]"
                parts.append(f"[Tool result for {m.get('tool_call_id', '').replace('call_', '')}]\n{content}")
        prompt = "\n\n".join(parts)
        prompt += "\n\n[System] If you already have tool results above that answer the user's question, use them directly. Do NOT call the same tool again."
        text, calls, tokens_in, tokens_out = "", [], 0, 0
        for chunk in model_obj.generate_content(prompt, stream=True):
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
```

- [ ] **Step 5: Make `chat_service.py` delegate**

Replace the module's private helpers and the streaming code so the chat uses the runtime. Concretely:

1. Imports: remove `from app.services.mcp_service import McpService, _build_http_transport`; add
   ```python
   from app.services.llm_runtime import MAX_TOOL_RESULT_LEN, build_tool_defs, call_llm, call_mcp_tool
   from app.utils.sse import sse_frame as _sse
   ```
   Keep `MAX_HISTORY = 20` and `MAX_TOOL_ROUNDS = 8`; delete the local `MAX_TOOL_RESULT_LEN`, `_FUNCTION_SCHEMA_FIELDS`, `_clean_schema`, `_stream_llm` and the trailing `_sse` definition.
2. `_get_mcp_tools` becomes:
   ```python
   @staticmethod
   async def _get_mcp_tools(session: AsyncSession) -> tuple[list[dict], dict[str, McpServer]]:
       servers = (await session.execute(select(McpServer).where(McpServer.enabled == True))).scalars().all()
       return await build_tool_defs(list(servers))
   ```
3. Delete `ChatService._call_mcp_tool`; in `stream_response` replace `await ChatService._call_mcp_tool(tool_name, tool_args, server)` with `await call_mcp_tool(tool_name, tool_args, server)`.
4. Replace the two `_stream_llm(...)` calls:
   ```python
   result = await call_llm(provider, model, api_key, messages, tools)
   text_chunk, tool_calls_batch = result.text, result.tool_calls
   ```
   and for the synthesis turn
   ```python
   result = await call_llm(provider, model, api_key, messages, None)
   text_chunk, dropped_tool_calls = result.text, result.tool_calls
   ```
   `if not tool_calls_batch:` keeps working because an empty list is falsy.

- [ ] **Step 6: Update the chat tests' patch target**

In `backend/tests/test_chat_service.py`, every `patch.object(chat_service, "_stream_llm", mock)` becomes `patch.object(chat_service, "call_llm", mock)`, and every mocked return value becomes an `LlmResult`. Add `from app.services.llm_runtime import LlmResult` to the imports and convert, e.g.:

```python
mock_stream_llm = AsyncMock(return_value=LlmResult("Bonjour !", []))
```

For tests that return a sequence (`side_effect=[...]`), wrap each tuple the same way: `("", [{"name": "t", "args": {}}])` → `LlmResult("", [{"name": "t", "args": {}}])`. Nothing else in those tests changes.

- [ ] **Step 7: Run the runtime and chat tests**

Run: `venv/bin/python -m pytest tests/test_llm_runtime.py tests/test_chat_service.py -q -p no:cacheprovider`
Expected: all passed (6 new + the 4 chat tests).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/llm_runtime.py backend/app/utils/sse.py backend/app/services/chat_service.py backend/tests/test_llm_runtime.py backend/tests/test_chat_service.py
git commit -m "refactor(chat): extract the LLM and MCP primitives into llm_runtime

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Settings, models and migration for tasks and steps

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/agent.py`
- Create: `backend/app/models/agent_task.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/4f5a6b7c8d9e_add_agent_tasks.py`
- Test: `backend/tests/test_agent_task_models.py`

**Interfaces:**
- Produces `AgentTask` and `AgentTaskStep` (columns per spec), `Agent.cron_expr`, settings `AGENT_WORKER_CONCURRENCY`, `AGENT_TASK_HEARTBEAT_SECONDS`, `AGENT_TASK_STALE_SECONDS`, `AGENT_TASK_FINAL_GRACE_SECONDS`. Constants `TASK_STATUSES`, `FINAL_STATUSES = {"completed","failed","cancelled"}`, `STEP_KINDS`, `OUTCOMES`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_task_models.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Agent, AgentTask, AgentTaskStep


async def _agent(session) -> Agent:
    agent = Agent(name="a", objective="o")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_task_defaults_and_snapshots(session):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="do it", instructions="be nice",
                     max_steps=5, timeout_seconds=60)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    assert task.status == "queued"
    assert task.outcome is None
    assert task.cancel_requested is False
    assert task.step_count == 0 and task.tokens_in == 0 and task.tokens_out == 0
    assert task.created_at is not None and task.started_at is None


async def test_steps_are_unique_per_seq_and_cascade(session):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60)
    session.add(task)
    await session.commit()
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="plan", payload={"steps": []}, prompt=[{"role": "system", "content": "x"}]))
    await session.commit()
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="turn", payload={}))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    await session.delete(await session.get(Agent, agent.id))
    await session.commit()
    assert (await session.execute(select(AgentTask))).scalars().all() == []
    assert (await session.execute(select(AgentTaskStep))).scalars().all() == []


@pytest.mark.parametrize("field,value", [("status", "done"), ("outcome", "ok"), ("trigger", "api")])
async def test_task_check_constraints(session, field, value):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60)
    setattr(task, field, value)
    session.add(task)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_step_kind_check_constraint(session):
    agent = await _agent(session)
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60)
    session.add(task)
    await session.commit()
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="thought", payload={}))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_agent_has_optional_cron(session):
    agent = Agent(name="a", objective="o", cron_expr="0 8 * * *")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    assert agent.cron_expr == "0 8 * * *"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_agent_task_models.py -q -p no:cacheprovider`
Expected: FAIL at import (`cannot import name 'AgentTask'`).

- [ ] **Step 3: Settings and the agent column**

In `backend/app/config.py` add inside `Settings`:

```python
    # Agent execution worker
    AGENT_WORKER_CONCURRENCY: int = 2
    AGENT_TASK_HEARTBEAT_SECONDS: int = 15
    AGENT_TASK_STALE_SECONDS: int = 90
    AGENT_TASK_FINAL_GRACE_SECONDS: int = 90
```

In `backend/app/models/agent.py` add after `timeout_seconds`:

```python
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

- [ ] **Step 4: Create `app/models/agent_task.py`**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base

TASK_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
FINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
OUTCOMES = ("success", "partial", "failed")
TRIGGERS = ("manual", "cron")
STEP_KINDS = ("plan", "turn", "tool_call", "critique", "report", "error")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentTask(Base):
    __tablename__ = "agent_task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(20))
    # Snapshots: editing the agent never changes a task already in flight.
    objective: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    max_steps: Mapped[int] = mapped_column(Integer)
    timeout_seconds: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(10), nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    critique: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)

    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["AgentTaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="AgentTaskStep.seq"
    )

    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_agent_task_status"),
        CheckConstraint("outcome IS NULL OR outcome IN ('success','partial','failed')", name="ck_agent_task_outcome"),
        CheckConstraint("trigger IN ('manual','cron')", name="ck_agent_task_trigger"),
        Index("ix_agent_task_agent_created", "agent_id", text("created_at DESC")),
        Index("ix_agent_task_queue", "created_at", postgresql_where=text("status = 'queued'")),
        Index("ix_agent_task_running", "agent_id", postgresql_where=text("status = 'running'")),
        Index("uq_agent_task_open_per_agent", "agent_id", unique=True, postgresql_where=text("status IN ('queued','running')")),
    )


class AgentTaskStep(Base):
    __tablename__ = "agent_task_step"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_task.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    prompt: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    task: Mapped[AgentTask] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("task_id", "seq", name="uq_agent_task_step_seq"),
        CheckConstraint("kind IN ('plan','turn','tool_call','critique','report','error')", name="ck_agent_task_step_kind"),
    )
```

In `backend/app/models/__init__.py` add `from app.models.agent_task import AgentTask, AgentTaskStep` after the `Agent` import and append `"AgentTask", "AgentTaskStep"` to `__all__`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_agent_task_models.py tests/test_agent_model.py -q -p no:cacheprovider`
Expected: all passed (7 new + 8 existing).

- [ ] **Step 6: Write the migration**

Create `backend/alembic/versions/4f5a6b7c8d9e_add_agent_tasks.py`:

```python
"""add agent tasks, steps and agent cron

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "4f5a6b7c8d9e"
down_revision = "3e4f5a6b7c8d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent", sa.Column("cron_expr", sa.String(length=100), nullable=True))
    op.create_table(
        "agent_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("outcome", sa.String(length=10), nullable=True),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("critique", postgresql.JSONB(), nullable=True),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_agent_task_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('success','partial','failed')", name="ck_agent_task_outcome"),
        sa.CheckConstraint("trigger IN ('manual','cron')", name="ck_agent_task_trigger"),
    )
    op.create_index("ix_agent_task_agent_created", "agent_task", ["agent_id", sa.text("created_at DESC")])
    op.create_index("ix_agent_task_queue", "agent_task", ["created_at"], postgresql_where=sa.text("status = 'queued'"))
    op.create_index("ix_agent_task_running", "agent_task", ["agent_id"], postgresql_where=sa.text("status = 'running'"))
    op.create_index("uq_agent_task_open_per_agent", "agent_task", ["agent_id"], unique=True,
                     postgresql_where=sa.text("status IN ('queued','running')"))
    op.create_table(
        "agent_task_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("prompt", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "seq", name="uq_agent_task_step_seq"),
        sa.CheckConstraint("kind IN ('plan','turn','tool_call','critique','report','error')", name="ck_agent_task_step_kind"),
    )


def downgrade():
    op.drop_table("agent_task_step")
    op.drop_index("uq_agent_task_open_per_agent", table_name="agent_task")
    op.drop_index("ix_agent_task_running", table_name="agent_task")
    op.drop_index("ix_agent_task_queue", table_name="agent_task")
    op.drop_index("ix_agent_task_agent_created", table_name="agent_task")
    op.drop_table("agent_task")
    op.drop_column("agent", "cron_expr")
```

Round-trip against the dev DB (from `backend/`, `.env` supplies `DATABASE_URL`):

```bash
PYTHONPATH=. venv/bin/alembic heads          # expect 3e4f5a6b7c8d (head) before, then:
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic downgrade -1
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic heads          # expect 4f5a6b7c8d9e (head), single
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/app/models/agent.py backend/app/models/agent_task.py backend/app/models/__init__.py backend/alembic/versions/4f5a6b7c8d9e_add_agent_tasks.py backend/tests/test_agent_task_models.py
git commit -m "feat(agents): add agent task and step tables, cron column and worker settings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `AgentTaskService` — enqueue, claim, heartbeat, steps, finish, notify

**Files:**
- Create: `backend/app/services/agent_task_service.py`
- Test: `backend/tests/test_agent_task_service.py`

**Interfaces:**
- Produces:
  ```python
  class TaskConflict(Exception): status_code = 409; detail: str
  EVENTS_CHANNEL = "agent_task_events"; QUEUED_CHANNEL = "agent_task_queued"
  class AgentTaskService:
      @staticmethod async def enqueue(session, agent: Agent, *, objective: str | None, trigger: str) -> AgentTask   # raises TaskConflict
      @staticmethod async def claim(session, worker_id: str) -> AgentTask | None
      @staticmethod async def heartbeat(session, task_id) -> None
      @staticmethod async def sweep_stale(session, older_than_seconds: int) -> int
      @staticmethod async def record_step(session, task: AgentTask, kind: str, payload: dict, *, prompt=None, tokens_in=None, tokens_out=None, duration_ms=None) -> AgentTaskStep
      @staticmethod async def finish(session, task: AgentTask, status: str, *, outcome=None, error=None) -> None
      @staticmethod async def request_cancel(session, task: AgentTask) -> None      # raises TaskConflict on final
      @staticmethod async def is_cancel_requested(session, task_id) -> bool
  ```
  Each method commits. `record_step` increments `task.step_count`, adds tokens to the task totals, and notifies. `finish` sets `finished_at` and notifies.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_task_service.py`:

```python
import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, AgentTaskStep, McpServer
from app.services.agent_task_service import AgentTaskService, TaskConflict


async def make_agent(session, name="a", status="active") -> Agent:
    server = McpServer(name=f"srv-{name}", transport="http", url="http://x", enabled=True)
    agent = Agent(name=name, objective="objective", instructions="rules", status=status, mcp_servers=[server])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_enqueue_snapshots_and_notifies(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    assert task.status == "queued" and task.trigger == "manual"
    assert task.objective == "objective" and task.instructions == "rules"
    assert task.max_steps == agent.max_steps and task.timeout_seconds == agent.timeout_seconds
    assert task.started_at is None and task.worker_id is None


async def test_enqueue_rejects_inactive_agent_and_duplicates(session):
    draft = await make_agent(session, "d", status="draft")
    with pytest.raises(TaskConflict):
        await AgentTaskService.enqueue(session, draft, objective=None, trigger="manual")
    active = await make_agent(session, "x")
    await AgentTaskService.enqueue(session, active, objective="first", trigger="manual")
    with pytest.raises(TaskConflict):
        await AgentTaskService.enqueue(session, active, objective="second", trigger="cron")


async def test_claim_is_exclusive_per_agent_and_across_workers(setup_db, session):
    a1 = await make_agent(session, "a1")
    a2 = await make_agent(session, "a2")
    t1 = await AgentTaskService.enqueue(session, a1, objective="1", trigger="manual")
    t2 = await AgentTaskService.enqueue(session, a2, objective="2", trigger="manual")
    # a second task of a1 cannot be enqueued while t1 is queued, so insert it directly
    t3 = AgentTask(agent_id=a1.id, trigger="manual", objective="3", instructions="", max_steps=5, timeout_seconds=60)
    session.add(t3)
    await session.commit()

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s1, factory() as s2, factory() as s3:
        c1, c2, c3 = await asyncio.gather(
            AgentTaskService.claim(s1, "w1"), AgentTaskService.claim(s2, "w2"), AgentTaskService.claim(s3, "w3"))
    claimed = {c.id for c in (c1, c2, c3) if c}
    assert claimed == {t1.id, t2.id}           # t3 waits: its agent already has a running task
    assert {c.worker_id for c in (c1, c2, c3) if c} == {"w1", "w2"} or len(claimed) == 2
    for c in (c1, c2, c3):
        if c:
            assert c.status == "running" and c.started_at is not None and c.heartbeat_at is not None

    await AgentTaskService.finish(session, await session.get(AgentTask, t1.id), "completed", outcome="success")
    assert (await AgentTaskService.claim(session, "w4")).id == t3.id
    assert await AgentTaskService.claim(session, "w5") is None


async def test_sweep_marks_only_stale_running_tasks(session):
    agent = await make_agent(session)
    fresh = await AgentTaskService.enqueue(session, agent, objective="f", trigger="manual")
    fresh = await AgentTaskService.claim(session, "w")
    stale = AgentTask(agent_id=(await make_agent(session, "b")).id, trigger="manual", objective="s", instructions="",
                      max_steps=5, timeout_seconds=60, status="running", worker_id="dead",
                      started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
                      heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    session.add(stale)
    await session.commit()

    assert await AgentTaskService.sweep_stale(session, older_than_seconds=90) == 1
    await session.refresh(stale)
    await session.refresh(fresh)
    assert stale.status == "failed" and stale.error == "worker lost" and stale.finished_at is not None
    assert fresh.status == "running"
    steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == stale.id))).scalars().all()
    assert [s.kind for s in steps] == ["error"] and steps[0].payload["phase"] == "claim"


async def test_record_step_increments_seq_and_totals(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
    s1 = await AgentTaskService.record_step(session, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "p"}], tokens_in=10, tokens_out=5)
    s2 = await AgentTaskService.record_step(session, task, "tool_call", {"tool": "t"}, duration_ms=12)
    assert (s1.seq, s2.seq) == (1, 2)
    await session.refresh(task)
    assert task.step_count == 2 and task.tokens_in == 10 and task.tokens_out == 5
    assert s1.prompt == [{"role": "system", "content": "p"}] and s2.prompt is None


async def test_heartbeat_and_cancel(session):
    agent = await make_agent(session)
    task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
    await AgentTaskService.request_cancel(session, task)       # queued -> cancelled immediately
    await session.refresh(task)
    assert task.status == "cancelled" and task.finished_at is not None
    with pytest.raises(TaskConflict):
        await AgentTaskService.request_cancel(session, task)   # already final

    agent2 = await make_agent(session, "b")
    running = await AgentTaskService.enqueue(session, agent2, objective="o", trigger="manual")
    running = await AgentTaskService.claim(session, "w")
    before = running.heartbeat_at
    await asyncio.sleep(0.01)
    await AgentTaskService.heartbeat(session, running.id)
    await session.refresh(running)
    assert running.heartbeat_at > before
    await AgentTaskService.request_cancel(session, running)
    assert await AgentTaskService.is_cancel_requested(session, running.id) is True
    await session.refresh(running)
    assert running.status == "running"                         # the runner turns it into cancelled


async def test_notifications_are_emitted(setup_db, session):
    """LISTEN on a raw asyncpg connection and check enqueue + step + finish notify."""
    agent = await make_agent(session)
    received: list[tuple[str, str]] = []
    async with setup_db.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        await raw.add_listener("agent_task_queued", lambda c, pid, ch, payload: received.append((ch, payload)))
        await raw.add_listener("agent_task_events", lambda c, pid, ch, payload: received.append((ch, payload)))
        task = await AgentTaskService.enqueue(session, agent, objective="o", trigger="manual")
        await AgentTaskService.record_step(session, task, "plan", {"steps": []})
        await AgentTaskService.finish(session, task, "completed", outcome="success")
        for _ in range(50):
            if len(received) >= 3:
                break
            await asyncio.sleep(0.05)
    channels = [c for c, _ in received]
    assert channels[0] == "agent_task_queued" and received[0][1] == str(task.id)
    assert channels.count("agent_task_events") >= 2
    assert all(str(task.id) in p for _, p in received[1:])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_agent_task_service.py -q -p no:cacheprovider`
Expected: FAIL at import (`No module named 'app.services.agent_task_service'`).

- [ ] **Step 3: Create the service**

```python
"""Every write to agent_task / agent_task_step goes through here.

The table doubles as the work queue: `claim` uses FOR UPDATE SKIP LOCKED and
guarantees one running task per agent; every step and status change is
followed by a Postgres NOTIFY so the API can stream it."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentTask, AgentTaskStep
from app.models.agent_task import FINAL_STATUSES

log = structlog.get_logger()

EVENTS_CHANNEL = "agent_task_events"
QUEUED_CHANNEL = "agent_task_queued"


class TaskConflict(Exception):
    status_code = 409

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _notify(session: AsyncSession, channel: str, payload: str) -> None:
    # Delivered when the surrounding transaction commits.
    await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": channel, "payload": payload})


async def _notify_event(session: AsyncSession, task: AgentTask, seq: int | None) -> None:
    await _notify(session, EVENTS_CHANNEL, json.dumps({"task_id": str(task.id), "seq": seq, "status": task.status}))


class AgentTaskService:

    @staticmethod
    async def enqueue(session: AsyncSession, agent: Agent, *, objective: str | None, trigger: str) -> AgentTask:
        if agent.status != "active":
            raise TaskConflict(f"Agent is {agent.status}; only active agents can run")
        open_task = (await session.execute(
            select(AgentTask.id).where(AgentTask.agent_id == agent.id, AgentTask.status.in_(("queued", "running"))).limit(1)
        )).scalar_one_or_none()
        if open_task:
            raise TaskConflict("Agent already has a queued or running task")
        task = AgentTask(
            agent_id=agent.id, trigger=trigger,
            objective=(objective or "").strip() or agent.objective,
            instructions=agent.instructions, max_steps=agent.max_steps, timeout_seconds=agent.timeout_seconds,
        )
        session.add(task)
        await session.flush()
        await _notify(session, QUEUED_CHANNEL, str(task.id))
        await session.commit()
        await session.refresh(task)
        log.info("agent_task_queued", task_id=str(task.id), agent_id=str(agent.id), trigger=trigger)
        return task

    @staticmethod
    async def claim(session: AsyncSession, worker_id: str) -> AgentTask | None:
        row = (await session.execute(text("""
            UPDATE agent_task
            SET status = 'running', worker_id = :worker_id, started_at = now(), heartbeat_at = now()
            WHERE id = (
                SELECT t.id FROM agent_task t
                JOIN agent a ON a.id = t.agent_id
                WHERE t.status = 'queued'
                  AND NOT EXISTS (SELECT 1 FROM agent_task r WHERE r.agent_id = t.agent_id AND r.status = 'running')
                ORDER BY t.created_at
                FOR UPDATE OF t, a SKIP LOCKED
                LIMIT 1)
            RETURNING id
        """), {"worker_id": worker_id})).first()
        await session.commit()
        if not row:
            return None
        task = await session.get(AgentTask, row[0])
        await session.refresh(task)
        await _notify_event(session, task, None)
        await session.commit()
        return task

    @staticmethod
    async def heartbeat(session: AsyncSession, task_id: uuid.UUID) -> None:
        await session.execute(update(AgentTask).where(AgentTask.id == task_id).values(heartbeat_at=_now()))
        await session.commit()

    @staticmethod
    async def sweep_stale(session: AsyncSession, older_than_seconds: int) -> int:
        cutoff = _now() - timedelta(seconds=older_than_seconds)
        stale = (await session.execute(
            select(AgentTask).where(AgentTask.status == "running", AgentTask.heartbeat_at < cutoff)
        )).scalars().all()
        for task in stale:
            await AgentTaskService.record_step(session, task, "error", {"message": "worker lost", "phase": "claim"})
            await AgentTaskService.finish(session, task, "failed", error="worker lost")
            log.warning("agent_task_worker_lost", task_id=str(task.id), worker_id=task.worker_id)
        return len(stale)

    @staticmethod
    async def record_step(session: AsyncSession, task: AgentTask, kind: str, payload: dict, *,
                          prompt: list | None = None, tokens_in: int | None = None,
                          tokens_out: int | None = None, duration_ms: int | None = None) -> AgentTaskStep:
        next_seq = (await session.execute(
            select(func.coalesce(func.max(AgentTaskStep.seq), 0) + 1).where(AgentTaskStep.task_id == task.id)
        )).scalar_one()
        step = AgentTaskStep(task_id=task.id, seq=next_seq, kind=kind, payload=payload, prompt=prompt,
                             tokens_in=tokens_in, tokens_out=tokens_out, duration_ms=duration_ms)
        session.add(step)
        task.step_count = next_seq
        task.tokens_in = (task.tokens_in or 0) + (tokens_in or 0)
        task.tokens_out = (task.tokens_out or 0) + (tokens_out or 0)
        await session.flush()
        await _notify_event(session, task, next_seq)
        await session.commit()
        return step

    @staticmethod
    async def finish(session: AsyncSession, task: AgentTask, status: str, *, outcome: str | None = None,
                     error: str | None = None) -> None:
        task.status = status
        task.outcome = outcome
        task.error = error
        task.finished_at = _now()
        await session.flush()
        await _notify_event(session, task, None)
        await session.commit()
        log.info("agent_task_finished", task_id=str(task.id), status=status, outcome=outcome)

    @staticmethod
    async def request_cancel(session: AsyncSession, task: AgentTask) -> None:
        if task.status in FINAL_STATUSES:
            raise TaskConflict(f"Task is already {task.status}")
        if task.status == "queued":
            await AgentTaskService.finish(session, task, "cancelled")
            return
        task.cancel_requested = True
        await session.commit()

    @staticmethod
    async def is_cancel_requested(session: AsyncSession, task_id: uuid.UUID) -> bool:
        return bool((await session.execute(
            select(AgentTask.cancel_requested).where(AgentTask.id == task_id)
        )).scalar_one())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_agent_task_service.py -q -p no:cacheprovider`
Expected: 7 passed. If `test_claim_is_exclusive...` is flaky because three sessions race on the same connection pool, it is a real bug in the claim SQL, not in the test: the `NOT EXISTS` must be evaluated inside the same `FOR UPDATE SKIP LOCKED` statement as written above.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_task_service.py backend/tests/test_agent_task_service.py
git commit -m "feat(agents): add the task queue service with claim, heartbeat, steps and notify

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The runner — plan, loop, critique, report, verdict

**Files:**
- Create: `backend/app/services/agent_runner.py`
- Test: `backend/tests/test_agent_runner.py`

**Interfaces:**
- Consumes `AgentTaskService`, `llm_runtime.build_tool_defs`, `LlmResult`, settings.
- Produces:
  ```python
  CONFIDENCE_THRESHOLD = 0.5
  class LimitHit(str, Enum): MAX_STEPS = "max_steps"; TIMEOUT = "timeout"
  def parse_json_object(text: str) -> dict                        # strips ``` fences; raises ValueError
  def derive_outcome(criteria: list[dict]) -> str                 # success | partial | failed
  async def run_task(task_id: uuid.UUID, *, llm=call_llm, tool=call_mcp_tool, tool_defs=build_tool_defs, session_factory=async_session, clock=time.monotonic) -> None
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_runner.py`:

```python
import json
import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, AgentTaskStep, Config, McpServer
from app.services.agent_runner import derive_outcome, parse_json_object, run_task
from app.services.agent_task_service import AgentTaskService
from app.services.llm_runtime import LlmResult
from app.utils.crypto import encrypt_value

PLAN = {"steps": [{"title": "look", "tools": ["list_x"]}],
        "success_criteria": [{"id": "c1", "description": "listed"}, {"id": "c2", "description": "summarised"}],
        "risks": []}
CRITIQUE = {"criteria": [{"id": "c1", "met": True, "confidence": 0.9, "justification": "yes"},
                         {"id": "c2", "met": True, "confidence": 0.8, "justification": "yes"}]}
REPORT = {"summary": "done", "actions": [{"step_seq": 3, "description": "listed x"}],
          "evidence": ["step 3"], "uncertainties": [], "next_steps": []}


async def setup(session, *, max_steps=5, timeout=60, server_enabled=True, with_key=True):
    session.add(Config(llm_provider="openai", llm_model="gpt-x", api_key=encrypt_value("sk") if with_key else None))
    server = McpServer(name="srv", transport="http", url="http://x", enabled=server_enabled)
    agent = Agent(name="a", objective="Inspect x", instructions="Be terse", status="active",
                  max_steps=max_steps, timeout_seconds=timeout, mcp_servers=[server])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    task = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    return await AgentTaskService.claim(session, "test-worker")


def scripted(*results):
    """An llm callable that returns the given LlmResults in order and records its prompts."""
    queue = list(results)
    calls = []

    async def llm(provider, model, api_key, messages, tools):
        calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        return queue.pop(0)
    llm.calls = calls
    return llm


async def fake_tool_defs(servers):
    if not servers:
        return [], {}
    return ([{"type": "function", "function": {"name": "list_x", "description": "[srv] list", "parameters": {"type": "object", "properties": {}}}}],
            {"list_x": servers[0]})


async def fake_tool(name, args, server):
    return json.dumps({"items": [1, 2, 3]})


def J(obj):
    return LlmResult(json.dumps(obj), [])


async def steps_of(session, task_id):
    return (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task_id).order_by(AgentTaskStep.seq))).scalars().all()


def test_parse_json_object_strips_fences_and_rejects_garbage():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('text before {"a": 1} after') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("no json here")
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


@pytest.mark.parametrize("criteria,expected", [
    ([{"met": True, "confidence": 0.9}, {"met": True, "confidence": 0.6}], "success"),
    ([{"met": True, "confidence": 0.9}, {"met": False, "confidence": 0.9}], "partial"),
    ([{"met": True, "confidence": 0.4}], "failed"),           # low confidence does not count
    ([{"met": False, "confidence": 1.0}], "failed"),
    ([], "failed"),
])
def test_derive_outcome(criteria, expected):
    assert derive_outcome(criteria) == expected


async def test_nominal_run_writes_every_step_and_completes(setup_db, session):
    task = await setup(session)
    llm = scripted(
        J(PLAN),
        LlmResult("Let me look.", [{"name": "list_x", "args": {"q": 1}}], tokens_in=10, tokens_out=2),
        LlmResult("I have what I need.", [], tokens_in=12, tokens_out=3),
        J(CRITIQUE),
        J(REPORT),
    )
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=fake_tool, tool_defs=fake_tool_defs, session_factory=factory)

    await session.refresh(task)
    assert task.status == "completed" and task.outcome == "success" and task.error is None
    assert task.plan == PLAN and task.critique == CRITIQUE and task.report["summary"] == "done"
    assert task.finished_at is not None and task.tokens_in == 22 and task.tokens_out == 5

    steps = await steps_of(session, task.id)
    assert [s.kind for s in steps] == ["plan", "turn", "tool_call", "turn", "critique", "report"]
    assert [s.seq for s in steps] == [1, 2, 3, 4, 5, 6]
    assert steps[1].payload == {"text": "Let me look.", "tool_calls": [{"name": "list_x", "args": {"q": 1}}]}
    assert steps[2].payload["tool"] == "list_x" and steps[2].payload["server"] == "srv" and steps[2].payload["ok"] is True
    assert json.loads(steps[2].payload["result"]) == {"items": [1, 2, 3]}
    assert steps[0].prompt[0]["role"] == "system" and "Inspect x" in steps[0].prompt[0]["content"] and "Be terse" in steps[0].prompt[0]["content"]
    assert steps[2].prompt is None and steps[4].prompt is not None and steps[5].prompt is not None
    # the loop turns received the tools; plan, critique and report did not
    assert llm.calls[0]["tools"] is None and llm.calls[1]["tools"] and llm.calls[3]["tools"] is None
    # the second loop turn saw the tool result in its history
    assert any(m.get("role") == "tool" and "items" in m["content"] for m in llm.calls[2]["messages"])
    assert "sk" not in json.dumps([c["messages"] for c in llm.calls])


async def test_max_steps_stops_the_loop_and_is_reported_to_the_critique(setup_db, session):
    task = await setup(session, max_steps=2)
    always_tool = LlmResult("more", [{"name": "list_x", "args": {}}])
    llm = scripted(J(PLAN), always_tool, always_tool, J({"criteria": [{"id": "c1", "met": True, "confidence": 0.9, "justification": ""},
                                                                        {"id": "c2", "met": False, "confidence": 0.9, "justification": ""}]}), J(REPORT))
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=fake_tool, tool_defs=fake_tool_defs, session_factory=factory)
    await session.refresh(task)
    assert task.status == "completed" and task.outcome == "partial"
    assert task.critique["limit_hit"] == "max_steps"
    assert "max_steps" in json.dumps(llm.calls[3]["messages"])
    kinds = [s.kind for s in await steps_of(session, task.id)]
    assert kinds.count("turn") == 2 and kinds.count("tool_call") == 2


async def test_timeout_stops_the_loop(setup_db, session):
    task = await setup(session, timeout=10)
    now = [0.0]

    async def slow_tool(name, args, server):
        now[0] = 100.0                                 # the first tool call eats the whole budget
        return "{}"
    llm = scripted(J(PLAN), LlmResult("more", [{"name": "list_x", "args": {}}]), J(CRITIQUE), J(REPORT))
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=slow_tool, tool_defs=fake_tool_defs, session_factory=factory, clock=lambda: now[0])
    await session.refresh(task)
    assert task.status == "completed" and task.critique["limit_hit"] == "timeout"
    kinds = [s.kind for s in await steps_of(session, task.id)]
    assert kinds.count("turn") == 1 and len(llm.calls) == 4


async def test_cancel_between_rounds(setup_db, session):
    task = await setup(session)

    async def tool_then_cancel(name, args, server):
        await AgentTaskService.request_cancel(session, await session.get(AgentTask, task.id))
        return "{}"
    llm = scripted(J(PLAN), LlmResult("go", [{"name": "list_x", "args": {}}]), LlmResult("never", []))
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=tool_then_cancel, tool_defs=fake_tool_defs, session_factory=factory)
    await session.refresh(task)
    assert task.status == "cancelled" and task.outcome is None and len(llm.calls) == 2


async def test_invalid_plan_twice_fails_with_phase(setup_db, session):
    task = await setup(session)
    llm = scripted(LlmResult("not json", []), LlmResult("still not", []))
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=fake_tool, tool_defs=fake_tool_defs, session_factory=factory)
    await session.refresh(task)
    assert task.status == "failed" and "plan" in task.error
    steps = await steps_of(session, task.id)
    assert steps[-1].kind == "error" and steps[-1].payload["phase"] == "plan"
    assert "not json" not in json.dumps(llm.calls[0]["messages"]) and "Invalid JSON" in json.dumps(llm.calls[1]["messages"])


async def test_tool_failure_is_recorded_and_loop_continues(setup_db, session):
    task = await setup(session)

    async def failing_tool(name, args, server):
        return json.dumps({"error": "boom"})
    llm = scripted(J(PLAN), LlmResult("try", [{"name": "list_x", "args": {}}]), LlmResult("ok", []), J(CRITIQUE), J(REPORT))
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=failing_tool, tool_defs=fake_tool_defs, session_factory=factory)
    await session.refresh(task)
    steps = await steps_of(session, task.id)
    tool_step = next(s for s in steps if s.kind == "tool_call")
    assert tool_step.payload["ok"] is False and task.status == "completed"


async def test_unknown_tool_and_disabled_server(setup_db, session):
    task = await setup(session, server_enabled=False)
    llm = scripted(J(PLAN), LlmResult("try", [{"name": "list_x", "args": {}}]), LlmResult("ok", []), J(CRITIQUE), J(REPORT))
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=fake_tool, tool_defs=fake_tool_defs, session_factory=factory)
    assert llm.calls[1]["tools"] == []                          # disabled server contributes nothing
    steps = await steps_of(session, task.id)
    tool_step = next(s for s in steps if s.kind == "tool_call")
    assert tool_step.payload["ok"] is False and "Unknown tool" in tool_step.payload["result"]


async def test_missing_api_key_fails_before_any_call(setup_db, session):
    task = await setup(session, with_key=False)
    llm = scripted()
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    await run_task(task.id, llm=llm, tool=fake_tool, tool_defs=fake_tool_defs, session_factory=factory)
    await session.refresh(task)
    assert task.status == "failed" and "LLM not configured" in task.error and llm.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_agent_runner.py -q -p no:cacheprovider`
Expected: FAIL at import (`No module named 'app.services.agent_runner'`).

- [ ] **Step 3: Create the runner**

```python
"""Execute one agent task: plan -> tool loop -> self-critique -> report.

Pure orchestration: the LLM, the tool executor, tool discovery, the session
factory and the clock are injected so the whole loop is testable without a
provider or an MCP server. Every persistent write goes through
AgentTaskService."""
import asyncio
import json
import re
import time
import uuid
from enum import Enum

import structlog
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Agent, AgentTask, Config
from app.services.agent_task_service import AgentTaskService
from app.services.llm_runtime import LlmResult, build_tool_defs, call_llm, call_mcp_tool
from app.utils.crypto import decrypt_value

log = structlog.get_logger()

CONFIDENCE_THRESHOLD = 0.5


class LimitHit(str, Enum):
    MAX_STEPS = "max_steps"
    TIMEOUT = "timeout"


class RunFailed(Exception):
    def __init__(self, phase: str, message: str):
        super().__init__(message)
        self.phase = phase
        self.message = message


class Cancelled(Exception):
    pass


SYSTEM_PROMPT = """You are an autonomous agent running inside MCP Tour De Control.

Objective of this task:
{objective}

Operator instructions (follow them exactly):
{instructions}

You work in phases. In the planning phase you answer with JSON only. In the execution phase you call the available tools to make progress and stop calling tools when the objective is reached or cannot be reached. In the critique and report phases you answer with JSON only, honestly, using only facts visible in this conversation."""

PLAN_PROMPT = """Produce the plan for this task as a single JSON object and nothing else:
{{"steps": [{{"title": "...", "tools": ["tool_name"]}}], "success_criteria": [{{"id": "c1", "description": "..."}}], "risks": ["..."]}}
Available tools: {tool_names}
Rules: at least one step, at least one success criterion with a unique id, tools only from the available list."""

EXECUTE_PROMPT = "Execute the plan now. Call tools as needed. When the objective is reached or you cannot progress further, answer with a short plain-text summary and no tool call."

CRITIQUE_PROMPT = """Evaluate the work above against the success criteria. {limit_note}Answer with a single JSON object and nothing else:
{{"criteria": [{{"id": "c1", "met": true, "confidence": 0.0, "justification": "..."}}]}}
Include every criterion id from the plan: {criteria_ids}. confidence is a number from 0 to 1."""

REPORT_PROMPT = """Write the final report as a single JSON object and nothing else:
{{"summary": "...", "actions": [{{"step_seq": 0, "description": "..."}}], "evidence": ["..."], "uncertainties": ["..."], "next_steps": ["..."]}}
step_seq refers to the numbered steps of this task: {step_index}."""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in a model answer, tolerating ``` fences and prose around it."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    match = _JSON_OBJECT.search(cleaned)
    if not match:
        raise ValueError("no JSON object found")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def derive_outcome(criteria: list[dict]) -> str:
    met = [bool(c.get("met")) and float(c.get("confidence") or 0) >= CONFIDENCE_THRESHOLD for c in criteria]
    if met and all(met):
        return "success"
    if any(met):
        return "partial"
    return "failed"


def _validate_plan(plan: dict) -> dict:
    steps, criteria = plan.get("steps"), plan.get("success_criteria")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("success_criteria must be a non-empty list")
    ids = [str(c.get("id")) for c in criteria]
    if len(set(ids)) != len(ids) or any(i in ("", "None") for i in ids):
        raise ValueError("success_criteria ids must be unique and non-empty")
    plan.setdefault("risks", [])
    return plan


def _validate_critique(critique: dict, expected_ids: list[str]) -> dict:
    criteria = critique.get("criteria")
    if not isinstance(criteria, list):
        raise ValueError("criteria must be a list")
    got = {str(c.get("id")) for c in criteria}
    if not set(expected_ids).issubset(got):
        raise ValueError(f"missing criteria: {sorted(set(expected_ids) - got)}")
    for c in criteria:
        c["met"] = bool(c.get("met"))
        c["confidence"] = max(0.0, min(1.0, float(c.get("confidence") or 0)))
        c["justification"] = str(c.get("justification") or "")
    return critique


def _validate_report(report: dict) -> dict:
    if not isinstance(report.get("summary"), str) or not report["summary"].strip():
        raise ValueError("summary must be a non-empty string")
    for key in ("actions", "evidence", "uncertainties", "next_steps"):
        if not isinstance(report.get(key), list):
            report[key] = []
    return report


class _Run:
    def __init__(self, task_id, llm, tool, tool_defs, session_factory, clock):
        self.task_id, self.llm, self.tool, self.tool_defs, self.sf, self.clock = task_id, llm, tool, tool_defs, session_factory, clock
        self.messages: list[dict] = []
        self.tools: list[dict] = []
        self.server_map = {}
        self.limit_hit: LimitHit | None = None

    async def _task(self, session) -> AgentTask:
        return await session.get(AgentTask, self.task_id)

    async def _llm_json(self, phase: str, messages: list[dict], validate, *, tools=None) -> tuple[dict, LlmResult, list[dict]]:
        """One JSON-returning call with a single retry that quotes the parse error."""
        attempt_messages = list(messages)
        last_error = ""
        for attempt in range(2):
            started = self.clock()
            result = await self.llm(self.provider, self.model, self.api_key, attempt_messages, tools)
            try:
                data = validate(parse_json_object(result.text))
                return data, result, attempt_messages
            except (ValueError, json.JSONDecodeError, TypeError) as exc:
                last_error = str(exc)
                attempt_messages = attempt_messages + [
                    {"role": "assistant", "content": result.text},
                    {"role": "user", "content": f"Invalid JSON: {last_error}. Answer again with the JSON object only."},
                ]
        raise RunFailed(phase, f"{phase} phase returned invalid JSON twice: {last_error}")

    async def _check_cancel_and_deadline(self, session):
        if await AgentTaskService.is_cancel_requested(session, self.task_id):
            raise Cancelled()
        if self.clock() > self.deadline:
            self.limit_hit = LimitHit.TIMEOUT
            return False
        return True

    async def run(self):
        async with self.sf() as session:
            task = await self._task(session)
            agent = await session.get(Agent, task.agent_id)
            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            if not config or not config.api_key:
                raise RunFailed("claim", "LLM not configured. Set API key in Config.")
            self.provider, self.model, self.api_key = config.llm_provider, config.llm_model, decrypt_value(config.api_key)
            servers = [s for s in agent.mcp_servers if s.enabled]
            self.tools, self.server_map = await self.tool_defs(servers)
            self.started = self.clock()
            self.deadline = self.started + task.timeout_seconds
            self.messages = [{"role": "system", "content": SYSTEM_PROMPT.format(objective=task.objective, instructions=task.instructions or "(none)")}]

            # Phase 1: plan
            plan_messages = self.messages + [{"role": "user", "content": PLAN_PROMPT.format(tool_names=", ".join(sorted(self.server_map)) or "(none)")}]
            plan, result, used = await self._llm_json("plan", plan_messages, _validate_plan)
            await AgentTaskService.record_step(session, task, "plan", plan, prompt=used, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                                               duration_ms=int((self.clock() - self.started) * 1000))
            task.plan = plan
            await session.commit()

            # Phase 2: tool loop
            self.messages.append({"role": "user", "content": EXECUTE_PROMPT + "\nPlan:\n" + json.dumps(plan)})
            rounds = 0
            while True:
                if rounds >= task.max_steps:
                    self.limit_hit = LimitHit.MAX_STEPS
                    break
                await AgentTaskService.heartbeat(session, task.id)
                if not await self._check_cancel_and_deadline(session):
                    break
                rounds += 1
                t0 = self.clock()
                prompt_snapshot = json.loads(json.dumps(self.messages))
                result = await self.llm(self.provider, self.model, self.api_key, self.messages, self.tools)
                await AgentTaskService.record_step(session, task, "turn", {"text": result.text or None, "tool_calls": result.tool_calls},
                                                   prompt=prompt_snapshot, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                                                   duration_ms=int((self.clock() - t0) * 1000))
                if not result.tool_calls:
                    if result.text:
                        self.messages.append({"role": "assistant", "content": result.text})
                    break
                turn_seq = task.step_count  # seq of the turn step just written; ids must match between the two messages
                self.messages.append({"role": "assistant", "content": result.text or None, "tool_calls": [
                    {"id": f"call_{turn_seq}_{i}", "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                    for i, tc in enumerate(result.tool_calls)]})
                for i, tc in enumerate(result.tool_calls):
                    server = self.server_map.get(tc["name"])
                    t1 = self.clock()
                    if server is None:
                        text, ok = json.dumps({"error": f"Unknown tool: {tc['name']}"}), False
                    else:
                        text = await self.tool(tc["name"], tc["args"], server)
                        ok = not _looks_like_error(text)
                    await AgentTaskService.record_step(session, task, "tool_call",
                                                       {"tool": tc["name"], "server": server.name if server else None, "args": tc["args"], "result": text, "ok": ok},
                                                       duration_ms=int((self.clock() - t1) * 1000))
                    self.messages.append({"role": "tool", "tool_call_id": f"call_{turn_seq}_{i}", "content": text})

            # Phases 3-4 run even after a limit, within a fixed grace.
            await self._finalize(session, task, plan)

    async def _finalize(self, session, task, plan):
        grace_deadline = max(self.deadline, self.clock()) + settings.AGENT_TASK_FINAL_GRACE_SECONDS
        if await AgentTaskService.is_cancel_requested(session, self.task_id):
            raise Cancelled()
        limit_note = f"The execution stopped because the limit '{self.limit_hit.value}' was reached. " if self.limit_hit else ""
        ids = [str(c["id"]) for c in plan["success_criteria"]]
        critique_messages = self.messages + [{"role": "user", "content": CRITIQUE_PROMPT.format(limit_note=limit_note, criteria_ids=", ".join(ids))}]
        critique, result, used = await asyncio.wait_for(
            self._llm_json("critique", critique_messages, lambda c: _validate_critique(c, ids)),
            timeout=max(1.0, grace_deadline - self.clock()))
        critique["limit_hit"] = self.limit_hit.value if self.limit_hit else None
        await AgentTaskService.record_step(session, task, "critique", critique, prompt=used, tokens_in=result.tokens_in, tokens_out=result.tokens_out)
        task.critique = critique
        await session.commit()

        await session.refresh(task, ["steps"])
        step_index = "; ".join(f"{s.seq}: {s.kind}" + (f" {s.payload.get('tool')}" if s.kind == "tool_call" else "") for s in task.steps)
        report_messages = self.messages + [{"role": "user", "content": REPORT_PROMPT.format(step_index=step_index or "(none)")}]
        report, result, used = await asyncio.wait_for(
            self._llm_json("report", report_messages, _validate_report),
            timeout=max(1.0, grace_deadline - self.clock()))
        await AgentTaskService.record_step(session, task, "report", report, prompt=used, tokens_in=result.tokens_in, tokens_out=result.tokens_out)
        task.report = report
        await AgentTaskService.finish(session, task, "completed", outcome=derive_outcome(critique["criteria"]))


def _looks_like_error(text: str) -> bool:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and set(data.keys()) == {"error"}


async def run_task(task_id: uuid.UUID, *, llm=call_llm, tool=call_mcp_tool, tool_defs=build_tool_defs,
                   session_factory=async_session, clock=time.monotonic) -> None:
    run = _Run(task_id, llm, tool, tool_defs, session_factory, clock)
    try:
        await run.run()
    except Cancelled:
        async with session_factory() as session:
            await AgentTaskService.finish(session, await session.get(AgentTask, task_id), "cancelled")
    except RunFailed as exc:
        async with session_factory() as session:
            task = await session.get(AgentTask, task_id)
            await AgentTaskService.record_step(session, task, "error", {"message": exc.message, "phase": exc.phase})
            await AgentTaskService.finish(session, task, "failed", error=f"{exc.phase}: {exc.message}")
    except asyncio.TimeoutError:
        async with session_factory() as session:
            task = await session.get(AgentTask, task_id)
            await AgentTaskService.record_step(session, task, "error", {"message": "final phases exceeded the grace period", "phase": "report"})
            await AgentTaskService.finish(session, task, "failed", error="report: final phases exceeded the grace period")
    except Exception as exc:  # noqa: BLE001 - the worker must never die on one task
        log.exception("agent_task_crashed", task_id=str(task_id))
        async with session_factory() as session:
            task = await session.get(AgentTask, task_id)
            if task and task.status == "running":
                await AgentTaskService.record_step(session, task, "error", {"message": str(exc), "phase": "loop"})
                await AgentTaskService.finish(session, task, "failed", error=f"loop: {exc}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_agent_runner.py -q -p no:cacheprovider`
Expected: 13 passed (2 parametrized groups + 9 async tests). Then re-run `tests/test_agent_task_service.py` to be sure nothing regressed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_runner.py backend/tests/test_agent_runner.py
git commit -m "feat(agents): add the task runner with plan, tool loop, critique and report

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The worker process and its compose service

**Files:**
- Create: `backend/app/worker.py`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Produces:
  ```python
  class Worker:
      def __init__(self, *, concurrency: int, run=run_task, session_factory=async_session, worker_id: str | None = None)
      async def process_available(self) -> int        # claims up to free slots, schedules run(), returns number started
      async def sweep(self) -> int
      async def run_forever(self) -> None             # LISTEN agent_task_queued + 5 s poll + minute sweep
  ```
  `python -m app.worker` calls `asyncio.run(Worker(concurrency=settings.AGENT_WORKER_CONCURRENCY).run_forever())`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_worker.py`:

```python
import asyncio
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, McpServer
from app.services.agent_task_service import AgentTaskService
from app.worker import Worker


async def _agent(session, name):
    agent = Agent(name=name, objective="o", status="active",
                  mcp_servers=[McpServer(name=f"s-{name}", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_process_available_respects_concurrency_and_runs_tasks(setup_db, session):
    a, b, c = [await _agent(session, n) for n in "abc"]
    for agent in (a, b, c):
        await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    ran: list = []
    gate = asyncio.Event()

    async def fake_run(task_id, **_):
        ran.append(task_id)
        await gate.wait()
        async with factory() as s:
            await AgentTaskService.finish(s, await s.get(AgentTask, task_id), "completed", outcome="success")

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=2, run=fake_run, session_factory=factory, worker_id="w-test")

    assert await worker.process_available() == 2          # two slots, two tasks started
    assert await worker.process_available() == 0          # slots full
    gate.set()
    await asyncio.sleep(0.2)
    assert await worker.process_available() == 1          # third task once a slot frees up
    await asyncio.sleep(0.2)
    assert len(ran) == 3
    await worker.close()


async def test_sweep_delegates_to_service(setup_db, session):
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=1, session_factory=factory)
    assert await worker.sweep() == 0
    await worker.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_worker.py -q -p no:cacheprovider`
Expected: FAIL at import (`No module named 'app.worker'`).

- [ ] **Step 3: Create `app/worker.py`**

```python
"""Agent task worker: claims queued tasks from Postgres and runs them.

Run with `python -m app.worker`. Shares the backend image and settings."""
import asyncio
import os
import socket

import structlog

from app.config import settings
from app.database import async_session, engine
from app.services.agent_runner import run_task
from app.services.agent_task_service import QUEUED_CHANNEL, AgentTaskService

log = structlog.get_logger()

POLL_SECONDS = 5
SWEEP_SECONDS = 60


class Worker:
    def __init__(self, *, concurrency: int, run=run_task, session_factory=async_session, worker_id: str | None = None):
        self.concurrency = concurrency
        self.run = run
        self.sf = session_factory
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._running: dict = {}          # task_id -> asyncio.Task
        self._wake = asyncio.Event()

    def _free_slots(self) -> int:
        self._running = {tid: t for tid, t in self._running.items() if not t.done()}
        return max(0, self.concurrency - len(self._running))

    async def process_available(self) -> int:
        started = 0
        while self._free_slots() > 0:
            async with self.sf() as session:
                task = await AgentTaskService.claim(session, self.worker_id)
            if task is None:
                break
            log.info("agent_task_claimed", task_id=str(task.id), worker_id=self.worker_id)
            self._running[task.id] = asyncio.create_task(self._run_with_heartbeat(task.id))
            started += 1
        return started

    async def _run_with_heartbeat(self, task_id):
        async def beat():
            while True:
                await asyncio.sleep(settings.AGENT_TASK_HEARTBEAT_SECONDS)
                async with self.sf() as session:
                    await AgentTaskService.heartbeat(session, task_id)
        beater = asyncio.create_task(beat())
        try:
            await self.run(task_id, session_factory=self.sf)
        finally:
            beater.cancel()
            self._wake.set()

    async def sweep(self) -> int:
        async with self.sf() as session:
            return await AgentTaskService.sweep_stale(session, settings.AGENT_TASK_STALE_SECONDS)

    async def close(self):
        for t in self._running.values():
            t.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)

    async def run_forever(self):
        log.info("agent_worker_started", worker_id=self.worker_id, concurrency=self.concurrency)
        await self.sweep()
        async with engine.connect() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.add_listener(QUEUED_CHANNEL, lambda *_: self._wake.set())
            last_sweep = asyncio.get_event_loop().time()
            while True:
                await self.process_available()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                self._wake.clear()
                if asyncio.get_event_loop().time() - last_sweep > SWEEP_SECONDS:
                    await self.sweep()
                    last_sweep = asyncio.get_event_loop().time()


if __name__ == "__main__":
    structlog.configure(processors=[structlog.stdlib.add_log_level, structlog.dev.ConsoleRenderer()])
    asyncio.run(Worker(concurrency=settings.AGENT_WORKER_CONCURRENCY).run_forever())
```

`run_task(task_id, session_factory=...)` already accepts the keyword (Task 4), and the fake in the test accepts `**_`.

- [ ] **Step 4: Add the compose service**

In `docker-compose.yml`, after the `backend` service:

```yaml
  worker:
    build: ./backend
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      backend:
        condition: service_started
    environment:
      DATABASE_URL: postgresql+asyncpg://mcp:mcp_secret@postgres:5432/mcp_control
      ENCRYPTION_KEY: ${ENCRYPTION_KEY:-B2d8zbySL4aG5LeprF4bM9x1qn0FB7t7V66_AHKXHGQ=}
      AGENT_WORKER_CONCURRENCY: ${AGENT_WORKER_CONCURRENCY:-2}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    # The backend runs the migrations; the worker only needs the schema to exist.
    command: python -m app.worker
```

- [ ] **Step 5: Run the tests and a local smoke of the entrypoint**

Run: `venv/bin/python -m pytest tests/test_worker.py -q -p no:cacheprovider` → 2 passed.
Then from `backend/`: `PYTHONPATH=. timeout 8 venv/bin/python -m app.worker; echo "exit $?"` (macOS has no `timeout`: run it in the background, `sleep 8`, then `kill %1`). Expected log line `agent_worker_started`, no traceback; a non-zero exit from the kill is fine.

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker.py backend/tests/test_worker.py docker-compose.yml
git commit -m "feat(agents): add the task worker process and its compose service

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `AgentService` — lifecycle out of the router, cron sync, task summaries

**Files:**
- Create: `backend/app/services/agent_service.py`
- Modify: `backend/app/services/scheduler_service.py`
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/routers/agents.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_agent_service.py`, `backend/tests/test_api_agents.py` (append)

**Interfaces:**
- Produces:
  ```python
  class AgentStateError(Exception): status_code: int; detail: str
  ALLOWED_TRANSITIONS  # moved here unchanged
  class AgentService:
      @staticmethod async def change_status(session, agent, target: str) -> Agent        # raises AgentStateError(409/400); syncs the cron job
      @staticmethod async def apply_update(session, agent, data: AgentUpdate, servers_loader) -> Agent  # syncs cron on active agents
      @staticmethod def sync_cron_job(agent) -> None
      @staticmethod async def task_summaries(session, agent_ids) -> dict[uuid.UUID, dict]  # {"running_task_id", "last_task"}
      @staticmethod async def enqueue_from_cron(agent_id: uuid.UUID) -> None
  # scheduler_service:
  def add_agent_job(self, agent_id, cron_expr); def remove_agent_job(self, agent_id); def reschedule_agent_job(self, agent_id, cron_expr)
  async def _execute_agent_cron(agent_id: str)
  ```
  `AgentRead` gains `cron_expr: str | None`, `running_task_id: uuid.UUID | None`, `last_task: AgentTaskSummary | None`; `AgentCreate`/`AgentUpdate` gain `cron_expr` validated with `CronTrigger.from_crontab`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_service.py`:

```python
import os
from unittest.mock import patch

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest

from app.models import Agent, AgentTask, McpServer
from app.schemas.agent import AgentUpdate
from app.services import agent_service
from app.services.agent_service import AgentService, AgentStateError
from app.services.agent_task_service import AgentTaskService
from app.services.scheduler_service import SchedulerService, _execute_agent_cron


async def _agent(session, *, status="draft", cron=None, enabled=True):
    agent = Agent(name="a", objective="o", status=status, cron_expr=cron,
                  mcp_servers=[McpServer(name="s", transport="http", url="http://x", enabled=enabled)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_activation_adds_cron_job_and_pause_removes_it(session):
    agent = await _agent(session, cron="0 8 * * *")
    service = SchedulerService(use_db_jobstore=False)
    service.start()
    with patch.object(agent_service, "scheduler_service", service):
        await AgentService.change_status(session, agent, "active")
        assert service.scheduler.get_job(f"agent_{agent.id}") is not None
        await AgentService.change_status(session, agent, "paused")
        assert service.scheduler.get_job(f"agent_{agent.id}") is None
    service.shutdown()


async def test_update_cron_on_active_agent_reschedules(session):
    agent = await _agent(session, status="active", cron="0 8 * * *")
    service = SchedulerService(use_db_jobstore=False)
    service.start()
    with patch.object(agent_service, "scheduler_service", service):
        async def loader(ids):
            return []
        await AgentService.apply_update(session, agent, AgentUpdate(cron_expr="0 9 * * *"), loader)
        job = service.scheduler.get_job(f"agent_{agent.id}")
        assert job is not None and "hour='9'" in str(job.trigger)
        await AgentService.apply_update(session, agent, AgentUpdate(cron_expr=None, name="renamed"), loader)
        assert service.scheduler.get_job(f"agent_{agent.id}") is None  # cron removed when cleared
    service.shutdown()


async def test_change_status_errors_are_typed(session):
    agent = await _agent(session, enabled=False)
    with pytest.raises(AgentStateError) as exc:
        await AgentService.change_status(session, agent, "active")
    assert exc.value.status_code == 400
    with pytest.raises(AgentStateError) as exc:
        await AgentService.change_status(session, agent, "paused")
    assert exc.value.status_code == 409


async def test_task_summaries(session):
    agent = await _agent(session, status="active")
    other = await _agent(session, status="active")
    done = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    await AgentTaskService.finish(session, done, "completed", outcome="partial")
    running = await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    running = await AgentTaskService.claim(session, "w")
    summaries = await AgentService.task_summaries(session, [agent.id, other.id])
    assert summaries[agent.id]["running_task_id"] == running.id
    assert summaries[agent.id]["last_task"]["id"] == running.id and summaries[agent.id]["last_task"]["status"] == "running"
    assert summaries[other.id] == {"running_task_id": None, "last_task": None}


async def test_cron_tick_enqueues_once(setup_db, session):
    agent = await _agent(session, status="active", cron="* * * * *")
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    with patch("app.services.agent_service.async_session", factory):
        await _execute_agent_cron(str(agent.id))
        await _execute_agent_cron(str(agent.id))      # second tick skips: one is already queued
    from sqlalchemy import select, func
    count = (await session.execute(select(func.count()).select_from(AgentTask).where(AgentTask.agent_id == agent.id))).scalar_one()
    assert count == 1
    assert (await session.execute(select(AgentTask.trigger).where(AgentTask.agent_id == agent.id))).scalar_one() == "cron"
```

Append to `backend/tests/test_api_agents.py`:

```python
# ---- cron and task summary fields -----------------------------------------

async def test_create_with_invalid_cron_is_422_and_valid_cron_round_trips():
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={"name": "x", "objective": "y", "mcp_server_ids": [], "cron_expr": "not a cron"})
        assert resp.status_code == 422
        data = await create_agent(c, cron_expr="0 8 * * *")
        assert data["cron_expr"] == "0 8 * * *"
        assert data["running_task_id"] is None and data["last_task"] is None
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"cron_expr": None})
        assert resp.status_code == 200 and resp.json()["cron_expr"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_agent_service.py tests/test_api_agents.py -q -p no:cacheprovider -k "cron or summaries or typed"`
Expected: FAIL at import (`No module named 'app.services.agent_service'`) and 422 on the unknown `cron_expr` field.

- [ ] **Step 3: Scheduler methods for agents**

In `backend/app/services/scheduler_service.py`, add after `_execute_sim_pair_calls`:

```python
async def _execute_agent_cron(agent_id: str):
    """Cron tick for one agent: enqueue a task (the worker runs it)."""
    from app.services.agent_service import AgentService
    try:
        await AgentService.enqueue_from_cron(uuid.UUID(agent_id))
    except Exception as exc:
        log.error("Agent cron tick failed", agent_id=agent_id, error=str(exc))
```

and inside `SchedulerService`, after `reschedule_job`:

```python
    # ---- per-agent cron jobs (enqueue only; the worker executes) ----
    def add_agent_job(self, agent_id: uuid.UUID, cron_expr: str):
        job_id = f"agent_{agent_id}"
        self.scheduler.add_job(_execute_agent_cron, trigger=CronTrigger.from_crontab(cron_expr),
                               id=job_id, args=[str(agent_id)], replace_existing=True)
        log.info("Agent job added", job_id=job_id, cron=cron_expr)

    def remove_agent_job(self, agent_id: uuid.UUID):
        try:
            self.scheduler.remove_job(f"agent_{agent_id}")
        except Exception:
            log.debug("Agent job not found for removal", agent_id=str(agent_id))

    def reschedule_agent_job(self, agent_id: uuid.UUID, cron_expr: str):
        try:
            self.scheduler.reschedule_job(f"agent_{agent_id}", trigger=CronTrigger.from_crontab(cron_expr))
        except Exception:
            self.add_agent_job(agent_id, cron_expr)
```

(`uuid` is already imported there; check and add `import uuid` if not.)

- [ ] **Step 4: Schemas**

In `backend/app/schemas/agent.py`:

```python
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator


def _validate_cron(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    try:
        CronTrigger.from_crontab(value)
    except ValueError as exc:
        raise ValueError(f"invalid cron expression: {exc}") from exc
    return value.strip()


class AgentTaskSummary(BaseModel):
    id: uuid.UUID
    status: str
    outcome: str | None
    finished_at: datetime | None
```

Add to `AgentCreate` and `AgentUpdate`: `cron_expr: str | None = None` plus

```python
    @field_validator("cron_expr")
    @classmethod
    def _cron(cls, v):
        return _validate_cron(v)
```

Add to `AgentRead`: `cron_expr: str | None`, `running_task_id: uuid.UUID | None = None`, `last_task: AgentTaskSummary | None = None`. Export `AgentTaskSummary` from `schemas/__init__.py`.

`AgentUpdate` must distinguish "not provided" from "clear": keep `cron_expr: str | None = None` and in the service use `"cron_expr" in data.model_fields_set` to detect an explicit `null`.

- [ ] **Step 5: Create `app/services/agent_service.py`**

```python
"""Agent lifecycle (status transitions, cron synchronisation) and read helpers."""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Agent, AgentTask
from app.schemas.agent import AgentUpdate
from app.services.agent_task_service import AgentTaskService, TaskConflict
from app.services.scheduler_service import scheduler_service

log = structlog.get_logger()

# from -> allowed targets. `archived` is terminal except for restore to draft.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": {"draft"},
}


class AgentStateError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AgentService:

    @staticmethod
    def sync_cron_job(agent: Agent) -> None:
        if agent.status == "active" and agent.cron_expr:
            scheduler_service.reschedule_agent_job(agent.id, agent.cron_expr)
        else:
            scheduler_service.remove_agent_job(agent.id)

    @staticmethod
    async def change_status(session: AsyncSession, agent: Agent, target: str) -> Agent:
        if target not in ALLOWED_TRANSITIONS[agent.status]:
            raise AgentStateError(409, f"Cannot move agent from {agent.status} to {target}")
        if target == "active" and not any(s.enabled for s in agent.mcp_servers):
            raise AgentStateError(400, "Agent needs at least one enabled MCP server to be activated")
        previous = agent.status
        agent.status = target
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(agent)
        AgentService.sync_cron_job(agent)
        log.info("agent_status_changed", agent_id=str(agent.id), previous=previous, status=target)
        return agent

    @staticmethod
    async def apply_update(session: AsyncSession, agent: Agent, data: AgentUpdate, servers_loader) -> Agent:
        if agent.status == "archived":
            raise AgentStateError(409, "Agent is archived; restore it before editing")
        for field in ("name", "objective", "instructions", "description", "max_steps", "timeout_seconds"):
            value = getattr(data, field)
            if value is not None:
                setattr(agent, field, value)
        if "cron_expr" in data.model_fields_set:
            agent.cron_expr = data.cron_expr
        if data.mcp_server_ids is not None:
            agent.mcp_servers = await servers_loader(data.mcp_server_ids)
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(agent)
        if "cron_expr" in data.model_fields_set:
            AgentService.sync_cron_job(agent)
        log.info("agent_updated", agent_id=str(agent.id), fields=sorted(data.model_fields_set))
        return agent

    @staticmethod
    async def task_summaries(session: AsyncSession, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        out = {aid: {"running_task_id": None, "last_task": None} for aid in agent_ids}
        if not agent_ids:
            return out
        rows = (await session.execute(
            select(AgentTask).where(AgentTask.agent_id.in_(agent_ids)).order_by(AgentTask.agent_id, AgentTask.created_at.desc())
        )).scalars().all()
        for task in rows:
            entry = out[task.agent_id]
            if entry["last_task"] is None:
                entry["last_task"] = {"id": task.id, "status": task.status, "outcome": task.outcome, "finished_at": task.finished_at}
            if task.status == "running" and entry["running_task_id"] is None:
                entry["running_task_id"] = task.id
        return out

    @staticmethod
    async def enqueue_from_cron(agent_id: uuid.UUID) -> None:
        async with async_session() as session:
            agent = await session.get(Agent, agent_id)
            if not agent or agent.status != "active":
                log.info("agent_cron_skipped", agent_id=str(agent_id), reason="not active")
                return
            try:
                await AgentTaskService.enqueue(session, agent, objective=None, trigger="cron")
            except TaskConflict as exc:
                log.info("agent_cron_skipped", agent_id=str(agent_id), reason=exc.detail)
```

- [ ] **Step 6: Thin the router and restore jobs at startup**

In `backend/app/routers/agents.py`:
- Delete `ALLOWED_TRANSITIONS`; import `from app.services.agent_service import AgentService, AgentStateError`.
- `_to_read(agent, summary=None)` passes `cron_expr=agent.cron_expr`, `running_task_id=(summary or {}).get("running_task_id")`, `last_task=(summary or {}).get("last_task")`.
- `list_agents`: after fetching, `summaries = await AgentService.task_summaries(session, [a.id for a in agents])` and `_to_read(a, summaries[a.id])`. `get_agent` does the same for one id.
- `create_agent`: pass `cron_expr=data.cron_expr` to `Agent(...)` (a draft never schedules).
- `update_agent` body becomes:
  ```python
  agent = await _get_agent(session, agent_id)
  try:
      agent = await AgentService.apply_update(session, agent, data, lambda ids: _load_servers(session, ids))
  except AgentStateError as exc:
      raise HTTPException(status_code=exc.status_code, detail=exc.detail)
  return _to_read(agent, (await AgentService.task_summaries(session, [agent.id]))[agent.id])
  ```
- `set_agent_status` body becomes the same shape around `AgentService.change_status(session, agent, data.status)`.
- `delete_agent`: call `scheduler_service.remove_agent_job(agent_id)` after the delete (import `scheduler_service`).

In `backend/app/main.py` lifespan, after the prompt jobs block:

```python
    # Restore per-agent cron jobs
    try:
        async with async_session() as session:
            from app.models import Agent
            result = await session.execute(select(Agent).where(Agent.status == "active", Agent.cron_expr.isnot(None)))
            for agent in result.scalars().all():
                scheduler_service.add_agent_job(agent.id, agent.cron_expr)
    except Exception as exc:
        log.error("Failed to restore agent cron jobs", error=str(exc))
```

- [ ] **Step 7: Run the tests**

Run: `venv/bin/python -m pytest tests/test_agent_service.py tests/test_api_agents.py tests/test_scheduler_service.py -q -p no:cacheprovider`
Expected: all passed (5 new service tests, 1 new API test, the 44 existing agent API tests, the scheduler suite).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/agent_service.py backend/app/services/scheduler_service.py backend/app/schemas/agent.py backend/app/schemas/__init__.py backend/app/routers/agents.py backend/app/main.py backend/tests/test_agent_service.py backend/tests/test_api_agents.py
git commit -m "feat(agents): move the lifecycle into agent_service and schedule agents by cron

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Task API — create, list, detail, step detail, cancel

**Files:**
- Create: `backend/app/schemas/agent_task.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/routers/agents.py` (append two endpoints)
- Create: `backend/app/routers/agent_tasks.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_api_agent_tasks.py`

**Interfaces:**
- Produces schemas `AgentTaskCreate {objective: str | None}`, `AgentTaskRead`, `AgentTaskStepRead` (no prompt), `AgentTaskStepDetail` (with prompt), `AgentTaskDetail (AgentTaskRead + steps)`; endpoints per the spec table; router `agent_tasks.router` with prefix `/api/v1/agent-tasks`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_agent_tasks.py`:

```python
import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Agent, AgentTask, Base, McpServer
from app.services.agent_task_service import AgentTaskService

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_async_session] = override
    yield factory
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def make_agent(factory, status="active") -> str:
    async with factory() as s:
        agent = Agent(name="a", objective="Inspect", instructions="r", status=status,
                      mcp_servers=[McpServer(name="s", transport="http", url="http://x", enabled=True)])
        s.add(agent)
        await s.commit()
        return str(agent.id)


async def test_create_task_201_then_409_and_404(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with client() as c:
        resp = await c.post(f"/api/v1/agents/{aid}/tasks", json={"objective": None})
        assert resp.status_code == 201, resp.text
        task = resp.json()
        assert task["status"] == "queued" and task["objective"] == "Inspect" and task["trigger"] == "manual"
        assert task["max_steps"] == 20 and task["timeout_seconds"] == 300
        resp = await c.post(f"/api/v1/agents/{aid}/tasks", json={"objective": "again"})
        assert resp.status_code == 409
        resp = await c.post(f"/api/v1/agents/{uuid.uuid4()}/tasks", json={})
        assert resp.status_code == 404
        agent = (await c.get(f"/api/v1/agents/{aid}")).json()
        assert agent["last_task"]["id"] == task["id"] and agent["running_task_id"] is None


async def test_create_task_on_draft_is_409_and_override_is_kept(setup_test_db):
    draft = await make_agent(setup_test_db, status="draft")
    active = await make_agent(setup_test_db)
    async with client() as c:
        assert (await c.post(f"/api/v1/agents/{draft}/tasks", json={})).status_code == 409
        resp = await c.post(f"/api/v1/agents/{active}/tasks", json={"objective": "  custom  "})
        assert resp.json()["objective"] == "custom"


async def test_list_detail_and_step_prompt(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        agent = await s.get(Agent, uuid.UUID(aid))
        task = await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        await AgentTaskService.record_step(s, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "secret-free"}], tokens_in=3, tokens_out=1)
        await AgentTaskService.record_step(s, task, "tool_call", {"tool": "t", "server": "s", "args": {}, "result": "{}", "ok": True})
    async with client() as c:
        listing = (await c.get(f"/api/v1/agents/{aid}/tasks")).json()
        assert len(listing) == 1 and "steps" not in listing[0]
        detail = (await c.get(f"/api/v1/agent-tasks/{task.id}")).json()
        assert [s["kind"] for s in detail["steps"]] == ["plan", "tool_call"]
        assert all("prompt" not in s for s in detail["steps"])
        assert detail["step_count"] == 2 and detail["tokens_in"] == 3
        step = (await c.get(f"/api/v1/agent-tasks/{task.id}/steps/1")).json()
        assert step["prompt"] == [{"role": "system", "content": "secret-free"}]
        assert (await c.get(f"/api/v1/agent-tasks/{task.id}/steps/9")).status_code == 404
        assert (await c.get(f"/api/v1/agent-tasks/{uuid.uuid4()}")).status_code == 404


async def test_cancel_queued_running_and_final(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with client() as c:
        task = (await c.post(f"/api/v1/agents/{aid}/tasks", json={})).json()
        resp = await c.post(f"/api/v1/agent-tasks/{task['id']}/cancel")
        assert resp.status_code == 202 and resp.json()["status"] == "cancelled"
        assert (await c.post(f"/api/v1/agent-tasks/{task['id']}/cancel")).status_code == 409

        task2 = (await c.post(f"/api/v1/agents/{aid}/tasks", json={})).json()
        async with setup_test_db() as s:
            claimed = await AgentTaskService.claim(s, "w")
            assert str(claimed.id) == task2["id"]
        resp = await c.post(f"/api/v1/agent-tasks/{task2['id']}/cancel")
        assert resp.status_code == 202 and resp.json()["status"] == "running" and resp.json()["cancel_requested"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_api_agent_tasks.py -q -p no:cacheprovider`
Expected: FAIL with 404/405 on the task routes.

- [ ] **Step 3: Schemas**

Create `backend/app/schemas/agent_task.py`:

```python
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

AgentTaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
AgentOutcome = Literal["success", "partial", "failed"]
StepKind = Literal["plan", "turn", "tool_call", "critique", "report", "error"]


class AgentTaskCreate(BaseModel):
    objective: str | None = None


class AgentTaskRead(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    trigger: Literal["manual", "cron"]
    objective: str
    instructions: str
    max_steps: int
    timeout_seconds: int
    status: AgentTaskStatus
    outcome: AgentOutcome | None
    plan: dict[str, Any] | None
    critique: dict[str, Any] | None
    report: dict[str, Any] | None
    error: str | None
    cancel_requested: bool
    step_count: int
    tokens_in: int
    tokens_out: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class AgentTaskStepRead(BaseModel):
    seq: int
    kind: StepKind
    payload: dict[str, Any]
    tokens_in: int | None
    tokens_out: int | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentTaskStepDetail(AgentTaskStepRead):
    prompt: list[dict[str, Any]] | None


class AgentTaskDetail(AgentTaskRead):
    steps: list[AgentTaskStepRead]
```

Export all six names from `schemas/__init__.py`.

- [ ] **Step 4: Endpoints**

Append to `backend/app/routers/agents.py` (imports: `AgentTaskCreate`, `AgentTaskRead`, `AgentTaskService`, `TaskConflict`, `AgentTask`):

```python
@router.post("/{agent_id}/tasks", response_model=AgentTaskRead, status_code=201)
async def create_task(agent_id: uuid.UUID, data: AgentTaskCreate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    try:
        task = await AgentTaskService.enqueue(session, agent, objective=data.objective, trigger="manual")
    except TaskConflict as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return AgentTaskRead.model_validate(task)


@router.get("/{agent_id}/tasks", response_model=list[AgentTaskRead])
async def list_tasks(agent_id: uuid.UUID, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                     session: AsyncSession = Depends(get_async_session)):
    await _get_agent(session, agent_id)
    rows = (await session.execute(
        select(AgentTask).where(AgentTask.agent_id == agent_id).order_by(AgentTask.created_at.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return [AgentTaskRead.model_validate(t) for t in rows]
```

Create `backend/app/routers/agent_tasks.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_session
from app.models import AgentTask, AgentTaskStep
from app.schemas import AgentTaskDetail, AgentTaskRead, AgentTaskStepDetail
from app.services.agent_task_service import AgentTaskService, TaskConflict

router = APIRouter(prefix="/api/v1/agent-tasks", tags=["agent-tasks"])


async def _get_task(session: AsyncSession, task_id: uuid.UUID, *, with_steps: bool = False) -> AgentTask:
    stmt = select(AgentTask).where(AgentTask.id == task_id)
    if with_steps:
        stmt = stmt.options(selectinload(AgentTask.steps))
    task = (await session.execute(stmt)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}", response_model=AgentTaskDetail)
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return AgentTaskDetail.model_validate(await _get_task(session, task_id, with_steps=True))


@router.get("/{task_id}/steps/{seq}", response_model=AgentTaskStepDetail)
async def get_step(task_id: uuid.UUID, seq: int, session: AsyncSession = Depends(get_async_session)):
    await _get_task(session, task_id)
    step = (await session.execute(
        select(AgentTaskStep).where(AgentTaskStep.task_id == task_id, AgentTaskStep.seq == seq)
    )).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return AgentTaskStepDetail.model_validate(step)


@router.post("/{task_id}/cancel", response_model=AgentTaskRead, status_code=202)
async def cancel_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    task = await _get_task(session, task_id)
    try:
        await AgentTaskService.request_cancel(session, task)
    except TaskConflict as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    await session.refresh(task)
    return AgentTaskRead.model_validate(task)
```

In `backend/app/main.py`: `from app.routers import agent_tasks as agent_tasks_router` and `app.include_router(agent_tasks_router.router)` next to the agents router.

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python -m pytest tests/test_api_agent_tasks.py tests/test_api_agents.py -q -p no:cacheprovider`
Expected: all passed (4 new + existing).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/agent_task.py backend/app/schemas/__init__.py backend/app/routers/agents.py backend/app/routers/agent_tasks.py backend/app/main.py backend/tests/test_api_agent_tasks.py
git commit -m "feat(agents): expose task creation, listing, detail, step prompts and cancel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: SSE stream of a task over LISTEN / NOTIFY

**Files:**
- Modify: `backend/app/routers/agent_tasks.py`
- Test: `backend/tests/test_api_agent_tasks.py` (append)

**Interfaces:**
- Produces `GET /api/v1/agent-tasks/{task_id}/events` → `text/event-stream` with events `step` (payload = `AgentTaskStepRead` dict), `status` (`{"status","outcome","error","finished_at"}`), `done`, `error`; keep-alive comment `: keep-alive` every 20 s.

- [ ] **Step 1: Append the failing tests**

```python
# ---- SSE -------------------------------------------------------------------

import asyncio
import json


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [l for l in block.split("\n") if l and not l.startswith(":")]
        if not lines:
            continue
        name = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


async def test_events_backlog_then_done_for_a_final_task(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        agent = await s.get(Agent, uuid.UUID(aid))
        task = await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        await AgentTaskService.record_step(s, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "p"}])
        await AgentTaskService.finish(s, task, "completed", outcome="success")
    async with client() as c:
        resp = await c.get(f"/api/v1/agent-tasks/{task.id}/events")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert [e for e, _ in events] == ["step", "status", "done"]
    assert events[0][1]["kind"] == "plan" and "prompt" not in events[0][1]
    assert events[1][1]["status"] == "completed" and events[1][1]["outcome"] == "success"


async def test_events_stream_live_steps_until_final(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        agent = await s.get(Agent, uuid.UUID(aid))
        task = await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        task = await AgentTaskService.claim(s, "w")

    async def produce():
        await asyncio.sleep(0.3)
        async with setup_test_db() as s:
            t = await s.get(AgentTask, task.id)
            await AgentTaskService.record_step(s, t, "turn", {"text": "hi", "tool_calls": []})
            await AgentTaskService.record_step(s, t, "report", {"summary": "ok"})
            await AgentTaskService.finish(s, t, "completed", outcome="partial")

    producer = asyncio.create_task(produce())
    async with client() as c:
        async with c.stream("GET", f"/api/v1/agent-tasks/{task.id}/events") as resp:
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
                if "event: done" in body:
                    break
    await producer
    events = _parse_sse(body)
    names = [e for e, _ in events]
    assert names[0] == "status" and names[-1] == "done"
    assert [d["kind"] for e, d in events if e == "step"] == ["turn", "report"]
    assert any(e == "status" and d["status"] == "completed" for e, d in events)
```

The second test uses the real `LISTEN`/`NOTIFY` path against Postgres through the ASGI transport; it must finish in well under 5 seconds.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_api_agent_tasks.py -q -p no:cacheprovider -k events`
Expected: FAIL with 404 (route missing).

- [ ] **Step 3: Implement the stream**

Append to `backend/app/routers/agent_tasks.py` (new imports: `asyncio`, `json`, `StreamingResponse`, `async_session` and `engine` from `app.database`, `sse_frame` from `app.utils.sse`, `AgentTaskStepRead`, `EVENTS_CHANNEL` from `agent_task_service`, `FINAL_STATUSES` from `app.models.agent_task`):

```python
KEEPALIVE_SECONDS = 20

# Module-level so tests can point the stream at the test database.
session_factory = async_session
db_engine = engine


def _status_payload(task: AgentTask) -> dict:
    return {"status": task.status, "outcome": task.outcome, "error": task.error,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None}


async def _steps_after(task_id: uuid.UUID, last_seq: int) -> list[AgentTaskStep]:
    async with session_factory() as session:
        return (await session.execute(
            select(AgentTaskStep).where(AgentTaskStep.task_id == task_id, AgentTaskStep.seq > last_seq).order_by(AgentTaskStep.seq)
        )).scalars().all()


async def _task_snapshot(task_id: uuid.UUID) -> AgentTask | None:
    async with session_factory() as session:
        return await session.get(AgentTask, task_id)


async def _event_stream(task_id: uuid.UUID):
    last_seq = 0
    last_status = None
    try:
        # Backlog first, so a reconnecting client never misses a step.
        for step in await _steps_after(task_id, 0):
            last_seq = step.seq
            yield sse_frame("step", AgentTaskStepRead.model_validate(step).model_dump(mode="json"))
        task = await _task_snapshot(task_id)
        last_status = task.status
        yield sse_frame("status", _status_payload(task))
        if task.status in FINAL_STATUSES:
            yield sse_frame("done", {})
            return

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_notify(_conn, _pid, _channel, payload):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return
            if data.get("task_id") == str(task_id):
                loop.call_soon_threadsafe(queue.put_nowait, data)

        async with db_engine.connect() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.add_listener(EVENTS_CHANNEL, on_notify)
            try:
                # Anything written between the backlog read and the LISTEN registration.
                queue.put_nowait({"task_id": str(task_id), "seq": None, "status": None})
                while True:
                    try:
                        await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    for step in await _steps_after(task_id, last_seq):
                        last_seq = step.seq
                        yield sse_frame("step", AgentTaskStepRead.model_validate(step).model_dump(mode="json"))
                    task = await _task_snapshot(task_id)
                    if task.status != last_status or task.status in FINAL_STATUSES:
                        last_status = task.status
                        yield sse_frame("status", _status_payload(task))
                    if task.status in FINAL_STATUSES:
                        yield sse_frame("done", {})
                        return
            finally:
                await raw.remove_listener(EVENTS_CHANNEL, on_notify)
    except Exception as exc:  # noqa: BLE001
        yield sse_frame("error", {"message": str(exc)})


@router.get("/{task_id}/events")
async def task_events(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    await _get_task(session, task_id)
    return StreamingResponse(_event_stream(task_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

asyncpg invokes listener callbacks on the event loop thread, so `call_soon_threadsafe` is merely defensive; keep it.

The stream helpers read through the module-level `session_factory` / `db_engine`, not through the request's dependency-injected session, so the tests must point them at the test database. In `backend/tests/test_api_agent_tasks.py`: add `from unittest.mock import patch` to the imports; in the `setup_test_db` fixture set `factory.engine = engine` right after creating `factory`; and in both SSE tests wrap the `async with client() as c:` block with

```python
    with patch("app.routers.agent_tasks.session_factory", setup_test_db), \
         patch("app.routers.agent_tasks.db_engine", setup_test_db.engine):
```

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_api_agent_tasks.py -q -p no:cacheprovider`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/agent_tasks.py backend/tests/test_api_agent_tasks.py
git commit -m "feat(agents): stream task steps and status over SSE backed by LISTEN/NOTIFY

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Docs, full verification, autogenerate check

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Full backend suite**

Run (from `backend/`): `venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
Expected: everything passes (previous 357 plus the new files). Report any failure instead of fixing unrelated tests.

- [ ] **Step 2: Autogenerate sees nothing new**

```bash
PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "check agent tasks"
grep -il "agent_task\|cron_expr" alembic/versions/*check_agent_tasks*.py || echo "no agent task diff"
rm alembic/versions/*check_agent_tasks*.py
```

Expected: `no agent task diff` (the usual spurious index / `apscheduler_jobs` noise is pre-existing).

- [ ] **Step 3: Document**

In `CLAUDE.md`, replace the `### Agents` paragraph with:

```markdown
### Agents

`Agent` rows (`models/agent.py`) describe autonomous agents: objective, instructions, allowed MCP servers through the `agent_mcp_server` association table (cascade both sides), `max_steps`, `timeout_seconds` and an optional `cron_expr`. Lifecycle is `draft → active ⇄ paused → archived → draft`, enforced by `ALLOWED_TRANSITIONS` in `services/agent_service.py`; activation requires at least one **enabled** authorised server, deletion is only allowed for `draft` and `archived`. The LLM model is inherited from the global `Config`.

Running an agent creates an `AgentTask` (`models/agent_task.py`) that snapshots objective, instructions and limits. The table is also the queue: `app/worker.py` (`python -m app.worker`, the `worker` compose service) claims tasks with `FOR UPDATE SKIP LOCKED` — one `running` task per agent is guaranteed by the claim SQL — heartbeats every 15 s, and a sweep marks tasks whose heartbeat is older than 90 s `failed` with `worker lost`; nothing is replayed. `services/agent_runner.py` runs *plan → tool loop → critique → report*: `max_steps` counts loop rounds only, `timeout_seconds` bounds the loop, and the two final phases get `AGENT_TASK_FINAL_GRACE_SECONDS` more. The **code** derives `outcome` (a criterion counts when `met` and confidence ≥ 0.5; all → `success`, none → `failed`, else `partial`); `status` is the run lifecycle, `outcome` the business result. Every event is an `AgentTaskStep` (`plan`, `turn`, `tool_call`, `critique`, `report`, `error`) and LLM-calling steps keep the **full prompt**; all writes go through `services/agent_task_service.py`, which `NOTIFY`s `agent_task_events`, and `GET /api/v1/agent-tasks/{id}/events` streams them over SSE via `LISTEN`. Per-agent cron jobs (`agent_{uuid}`) only enqueue; they skip when a task is already queued or running. **There is no approval step yet: every authorised tool runs immediately.** The chat and the runner share `services/llm_runtime.py` (`call_llm`, `call_mcp_tool`, `build_tool_defs`, `clean_schema`).
```

Also update the `## Commands` block: after `venv/bin/uvicorn app.main:app --reload`, add `PYTHONPATH=. venv/bin/python -m app.worker              # agent task worker (separate process)`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agents): describe task execution, the worker and the SSE stream

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
