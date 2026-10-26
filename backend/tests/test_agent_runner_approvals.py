import json
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config, McpServer
from app.services.agent_runner import run_task
from app.services.agent_task_service import AgentTaskService
from app.services.approval_service import ApprovalService
from app.services.llm_runtime import LlmResult
from app.utils.crypto import encrypt_value

PLAN = {"steps": [{"title": "do", "tools": ["list_x", "write_x"]}],
        "success_criteria": [{"id": "c1", "description": "done"}], "risks": []}
CRITIQUE = {"criteria": [{"id": "c1", "met": True, "confidence": 0.9, "justification": "ok"}]}
REPORT = {"summary": "done", "actions": [], "evidence": [], "uncertainties": [], "next_steps": []}
LEVELS = {"list_x": 0, "write_x": 2, "purge_x": 3}


def J(obj):
    return LlmResult(json.dumps(obj), [])


def scripted(*results):
    queue = list(results)
    calls = []

    async def llm(provider, model, api_key, messages, tools):
        calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        return queue.pop(0)
    llm.calls = calls
    return llm


async def fake_tool_defs(servers):
    return ([{"type": "function", "function": {"name": n, "description": n, "parameters": {"type": "object", "properties": {}}}} for n in LEVELS],
            {n: servers[0] for n in LEVELS})


async def fake_levels(session, server_map):
    return {n: LEVELS[n] for n in server_map}


def recording_tool():
    calls = []

    async def tool(name, args, server):
        calls.append((name, args))
        return json.dumps({"ok": name})
    tool.calls = calls
    return tool


