import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Agent, AgentTask, Base, Config, McpServer
from app.services.agent_task_service import AgentTaskService
from app.services.approval_service import ApprovalService

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_async_session] = override
    yield factory
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def pending_approval(factory):
    async with factory() as s:
        s.add(Config(llm_provider="openai", llm_model="m", api_key=""))
        agent = Agent(name="Bot", objective="Inspect", status="active",
                      mcp_servers=[McpServer(name="srv", transport="http", url="http://x", enabled=True)])
        s.add(agent)
        await s.commit()
        await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        task = await AgentTaskService.claim(s, "w")
        await AgentTaskService.record_step(s, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {"v": 1}}]})
        approval = await ApprovalService.request(s, task, step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={"v": 1}, risk_level=2)
        return str(approval.id), str(task.id)


async def test_list_pending_and_approve(setup_test_db):
    aid, tid = await pending_approval(setup_test_db)
    async with client() as c:
        items = (await c.get("/api/v1/approvals")).json()
        assert [i["id"] for i in items] == [aid]
        assert items[0]["agent_name"] == "Bot" and items[0]["task_objective"] == "Inspect" and items[0]["seconds_left"] > 0
        assert items[0]["args"] == {"v": 1} and len(items[0]["code"]) == 6
        task = (await c.get(f"/api/v1/agent-tasks/{tid}")).json()
        assert task["status"] == "waiting_approval" and task["approval"]["id"] == aid
        resp = await c.post(f"/api/v1/approvals/{aid}/approve", json={"reason": "fine"})
        assert resp.status_code == 200 and resp.json()["status"] == "approved" and resp.json()["decided_by"] == "ui"
        assert (await c.get("/api/v1/approvals")).json() == []
        assert [i["id"] for i in (await c.get("/api/v1/approvals?status=approved")).json()] == [aid]
        task = (await c.get(f"/api/v1/agent-tasks/{tid}")).json()
        assert task["status"] == "queued" and task["approval"] is None
        assert (await c.post(f"/api/v1/approvals/{aid}/reject", json={})).status_code == 409


async def test_reject_and_404s(setup_test_db):
    aid, tid = await pending_approval(setup_test_db)
    async with client() as c:
        resp = await c.post(f"/api/v1/approvals/{aid}/reject", json={"reason": "no"})
        assert resp.status_code == 200 and resp.json()["status"] == "rejected" and resp.json()["decision_reason"] == "no"
        assert (await c.post(f"/api/v1/approvals/{uuid.uuid4()}/approve", json={})).status_code == 404
        assert (await c.get("/api/v1/approvals?status=bogus")).status_code == 422
