from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.database import async_session
from app.models import McpServer, Prompt
from app.routers import chat as chat_router
from app.routers import config as config_router
from app.routers import executions as executions_router
from app.routers import mcp_servers as mcp_servers_router
from app.routers import projects as projects_router
from app.routers import prompts as prompts_router
from app.routers import scripts as scripts_router
from app.routers import stress_tests as stress_tests_router
from app.services.scheduler_service import scheduler_service

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting MCP Tour De Control")
    scheduler_service.start()

    # Reload cron jobs from DB on startup
    try:
        async with async_session() as session:
            result = await session.execute(
                select(Prompt).where(Prompt.enabled == True, Prompt.cron_expr.isnot(None))
            )
            for prompt in result.scalars().all():
                scheduler_service.add_job(prompt.id, prompt.cron_expr)
                log.info("Restored cron job", prompt_id=str(prompt.id), cron=prompt.cron_expr)
    except Exception as exc:
        log.error("Failed to restore cron jobs from DB", error=str(exc))

    # Schedule the daily projects refresh from the stored cron expression
    try:
        async with async_session() as session:
            from app.models import Config

            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            cron_expr = config.projects_cron if config else "0 6 * * *"
            scheduler_service.set_projects_job(cron_expr)
            log.info("Projects refresh scheduled", cron=cron_expr)
    except Exception as exc:
        log.error("Failed to schedule projects refresh", error=str(exc))

    # Auto-register or update sipp-stress MCP server
    try:
        async with async_session() as session:
            from app.config import settings as app_settings
            result = await session.execute(
                select(McpServer).where(McpServer.name == "sipp-stress")
            )
            existing = result.scalar_one_or_none()
            if existing:
                if existing.url != app_settings.SIPP_MCP_URL:
                    existing.url = app_settings.SIPP_MCP_URL
                    await session.commit()
                    log.info("Updated sipp-stress MCP server URL", url=app_settings.SIPP_MCP_URL)
            else:
                sipp_server = McpServer(
                    name="sipp-stress",
                    transport="http",
                    url=app_settings.SIPP_MCP_URL,
                    enabled=True,
                )
                session.add(sipp_server)
                await session.commit()
                log.info("Auto-registered sipp-stress MCP server", url=app_settings.SIPP_MCP_URL)
    except Exception as exc:
        log.warning("Failed to auto-register sipp-stress", error=str(exc))

    yield

    scheduler_service.shutdown()
    log.info("Shutting down MCP Tour De Control")


app = FastAPI(title="MCP Tour De Control", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router.router)
app.include_router(executions_router.router)
app.include_router(mcp_servers_router.router)
app.include_router(prompts_router.router)
app.include_router(scripts_router.router)
app.include_router(stress_tests_router.router)
app.include_router(chat_router.router)
app.include_router(projects_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