async def setup(session, *, ceiling=1):
    session.add(Config(llm_provider="openai", llm_model="m", api_key=encrypt_value("sk-live-SENTINEL")))
    agent = Agent(name="a", objective="Inspect x", instructions="Be terse", status="active", max_auto_risk=ceiling,
                  mcp_servers=[McpServer(name="srv", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    return agent, await AgentTaskService.claim(session, "w")


def factory_of(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def steps_of(session, task_id):
    return (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task_id).order_by(AgentTaskStep.seq))).scalars().all()


TWO_CALLS = LlmResult("go", [{"name": "list_x", "args": {"q": 1}}, {"name": "write_x", "args": {"v": 2}}])
DONE = LlmResult("finished", [])


async def test_tool_at_or_below_ceiling_runs_and_records_risk(setup_db, session):
    agent, task = await setup(session, ceiling=2)
    tool = recording_tool()
    llm = scripted(J(PLAN), TWO_CALLS, DONE, J(CRITIQUE), J(REPORT))
    await run_task(task.id, llm=llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory_of(setup_db))
    await session.refresh(task)
    assert task.status == "completed" and [c[0] for c in tool.calls] == ["list_x", "write_x"]
    tool_steps = [s for s in await steps_of(session, task.id) if s.kind == "tool_call"]
    assert [s.payload["risk_level"] for s in tool_steps] == [0, 2]
    assert (await session.execute(select(Approval))).scalars().all() == []


async def test_gated_tool_parks_after_executing_earlier_calls(setup_db, session):
    agent, task = await setup(session, ceiling=1)
    tool = recording_tool()
    llm = scripted(J(PLAN), TWO_CALLS)
    notified = []

    async def notify(sess, approval):
        notified.append(approval.code)
    await run_task(task.id, llm=llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels,
                   session_factory=factory_of(setup_db), notify=notify)
    await session.refresh(task)
    assert task.status == "waiting_approval" and task.finished_at is None
    assert [c[0] for c in tool.calls] == ["list_x"]                       # the R0 call ran, the R2 call did not
    kinds = [s.kind for s in await steps_of(session, task.id)]
    assert kinds == ["plan", "turn", "tool_call", "approval_requested"]
    approval = (await session.execute(select(Approval))).scalar_one()
    assert approval.tool_name == "write_x" and approval.args == {"v": 2} and approval.step_seq == 2 and approval.call_index == 1
    assert notified == [approval.code]


async def test_notify_failure_does_not_break_the_park(setup_db, session):
    agent, task = await setup(session, ceiling=1)

    async def notify(sess, approval):
        raise RuntimeError("whatsapp down")
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=recording_tool(), tool_defs=fake_tool_defs,
                   policy_levels=fake_levels, session_factory=factory_of(setup_db), notify=notify)
    await session.refresh(task)
    assert task.status == "waiting_approval"


async def test_approved_resume_executes_exact_args_and_history_matches_a_continuous_run(setup_db, session):
    factory = factory_of(setup_db)
    # Reference: same scenario with no gate, capture the prompt the model saw after both tools.
    ref_agent, ref_task = await setup(session, ceiling=2)
    ref_llm = scripted(J(PLAN), TWO_CALLS, DONE, J(CRITIQUE), J(REPORT))
    await run_task(ref_task.id, llm=ref_llm, tool=recording_tool(), tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    reference_prompt = ref_llm.calls[2]["messages"]
    # Gated run: park, approve with the model's args, resume.
    await session.delete(await session.get(Agent, ref_agent.id))
    await session.commit()
    agent, task = await setup(session, ceiling=1)
    tool = recording_tool()
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    # The park happened through `factory`'s own session; refresh so the ambient
    # session's cached task (last touched by `setup`'s claim) is not stale when
    # `decide()` reads its status.
    await session.refresh(task)
    approval = (await session.execute(select(Approval))).scalar_one()
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    claimed = await AgentTaskService.claim(session, "w2")
    assert claimed.id == task.id
    resumed_llm = scripted(DONE, J(CRITIQUE), J(REPORT))
    await run_task(task.id, llm=resumed_llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "completed" and task.outcome == "success"
    assert tool.calls == [("list_x", {"q": 1}), ("write_x", {"v": 2})]
    assert resumed_llm.calls[0]["messages"] == reference_prompt           # the rebuilt history is the real one
    steps = await steps_of(session, task.id)
    kinds = [s.kind for s in steps]
    assert kinds == ["plan", "turn", "tool_call", "approval_requested", "tool_call", "turn", "critique", "report"]
    assert steps[4].payload["approval_id"] == str(approval.id) and steps[4].payload["risk_level"] == 2
    await session.refresh(approval)
    assert approval.consumed_at is not None


async def test_rejected_resume_injects_the_refusal(setup_db, session):
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)
    tool = recording_tool()
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    approval = (await session.execute(select(Approval))).scalar_one()
    await ApprovalService.decide(session, approval, approve=False, decided_by="ui", reason="not now")
    await AgentTaskService.claim(session, "w2")
    resumed_llm = scripted(DONE, J(CRITIQUE), J(REPORT))
    await run_task(task.id, llm=resumed_llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "completed" and [c[0] for c in tool.calls] == ["list_x"]
    refusal = next(m for m in resumed_llm.calls[0]["messages"] if m.get("role") == "tool" and m["tool_call_id"].endswith("_1"))
    assert json.loads(refusal["content"]) == {"error": "rejected by operator: not now"}
    tool_steps = [s for s in await steps_of(session, task.id) if s.kind == "tool_call"]
    assert tool_steps[-1].payload["ok"] is False and tool_steps[-1].payload["approval_id"] == str(approval.id)


async def test_second_gated_call_in_the_same_turn_parks_again(setup_db, session):
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)
    three = LlmResult("go", [{"name": "list_x", "args": {}}, {"name": "write_x", "args": {"v": 1}}, {"name": "purge_x", "args": {}}])
    tool = recording_tool()
    await run_task(task.id, llm=scripted(J(PLAN), three), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    first = (await session.execute(select(Approval))).scalar_one()
    await ApprovalService.decide(session, first, approve=True, decided_by="ui", reason=None)
    await AgentTaskService.claim(session, "w2")
    await run_task(task.id, llm=scripted(), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "waiting_approval"
    approvals = (await session.execute(select(Approval).order_by(Approval.requested_at))).scalars().all()
    assert [a.tool_name for a in approvals] == ["write_x", "purge_x"] and approvals[1].call_index == 2
    assert [c[0] for c in tool.calls] == ["list_x", "write_x"]


async def test_park_conflict_when_task_already_finished_exits_quietly(setup_db, session):
    """If the task goes final (e.g. another path finishes it) between the gated call being
    reached and ApprovalService.request() parking it, request() raises ApprovalConflict after
    expiring the approval it just created. run_task must swallow that and simply return,
    leaving the task's already-final status untouched."""
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)

    async def tool(name, args, server):
        # Simulate the task finishing (e.g. a sweep or a cancel) while the loop
        # is still mid-turn, through a completely separate session.
        async with factory() as s:
            finishing_task = await s.get(AgentTask, task.id)
            await AgentTaskService.finish(s, finishing_task, "failed", error="finished early")
        return json.dumps({"ok": name})

    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=tool, tool_defs=fake_tool_defs,
                   policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "failed" and task.error == "finished early"


async def test_resume_without_a_decision_fails_cleanly(setup_db, session):
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=recording_tool(), tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    # Force an inconsistent state: queued again with steps but no decided approval.
    await AgentTaskService.resume(session, task)
    await AgentTaskService.claim(session, "w2")
    await run_task(task.id, llm=scripted(), tool=recording_tool(), tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "failed" and task.error.startswith("resume:")
