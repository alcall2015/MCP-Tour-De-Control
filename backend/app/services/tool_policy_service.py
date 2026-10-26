"""Risk levels of MCP tools. Discovery only ever adds rows at the default
level or refreshes descriptions; levels change only through set_level."""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import McpServer, ToolPolicy
from app.models.tool_policy import DEFAULT_RISK_LEVEL
from app.schemas.tool_policy import ToolPolicyRead
from app.services.mcp_service import McpService

log = structlog.get_logger()


class ToolDiscoveryError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ToolPolicyService:

    @staticmethod
    async def sync(session: AsyncSession, server: McpServer, tools: list[dict]) -> None:
        """Insert any (server, tool) rows discovery hasn't seen yet and refresh descriptions on
        existing ones. Missing rows go through `INSERT ... ON CONFLICT DO NOTHING` rather than a
        plain `session.add` so two concurrent syncs of the same server (a manual test racing a
        tool listing, or two `levels_for` calls) can't both try to insert the same (server, tool)
        and raise an IntegrityError — the loser's insert is silently skipped and a fresh row
        already exists under the unique constraint. Existing rows keep the description-refresh
        path as is; risk_level is never touched here."""
        existing = {p.tool_name: p for p in (await session.execute(
            select(ToolPolicy).where(ToolPolicy.mcp_server_id == server.id))).scalars().all()}
        new_rows: dict[str, dict] = {}
        for t in tools:
            name = t.get("name")
            if not name:
                continue
            description = t.get("description")
            row = existing.get(name)
            if row is not None:
                if description is not None and row.description != description:
                    row.description = description
            elif name not in new_rows:
                now = datetime.now(timezone.utc)
                new_rows[name] = {
                    "id": uuid.uuid4(),
                    "mcp_server_id": server.id,
                    "tool_name": name,
                    "risk_level": DEFAULT_RISK_LEVEL,
                    "description": description,
                    "first_seen_at": now,
                    "updated_at": now,
                }
        if new_rows:
            stmt = pg_insert(ToolPolicy).values(list(new_rows.values())).on_conflict_do_nothing(
                constraint="uq_tool_policy_server_tool")
            await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def levels_for(session: AsyncSession, server_map: dict[str, McpServer]) -> dict[str, int]:
        """tool_name -> risk level for the tools in server_map, creating missing rows at the default."""
        by_server: dict = {}
        for name, server in server_map.items():
            by_server.setdefault(server.id, (server, []))[1].append(name)
        levels: dict[str, int] = {}
        for server, names in by_server.values():
            await ToolPolicyService.sync(session, server, [{"name": n} for n in names])
            rows = (await session.execute(
                select(ToolPolicy.tool_name, ToolPolicy.risk_level)
                .where(ToolPolicy.mcp_server_id == server.id, ToolPolicy.tool_name.in_(names)))).all()
            levels.update({n: int(l) for n, l in rows})
        for name in server_map:
            levels.setdefault(name, DEFAULT_RISK_LEVEL)
        return levels

    @staticmethod
    async def discover(session: AsyncSession, server: McpServer) -> list[ToolPolicyRead]:
        result = await McpService.test_connection(server)
        if not result.success:
            raise ToolDiscoveryError(result.error or "discovery failed")
        tools = [t.model_dump() for t in result.tools]
        await ToolPolicyService.sync(session, server, tools)
        rows = {p.tool_name: p for p in (await session.execute(
            select(ToolPolicy).where(ToolPolicy.mcp_server_id == server.id))).scalars().all()}
        return [ToolPolicyRead(name=t["name"], description=t.get("description"),
                               risk_level=rows[t["name"]].risk_level if t["name"] in rows else DEFAULT_RISK_LEVEL)
                for t in tools]

    @staticmethod
    async def set_level(session: AsyncSession, server: McpServer, tool_name: str, level: int) -> ToolPolicy:
        row = (await session.execute(select(ToolPolicy).where(
            ToolPolicy.mcp_server_id == server.id, ToolPolicy.tool_name == tool_name))).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Tool {tool_name} is not known on server {server.name}")
        row.risk_level = level
        await session.commit()
        await session.refresh(row)
        log.info("tool_policy_set", server=server.name, tool=tool_name, risk_level=level)
        return row
