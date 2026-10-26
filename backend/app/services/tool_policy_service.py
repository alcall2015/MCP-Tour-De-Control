"""Risk levels of MCP tools. Discovery only ever adds rows at the default
level or refreshes descriptions; levels change only through set_level."""
import structlog
from sqlalchemy import select
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
        existing = {p.tool_name: p for p in (await session.execute(
            select(ToolPolicy).where(ToolPolicy.mcp_server_id == server.id))).scalars().all()}
        for t in tools:
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
            if not name:
                continue
            description = t.get("description") if isinstance(t, dict) else getattr(t, "description", None)
            row = existing.get(name)
            if row is None:
                session.add(ToolPolicy(mcp_server_id=server.id, tool_name=name, description=description))
            elif description is not None and row.description != description:
                row.description = description
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
