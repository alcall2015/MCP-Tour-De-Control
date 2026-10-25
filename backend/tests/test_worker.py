import asyncio
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, McpServer
from app.services.agent_task_service import AgentTaskService
from app.worker import Worker


async def _agent(session, name):
    agent = Agent(name=name, objective="o", status="active",
                  mcp_servers=[McpServer(name=f"s-{name}", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_process_available_respects_concurrency_and_runs_tasks(setup_db, session):
    a, b, c = [await _agent(session, n) for n in "abc"]
    for agent in (a, b, c):
        await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    ran: list = []
    gate = asyncio.Event()

    async def fake_run(task_id, **_):
        ran.append(task_id)
        await gate.wait()
        async with factory() as s:
            await AgentTaskService.finish(s, await s.get(AgentTask, task_id), "completed", outcome="success")

    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=2, run=fake_run, session_factory=factory, worker_id="w-test")

    assert await worker.process_available() == 2          # two slots, two tasks started
    assert await worker.process_available() == 0          # slots full
    gate.set()
    await asyncio.sleep(0.2)
    assert await worker.process_available() == 1          # third task once a slot frees up
    await asyncio.sleep(0.2)
    assert len(ran) == 3
    await worker.close()


async def test_sweep_delegates_to_service(setup_db, session):
    factory = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
    worker = Worker(concurrency=1, session_factory=factory)
    assert await worker.sweep() == 0
    await worker.close()
