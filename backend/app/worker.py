"""Agent task worker: claims queued tasks from Postgres and runs them.

Run with `python -m app.worker`. Shares the backend image and settings."""
import asyncio
import os
import signal
import socket

import structlog

from app.config import settings
from app.database import async_session, engine
from app.models import AgentTask
from app.models.agent_task import OPEN_STATUSES
from app.services.agent_runner import run_task
from app.services.agent_task_service import QUEUED_CHANNEL, AgentTaskService

log = structlog.get_logger()

POLL_SECONDS = 5
SWEEP_SECONDS = 60
# Used only when the task row cannot be read back right after the claim; the
# same value as the agent model's own default.
FALLBACK_TASK_TIMEOUT_SECONDS = 300


class Worker:
    def __init__(self, *, concurrency: int, run=run_task, session_factory=async_session, worker_id: str | None = None):
        self.concurrency = concurrency
        self.run = run
        self.sf = session_factory
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._running: dict = {}          # task_id -> asyncio.Task
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()

    def request_stop(self):
        self._stopping.set()
        self._wake.set()

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
        loop = asyncio.get_running_loop()
        # Past the task's own hard budget the heartbeat stops: a run wedged in a
        # call that never returns would otherwise look alive to the stale sweep
        # forever, and nothing else can reclaim it.
        timeout_seconds = FALLBACK_TASK_TIMEOUT_SECONDS
        try:
            async with self.sf() as session:
                task = await session.get(AgentTask, task_id)
            if task is not None:
                timeout_seconds = task.timeout_seconds
        except Exception as exc:
            log.warning("agent_task_budget_unknown", task_id=str(task_id), error=str(exc))
        hard_stop = loop.time() + timeout_seconds + settings.AGENT_TASK_FINAL_GRACE_SECONDS + settings.LLM_CALL_TIMEOUT_SECONDS

        async def beat():
            while True:
                await asyncio.sleep(settings.AGENT_TASK_HEARTBEAT_SECONDS)
                if loop.time() > hard_stop:
                    log.warning("agent_task_heartbeat_budget_exhausted", task_id=str(task_id),
                                timeout_seconds=timeout_seconds)
                    return
                try:
                    async with self.sf() as session:
                        await AgentTaskService.heartbeat(session, task_id)
                except Exception as exc:
                    log.warning("agent_task_heartbeat_failed", task_id=str(task_id), error=str(exc))
        beater = asyncio.create_task(beat())
        try:
            await self.run(task_id, session_factory=self.sf)
        except Exception as exc:
            # The runner marks the task row itself on a handled failure; this
            # is the backstop for whatever escapes it (e.g. CancelledError is
            # a BaseException and is not caught here on purpose - it must
            # still propagate so task.cancel() in close() actually cancels).
            log.exception("agent_task_run_crashed", task_id=str(task_id))
            try:
                async with self.sf() as session:
                    task = await session.get(AgentTask, task_id)
                    if task is not None and task.status in OPEN_STATUSES:
                        await AgentTaskService.record_step(session, task, "error", {"message": str(exc), "phase": "claim"})
                        await AgentTaskService.finish(session, task, "failed", error=f"claim: {exc}")
            except Exception as mark_exc:
                log.warning("agent_task_mark_failed_error", task_id=str(task_id), error=str(mark_exc))
        finally:
            beater.cancel()
            self._wake.set()

    async def sweep(self) -> int:
        async with self.sf() as session:
            return await AgentTaskService.sweep_stale(session, settings.AGENT_TASK_STALE_SECONDS)

    async def close(self):
        running = dict(self._running)
        for t in running.values():
            t.cancel()
        await asyncio.gather(*running.values(), return_exceptions=True)
        # asyncio.CancelledError is a BaseException: run_task's except clauses
        # (Cancelled/RunFailed/Exception) never catch it, so a task cancelled
        # here would otherwise leave its row stuck on "running" forever.
        if running:
            async with self.sf() as session:
                for task_id in running:
                    task = await session.get(AgentTask, task_id)
                    if task is not None and task.status == "running":
                        await AgentTaskService.finish(session, task, "failed", error="worker stopped")

    async def run_forever(self):
        log.info("agent_worker_started", worker_id=self.worker_id, concurrency=self.concurrency)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except NotImplementedError:  # non-Unix event loops
                pass

        def on_queued(*_):
            self._wake.set()

        last_sweep = loop.time()
        swept_at_start = False
        backoff = 1
        while not self._stopping.is_set():
            try:
                async with engine.connect() as conn:
                    raw = (await conn.get_raw_connection()).driver_connection
                    await raw.add_listener(QUEUED_CHANNEL, on_queued)
                    backoff = 1
                    try:
                        if not swept_at_start:
                            # Inside the retry: a database that is not up yet
                            # must back off, not kill the worker on startup.
                            await self.sweep()
                            last_sweep = loop.time()
                            swept_at_start = True
                        while not self._stopping.is_set():
                            try:
                                await self.process_available()
                            except Exception as exc:
                                log.warning("agent_worker_claim_error", error=str(exc))
                            try:
                                await asyncio.wait_for(self._wake.wait(), timeout=POLL_SECONDS)
                            except asyncio.TimeoutError:
                                pass
                            self._wake.clear()
                            if loop.time() - last_sweep > SWEEP_SECONDS:
                                try:
                                    await self.sweep()
                                except Exception as exc:
                                    log.warning("agent_worker_sweep_error", error=str(exc))
                                last_sweep = loop.time()
                    finally:
                        # Before the connection goes back, like the SSE stream:
                        # a listener left on a returned connection fires into a
                        # closure whose loop may already be gone.
                        await raw.remove_listener(QUEUED_CHANNEL, on_queued)
            except Exception as exc:
                log.warning("agent_worker_listen_error", error=str(exc))
                await asyncio.sleep(min(30, backoff))
                backoff *= 2
        await self.close()
        log.info("agent_worker_stopped", worker_id=self.worker_id)


if __name__ == "__main__":
    structlog.configure(processors=[structlog.stdlib.add_log_level, structlog.dev.ConsoleRenderer()])
    asyncio.run(Worker(concurrency=settings.AGENT_WORKER_CONCURRENCY).run_forever())
