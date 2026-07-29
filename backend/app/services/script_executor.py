import asyncio
import json
import time
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import re

from app.config import settings
from app.models import Config, Execution, McpServer, Script
from app.utils.crypto import decrypt_value

log = structlog.get_logger()


class ScriptExecutor:
    @staticmethod
    async def run(script: Script, session: AsyncSession, timeout: int | None = None) -> Execution:
        timeout = timeout or settings.DEFAULT_SCRIPT_TIMEOUT

        # Create execution record
        execution = Execution(script_id=script.id, status="running")
        session.add(execution)
        await session.commit()
        await session.refresh(execution)

        start_time = time.monotonic()

        # Build environment variables
        env = await ScriptExecutor._build_env(session)

        try:
            process = await asyncio.create_subprocess_exec(
                "python", "-c", script.code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                execution.status = "timeout"
                execution.error = f"Script timed out after {timeout}s"
                execution.finished_at = datetime.now(timezone.utc)
                execution.duration_ms = int((time.monotonic() - start_time) * 1000)
                await session.commit()
                return execution

            duration_ms = int((time.monotonic() - start_time) * 1000)
            execution.duration_ms = duration_ms
            execution.finished_at = datetime.now(timezone.utc)

            if process.returncode != 0:
                execution.status = "failed"
                execution.error = stderr.decode("utf-8", errors="replace")
                await session.commit()
                return execution

            # Parse output
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            try:
                # Take the last line as JSON output
                last_line = stdout_str.strip().split("\n")[-1]
                result = json.loads(last_line)
                execution.status = "success"
                execution.output = result.get("output", stdout_str)
                execution.llm_output = result.get("output") if result.get("llm_used") else None
                execution.tokens_used = result.get("tokens", 0)
            except (json.JSONDecodeError, IndexError):
                execution.status = "success"
                execution.output = stdout_str
                execution.tokens_used = 0

            await session.commit()
            return execution

        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)
            execution.finished_at = datetime.now(timezone.utc)
            execution.duration_ms = int((time.monotonic() - start_time) * 1000)
            await session.commit()
            log.error("Script execution error", script_id=str(script.id), error=str(e))
            return execution

    @staticmethod
    async def _build_env(session: AsyncSession) -> dict:
        import os
        env = os.environ.copy()

        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if config and config.api_key:
            env["LLM_API_KEY"] = decrypt_value(config.api_key)
            env["LLM_PROVIDER"] = config.llm_provider
            env["LLM_MODEL"] = config.llm_model

        # Inject MCP server API keys as MCP_API_KEY_<SERVER_NAME>
        servers = (await session.execute(
            select(McpServer).where(McpServer.api_key.isnot(None))
        )).scalars().all()
        for server in servers:
            env_name = re.sub(r"[^A-Z0-9]", "_", server.name.upper())
            env[f"MCP_API_KEY_{env_name}"] = decrypt_value(server.api_key)

        return env
