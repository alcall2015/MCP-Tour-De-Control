import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import McpServer
from app.schemas import McpServerCreate, McpServerRead, McpServerUpdate, McpTestResult
from app.services.mcp_service import McpService
from app.utils.crypto import encrypt_value

router = APIRouter(prefix="/api/v1/mcp-servers", tags=["mcp-servers"])


def _server_to_read(server: McpServer) -> McpServerRead:
    return McpServerRead(
        id=server.id,
        name=server.name,
        transport=server.transport,
        command=server.command,
        args=server.args,
        env=server.env,
        url=server.url,
        api_key_set=bool(server.api_key),
        enabled=server.enabled,
        created_at=server.created_at,
    )


@router.get("", response_model=list[McpServerRead])
async def list_servers(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(McpServer).order_by(McpServer.created_at.desc()))
    return [_server_to_read(s) for s in result.scalars().all()]


@router.post("", response_model=McpServerRead, status_code=201)
async def create_server(data: McpServerCreate, session: AsyncSession = Depends(get_async_session)):
    dump = data.model_dump()
    if dump.get("api_key"):
        dump["api_key"] = encrypt_value(dump["api_key"])
    server = McpServer(**dump)
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return _server_to_read(server)


@router.get("/{server_id}", response_model=McpServerRead)
async def get_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _server_to_read(server)


@router.put("/{server_id}", response_model=McpServerRead)
async def update_server(server_id: uuid.UUID, data: McpServerUpdate, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "api_key" and value is not None:
            value = encrypt_value(value)
        setattr(server, field, value)
    await session.commit()
    await session.refresh(server)
    return _server_to_read(server)


@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await session.delete(server)
    await session.commit()


@router.post("/{server_id}/test", response_model=McpTestResult)
async def test_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return await McpService.test_connection(server)
