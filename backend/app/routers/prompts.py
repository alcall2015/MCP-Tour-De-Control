import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_session
from app.models import Config, McpServer, Prompt, Script
from app.schemas import PromptCreate, PromptRead, PromptUpdate, ScriptRead
from app.services.llm_service import LlmService
from app.services.mcp_service import McpService
from app.services.scheduler_service import scheduler_service
from app.utils.crypto import decrypt_value

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.get("", response_model=list[PromptRead])
async def list_prompts(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Prompt).options(selectinload(Prompt.scripts)).order_by(Prompt.created_at.desc())
    )
    prompts = result.scalars().all()
    out = []
    for p in prompts:
        latest = max(p.scripts, key=lambda s: s.version, default=None)
        out.append(PromptRead(
            id=p.id, name=p.name, description=p.description,
            prompt_text=p.prompt_text, cron_expr=p.cron_expr,
            enabled=p.enabled, created_at=p.created_at, updated_at=p.updated_at,
            latest_script_version=latest.version if latest else None,
            needs_llm=latest.needs_llm if latest else None,
        ))
    return out


@router.post("", response_model=PromptRead, status_code=201)
async def create_prompt(data: PromptCreate, session: AsyncSession = Depends(get_async_session)):
    # Get config for LLM
    config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
    if not config or not config.api_key:
        raise HTTPException(status_code=400, detail="LLM not configured. Set API key in Config first.")

    # Get selected MCP servers and their tools
    servers = []
    for sid in data.mcp_server_ids:
        server = await session.get(McpServer, sid)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server {sid} not found")
        tools = await McpService.get_server_tools(server)
        servers.append({
            "name": server.name,
            "transport": server.transport,
            "command": server.command,
            "args": server.args or [],
            "url": server.url,
            "tools": tools,
        })

    # Create prompt
    prompt = Prompt(
        name=data.name, description=data.description,
        prompt_text=data.prompt_text, cron_expr=data.cron_expr, enabled=data.enabled,
    )
    session.add(prompt)
    await session.commit()
    await session.refresh(prompt)

    # Generate script
    script_version = None
    script_needs_llm = None
    try:
        api_key = decrypt_value(config.api_key)
        code, needs_llm, llm_steps = await LlmService.generate_script(
            prompt_text=data.prompt_text,
            mcp_servers_info=servers,
            api_key=api_key,
            llm_provider=config.llm_provider,
            llm_model=config.llm_model,
        )
        script = Script(
            prompt_id=prompt.id, version=1, code=code,
            needs_llm=needs_llm, llm_steps=llm_steps,
        )
        session.add(script)
        await session.commit()
        script_version = 1
        script_needs_llm = needs_llm
    except Exception as e:
        log.error("Script generation failed", prompt_id=str(prompt.id), error=str(e))
        # Prompt is saved, but no script — user can retry via regenerate

    # Schedule cron job if cron_expr is set and prompt is enabled
    if prompt.cron_expr and prompt.enabled:
        scheduler_service.add_job(prompt.id, prompt.cron_expr)

    return PromptRead(
        id=prompt.id, name=prompt.name, description=prompt.description,
        prompt_text=prompt.prompt_text, cron_expr=prompt.cron_expr,
        enabled=prompt.enabled, created_at=prompt.created_at, updated_at=prompt.updated_at,
        latest_script_version=script_version,
        needs_llm=script_needs_llm,
    )


@router.get("/{prompt_id}", response_model=PromptRead)
async def get_prompt(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Prompt).options(selectinload(Prompt.scripts)).where(Prompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    latest = max(prompt.scripts, key=lambda s: s.version, default=None)
    return PromptRead(
        id=prompt.id, name=prompt.name, description=prompt.description,
        prompt_text=prompt.prompt_text, cron_expr=prompt.cron_expr,
        enabled=prompt.enabled, created_at=prompt.created_at, updated_at=prompt.updated_at,
        latest_script_version=latest.version if latest else None,
        needs_llm=latest.needs_llm if latest else None,
    )


@router.put("/{prompt_id}", response_model=PromptRead)
async def update_prompt(prompt_id: uuid.UUID, data: PromptUpdate, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    old_cron_expr = prompt.cron_expr
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(prompt, field, value)
    await session.commit()
    await session.refresh(prompt)

    # If cron_expr changed, reschedule or add job
    if data.cron_expr is not None and data.cron_expr != old_cron_expr:
        if prompt.cron_expr and prompt.enabled:
            scheduler_service.reschedule_job(prompt.id, prompt.cron_expr)
        elif not prompt.cron_expr:
            scheduler_service.remove_job(prompt.id)

    return PromptRead(
        id=prompt.id, name=prompt.name, description=prompt.description,
        prompt_text=prompt.prompt_text, cron_expr=prompt.cron_expr,
        enabled=prompt.enabled, created_at=prompt.created_at, updated_at=prompt.updated_at,
        latest_script_version=None,
        needs_llm=None,
    )


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    scheduler_service.remove_job(prompt_id)
    await session.delete(prompt)
    await session.commit()


@router.put("/{prompt_id}/toggle", response_model=PromptRead)
async def toggle_prompt(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt.enabled = not prompt.enabled
    await session.commit()
    await session.refresh(prompt)

    # Pause or resume cron job based on new enabled state
    if prompt.cron_expr:
        if prompt.enabled:
            scheduler_service.resume_job(prompt.id)
        else:
            scheduler_service.pause_job(prompt.id)

    return PromptRead(
        id=prompt.id, name=prompt.name, description=prompt.description,
        prompt_text=prompt.prompt_text, cron_expr=prompt.cron_expr,
        enabled=prompt.enabled, created_at=prompt.created_at, updated_at=prompt.updated_at,
        latest_script_version=None,
        needs_llm=None,
    )


@router.post("/{prompt_id}/regenerate", response_model=ScriptRead)
async def regenerate_script(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    prompt = await session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
    if not config or not config.api_key:
        raise HTTPException(status_code=400, detail="LLM not configured")

    # Get MCP servers (all enabled)
    servers_result = await session.execute(select(McpServer).where(McpServer.enabled == True))
    servers_info = []
    for server in servers_result.scalars().all():
        tools = await McpService.get_server_tools(server)
        servers_info.append({
            "name": server.name, "transport": server.transport,
            "command": server.command, "args": server.args or [],
            "url": server.url, "tools": tools,
        })

    api_key = decrypt_value(config.api_key)
    code, needs_llm, llm_steps = await LlmService.generate_script(
        prompt_text=prompt.prompt_text,
        mcp_servers_info=servers_info,
        api_key=api_key,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
    )

    # Get next version number
    max_version = await session.execute(
        select(func.max(Script.version)).where(Script.prompt_id == prompt_id)
    )
    current_max = max_version.scalar() or 0

    script = Script(
        prompt_id=prompt.id, version=current_max + 1,
        code=code, needs_llm=needs_llm, llm_steps=llm_steps,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)
    return script


@router.get("/{prompt_id}/scripts", response_model=list[ScriptRead])
async def list_prompt_scripts(prompt_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(
        select(Script).where(Script.prompt_id == prompt_id).order_by(Script.version.desc())
    )
    return result.scalars().all()
