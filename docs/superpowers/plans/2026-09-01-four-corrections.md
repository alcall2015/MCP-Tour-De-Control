# Four Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four open defects found during the SMS auto-reply build: colliding scheduler jobs, a leaked external wire format that can fail silently, a permanently broken test suite, and unbounded archived-pair growth.

**Architecture:** Four independent corrections, one per task, in ascending order of blast radius. Nothing here changes what any feature does — each is about the system being honest when it breaks, or not breaking in the first place.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, APScheduler 3, FastMCP client, pytest.

## Global Constraints

- Business logic lives in `app/services/`; routers stay thin and declare `APIRouter(prefix="/api/v1/<resource>")`.
- One file per entity across `models/`, `schemas/`, `routers/`, `services/`. Every model must be exported from `app/models/__init__.py` or Alembic autogenerate misses it. Model changes require a migration.
- Migrations are written by hand: `alembic revision --autogenerate` in this repo always proposes dropping `apscheduler_jobs` and `ix_chat_message_conversation_id`, and applying that wipes every persisted cron job.
- Code, comments, UI and docs in English.
- Conventional Commits.
- This branch starts from commit `7b1b50e`, where the suite reports **278 passed, 7 failed**. The 7 are the subject of Task 3; until it lands, that is the expected baseline. After Task 3 there must be **zero** failures. Each task states the count it should reach — if yours does not match, stop and reconcile before continuing rather than adjusting the expectation.
- The venv is `backend/venv`; `backend/tests/conftest.py` needs the local Postgres, which is running.

---

### Task 1: Stagger the scheduler jobs

**Files:**
- Modify: `backend/app/services/scheduler_service.py`
- Test: `backend/tests/test_scheduler_service.py`

**The defect:** `set_pairing_job()`, `set_pair_conversation_job()` and `set_sms_auto_reply_job()` are all registered in `main.py`'s lifespan with a bare `IntervalTrigger(minutes=15)`. APScheduler anchors an interval trigger at registration time, so all three run within the same second, for the life of the process. Each opens its own FastMCP client to the external TmLite service and pages `list_sims` in full, so every fifteen minutes TmLite receives three simultaneous full-fleet enumerations plus whatever else each job does. They also contend for the same SIMs: work one job defers because a SIM is busy is often work another job just started.

