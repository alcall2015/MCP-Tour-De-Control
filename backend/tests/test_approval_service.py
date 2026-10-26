import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select

from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config, McpServer
from app.models.approval import CODE_ALPHABET
from app.services.agent_task_service import AgentTaskService, TaskConflict
from app.services.approval_service import ApprovalConflict, ApprovalService, canonical_hash


async def running_task(session, *, expiry_hours=24):
    session.add(Config(llm_provider="openai", llm_model="m", api_key="", approval_expiry_hours=expiry_hours))
    agent = Agent(name="a", objective="o", status="active",
                  mcp_servers=[McpServer(name="srv", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    task = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {"a": 1}}]})
    return agent, task


async def request(session, task, **over):
    kw = dict(step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={"a": 1}, risk_level=2)
    kw.update(over)
    return await ApprovalService.request(session, task, **kw)


def test_canonical_hash_is_order_independent():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


async def test_request_creates_pending_approval_and_parks(session):
    agent, task = await running_task(session, expiry_hours=2)
    before = datetime.now(timezone.utc)
    approval = await request(session, task)
    await session.refresh(task)
    assert task.status == "waiting_approval"
    assert approval.status == "pending" and len(approval.code) == 6
    assert all(c in CODE_ALPHABET for c in approval.code)
    assert approval.args_hash == canonical_hash({"a": 1})
    assert timedelta(hours=1, minutes=59) < approval.expires_at - before < timedelta(hours=2, minutes=1)
    steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq))).scalars().all()
    assert steps[-1].kind == "approval_requested" and steps[-1].payload["code"] == approval.code
    assert steps[-1].payload["approval_id"] == str(approval.id) and steps[-1].payload["risk_level"] == 2


async def test_codes_are_unique_among_open_approvals(session):
    agent, task = await running_task(session)
    first = await request(session, task)
    # a second task of another agent, to get a second pending approval
    agent2 = Agent(name="b", objective="o", status="active", mcp_servers=[McpServer(name="s2", transport="http", url="http://y", enabled=True)])
    session.add(agent2)
    await session.commit()
    await AgentTaskService.enqueue(session, agent2, objective=None, trigger="manual")
    task2 = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task2, "turn", {"text": None, "tool_calls": []})
    import app.services.approval_service as mod
    codes = iter([first.code, first.code, "ZZZZZ9"])
    original = mod._new_code
    mod._new_code = lambda: next(codes)
    try:
        second = await request(session, task2)
    finally:
        mod._new_code = original
    assert second.code == "ZZZZZ9"

    # a code held by a non-pending approval (e.g. expired) is reusable
    first.status = "expired"
    await session.commit()
    agent3 = Agent(name="c", objective="o", status="active", mcp_servers=[McpServer(name="s3", transport="http", url="http://z", enabled=True)])
    session.add(agent3)
    await session.commit()
    await AgentTaskService.enqueue(session, agent3, objective=None, trigger="manual")
    task3 = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task3, "turn", {"text": None, "tool_calls": []})
    mod._new_code = lambda: first.code
    try:
        third = await request(session, task3)
    finally:
        mod._new_code = original
    assert third.code == first.code


async def test_approve_resumes_and_is_single_shot(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    decided = await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    await session.refresh(task)
    assert decided.status == "approved" and decided.decided_by == "ui" and decided.decided_at is not None
    assert task.status == "queued"
    task_id = task.id  # captured before decide()'s conflict-branch rollback expires `task`
    with pytest.raises(ApprovalConflict):
        await ApprovalService.decide(session, approval, approve=False, decided_by="ui", reason="late")
    pending = await ApprovalService.decided_unconsumed(session, task_id)
    assert pending is not None and pending.id == approval.id
    assert await ApprovalService.mark_consumed(session, approval) is True
    assert await ApprovalService.decided_unconsumed(session, task_id) is None
    assert await ApprovalService.mark_consumed(session, approval) is False


async def test_reject_resumes_with_reason(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    decided = await ApprovalService.decide(session, approval, approve=False, decided_by="whatsapp:2250700003331", reason="NON ABC234")
    await session.refresh(task)
    assert decided.status == "rejected" and decided.decision_reason == "NON ABC234" and task.status == "queued"


async def test_decide_on_inactive_agent_fails_the_task(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    agent.status = "paused"
    await session.commit()
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    await session.refresh(task)
    assert task.status == "failed" and task.error == "agent is not active"
    assert await ApprovalService.decided_unconsumed(session, task.id) is not None  # decided, never consumed


async def test_cancel_waiting_task_expires_its_approval(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    await AgentTaskService.request_cancel(session, task)
    await session.refresh(task)
    await session.refresh(approval)
    assert task.status == "cancelled" and approval.status == "expired" and approval.decided_by == "system:cancel"
    with pytest.raises(TaskConflict):
        await AgentTaskService.request_cancel(session, task)


async def test_decide_after_cancel_changes_nothing_on_the_task(session):
    # request_cancel is what normally expires the approval; here the task was
    # finished directly so the approval is still pending while the task is final.
    agent, task = await running_task(session)
    approval = await request(session, task)
    await AgentTaskService.finish(session, task, "cancelled")
    decided = await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    await session.refresh(task)
    assert decided.status == "approved" and task.status == "cancelled"


async def test_expire_due_fails_the_task(session):
    agent, task = await running_task(session, expiry_hours=1)
    approval = await request(session, task)
    approval.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()
    assert await ApprovalService.expire_due(session) == 1
    await session.refresh(task)
    await session.refresh(approval)
    assert approval.status == "expired" and approval.decided_by == "system:expiry"
    assert task.status == "failed" and task.error == "approval expired"
    steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq))).scalars().all()
    assert steps[-1].kind == "error" and steps[-1].payload["phase"] == "approval"
    assert await ApprovalService.expire_due(session) == 0


async def test_expire_due_does_not_overwrite_a_decision_made_just_before_it_runs(session):
    agent, task = await running_task(session, expiry_hours=1)
    approval = await request(session, task)
    approval.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()
    # Simulates the race: a decide() commits in the window between expire_due's
    # due-row scan and its per-row UPDATE. Here it simply runs first.
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    assert await ApprovalService.expire_due(session) == 0
    await session.refresh(task)
    await session.refresh(approval)
    assert approval.status == "approved" and task.status == "queued"


async def test_request_when_task_no_longer_running_expires_the_approval_and_raises(session):
    agent, task = await running_task(session)
    await AgentTaskService.finish(session, task, "failed", error="worker lost")
    with pytest.raises(ApprovalConflict):
        await request(session, task)
    approval = (await session.execute(
        select(Approval).where(Approval.task_id == task.id)
    )).scalars().first()
    assert approval is None or approval.status == "expired"


async def test_list_pending_oldest_first_and_set_notified(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    assert [a.id for a in await ApprovalService.list_pending(session)] == [approval.id]
    await ApprovalService.set_notified(session, approval, error=None)
    await session.refresh(approval)
    assert approval.notified_at is not None and approval.notify_error is None
    await ApprovalService.set_notified(session, approval, error="boom")
    await session.refresh(approval)
    assert approval.notify_error == "boom"
