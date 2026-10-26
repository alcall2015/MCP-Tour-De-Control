import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import patch

from app.main import app
from app.database import get_async_session
from app.models import Agent, AgentTask, Base, McpServer
from app.services.agent_task_service import AgentTaskService

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    factory.engine = engine

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


async def make_agent(factory, status="active") -> str:
    async with factory() as s:
        agent = Agent(name="a", objective="Inspect", instructions="r", status=status,
                      mcp_servers=[McpServer(name="s", transport="http", url="http://x", enabled=True)])
        s.add(agent)
        await s.commit()
        return str(agent.id)


async def test_create_task_201_then_409_and_404(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with client() as c:
        resp = await c.post(f"/api/v1/agents/{aid}/tasks", json={"objective": None})
        assert resp.status_code == 201, resp.text
        task = resp.json()
        assert task["status"] == "queued" and task["objective"] == "Inspect" and task["trigger"] == "manual"
        assert task["max_steps"] == 20 and task["timeout_seconds"] == 300
        resp = await c.post(f"/api/v1/agents/{aid}/tasks", json={"objective": "again"})
        assert resp.status_code == 409
        resp = await c.post(f"/api/v1/agents/{uuid.uuid4()}/tasks", json={})
        assert resp.status_code == 404
        agent = (await c.get(f"/api/v1/agents/{aid}")).json()
        assert agent["last_task"]["id"] == task["id"] and agent["running_task_id"] is None


async def test_create_task_on_draft_is_409_and_override_is_kept(setup_test_db):
    draft = await make_agent(setup_test_db, status="draft")
    active = await make_agent(setup_test_db)
    async with client() as c:
        assert (await c.post(f"/api/v1/agents/{draft}/tasks", json={})).status_code == 409
        resp = await c.post(f"/api/v1/agents/{active}/tasks", json={"objective": "  custom  "})
        assert resp.json()["objective"] == "custom"


async def test_list_detail_and_step_prompt(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        agent = await s.get(Agent, uuid.UUID(aid))
        task = await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        await AgentTaskService.record_step(s, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "secret-free"}], tokens_in=3, tokens_out=1)
        await AgentTaskService.record_step(s, task, "tool_call", {"tool": "t", "server": "s", "args": {}, "result": "{}", "ok": True})
    async with client() as c:
        listing = (await c.get(f"/api/v1/agents/{aid}/tasks")).json()
        assert len(listing) == 1 and "steps" not in listing[0]
        detail = (await c.get(f"/api/v1/agent-tasks/{task.id}")).json()
        assert [s["kind"] for s in detail["steps"]] == ["plan", "tool_call"]
        assert all("prompt" not in s for s in detail["steps"])
        assert detail["step_count"] == 2 and detail["tokens_in"] == 3
        step = (await c.get(f"/api/v1/agent-tasks/{task.id}/steps/1")).json()
        assert step["prompt"] == [{"role": "system", "content": "secret-free"}]
        assert (await c.get(f"/api/v1/agent-tasks/{task.id}/steps/9")).status_code == 404
        assert (await c.get(f"/api/v1/agent-tasks/{uuid.uuid4()}")).status_code == 404


async def test_cancel_queued_running_and_final(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with client() as c:
        task = (await c.post(f"/api/v1/agents/{aid}/tasks", json={})).json()
        resp = await c.post(f"/api/v1/agent-tasks/{task['id']}/cancel")
        assert resp.status_code == 202 and resp.json()["status"] == "cancelled"
        assert (await c.post(f"/api/v1/agent-tasks/{task['id']}/cancel")).status_code == 409

        task2 = (await c.post(f"/api/v1/agents/{aid}/tasks", json={})).json()
        async with setup_test_db() as s:
            claimed = await AgentTaskService.claim(s, "w")
            assert str(claimed.id) == task2["id"]
        resp = await c.post(f"/api/v1/agent-tasks/{task2['id']}/cancel")
        assert resp.status_code == 202 and resp.json()["status"] == "running" and resp.json()["cancel_requested"] is True


# ---- SSE -------------------------------------------------------------------

import asyncio
import json


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [l for l in block.split("\n") if l and not l.startswith(":")]
        if not lines:
            continue
        name = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


async def test_events_backlog_then_done_for_a_final_task(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        agent = await s.get(Agent, uuid.UUID(aid))
        task = await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        await AgentTaskService.record_step(s, task, "plan", {"steps": []}, prompt=[{"role": "system", "content": "p"}])
        await AgentTaskService.finish(s, task, "completed", outcome="success")
    with patch("app.routers.agent_tasks.session_factory", setup_test_db), \
         patch("app.routers.agent_tasks.db_engine", setup_test_db.engine):
        async with client() as c:
            resp = await c.get(f"/api/v1/agent-tasks/{task.id}/events")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert [e for e, _ in events] == ["step", "status", "done"]
    assert events[0][1]["kind"] == "plan" and "prompt" not in events[0][1]
    assert events[1][1]["status"] == "completed" and events[1][1]["outcome"] == "success"


async def test_events_stream_live_steps_until_final(setup_test_db):
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        agent = await s.get(Agent, uuid.UUID(aid))
        task = await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        task = await AgentTaskService.claim(s, "w")

    async def produce():
        await asyncio.sleep(0.3)
        async with setup_test_db() as s:
            t = await s.get(AgentTask, task.id)
            await AgentTaskService.record_step(s, t, "turn", {"text": "hi", "tool_calls": []})
            await AgentTaskService.record_step(s, t, "report", {"summary": "ok"})
            await AgentTaskService.finish(s, t, "completed", outcome="partial")

    producer = asyncio.create_task(produce())
    with patch("app.routers.agent_tasks.session_factory", setup_test_db), \
         patch("app.routers.agent_tasks.db_engine", setup_test_db.engine):
        async with client() as c:
            async with c.stream("GET", f"/api/v1/agent-tasks/{task.id}/events") as resp:
                body = ""
                async for chunk in resp.aiter_text():
                    body += chunk
                    if "event: done" in body:
                        break
    await producer
    events = _parse_sse(body)
    names = [e for e, _ in events]
    assert names[0] == "status" and names[-1] == "done"
    assert [d["kind"] for e, d in events if e == "step"] == ["turn", "report"]
    assert any(e == "status" and d["status"] == "completed" for e, d in events)


async def test_cancel_waiting_task_closes_its_approval(setup_test_db):
    from app.models import Config
    from app.services.approval_service import ApprovalService
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        s.add(Config(llm_provider="openai", llm_model="m", api_key=""))
        await s.commit()
        agent = await s.get(Agent, uuid.UUID(aid))
        await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        task = await AgentTaskService.claim(s, "w")
        await AgentTaskService.record_step(s, task, "turn", {"text": None, "tool_calls": [{"name": "t", "args": {}}]})
        approval = await ApprovalService.request(s, task, step_seq=1, call_index=0, tool_name="t", server_name="s", args={}, risk_level=2)
    async with client() as c:
        resp = await c.post(f"/api/v1/agent-tasks/{task.id}/cancel")
        assert resp.status_code == 202 and resp.json()["status"] == "cancelled"
        assert (await c.get(f"/api/v1/approvals?status=expired")).json()[0]["id"] == str(approval.id)