**Interfaces:**
- Consumes: nothing
- Produces: `SchedulerService.JOB_OFFSET_MINUTES: dict[str, int]` mapping each job id to its offset within the fifteen-minute cycle; the three setters unchanged in name and signature.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_scheduler_service.py`:

```python
def test_the_three_tmlite_jobs_do_not_fire_on_the_same_tick():
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
    # cycle rather than shifting it within one.
    assert all(0 <= minutes < 15 for minutes in SchedulerService.JOB_OFFSET_MINUTES.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_scheduler_service.py -v -k "same_tick or one_cycle"`
Expected: FAIL — `AttributeError: type object 'SchedulerService' has no attribute 'JOB_OFFSET_MINUTES'`, and the start dates are identical.

- [ ] **Step 3: Implement the offsets**

In `backend/app/services/scheduler_service.py`, add `from datetime import datetime, timedelta, timezone` to the imports if absent, then inside `SchedulerService`, below the existing job id constants:

```python
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
```

Then rewrite the three setters to use it, leaving their names and signatures alone:

```python
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
```

Note the constants are referenced bare (`PAIRING_JOB_ID`, not `self.PAIRING_JOB_ID`) inside the class-body dict, because `self` does not exist there. Place `JOB_OFFSET_MINUTES` **after** the three id constants in the class body or it will raise `NameError` at import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_scheduler_service.py -v`
Expected: all pass, including the pre-existing scheduler tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scheduler_service.py backend/tests/test_scheduler_service.py
git commit -m "fix(scheduler): stagger the three TmLite jobs inside the cycle"
```

---

### Task 2: Put the TmLite date format back behind the adapter

**Files:**
- Modify: `backend/app/services/tmlite_shapes.py`, `backend/app/services/sms_auto_reply_service.py`
- Test: `backend/tests/test_tmlite_shapes.py`, `backend/tests/test_sms_auto_reply_service.py`

**The defect:** `tmlite_shapes.py` exists so that every assumption about TmLite's wire format lives in one file. Two assumptions escaped into `SmsAutoReplyService`: `_naive_iso()` encodes TmLite's date dialect, and `_recent_sms()` reads the raw key `received_at` directly to decide where its window ends.

The second is the dangerous one. The comparison is `str(row.get("received_at") or "") < cutoff`. If TmLite renames that field, `row.get` returns `None`, the expression becomes `"" < cutoff` which is **True**, the loop returns on its very first row, and the feature processes nothing — forever, with no error, no log and a green health check. That is precisely the silent failure the adapter layer was introduced to prevent.

**Interfaces:**
- Consumes: the existing `_first()` helper in `tmlite_shapes.py`
- Produces: `naive_iso(when: datetime) -> str` and `sms_is_older_than(raw: dict, cutoff: str) -> bool` in `tmlite_shapes.py`. `sms_is_older_than` returns `False` when no timestamp field can be found.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_tmlite_shapes.py`:

```python
from datetime import datetime, timezone

from app.services.tmlite_shapes import naive_iso, sms_is_older_than


def test_naive_iso_emits_no_offset():
    # TmLite's from_date answers a facade 500 when given an offset.
    stamped = naive_iso(datetime(2026, 9, 1, 13, 5, 9, tzinfo=timezone.utc))
    assert stamped == "2026-09-01T13:05:09"
    assert "+" not in stamped and "Z" not in stamped


def test_a_row_older_than_the_cutoff_is_older():
    assert sms_is_older_than({"received_at": "2026-09-01T12:00:00"}, "2026-09-01T13:00:00")


def test_a_row_newer_than_the_cutoff_is_not_older():
    assert not sms_is_older_than({"received_at": "2026-09-01T14:00:00"}, "2026-09-01T13:00:00")


def test_a_row_whose_timestamp_field_was_renamed_is_never_treated_as_old():
    # The whole point: a missing timestamp must not silently end the window and
    # kill the feature. Keeping the row costs one extra page; dropping it costs
    # everything.
    assert not sms_is_older_than({"stamped_at": "2026-09-01T12:00:00"}, "2026-09-01T13:00:00")
    assert not sms_is_older_than({}, "2026-09-01T13:00:00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_tmlite_shapes.py -v`
Expected: FAIL with `ImportError: cannot import name 'naive_iso' from 'app.services.tmlite_shapes'`

- [ ] **Step 3: Move both assumptions into the adapter**

Add to `backend/app/services/tmlite_shapes.py` (it needs `from datetime import datetime, timezone` at the top):

```python
def naive_iso(when: datetime) -> str:
    """TmLite's from_date rejects an offset with a facade 500 rather than a
    validation error, so it must be given a naive ISO timestamp."""
    return when.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def sms_is_older_than(raw: dict, cutoff: str) -> bool:
    """Is this inbound SMS older than the window's cutoff?

    Returns False when no timestamp field can be found. That direction is
    deliberate: a caller uses this to stop paging, so answering "old" for an
    unrecognised row would end the window at the very first row and silently
    process nothing at all. Answering "not old" costs an extra page instead.
    """
    stamped = _first(raw, "received_at", "created_at")
    if stamped is None:
        return False
    return str(stamped) < cutoff
```

- [ ] **Step 4: Use them from the service**

In `backend/app/services/sms_auto_reply_service.py`, extend the import to
`from app.services.tmlite_shapes import naive_iso, normalize_call, normalize_sms, sim_index, sms_is_older_than`,
delete the `_naive_iso` static method entirely, replace its two call sites in `_recent_calls` and `_recent_sms` with `naive_iso(since)`, and replace the cutoff comparison in `_recent_sms` with:

```python
            for row in batch:
                if sms_is_older_than(row, cutoff):
                    return rows
                rows.append(row)
```

- [ ] **Step 5: Run the full suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -q`
Expected: **284 passed, 7 failed** — 280 after Task 1, plus these 4; the 7 pre-existing failures are still there (Task 3 removes them). The existing `test_the_fetchers_ask_for_only_the_configured_window` must still pass: it asserts `from_date` carries no offset, which now comes from `naive_iso`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/tmlite_shapes.py backend/app/services/sms_auto_reply_service.py \
        backend/tests/test_tmlite_shapes.py
git commit -m "fix(sms-reply): keep TmLite's date dialect inside the adapter"
```

---

### Task 3: Stop the suite failing on a missing interpreter

**Files:**
- Modify: `backend/app/services/script_executor.py`, `backend/app/config.py`
- Test: `backend/tests/test_script_executor.py`

**The defect:** `ScriptExecutor.run()` spawns `"python", "-c", script.code`. On any machine where the executable is named `python3` — every current macOS, most modern Linux distributions — that raises `FileNotFoundError`, the execution is recorded as `failed`, and **7 tests fail on every run**. They have been failing for months. A permanently red suite is worse than the bug it reports: it trains everyone to ignore the failure list, which is where the next real regression will appear.

There is also a correctness point hiding behind the cosmetic one. Generated scripts import `fastmcp`, `openai` and the other runtime dependencies. Those live in the backend's own environment, so the interpreter that must run them is the one running the backend — not whatever `python` happens to resolve to on `PATH`.

**Interfaces:**
- Consumes: nothing
- Produces: `settings.SCRIPT_PYTHON: str` (empty means "use the running interpreter")

- [ ] **Step 1: Run the failing tests and read the failure**

Run: `cd backend && venv/bin/python -m pytest tests/test_script_executor.py -q`
Expected: 6 failed. At least one shows `error="[Errno 2] No such file or directory: 'python'"` in captured stdout. Confirm that is the cause before changing anything — do not fix a different bug.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_script_executor.py`:

```python
import sys

from app.services.script_executor import ScriptExecutor


def test_the_interpreter_is_the_one_running_the_backend():
    # Generated scripts import fastmcp and openai, which live in this
    # environment. Resolving "python" from PATH finds a different interpreter
    # or, on macOS, none at all.
    assert ScriptExecutor._interpreter() == sys.executable
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_script_executor.py::test_the_interpreter_is_the_one_running_the_backend -v`
Expected: FAIL with `AttributeError: type object 'ScriptExecutor' has no attribute '_interpreter'`

- [ ] **Step 4: Implement**

Add to `backend/app/config.py` inside `Settings`, above `model_config`:

```python
    # Empty means "the interpreter running this backend", which is the only one
    # guaranteed to have the generated scripts' dependencies installed.
    SCRIPT_PYTHON: str = ""
```

In `backend/app/services/script_executor.py`, add `import sys` and `from app.config import settings` if either is absent, then add the resolver to the class:

```python
    @staticmethod
    def _interpreter() -> str:
        return settings.SCRIPT_PYTHON or sys.executable
```

and change the spawn from `"python", "-c", script.code` to:

```python
                ScriptExecutor._interpreter(), "-c", script.code,
```

- [ ] **Step 5: Run the whole suite — it must be fully green**

Run: `cd backend && venv/bin/python -m pytest tests/ -q`
Expected: **292 passed, 0 failed** — 284, plus this task's 1 new test, plus the 7 that were failing and now pass. Zero failures is the task's real deliverable. If anything still fails, it is a genuine defect that was hidden behind the interpreter error — read it and report it rather than adjusting the expectation.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/script_executor.py backend/app/config.py backend/tests/test_script_executor.py
git commit -m "fix(executor): run generated scripts with the backend's own interpreter"
```

---

### Task 4: Retention for archived pairs

**Files:**
- Create: `backend/app/services/sim_pairing_retention.py`
- Create: `backend/alembic/versions/e5f6a7b8c9d0_add_pairing_archive_retention.py`
- Modify: `backend/app/models/config.py`, `backend/app/schemas/config.py`, `backend/app/routers/config.py`, `backend/app/services/scheduler_service.py`
- Test: `backend/tests/test_sim_pairing_retention.py`

**The defect:** pairs are archived and never deleted, by design — but nothing ever removes them, and each carries rows in three other tables. Production holds 34 archived pairs against 10 active ones after a few days. None of `sim_pair_message`, `sim_pair_history` or `sim_pair_message_queue` declares a foreign key to `sim_pair`, so deleting a pair on its own would leave orphans that nothing would ever find again. All four tables must be cleared together, children first.

**Interfaces:**
- Consumes: nothing
- Produces: `purge_archived_pairs(session, retention_days: int) -> dict` returning `{"pairs": int, "messages": int, "history": int, "queue": int}`; `Config.pairing_archive_retention_days: int`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sim_pairing_retention.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue
from app.services.sim_pairing_retention import purge_archived_pairs


def _pair(session, *, status, archived_days_ago=None):
    pair = SimPair(
        id=uuid.uuid4(), sim_a_id=1, sim_b_id=2, sim_a_name="Aminata", sim_b_name="Adama",
        country="GUINEA", group_a="g", group_b="g", topic="love", status=status,
        archived_at=None if archived_days_ago is None
        else datetime.now(timezone.utc) - timedelta(days=archived_days_ago),
    )
    session.add(pair)
    session.add(SimPairMessage(pair_id=pair.id, from_sim_id=1, to_sim_id=2,
                               content="x", model="m", status="sent"))
    session.add(SimPairHistory(pair_id=pair.id, event="created"))
    session.add(SimPairMessageQueue(pair_id=pair.id, due_at=datetime.now(timezone.utc)))
    return pair


async def test_an_old_archived_pair_is_removed_from_all_four_tables(session):
    pair = _pair(session, status="archived", archived_days_ago=100)
    await session.commit()

    removed = await purge_archived_pairs(session, retention_days=90)

    assert removed == {"pairs": 1, "messages": 1, "history": 1, "queue": 1}
    for model in (SimPair, SimPairMessage, SimPairHistory, SimPairMessageQueue):
        rows = (await session.execute(select(model))).scalars().all()
        assert rows == [], f"{model.__name__} still holds a row for the purged pair"


async def test_a_recently_archived_pair_is_kept(session):
    _pair(session, status="archived", archived_days_ago=10)
    await session.commit()
    assert await purge_archived_pairs(session, retention_days=90) == {
        "pairs": 0, "messages": 0, "history": 0, "queue": 0}


async def test_an_active_pair_is_never_purged_however_old(session):
    pair = _pair(session, status="active")
    pair.created_at = datetime.now(timezone.utc) - timedelta(days=999)
    await session.commit()
    assert (await purge_archived_pairs(session, retention_days=1))["pairs"] == 0


async def test_zero_retention_disables_the_purge(session):
    _pair(session, status="archived", archived_days_ago=9999)
    await session.commit()
    assert await purge_archived_pairs(session, retention_days=0) == {
        "pairs": 0, "messages": 0, "history": 0, "queue": 0}


async def test_an_archived_pair_with_no_archived_at_is_left_alone(session):
    # Rows predating the archived_at column must not be deleted on a guess.
    _pair(session, status="archived", archived_days_ago=None)
    await session.commit()
    assert (await purge_archived_pairs(session, retention_days=1))["pairs"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_sim_pairing_retention.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.sim_pairing_retention'`

- [ ] **Step 3: Write the retention service**

Create `backend/app/services/sim_pairing_retention.py`:

```python
"""Delete archived SIM pairs once they are older than the retention window.

None of sim_pair_message, sim_pair_history or sim_pair_message_queue declares a
foreign key to sim_pair, so there is no cascade to rely on: removing a pair
without its children would leave rows nothing can ever find again. All four
tables are cleared in one transaction, children first.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select

from app.models import SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue

log = structlog.get_logger()


async def purge_archived_pairs(session, retention_days: int) -> dict:
    empty = {"pairs": 0, "messages": 0, "history": 0, "queue": 0}
    # Zero means keep everything. An archived pair with no archived_at predates
    # that column, and its age is unknown — never guess and delete.
    if retention_days <= 0:
        return empty

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pair_ids = list((await session.execute(
        select(SimPair.id).where(
            SimPair.status == "archived",
            SimPair.archived_at.is_not(None),
            SimPair.archived_at < cutoff,
        )
    )).scalars())
    if not pair_ids:
        return empty

    removed = dict(empty)
    for key, model in (("messages", SimPairMessage), ("history", SimPairHistory),
                       ("queue", SimPairMessageQueue)):
        result = await session.execute(delete(model).where(model.pair_id.in_(pair_ids)))
        removed[key] = result.rowcount or 0
    result = await session.execute(delete(SimPair).where(SimPair.id.in_(pair_ids)))
    removed["pairs"] = result.rowcount or 0

    await session.commit()
    log.info("Purged archived SIM pairs", retention_days=retention_days, **removed)
    return removed
```

- [ ] **Step 4: Add the setting and its migration**

In `backend/app/models/config.py`, add to `Config` beside the other pairing fields:

```python
    # 0 keeps archived pairs forever. Deleting one removes its messages,
    # history and queue rows too — there is no foreign key to cascade.
    pairing_archive_retention_days: Mapped[int] = mapped_column(Integer, default=90)
```

Create `backend/alembic/versions/e5f6a7b8c9d0_add_pairing_archive_retention.py`:

```python
"""add pairing archive retention

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("config", sa.Column("pairing_archive_retention_days", sa.Integer(),
                                      nullable=False, server_default="90"))


def downgrade() -> None:
    op.drop_column("config", "pairing_archive_retention_days")
```

Add the field to `ConfigRead` and `ConfigUpdate` in `backend/app/schemas/config.py`, map it in `_to_read` in `backend/app/routers/config.py`, and validate it there:

```python
    if data.pairing_archive_retention_days is not None:
        if not 0 <= data.pairing_archive_retention_days <= 3650:
            raise HTTPException(status_code=422,
                                detail="pairing_archive_retention_days must be between 0 and 3650")
        config.pairing_archive_retention_days = data.pairing_archive_retention_days
```

- [ ] **Step 5: Run it from the existing sync job**

No new scheduler job — the purge belongs to the pairing cycle that already runs. In `backend/app/services/scheduler_service.py`, extend `_execute_sim_pairing_sync`:

```python
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
```

Leave the rest of that function as it is, including its lack of a try/except — that is tracked separately.

- [ ] **Step 6: Run the tests and the migration**

Run: `cd backend && venv/bin/python -m pytest tests/test_sim_pairing_retention.py tests/test_api_config.py -v`
Expected: all pass
Run: `cd backend && PYTHONPATH=. venv/bin/alembic upgrade head && PYTHONPATH=. venv/bin/alembic current`
Expected: `e5f6a7b8c9d0 (head)`
Run: `cd backend && venv/bin/python -m pytest tests/ -q`
Expected: **297 passed, 0 failed** (292 after Task 3, plus these 5).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/sim_pairing_retention.py backend/app/models/config.py \
        backend/app/schemas/config.py backend/app/routers/config.py \
        backend/app/services/scheduler_service.py \
        backend/alembic/versions/e5f6a7b8c9d0_add_pairing_archive_retention.py \
        backend/tests/test_sim_pairing_retention.py
git commit -m "feat(pairing): purge archived pairs past the retention window"
```

---

## Deployment

Production is deployed by copying tracked files, not by `git pull`, and its working tree carries local state — never assume `main` is what it serves.

```bash
H=root@46.225.115.154; D=/opt/mcp-tour-de-control
ssh $H "cd $D && docker compose exec -T postgres pg_dump -U mcp -d mcp_control > /root/backup-before-corrections.sql"
git archive HEAD -- backend/app backend/alembic | ssh $H "tar -x -C $D"
ssh $H "cd $D && docker compose build backend && docker compose up -d backend"
ssh $H "cd $D && docker compose exec -T postgres psql -U mcp -d mcp_control -tAc 'select version_num from alembic_version'"
```

Expected: `e5f6a7b8c9d0`.

Task 4 deletes production data the first time the sync job runs after deploy. **Before deploying it**, decide the retention value and check what it would remove:

```sql
select count(*) from sim_pair
 where status = 'archived' and archived_at is not null
   and archived_at < now() - interval '90 days';
```

The shipped default is 90 days. Production's oldest archived pairs are days old, so the first purge will delete nothing — the setting exists for months from now, not for this deploy.
