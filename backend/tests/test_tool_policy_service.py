import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select

from app.models import McpServer, ToolPolicy
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
