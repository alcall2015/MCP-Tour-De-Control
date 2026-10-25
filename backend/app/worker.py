"""Agent task worker: claims queued tasks from Postgres and runs them.

Run with `python -m app.worker`. Shares the backend image and settings."""
import asyncio
import os
import socket

import structlog

from app.config import settings
from app.database import async_session, engine
from app.services.agent_runner import run_task
from app.services.agent_task_service import QUEUED_CHANNEL, AgentTaskService

log = structlog.get_logger()

POLL_SECONDS = 5
SWEEP_SECONDS = 60


class Worker:
    def __init__(self, *, concurrency: int, run=run_task, session_factory=async_session, worker_id: str | None = None):
        self.concurrency = concurrency
        self.run = run
        self.sf = session_factory
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._running: dict = {}          # task_id -> asyncio.Task
        self._wake = asyncio.Event()

    def _free_slots(self) -> int:
        self._running = {tid: t for tid, t in self._running.items() if not t.done()}
        return max(0, self.concurrency - len(self._running))

    async def process_available(self) -> int:
        started = 0
        while self._free_slots() > 0:
            async with self.sf() as session:
                task = await AgentTaskService.claim(session, self.worker_id)
            if task is None:
                break
            log.info("agent_task_claimed", task_id=str(task.id), worker_id=self.worker_id)
            self._running[task.id] = asyncio.create_task(self._run_with_heartbeat(task.id))
            started += 1
        return started

    async def _run_with_heartbeat(self, task_id):
        async def beat():
            while True:
                await asyncio.sleep(settings.AGENT_TASK_HEARTBEAT_SECONDS)
                async with self.sf() as session:
                    await AgentTaskService.heartbeat(session, task_id)
        beater = asyncio.create_task(beat())
        try:
            await self.run(task_id, session_factory=self.sf)
        finally:
            beater.cancel()
            self._wake.set()

    async def sweep(self) -> int:
        async with self.sf() as session:
            return await AgentTaskService.sweep_stale(session, settings.AGENT_TASK_STALE_SECONDS)

    async def close(self):
        for t in self._running.values():
            t.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)

    async def run_forever(self):
        log.info("agent_worker_started", worker_id=self.worker_id, concurrency=self.concurrency)
        await self.sweep()
        async with engine.connect() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.add_listener(QUEUED_CHANNEL, lambda *_: self._wake.set())
            last_sweep = asyncio.get_event_loop().time()
            while True:
                await self.process_available()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                self._wake.clear()
                if asyncio.get_event_loop().time() - last_sweep > SWEEP_SECONDS:
                    await self.sweep()
                    last_sweep = asyncio.get_event_loop().time()


if __name__ == "__main__":
    structlog.configure(processors=[structlog.stdlib.add_log_level, structlog.dev.ConsoleRenderer()])
    asyncio.run(Worker(concurrency=settings.AGENT_WORKER_CONCURRENCY).run_forever())
