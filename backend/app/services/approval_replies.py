"""Read the administrator's WhatsApp chat and apply `OUI <code>` / `NON <code>` replies."""
import json
import re
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approval, Config
from app.services.approval_notifier import admin_chat_id, resolve_session_id, resolve_whatsapp_server
from app.services.approval_service import ApprovalConflict, ApprovalService
from app.services.llm_runtime import call_mcp_tool

log = structlog.get_logger()

REPLY = re.compile(r"^\s*(OUI|YES|NON|NO)\s+([A-Z0-9]{6})\b", re.IGNORECASE)
PAGE = 20


def parse_reply(text: str) -> tuple[bool, str] | None:
    m = REPLY.match(text or "")
    if not m:
        return None
    return m.group(1).upper() in ("OUI", "YES"), m.group(2).upper()


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def extract_messages(raw: str) -> list[dict]:
    """Normalise the WhatsApp server's message list into {body, from_me, timestamp}."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    out = []
    for m in items or []:
        if not isinstance(m, dict):
            continue
        body = next((m[k] for k in ("body", "text", "content", "message") if isinstance(m.get(k), str)), "")
        from_me = bool(m.get("fromMe", m.get("from_me", False)))
        timestamp = _to_datetime(next((m[k] for k in ("timestamp", "t", "created_at", "createdAt") if k in m), None))
        out.append({"body": body, "from_me": from_me, "timestamp": timestamp})
    return out


class ApprovalReplies:

    @staticmethod
    async def poll(session: AsyncSession, *, tool=call_mcp_tool) -> int:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.approval_whatsapp_enabled:
            return 0
        pending = await ApprovalService.list_pending(session)
        if not pending:
            return 0
        server = await resolve_whatsapp_server(session, config)
        if server is None:
            return 0
        try:
            session_id = await resolve_session_id(config, server, tool)
        except Exception as exc:  # noqa: BLE001 - a flaky bridge must not turn the poll into an error
            log.warning("approval_replies_session_lookup_failed", error=str(exc))
            return 0
        if not session_id:
            return 0
        chat_id = admin_chat_id(config.approval_whatsapp_number)
        decided_by = "whatsapp:" + re.sub(r"\D", "", config.approval_whatsapp_number)
        raw = await tool("MessageList", {"sessionId": session_id, "chatId": chat_id, "limit": PAGE}, server)
        oldest = min(a.requested_at for a in pending)
        by_code = {a.code: a for a in pending}
        decided = 0
        for msg in extract_messages(raw):
            if msg["from_me"] or (msg["timestamp"] is not None and msg["timestamp"] < oldest):
                continue
            parsed = parse_reply(msg["body"])
            if not parsed:
                continue
            approve, code = parsed
            approval = by_code.get(code)
            if approval is None:
                continue
            try:
                await ApprovalService.decide(session, approval, approve=approve, decided_by=decided_by,
                                             reason=msg["body"].strip())
                decided += 1
                by_code.pop(code, None)
            except ApprovalConflict:
                continue
        return decided
