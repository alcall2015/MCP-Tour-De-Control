import asyncio
import pytest

from app.services.scheduler_service import SchedulerService


@pytest.mark.asyncio
async def test_scheduler_starts_and_stops():
    service = SchedulerService(use_db_jobstore=False)
    service.start()
    assert service.scheduler.running
    service.shutdown()
    # AsyncIOScheduler.running becomes False after event loop processes the shutdown
    await asyncio.sleep(0.1)
    assert not service.scheduler.running


@pytest.mark.asyncio
async def test_add_and_remove_job():
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")

    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is not None

    service.remove_job(prompt_id)
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is None

    service.shutdown()


@pytest.mark.asyncio
async def test_pause_and_resume_job():
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")

    service.pause_job(prompt_id)
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job.next_run_time is None  # paused

    service.resume_job(prompt_id)
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job.next_run_time is not None

    service.shutdown()


@pytest.mark.asyncio
async def test_reschedule_job():
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")

    service.reschedule_job(prompt_id, "0 12 * * *")
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is not None  # still exists with new schedule

    service.shutdown()


@pytest.mark.asyncio
async def test_remove_nonexistent_job_does_not_raise():
    """Removing a job that doesn't exist should not raise."""
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    # Should not raise
    service.remove_job(prompt_id)

    service.shutdown()


@pytest.mark.asyncio
async def test_pause_nonexistent_job_does_not_raise():
    """Pausing a job that doesn't exist should not raise."""
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    # Should not raise
    service.pause_job(prompt_id)

    service.shutdown()


@pytest.mark.asyncio
async def test_resume_nonexistent_job_does_not_raise():
    """Resuming a job that doesn't exist should not raise."""
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    # Should not raise
    service.resume_job(prompt_id)

    service.shutdown()


@pytest.mark.asyncio
async def test_reschedule_nonexistent_job_adds_it():
    """Rescheduling a job that doesn't exist should add it instead."""
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.reschedule_job(prompt_id, "0 12 * * *")
    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is not None

    service.shutdown()


@pytest.mark.asyncio
async def test_add_job_replace_existing():
    """Adding a job with same prompt_id replaces the existing one."""
    service = SchedulerService(use_db_jobstore=False)
    service.start()

    import uuid
    prompt_id = uuid.uuid4()
    service.add_job(prompt_id, "0 8 * * *")
    service.add_job(prompt_id, "0 12 * * *")  # Should replace, not error

    job = service.scheduler.get_job(f"prompt_{prompt_id}")
    assert job is not None

    service.shutdown()


@pytest.mark.asyncio
async def test_the_three_tmlite_jobs_do_not_fire_on_the_same_tick():
    # The scheduler must be started before get_job() can see the jobs: until
    # then APScheduler holds them as pending and get_job() returns None.
    # Their start dates are minutes out, so none of them actually fires here.
    service = SchedulerService(use_db_jobstore=False)
    service.start()
    try:
        service.set_pairing_job()
        service.set_pair_conversation_job()
        service.set_sms_auto_reply_job()

        starts = {
            job_id: service.scheduler.get_job(job_id).trigger.start_date
            for job_id in (
                SchedulerService.PAIRING_JOB_ID,
                SchedulerService.PAIR_CONVERSATION_JOB_ID,
                SchedulerService.SMS_AUTO_REPLY_JOB_ID,
            )
        }
    finally:
        service.shutdown()

    assert len(set(starts.values())) == 3, "two jobs share a start time"

    ordered = sorted(starts.values())
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(ordered, ordered[1:])]
    assert all(gap >= 4 for gap in gaps), f"jobs are less than 4 minutes apart: {gaps}"


def test_every_offset_stays_inside_one_cycle():
    # An offset at or beyond the interval would silently delay a job by a whole
    # cycle rather than shifting it within one. Zero is not usable either: it
    # makes start_date equal "now", which APScheduler reads as already elapsed
    # and pushes the first fire out by a full interval.
    assert all(0 < minutes < 15 for minutes in SchedulerService.JOB_OFFSET_MINUTES.values())
