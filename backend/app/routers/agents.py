import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Agent, AgentTask, McpServer
from app.schemas import AgentCreate, AgentRead, AgentServerRef, AgentStatusUpdate, AgentTaskRead, AgentUpdate
from app.schemas.agent import AgentStatus
from app.schemas.agent_task import AgentTaskCreate
from app.services.agent_service import AgentService, AgentStateError
from app.services.agent_task_service import AgentTaskService, TaskConflict
from app.services.scheduler_service import scheduler_service

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _to_read(agent: Agent, summary: dict | None = None) -> AgentRead:
    summary = summary or {}
    return AgentRead(
        id=agent.id,
        name=agent.name,
        objective=agent.objective,
        instructions=agent.instructions,
        description=agent.description,
        status=agent.status,
        max_steps=agent.max_steps,
        timeout_seconds=agent.timeout_seconds,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        mcp_servers=[AgentServerRef(id=s.id, name=s.name, enabled=s.enabled) for s in agent.mcp_servers],
        cron_expr=agent.cron_expr,
        running_task_id=summary.get("running_task_id"),
        last_task=summary.get("last_task"),
    )


async def _load_servers(session: AsyncSession, ids: list[uuid.UUID]) -> list[McpServer]:
    servers = []
    # A repeated id would violate agent_mcp_server's composite primary key; keep first occurrence order.
    for sid in dict.fromkeys(ids):
        server = await session.get(McpServer, sid)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server {sid} not found")
        servers.append(server)
    return servers


async def _get_agent(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("", response_model=list[AgentRead])
async def list_agents(
    status: AgentStatus | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Agent).order_by(Agent.created_at.desc())
    if status is None:
        stmt = stmt.where(Agent.status != "archived")
    else:
        stmt = stmt.where(Agent.status == status)
    agents = (await session.execute(stmt)).scalars().all()
    summaries = await AgentService.task_summaries(session, [a.id for a in agents])
    return [_to_read(a, summaries[a.id]) for a in agents]


@router.post("", response_model=AgentRead, status_code=201)
async def create_agent(data: AgentCreate, session: AsyncSession = Depends(get_async_session)):
    servers = await _load_servers(session, data.mcp_server_ids)
    agent = Agent(
        name=data.name,
        objective=data.objective,
        instructions=data.instructions,
        description=data.description,
        max_steps=data.max_steps,
        timeout_seconds=data.timeout_seconds,
        mcp_servers=servers,
        cron_expr=data.cron_expr,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    log.info("agent_created", agent_id=str(agent.id), name=agent.name)
    return _to_read(agent)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    summary = (await AgentService.task_summaries(session, [agent.id]))[agent.id]
    return _to_read(agent, summary)


@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(agent_id: uuid.UUID, data: AgentUpdate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    try:
        agent = await AgentService.apply_update(session, agent, data, lambda ids: _load_servers(session, ids))
    except AgentStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return _to_read(agent, (await AgentService.task_summaries(session, [agent.id]))[agent.id])


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    if agent.status not in ("draft", "archived"):
        raise HTTPException(status_code=409, detail=f"Cannot delete a {agent.status} agent; archive it first")
    try:
        await AgentService.assert_no_open_task(session, agent_id)
    except AgentStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    await session.delete(agent)
    await session.commit()
    scheduler_service.remove_agent_job(agent_id)
    log.info("agent_deleted", agent_id=str(agent_id))


@router.put("/{agent_id}/status", response_model=AgentRead)
async def set_agent_status(agent_id: uuid.UUID, data: AgentStatusUpdate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    try:
        agent = await AgentService.change_status(session, agent, data.status)
    except AgentStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return _to_read(agent, (await AgentService.task_summaries(session, [agent.id]))[agent.id])


@router.post("/{agent_id}/tasks", response_model=AgentTaskRead, status_code=201)
async def create_task(agent_id: uuid.UUID, data: AgentTaskCreate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    try:
        task = await AgentTaskService.enqueue(session, agent, objective=data.objective, trigger="manual")
    except TaskConflict as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return AgentTaskRead.model_validate(task)


@router.get("/{agent_id}/tasks", response_model=list[AgentTaskRead])
async def list_tasks(agent_id: uuid.UUID, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                     session: AsyncSession = Depends(get_async_session)):
    await _get_agent(session, agent_id)
    rows = (await session.execute(
        select(AgentTask).where(AgentTask.agent_id == agent_id).order_by(AgentTask.created_at.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return [AgentTaskRead.model_validate(t) for t in rows]
