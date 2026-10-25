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
