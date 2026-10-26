"""Tell the administrator on WhatsApp that an approval is waiting.

Best effort by design: failures are recorded on the approval and logged, and
nothing in the task's fate depends on the message having left."""
import json
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, Approval, Config, McpServer
from app.services.approval_service import ApprovalService
from app.services.llm_runtime import call_mcp_tool

log = structlog.get_logger()

ARGS_MAX_CHARS = 600


def admin_chat_id(number: str) -> str:
    return re.sub(r"\D", "", number or "") + "@c.us"


def render_message(template: str, *, agent: str, tool: str, server: str, args: dict, code: str, expires_at, link: str) -> str:
    pretty = json.dumps(args, ensure_ascii=False, indent=None, default=str)
    if len(pretty) > ARGS_MAX_CHARS:
        pretty = pretty[:ARGS_MAX_CHARS] + "…"
    return template.format(agent=agent, tool=tool, server=server, args=pretty, code=code,
                           expires=expires_at.strftime("%H:%M UTC"), link=link)


async def resolve_whatsapp_server(session: AsyncSession, config: Config) -> McpServer | None:
    if config.approval_whatsapp_server_id:
        server = await session.get(McpServer, config.approval_whatsapp_server_id)
        return server if server and server.enabled else None
    rows = (await session.execute(select(McpServer).where(McpServer.enabled == True))).scalars().all()
    return next((s for s in rows if "whatsapp" in s.name.lower()), None)


async def resolve_session_id(config: Config, server: McpServer, tool) -> str | None:
    if config.approval_whatsapp_session_id:
        return config.approval_whatsapp_session_id
    raw = await tool("SessionFindAll", {"limit": 50}, server)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and set(data.keys()) == {"error"}:
        raise RuntimeError(str(data["error"]))
    items = data.get("items") if isinstance(data, dict) else data
    for item in items or []:
        if isinstance(item, dict) and str(item.get("status", "")).lower() == "ready" and item.get("id"):
            return str(item["id"])
    return None


class ApprovalNotifier:

    @staticmethod
    async def notify(session: AsyncSession, approval: Approval, *, tool=call_mcp_tool) -> None:
        try:
            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            if not config or not config.approval_whatsapp_enabled:
                await ApprovalService.set_notified(session, approval, error="notifications disabled")
                return
            server = await resolve_whatsapp_server(session, config)
            if server is None:
                await ApprovalService.set_notified(session, approval, error="no WhatsApp MCP server")
                return
            session_id = await resolve_session_id(config, server, tool)
            if not session_id:
                await ApprovalService.set_notified(session, approval, error="no ready WhatsApp session")
                return
            agent = await session.get(Agent, approval.agent_id)
            link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/agents/{approval.agent_id}/tasks/{approval.task_id}"
            text = render_message(config.approval_whatsapp_template, agent=agent.name if agent else "agent",
                                  tool=approval.tool_name, server=approval.server_name, args=approval.args,
                                  code=approval.code, expires_at=approval.expires_at, link=link)
            raw = await tool("MessageSendText", {"sessionId": session_id, "chatId": admin_chat_id(config.approval_whatsapp_number), "text": text}, server)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict) and set(data.keys()) == {"error"}:
                await ApprovalService.set_notified(session, approval, error=str(data["error"]))
                return
            await ApprovalService.set_notified(session, approval, error=None)
            log.info("approval_notified", approval_id=str(approval.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("approval_notify_failed", approval_id=str(approval.id), error=str(exc))
            try:
                await ApprovalService.set_notified(session, approval, error=str(exc))
            except Exception:
                log.exception("approval_notify_record_failed", approval_id=str(approval.id))
