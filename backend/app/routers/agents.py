import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Agent, McpServer
from app.schemas import AgentCreate, AgentRead, AgentServerRef, AgentStatusUpdate, AgentUpdate
from app.schemas.agent import AgentStatus

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _to_read(agent: Agent) -> AgentRead:
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
    return [_to_read(a) for a in agents]


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
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    log.info("agent_created", agent_id=str(agent.id), name=agent.name)
    return _to_read(agent)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return _to_read(await _get_agent(session, agent_id))


@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(agent_id: uuid.UUID, data: AgentUpdate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    if agent.status == "archived":
        raise HTTPException(status_code=409, detail="Agent is archived; restore it before editing")

    for field in ("name", "objective", "instructions", "description", "max_steps", "timeout_seconds"):
        value = getattr(data, field)
        if value is not None:
            setattr(agent, field, value)
    if data.mcp_server_ids is not None:
        agent.mcp_servers = await _load_servers(session, data.mcp_server_ids)
    # Changing only the server set touches no column on `agent`, so onupdate would not fire.
    agent.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(agent)
    return _to_read(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    if agent.status not in ("draft", "archived"):
        raise HTTPException(status_code=409, detail=f"Cannot delete a {agent.status} agent; archive it first")
    await session.delete(agent)
    await session.commit()
    log.info("agent_deleted", agent_id=str(agent_id))
