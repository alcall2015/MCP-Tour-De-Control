import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from app.models import Agent, AgentTask, Approval, Config, McpServer
from app.services.agent_task_service import AgentTaskService
from app.services.approval_notifier import ApprovalNotifier, admin_chat_id, render_message
from app.services.approval_service import ApprovalService


def test_admin_chat_id_strips_formatting():
    assert admin_chat_id("+225 07 00 00 33 31") == "2250700003331@c.us"
    assert admin_chat_id("2250700003331") == "2250700003331@c.us"


def test_render_message_fills_every_variable_and_truncates_args():
    text = render_message("A {agent} {tool} {server} {args} {code} {expires} {link}", agent="Bot", tool="write_x", server="srv",
                          args={"big": "x" * 1000}, code="ABC234", expires_at=datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc), link="https://t/x")
    assert "Bot write_x srv" in text and "ABC234" in text and "10:30 UTC" in text and "https://t/x" in text
    assert len(text) < 800 and text.count("x") <= 600


async def _pending(session, *, enabled=True, server_id=None, session_id=None, whatsapp_name="Whatsapp (OpenWa)"):
    wa = McpServer(name=whatsapp_name, transport="http", url="http://wa", enabled=True)
    srv = McpServer(name="srv", transport="http", url="http://x", enabled=True)
    session.add_all([wa, srv])
    await session.commit()
    session.add(Config(llm_provider="openai", llm_model="m", api_key="", approval_whatsapp_enabled=enabled,
                       approval_whatsapp_server_id=server_id, approval_whatsapp_session_id=session_id))
    agent = Agent(name="Bot", objective="o", status="active", mcp_servers=[srv])
    session.add(agent)
    await session.commit()
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    task = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {"v": 1}}]})
    approval = await ApprovalService.request(session, task, step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={"v": 1}, risk_level=2)
    return wa, approval


async def test_notify_sends_to_the_admin_with_the_code(session):
    wa, approval = await _pending(session)
    calls = []

    async def tool(name, args, server):
        calls.append((name, args, server.name))
        if name == "SessionFindAll":
            return json.dumps([{"id": "s-dead", "status": "disconnected"}, {"id": "s-ok", "status": "ready"}])
        return json.dumps({"id": "msg1"})
    await ApprovalNotifier.notify(session, approval, tool=tool)
    await session.refresh(approval)
    assert approval.notified_at is not None and approval.notify_error is None
    name, args, server = calls[-1]
    assert name == "MessageSendText" and server == "Whatsapp (OpenWa)"
    assert args["sessionId"] == "s-ok" and args["chatId"] == "2250700003331@c.us"
    assert approval.code in args["text"] and "write_x" in args["text"] and f"/tasks/{approval.task_id}" in args["text"]


async def test_notify_uses_configured_session_and_server(session):
    wa, approval = await _pending(session, session_id="s-cfg")
    cfg = (await session.execute(__import__("sqlalchemy").select(Config))).scalar_one()
    cfg.approval_whatsapp_server_id = wa.id
    await session.commit()
    calls = []

    async def tool(name, args, server):
        calls.append(name)
        return "{}"
    await ApprovalNotifier.notify(session, approval, tool=tool)
    assert calls == ["MessageSendText"]  # no SessionFindAll round trip


async def test_notify_records_errors_and_never_raises(session):
    wa, approval = await _pending(session)

    async def tool(name, args, server):
        return json.dumps({"error": "boom"})
    await ApprovalNotifier.notify(session, approval, tool=tool)
    await session.refresh(approval)
    assert approval.notified_at is None and "boom" in approval.notify_error


async def test_notify_disabled_or_no_server(session):
    wa, approval = await _pending(session, enabled=False)
    sent = []

    async def tool(name, args, server):
        sent.append(name)
        return "{}"
    await ApprovalNotifier.notify(session, approval, tool=tool)
    assert sent == []
    await session.refresh(approval)
    assert approval.notified_at is None and approval.notify_error == "notifications disabled"
