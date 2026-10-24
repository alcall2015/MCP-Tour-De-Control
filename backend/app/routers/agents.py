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
    for sid in ids:
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
