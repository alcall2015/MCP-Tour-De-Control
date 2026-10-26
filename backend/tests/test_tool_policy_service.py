import asyncio
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import McpServer, ToolPolicy
from app.models.tool_policy import DEFAULT_RISK_LEVEL
from app.services.tool_policy_service import ToolPolicyService


async def _server(session, name="srv"):
    s = McpServer(name=name, transport="http", url="http://x", enabled=True)
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def test_sync_inserts_at_default_and_never_overwrites_a_level(session):
    server = await _server(session)
    await ToolPolicyService.sync(session, server, [{"name": "list_x", "description": "list"}, {"name": "write_x", "description": None}])
    rows = {p.tool_name: p for p in (await session.execute(select(ToolPolicy))).scalars().all()}
    assert rows["list_x"].risk_level == 2 and rows["list_x"].description == "list"
    await ToolPolicyService.set_level(session, server, "list_x", 0)
    await ToolPolicyService.sync(session, server, [{"name": "list_x", "description": "list v2"}])
    await session.refresh(rows["list_x"])
    assert rows["list_x"].risk_level == 0 and rows["list_x"].description == "list v2"


async def test_levels_for_returns_levels_and_creates_missing(session):
    server = await _server(session)
    await ToolPolicyService.sync(session, server, [{"name": "list_x", "description": ""}])
    await ToolPolicyService.set_level(session, server, "list_x", 0)
    levels = await ToolPolicyService.levels_for(session, {"list_x": server, "brand_new": server})
    assert levels == {"list_x": 0, "brand_new": 2}
    assert (await session.execute(select(ToolPolicy).where(ToolPolicy.tool_name == "brand_new"))).scalar_one().risk_level == 2


async def test_set_level_unknown_tool_raises(session):
    server = await _server(session)
    with pytest.raises(LookupError):
        await ToolPolicyService.set_level(session, server, "nope", 1)


async def test_levels_are_per_server(session):
    a = await _server(session, "a")
    b = await _server(session, "b")
    await ToolPolicyService.sync(session, a, [{"name": "t"}])
    await ToolPolicyService.sync(session, b, [{"name": "t"}])
    await ToolPolicyService.set_level(session, a, "t", 0)
    assert await ToolPolicyService.levels_for(session, {"t": b}) == {"t": 2}


async def test_sync_concurrent_insert_of_same_new_tool_does_not_raise(setup_db):
    """Two sessions discovering the same brand-new tool on the same server at once (e.g. a
    manual POST /test racing a GET /tools, or the agent runner's levels_for racing either) must
    not raise an IntegrityError on uq_tool_policy_server_tool.

    This forces the race deterministically rather than relying on asyncio scheduling luck:
    session_a inserts the row for "racey_tool" but does NOT commit yet, holding the row
    uncommitted (and the unique-index entry locked) on its own session/connection. While that
    transaction is still open, session_b's sync() call runs for the same tool name -- under
    the app's default READ COMMITTED isolation, session_b's own SELECT correctly sees no row
    yet (session_a hasn't committed), so session_b also attempts to insert. Its INSERT blocks
    server-side on session_a's in-flight row. session_b's sync() runs as a background task,
    given a brief real-time window to reach that blocked INSERT, and only then does session_a
    commit -- which is what unblocks session_b: its INSERT ... ON CONFLICT DO NOTHING must see
    the now-committed conflicting row and silently skip rather than raise."""
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        server = McpServer(name="srv", transport="http", url="http://x", enabled=True)
        s.add(server)
        await s.commit()
        server_id = server.id

    async with factory() as sa, factory() as sb:
        server_b = await sb.get(McpServer, server_id)

        now = datetime.now(timezone.utc)
        stmt = pg_insert(ToolPolicy).values([{
            "id": uuid.uuid4(),
            "mcp_server_id": server_id,
            "tool_name": "racey_tool",
            "risk_level": DEFAULT_RISK_LEVEL,
            "description": "d",
            "first_seen_at": now,
            "updated_at": now,
        }]).on_conflict_do_nothing(constraint="uq_tool_policy_server_tool")
        # session_a's insert is sent but left uncommitted -- the row is only visible within
        # session_a's own transaction, and the unique-index entry is locked against sb.
        await sa.execute(stmt)

        # session_b's sync() races this: its SELECT sees no "racey_tool" row (sa hasn't
        # committed), so it tries to insert too. Its INSERT then blocks server-side on sa's
        # uncommitted row. Run it as a background task and give it a brief real-time window
        # to reach that blocked INSERT before we commit sa -- this is what actually unblocks
        # it, so ordering it via asyncio.gather (no real wait) left the two racing on event
        # loop scheduling and didn't reliably reproduce the conflict.
        task_b = asyncio.create_task(
            ToolPolicyService.sync(sb, server_b, [{"name": "racey_tool", "description": "d2"}]))
        await asyncio.sleep(0.05)
        await sa.commit()
        await task_b  # must not raise IntegrityError

    async with factory() as s:
        rows = (await s.execute(select(ToolPolicy).where(
            ToolPolicy.mcp_server_id == server_id, ToolPolicy.tool_name == "racey_tool"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].risk_level == 2
