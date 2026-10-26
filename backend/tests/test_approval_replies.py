import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy import select

from app.models import Agent, AgentTask, Approval, Config, McpServer
from app.services.agent_task_service import AgentTaskService
from app.services.approval_replies import ApprovalReplies, extract_messages, parse_reply
from app.services.approval_service import ApprovalService


def test_parse_reply_accepts_both_languages_and_case():
    assert parse_reply("OUI ABC234") == (True, "ABC234")
    assert parse_reply("  non abc234 merci") == (False, "ABC234")
    assert parse_reply("YES ABC234") == (True, "ABC234")
    assert parse_reply("No ABC234") == (False, "ABC234")
    assert parse_reply("ok ABC234") is None and parse_reply("OUI") is None and parse_reply("OUI ABC23") is None


def test_extract_messages_tolerates_shapes():
    raw = json.dumps({"items": [{"body": "OUI ABC234", "fromMe": False, "timestamp": 1_800_000_000},
                                {"text": "x", "fromMe": True, "timestamp": 1_800_000_000_000},
                                {"message": "y", "from_me": False, "created_at": "2027-01-01T00:00:00Z"}]})
    msgs = extract_messages(raw)
    assert [m["body"] for m in msgs] == ["OUI ABC234", "x", "y"]
    assert [m["from_me"] for m in msgs] == [False, True, False]
    assert all(isinstance(m["timestamp"], datetime) for m in msgs)
    assert extract_messages(json.dumps([{"body": "z"}]))[0]["timestamp"] is None


async def _setup_whatsapp(session) -> McpServer:
    """One-time WhatsApp server + Config, shared by every approval created in a test."""
    wa = McpServer(name="Whatsapp (OpenWa)", transport="http", url="http://wa", enabled=True)
    srv = McpServer(name="srv", transport="http", url="http://x", enabled=True)
    session.add_all([wa, srv])
    await session.commit()
    session.add(Config(llm_provider="openai", llm_model="m", api_key="", approval_whatsapp_enabled=True, approval_whatsapp_session_id="s1"))
    await session.commit()
    return srv


async def _pending_approval(session, srv: McpServer, *, name: str = "Bot") -> Approval:
    """One pending approval on a fresh agent/task, reusing an already set-up WhatsApp server."""
    agent = Agent(name=name, objective="o", status="active", mcp_servers=[srv])
    session.add(agent)
    await session.commit()
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    task = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {}}]})
    return await ApprovalService.request(session, task, step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={}, risk_level=2)


async def _pending(session) -> Approval:
    srv = await _setup_whatsapp(session)
    return await _pending_approval(session, srv)


def tool_returning(messages):
    seen = []

    async def tool(name, args, server):
        seen.append((name, args))
        return json.dumps(messages)
    tool.seen = seen
    return tool


def ts(dt):
    return int(dt.timestamp())


async def test_yes_reply_approves_once(session):
    approval = await _pending(session)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    tool = tool_returning([{"body": f"oui {approval.code}", "fromMe": False, "timestamp": ts(later)}])
    assert await ApprovalReplies.poll(session, tool=tool) == 1
    await session.refresh(approval)
    assert approval.status == "approved" and approval.decided_by == "whatsapp:2250700003331" and approval.decision_reason == f"oui {approval.code}"
    assert tool.seen[0][0] == "MessageList" and tool.seen[0][1]["chatId"] == "2250700003331@c.us"
    assert await ApprovalReplies.poll(session, tool=tool) == 0          # same messages again: nothing pending any more


async def test_no_reply_rejects(session):
    approval = await _pending(session)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert await ApprovalReplies.poll(session, tool=tool_returning([{"body": f"NON {approval.code}", "fromMe": False, "timestamp": ts(later)}])) == 1
    await session.refresh(approval)
    assert approval.status == "rejected"


async def test_ignores_old_fromme_and_unknown_codes(session):
    approval = await _pending(session)
    earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    tool = tool_returning([
        {"body": f"OUI {approval.code}", "fromMe": False, "timestamp": ts(earlier)},   # before the request
        {"body": f"OUI {approval.code}", "fromMe": True, "timestamp": ts(later)},      # our own message
        {"body": "OUI ZZZZZ9", "fromMe": False, "timestamp": ts(later)},               # unknown code
    ])
    assert await ApprovalReplies.poll(session, tool=tool) == 0
    await session.refresh(approval)
    assert approval.status == "pending"


async def test_poll_skips_when_nothing_pending_or_disabled(session):
    approval = await _pending(session)
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    tool = tool_returning([])
    assert await ApprovalReplies.poll(session, tool=tool) == 0 and tool.seen == []


async def test_poll_tolerates_an_approval_expired_out_of_band_before_it_is_decided(session):
    """Regression for the MissingGreenlet crash: `decide()`'s conflict branch
    rolls back the session, which expires every ORM instance still held by
    it, including the other pending approval `poll()` is about to process
    next. The fix re-loads each approval fresh right before deciding it,
    instead of reusing the instance captured when `pending` was first read.

    `first` is expired directly on the row (as the expiry job would) inside
    the `MessageList` tool call, i.e. after `list_pending()` already captured
    it as pending but before the reply loop reaches its message — the exact
    window the original code got wrong."""
    srv = await _setup_whatsapp(session)
    first = await _pending_approval(session, srv, name="Bot1")
    second = await _pending_approval(session, srv, name="Bot2")
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    messages = [
        {"body": f"OUI {first.code}", "fromMe": False, "timestamp": ts(later)},
        {"body": f"OUI {second.code}", "fromMe": False, "timestamp": ts(later)},
    ]

    async def tool(name, args, server):
        first.status = "expired"
        await session.commit()
        return json.dumps(messages)

    assert await ApprovalReplies.poll(session, tool=tool) == 1
    await session.refresh(second)
    assert second.status == "approved"


async def test_poll_returns_zero_when_session_lookup_fails(session):
    approval = await _pending(session)
    cfg = (await session.execute(select(Config))).scalar_one()
    cfg.approval_whatsapp_session_id = None
    await session.commit()

    async def tool(name, args, server):
        return json.dumps({"error": "boom-from-session-find-all"})
    assert await ApprovalReplies.poll(session, tool=tool) == 0
    await session.refresh(approval)
    assert approval.status == "pending"
