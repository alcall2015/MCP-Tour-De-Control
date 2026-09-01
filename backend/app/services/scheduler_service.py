import uuid
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

log = structlog.get_logger()

# Convert async DB URL to sync for APScheduler jobstore
_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")


async def _execute_prompt_job(prompt_id: str):
    """Callback executed by APScheduler on each cron tick."""
    from app.database import async_session
    from app.models import Prompt, Script
    from app.services.script_executor import ScriptExecutor
    from sqlalchemy import select

    log.info("Cron job triggered", prompt_id=prompt_id)

    async with async_session() as session:
        prompt = await session.get(Prompt, uuid.UUID(prompt_id))
        if not prompt or not prompt.enabled:
            log.warning("Prompt not found or disabled", prompt_id=prompt_id)
            return

        # Get latest script version
        result = await session.execute(
            select(Script)
            .where(Script.prompt_id == prompt.id)
            .order_by(Script.version.desc())
            .limit(1)
        )
        script = result.scalar_one_or_none()
        if not script:
            log.warning("No script found for prompt", prompt_id=prompt_id)
            return

        execution = await ScriptExecutor.run(script, session)
        log.info("Cron job completed", prompt_id=prompt_id, status=execution.status)


async def _execute_activity_scan():
    """Callback executed by APScheduler to rescan the tracked Drive folder."""
    from app.database import async_session
    from app.services.document_scanner import DocumentScanner

    log.info("Activity scan triggered")
    try:
        async with async_session() as session:
            count = await DocumentScanner.scan_all(session)
        log.info("Activity scan completed", documents=count)
    except Exception as exc:
        log.error("Activity scan failed", error=str(exc))


async def _execute_sim_pairing_sync():
    from app.database import async_session
    from app.models import Config
    from sqlalchemy import select
    from app.services.sim_pairing_service import SimPairingService
    from app.services.sim_pairing_retention import purge_archived_pairs
    async with async_session() as session:
        await SimPairingService.sync(session)
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if config:
            await purge_archived_pairs(session, config.pairing_archive_retention_days)


async def _execute_sim_pair_conversation():
    from app.database import async_session
    from app.services.sim_pair_conversation_service import SimPairConversationService
    try:
        async with async_session() as session:
            summary = await SimPairConversationService.run_due(session)
        log.info("SIM pair conversation run completed", **summary)
    except Exception as exc:
        log.error("SIM pair conversation run failed", error=str(exc))


async def _execute_sms_auto_reply():
    from app.database import async_session
    from app.services.sms_auto_reply_service import SmsAutoReplyService
    try:
        async with async_session() as session:
            summary = await SmsAutoReplyService.run(session)
        log.info("SMS auto-reply run completed", **summary)
    except Exception as exc:
        log.error("SMS auto-reply run failed", error=str(exc))


