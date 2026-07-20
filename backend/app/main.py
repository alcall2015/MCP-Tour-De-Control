from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import config as config_router
from app.routers import mcp_servers as mcp_servers_router

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
    yield
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
app.include_router(mcp_servers_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