class SchedulerService:
    def __init__(self, use_db_jobstore: bool = True):
        jobstores = {}
        if use_db_jobstore:
            jobstores["default"] = SQLAlchemyJobStore(url=_sync_db_url)

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )

    def start(self):
        self.scheduler.start()
        log.info("Scheduler started")

    def shutdown(self):
        self.scheduler.shutdown(wait=True)
        log.info("Scheduler stopped")

    def add_job(self, prompt_id: uuid.UUID, cron_expr: str):
        job_id = f"prompt_{prompt_id}"
        self.scheduler.add_job(
            _execute_prompt_job,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=job_id,
            args=[str(prompt_id)],
            replace_existing=True,
        )
        log.info("Job added", job_id=job_id, cron=cron_expr)

    def remove_job(self, prompt_id: uuid.UUID):
        job_id = f"prompt_{prompt_id}"
        try:
            self.scheduler.remove_job(job_id)
            log.info("Job removed", job_id=job_id)
        except Exception:
            log.warning("Job not found for removal", job_id=job_id)

    def pause_job(self, prompt_id: uuid.UUID):
        job_id = f"prompt_{prompt_id}"
        try:
            self.scheduler.pause_job(job_id)
            log.info("Job paused", job_id=job_id)
        except Exception:
            log.warning("Job not found for pause", job_id=job_id)

    def resume_job(self, prompt_id: uuid.UUID):
        job_id = f"prompt_{prompt_id}"
        try:
            self.scheduler.resume_job(job_id)
            log.info("Job resumed", job_id=job_id)
        except Exception:
            log.warning("Job not found for resume", job_id=job_id)

    def reschedule_job(self, prompt_id: uuid.UUID, cron_expr: str):
        job_id = f"prompt_{prompt_id}"
        try:
            self.scheduler.reschedule_job(job_id, trigger=CronTrigger.from_crontab(cron_expr))
            log.info("Job rescheduled", job_id=job_id, cron=cron_expr)
        except Exception:
            log.warning("Job not found for reschedule, adding instead", job_id=job_id)
            self.add_job(prompt_id, cron_expr)

    ACTIVITY_JOB_ID = "activity_scan"
    PAIRING_JOB_ID = "sim_pairing_sync"
    PAIR_CONVERSATION_JOB_ID = "sim_pair_conversation"
    SMS_AUTO_REPLY_JOB_ID = "sms_auto_reply"

    # All three of these talk to the same external TmLite service and the same
    # SIMs. Anchoring them at the same instant means three simultaneous
    # full-fleet enumerations every cycle, and two jobs racing for one SIM.
    # Offsets spread them deterministically inside the fifteen-minute cycle;
    # they must stay below the interval or a job slips a whole cycle.
    JOB_OFFSET_MINUTES = {
        PAIRING_JOB_ID: 0,
        PAIR_CONVERSATION_JOB_ID: 5,
        SMS_AUTO_REPLY_JOB_ID: 10,
    }

    def _interval_trigger(self, job_id: str) -> IntervalTrigger:
        offset = self.JOB_OFFSET_MINUTES[job_id]
        return IntervalTrigger(
            minutes=15,
            start_date=datetime.now(timezone.utc) + timedelta(minutes=offset),
        )

    def set_activity_job(self, cron_expr: str):
        """Create or reschedule the daily activity scan."""
        self.scheduler.add_job(
            _execute_activity_scan,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=self.ACTIVITY_JOB_ID,
            replace_existing=True,
        )
        log.info("Activity job scheduled", cron=cron_expr)

    def set_pairing_job(self):
        self.scheduler.add_job(
            _execute_sim_pairing_sync,
            trigger=self._interval_trigger(self.PAIRING_JOB_ID),
            id=self.PAIRING_JOB_ID,
            replace_existing=True,
        )

    def set_pair_conversation_job(self):
        self.scheduler.add_job(
            _execute_sim_pair_conversation,
            trigger=self._interval_trigger(self.PAIR_CONVERSATION_JOB_ID),
            id=self.PAIR_CONVERSATION_JOB_ID,
            replace_existing=True,
        )

    def set_sms_auto_reply_job(self):
        self.scheduler.add_job(
            _execute_sms_auto_reply,
            trigger=self._interval_trigger(self.SMS_AUTO_REPLY_JOB_ID),
            id=self.SMS_AUTO_REPLY_JOB_ID,
            replace_existing=True,
        )


def is_valid_cron(cron_expr: str) -> bool:
    """Return True if cron_expr can be parsed by APScheduler's CronTrigger."""
    try:
        CronTrigger.from_crontab(cron_expr)
        return True
    except Exception:
        return False


def _make_scheduler_service() -> "SchedulerService":
    """Create the global scheduler service, catching DB errors gracefully."""
    try:
        return SchedulerService(use_db_jobstore=True)
    except Exception as exc:
        log.warning("Could not create DB-backed scheduler, falling back to in-memory", error=str(exc))
        return SchedulerService(use_db_jobstore=False)


# Global instance (uses DB jobstore in production)
scheduler_service = _make_scheduler_service()
