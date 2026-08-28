# SMS Auto-Reply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer inbound SMS from numbers outside the fleet, and follow up the most recent unanswered inbound call, by sending one fixed-template SMS from the same SIM that handled the contact, naming the original caller as a WhatsApp contact.

**Architecture:** A `SmsAutoReplyService` reads TmLite's `list_sms` and `list_calls`, classifies each trigger, resolves the WhatsApp number from the CDR, and sends through `send_sms`. Every reply is recorded in a new `sms_reply` table, guarded twice over: `trigger_ref` is **unique**, so the 15-minute job re-reading an overlapping window can never answer the same event twice; and a per-recipient cooldown stops one person being messaged repeatedly because the same caller tried them several times. Quiet hours are shared with SIM Pairing rather than duplicated.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, APScheduler, FastMCP client, React 19 + TanStack Query.

## Global Constraints

- The reply text is **fixed**, rendered from one configured template. No LLM, no per-message rephrasing, no randomisation of wording. This is deliberate: a notification must read the same every time so a recipient can recognise it for what it is.
- Never message a number that belongs to the fleet — those are SIM Pairing's business.
- Never send a reply whose WhatsApp number could not be resolved; record the skip and its reason instead.
- One reply per trigger, ever, enforced by a database unique constraint — not by application logic alone.
- Reuse the existing quiet window (`Config.pairing_quiet_*`). Do not add a second set of hour settings.
- Code, comments, UI and docs in English. The SMS template itself is French, like the rest of the outbound traffic.
- Conventional Commits. Business logic in `app/services/`, routers thin, every model exported from `app/models/__init__.py`, model change means a migration.
- `alembic revision --autogenerate` in this repo always proposes dropping `apscheduler_jobs` and `ix_chat_message_conversation_id`. Both are wrong — write the migration by hand instead.

## Verified against production, 2026-08-28

The wire shapes below were read from the live TmLite, not guessed. Two of them invalidate the obvious design, which is why this section exists.

**`list_sms`** — `id, sim_card_id, sender, body, received_at, status, created_at, sim_phone_number, operator_name, gateway_name, phone_name`. Pages with `page`, **not** `skip` (`skip` is rejected outright). It carries `sim_card_id` directly, so the receiving SIM needs no lookup.

**`list_calls`** — 29 fields, and **none of them is a SIM id**. It exposes `gateway_id`, `gateway_name` and `sim_card_slot` instead. Since `list_sims` exposes `slot` and `gateway_name`, the SIM that handled a call is recoverable as `(gateway_name, sim_card_slot) → sim id`. Without that index the missed-call half of this feature can never send anything, because it would have no SIM to send from.

**Call statuses in the last 100 rows:** `CANCELLED` 57, `COMPLETED` 24, `REJECTED` 13, `MISSED` 6. There is no `NO_ANSWER` — do not invent it.

`UNANSWERED_STATUSES` is `{"MISSED", "CANCELLED", "REJECTED"}`: every attempt that did not become a conversation. The three differ in how the leg ended, not in whether the person was reached — the observed `REJECTED` rows carry `gsm_disconnect_cause` values like `"GSM call failed"` and `"remote: CM_NORMAL_CALL_CLR, NORMAL"`, which are network- or handset-level outcomes rather than a human pressing decline. `COMPLETED` with a non-zero duration is the only status that means the call happened, and it is never followed up.

Two consequences to keep in mind:
- The eligible pool is roughly **twelve times** larger than `MISSED` alone (76 rows out of 100 instead of 6). Because the job takes only the single most recent unanswered call per run, total volume is unchanged — but the call it picks will now almost always be a `CANCELLED` one, simply because those dominate the traffic.
- Volume is therefore bounded by the schedule and the per-recipient cooldown, not by the status filter. Those two are what to tune if the rate is wrong.

**The same person is called repeatedly.** In the sample, `33321576643 → +2250708243098` appears twice eight minutes apart, and `33629767468 → +2250711099083` twice across two gateways. Each is a distinct call `uuid`, so uniqueness on `trigger_ref` would happily send that person two identical SMS. Dedup must therefore also apply **per recipient number**, over a time window.

**`call_purpose` is null and `is_callback` is false on all 100 rows** — TmLite has its own callback concept but it is unused here, so there is no collision with this feature.

**Number formats are inconsistent** across the API: `+2250748524199`, `0748524199`, `33650715871`. Every comparison must go through digit-only suffix matching.

**Windowing — the two tools are not equal.** The job runs every fifteen minutes and must not walk the whole history each time.

- `list_calls` **supports `from_date`**, and it genuinely filters: 100 rows unwindowed became 80 for the last 30 minutes. **It must be naive ISO.** Passing an offset (`2026-08-28T13:23:12+00:00`) returns a **facade error 500**, not a validation message — an easy trap to fall into and a hard one to read.
- `list_sms` **supports no filter at all**. `from_date`, `since`, `start_date`, `received_after`, `sim_id`, `sim_card_id` and `status` are each rejected as an unexpected keyword. Only `limit` and `page` exist. It does return newest-first, so the window has to be applied client-side by **stopping at the first row older than the cutoff** rather than paging to the end.

This is what `sms_autoreply_lookback_minutes` is for. Both fetchers take it; neither may ignore it.

---

### Task 1: Pin the TmLite payload shapes

The keys are now known (see above), but they still belong behind adapters: `list_calls` gives no SIM id, so the normalized shape has to carry `(gateway_name, slot)` and let a separate index resolve it.

**Files:**
- Create: `backend/tests/fixtures/tmlite_payloads.json`
- Create: `backend/app/services/tmlite_shapes.py`
- Test: `backend/tests/test_tmlite_shapes.py`

**Interfaces:**
- Consumes: nothing
- Produces: `normalize_sms(raw) -> dict | None` returning `{"ref": str, "sim_id": int, "from_number": str, "text": str, "at": str}`; `normalize_call(raw) -> dict | None` returning `{"ref": str, "gateway": str, "slot": int | None, "caller": str, "callee": str, "status": str, "duration": int | None, "at": str}`; `sim_index(sims) -> dict[tuple[str, int], int]` mapping `(gateway_name, slot)` to a SIM id. All return `None` / skip rows missing a required field.

- [ ] **Step 1: Refresh the fixture**

The shapes were captured on 2026-08-28 and are recorded in the "Verified against production" section above. Re-run this to regenerate the fixture file, keeping the output verbatim:

```bash
ssh root@46.225.115.154 "cd /opt/mcp-tour-de-control && docker compose exec -T backend python -" <<'PY'
import asyncio, json
from fastmcp import Client
from sqlalchemy import select
from app.database import async_session
from app.models import McpServer
from app.services.mcp_service import _build_http_transport
from app.services.sim_pairing_service import SimPairingService

async def main():
    async with async_session() as s:
        srv = (await s.execute(select(McpServer).where(McpServer.name == "TmLite"))).scalar_one()
    async with Client(_build_http_transport(srv.url, srv.api_key)) as c:
        sms = SimPairingService._items(await c.call_tool("list_sms", {"limit": 3}))
        calls = SimPairingService._items(await c.call_tool("list_calls", {"limit": 3, "status": ["MISSED"]}))
        sims = SimPairingService._items(await c.call_tool("list_sims", {"limit": 3, "skip": 0}))
    print(json.dumps({"list_sms": sms, "list_calls": calls, "list_sims": sims}, ensure_ascii=False, indent=1))

asyncio.run(main())
PY
```

Save it as `backend/tests/fixtures/tmlite_payloads.json`. **Replace every `body` with `"<redacted>"`** — those are real messages from real people and have no business in the repository. Change nothing else; the fixture is worth having only because it is real.

- [ ] **Step 2: Write the failing test**

```python
import json
from pathlib import Path

from app.services.tmlite_shapes import normalize_call, normalize_sms

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "tmlite_payloads.json").read_text())


def test_every_fixture_sms_normalizes():
    rows = [normalize_sms(r) for r in FIXTURES["list_sms"]]
    assert all(r is not None for r in rows), "a real payload failed to normalize"
    assert all(isinstance(r["sim_id"], int) and r["from_number"] and r["ref"] for r in rows)


def test_every_fixture_call_normalizes():
    rows = [normalize_call(r) for r in FIXTURES["list_calls"]]
    assert all(r is not None for r in rows)
    assert all(r["caller"] and r["callee"] and r["status"] for r in rows)


def test_a_call_carries_gateway_and_slot_because_it_has_no_sim_id():
    row = normalize_call(FIXTURES["list_calls"][0])
    assert "sim_id" not in row
    assert row["gateway"] and isinstance(row["slot"], int)


def test_the_sim_index_resolves_a_call_to_a_sim():
    index = sim_index(FIXTURES["list_sims"])
    sim = FIXTURES["list_sims"][0]
    assert index[(sim["gateway_name"], sim["slot"])] == sim["id"]


def test_a_row_missing_a_required_field_is_dropped_not_guessed():
    assert normalize_sms({}) is None
    assert normalize_call({"caller": "33600000000"}) is None
```

Import `sim_index` alongside the two adapters.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_tmlite_shapes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.tmlite_shapes'`

- [ ] **Step 4: Write the adapters**

```python
"""Normalise TmLite payloads into the shapes this application reasons about.

TmLite is an external service whose field names are not guaranteed. Every
assumption about its wire format lives here and nowhere else, so a rename
upstream breaks one file with one test rather than the whole feature.
"""


def _first(raw: dict, *names):
    for name in names:
        value = raw.get(name)
        if value not in (None, ""):
            return value
    return None


def normalize_sms(raw: dict) -> dict | None:
    ref = _first(raw, "id", "uuid", "message_id")
    sim_id = _first(raw, "sim_card_id", "sim_id")
    sender = _first(raw, "sender", "from_number", "from", "msisdn")
    if ref is None or sim_id is None or sender is None:
        return None
    return {
        "ref": f"sms:{ref}",
        "sim_id": int(sim_id),
        "from_number": str(sender),
        "text": str(_first(raw, "body", "text", "content") or ""),
        "at": str(_first(raw, "received_at", "created_at") or ""),
    }


def normalize_call(raw: dict) -> dict | None:
    """A CDR row carries no SIM id — only gateway and slot. Resolving the SIM
    is `sim_index`'s job, so this shape deliberately has no `sim_id` key."""
    ref = _first(raw, "uuid", "id")
    caller, callee = _first(raw, "caller"), _first(raw, "callee")
    if ref is None or caller is None or callee is None:
        return None
    slot = raw.get("sim_card_slot")
    duration = raw.get("duration")
    return {
        "ref": f"call:{ref}",
        "gateway": str(_first(raw, "gateway_name") or ""),
        "slot": int(slot) if slot is not None else None,
        "caller": str(caller),
        "callee": str(callee),
        "status": str(raw.get("status") or ""),
        "duration": int(duration) if duration is not None else None,
        "at": str(_first(raw, "started_at", "answered_at", "finalized_at") or ""),
    }


def sim_index(sims: list[dict]) -> dict[tuple[str, int], int]:
    """(gateway_name, slot) -> sim id. The only bridge between a CDR row and
    the SIM that handled it."""
    index = {}
    for sim in sims:
        gateway, slot, sim_id = sim.get("gateway_name"), sim.get("slot"), sim.get("id")
        if gateway and slot is not None and sim_id is not None:
            index[(str(gateway), int(slot))] = int(sim_id)
    return index
```

Do **not** rename the normalized output keys — Tasks 4 and 5 are written against them.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_tmlite_shapes.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/tmlite_shapes.py backend/tests/test_tmlite_shapes.py backend/tests/fixtures/tmlite_payloads.json
git commit -m "feat(sms-reply): pin TmLite payload shapes behind adapters"
```

---

### Task 2: Share the quiet window

`_quiet_window` / `_is_quiet` / `_shift_out_of_quiet` are static methods on `SimPairConversationService`. Auto-reply needs the same behaviour and must not grow a second copy, nor a second set of settings for the user to keep in sync.

**Files:**
- Create: `backend/app/utils/quiet_hours.py`
- Modify: `backend/app/services/sim_pair_conversation_service.py`
- Test: `backend/tests/test_sim_pair_quiet_hours.py` (existing, unchanged assertions)

**Interfaces:**
- Consumes: nothing
- Produces: `quiet_window(config) -> tuple[int, int] | None`, `is_quiet(when: datetime, window) -> bool`, `shift_out_of_quiet(when: datetime, window, spread_minutes: int = 90) -> datetime`

- [ ] **Step 1: Move the three functions into the util, behaviour unchanged**

```python
"""Fleet-wide quiet hours, expressed in UTC.

Shared by SIM Pairing and SMS auto-reply so both obey one window and one set
of settings. Equal bounds describe an empty window, never a silent day.
"""
import random
from datetime import datetime, timedelta, timezone

WAKE_SPREAD_MINUTES = 90


def quiet_window(config) -> tuple[int, int] | None:
    if not config.pairing_quiet_hours_enabled:
        return None
    start, end = config.pairing_quiet_start_hour, config.pairing_quiet_end_hour
    return None if start == end else (start, end)


def is_quiet(when: datetime, window: tuple[int, int] | None) -> bool:
    if window is None:
        return False
    start, end = window
    hour = when.astimezone(timezone.utc).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def shift_out_of_quiet(when: datetime, window: tuple[int, int] | None,
                       spread_minutes: int = WAKE_SPREAD_MINUTES) -> datetime:
    if not is_quiet(when, window):
        return when
    when = when.astimezone(timezone.utc)
    wake = when.replace(hour=window[1], minute=0, second=0, microsecond=0)
    if wake <= when:
        wake += timedelta(days=1)
    return wake + timedelta(minutes=random.uniform(0, spread_minutes))
```

- [ ] **Step 2: Delegate from the pairing service**

In `sim_pair_conversation_service.py` add `from app.utils import quiet_hours`, then replace the three method bodies with delegations, keeping the method names so no caller changes:

```python
    @staticmethod
    def _quiet_window(config: Config):
        return quiet_hours.quiet_window(config)

    @staticmethod
    def _is_quiet(when: datetime, window) -> bool:
        return quiet_hours.is_quiet(when, window)

    @staticmethod
    def _shift_out_of_quiet(when: datetime, window) -> datetime:
        return quiet_hours.shift_out_of_quiet(when, window, SimPairConversationService.WAKE_SPREAD_MINUTES)
```

- [ ] **Step 3: Run the existing suite to prove behaviour is unchanged**

Run: `cd backend && venv/bin/python -m pytest tests/test_sim_pair_quiet_hours.py tests/test_sim_pair_conversation_flow.py -v`
Expected: 27 passed. These tests were written against the old methods; if any fail, the move changed behaviour — fix the move, not the tests.

- [ ] **Step 4: Commit**

```bash
git add backend/app/utils/quiet_hours.py backend/app/services/sim_pair_conversation_service.py
git commit -m "refactor(pairing): extract quiet hours into a shared util"
```

---

### Task 3: Model, migration and settings

**Files:**
- Create: `backend/app/models/sms_reply.py`, `backend/app/schemas/sms_reply.py`, `backend/alembic/versions/d4e5f6a7b8c9_add_sms_auto_reply.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/config.py`, `backend/app/schemas/config.py`, `backend/app/routers/config.py`
- Test: `backend/tests/test_sms_reply_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `SmsReply` with `id, trigger_kind, trigger_ref (unique), sim_id, to_number, whatsapp_number, content, status, error, sent_at, created_at`; `Config.sms_autoreply_enabled: bool`, `Config.sms_autoreply_template: str`, `Config.sms_autoreply_max_per_run: int`, `Config.sms_autoreply_lookback_minutes: int`; `SmsReplyRead`, `SmsAutoReplyStats`.

- [ ] **Step 1: Write the failing test**

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import SmsReply


async def test_one_reply_per_trigger_is_enforced_by_the_database(session):
    for _ in range(2):
        session.add(SmsReply(trigger_kind="sms", trigger_ref="sms:42", sim_id=872,
                             to_number="0700003331", whatsapp_number="33600000000",
                             content="x", status="sent"))
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_sms_reply_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'SmsReply' from 'app.models'`

- [ ] **Step 3: Write the model and settings**

`backend/app/models/sms_reply.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base


class SmsReply(Base):
    """One automatic reply.

    `trigger_ref` is unique on purpose: the 15-minute job re-reads an
    overlapping window, and this constraint is what stops a second reply.
    """

    __tablename__ = "sms_reply"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_kind: Mapped[str] = mapped_column(String(20))  # "sms" | "missed_call"
    trigger_ref: Mapped[str] = mapped_column(String(200), unique=True)
    sim_id: Mapped[int] = mapped_column(Integer)
    to_number: Mapped[str] = mapped_column(String(40))
    whatsapp_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent | failed | skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

In `app/models/__init__.py` add `from app.models.sms_reply import SmsReply` and `"SmsReply"` to `__all__`. In `app/models/config.py` add to `Config`:

```python
    sms_autoreply_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_autoreply_template: Mapped[str] = mapped_column(
        Text,
        default="Salut, j'essaye de te joindre. Ecris-moi sur WhatsApp au {whatsapp}.",
    )
    sms_autoreply_max_per_run: Mapped[int] = mapped_column(Integer, default=10)
    sms_autoreply_lookback_minutes: Mapped[int] = mapped_column(Integer, default=60)
    # The same person is called several times in a row by the same caller, each
    # attempt being a distinct CDR row. Uniqueness on trigger_ref would let all
    # of them through, so a recipient is also silenced for a while.
    sms_autoreply_recipient_cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
```

- [ ] **Step 4: Write the migration by hand**

```python
"""add sms auto-reply

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATE = "Salut, j'essaye de te joindre. Ecris-moi sur WhatsApp au {whatsapp}."


def upgrade() -> None:
    op.create_table(
        "sms_reply",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("trigger_kind", sa.String(20), nullable=False),
        sa.Column("trigger_ref", sa.String(200), nullable=False, unique=True),
        sa.Column("sim_id", sa.Integer(), nullable=False),
        sa.Column("to_number", sa.String(40), nullable=False),
        sa.Column("whatsapp_number", sa.String(40), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sms_reply_created", "sms_reply", ["created_at"])
    # The per-recipient cooldown queries by number and date on every run.
    op.create_index("ix_sms_reply_recipient", "sms_reply", ["to_number", "created_at"])
    op.add_column("config", sa.Column("sms_autoreply_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("config", sa.Column("sms_autoreply_template", sa.Text(), nullable=False, server_default=TEMPLATE))
    op.add_column("config", sa.Column("sms_autoreply_max_per_run", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("config", sa.Column("sms_autoreply_lookback_minutes", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("config", sa.Column("sms_autoreply_recipient_cooldown_hours", sa.Integer(), nullable=False, server_default="24"))


def downgrade() -> None:
    for column in ("sms_autoreply_recipient_cooldown_hours", "sms_autoreply_lookback_minutes",
                   "sms_autoreply_max_per_run", "sms_autoreply_template", "sms_autoreply_enabled"):
        op.drop_column("config", column)
    op.drop_index("ix_sms_reply_recipient", table_name="sms_reply")
    op.drop_index("ix_sms_reply_created", table_name="sms_reply")
    op.drop_table("sms_reply")
```

- [ ] **Step 5: Write the schemas and wire the config router**

`backend/app/schemas/sms_reply.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class SmsReplyRead(BaseModel):
    id: uuid.UUID
    trigger_kind: str
    trigger_ref: str
    sim_id: int
    to_number: str
    whatsapp_number: str | None
    content: str
    status: str
    error: str | None
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SmsAutoReplyStats(BaseModel):
    sent: int
    failed: int
    skipped: int
    last_sent_at: datetime | None
```

Add the four `sms_autoreply_*` fields to `ConfigRead` and `ConfigUpdate`, map them in `_to_read`, and validate in `update_config`:

```python
    if data.sms_autoreply_enabled is not None:
        config.sms_autoreply_enabled = data.sms_autoreply_enabled
    if data.sms_autoreply_template is not None:
        template = data.sms_autoreply_template.strip()
        if "{whatsapp}" not in template:
            raise HTTPException(status_code=422, detail="sms_autoreply_template must contain {whatsapp}")
        config.sms_autoreply_template = template
    if data.sms_autoreply_max_per_run is not None:
        if not 1 <= data.sms_autoreply_max_per_run <= 50:
            raise HTTPException(status_code=422, detail="sms_autoreply_max_per_run must be between 1 and 50")
        config.sms_autoreply_max_per_run = data.sms_autoreply_max_per_run
    # The floor is 30, not 15: the job runs every 15 minutes with coalesce=True,
    # so a window equal to the interval loses every contact made during a
    # restart gap. And the window must never exceed the recipient cooldown — a
    # trigger dropped by the cooldown is recorded nowhere, so it stays live in
    # the window and re-fires the moment the cooldown expires, turning one
    # burst of five inbound SMS into five identical replies.
    if data.sms_autoreply_lookback_minutes is not None:
        if not 30 <= data.sms_autoreply_lookback_minutes <= 1440:
            raise HTTPException(status_code=422, detail="sms_autoreply_lookback_minutes must be between 30 and 1440")
        config.sms_autoreply_lookback_minutes = data.sms_autoreply_lookback_minutes
    # Compare against effective values: a request may set only one of the pair.
    if config.sms_autoreply_lookback_minutes > config.sms_autoreply_recipient_cooldown_hours * 60:
        raise HTTPException(
            status_code=422,
            detail="sms_autoreply_lookback_minutes must not exceed sms_autoreply_recipient_cooldown_hours * 60",
        )
    if data.sms_autoreply_recipient_cooldown_hours is not None:
        if not 1 <= data.sms_autoreply_recipient_cooldown_hours <= 720:
            raise HTTPException(status_code=422,
                                detail="sms_autoreply_recipient_cooldown_hours must be between 1 and 720")
        config.sms_autoreply_recipient_cooldown_hours = data.sms_autoreply_recipient_cooldown_hours
```

- [ ] **Step 6: Run tests and the migration**

Run: `cd backend && venv/bin/python -m pytest tests/test_sms_reply_models.py tests/test_api_config.py -v`
Expected: all passed
Run: `cd backend && PYTHONPATH=. venv/bin/alembic upgrade head && PYTHONPATH=. venv/bin/alembic current`
Expected: `d4e5f6a7b8c9 (head)`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/sms_reply.py backend/app/models/__init__.py backend/app/models/config.py \
        backend/app/schemas/sms_reply.py backend/app/schemas/config.py backend/app/routers/config.py \
        backend/alembic/versions/d4e5f6a7b8c9_add_sms_auto_reply.py backend/tests/test_sms_reply_models.py
git commit -m "feat(sms-reply): add sms_reply table and auto-reply settings"
```

---

### Task 4: The decision logic, as pure functions

Everything that decides *who gets a message and what it says* is I/O-free, so it can be tested exhaustively without TmLite or a database. Task 5 only wires these together.

Note the asymmetry between the two triggers, because it drives the design: a **missed call** already carries both ends in one CDR row (`callee` is the recipient, `caller` is the WhatsApp number), while an **inbound SMS** only gives the sender, so the WhatsApp number has to be looked up as the most recent call *to* that sender.

**Files:**
- Create: `backend/app/services/sms_auto_reply_rules.py`
- Test: `backend/tests/test_sms_auto_reply_rules.py`

**Interfaces:**
- Consumes: the normalized shapes from Task 1
- Produces: `fleet_numbers(sims) -> set[str]`, `is_fleet_number(number, fleet) -> bool`, `whatsapp_for(target_number, calls) -> str | None`, `sms_triggers(messages, fleet, calls) -> list[dict]`, `missed_call_trigger(calls, fleet, index) -> dict | None`, `drop_recent_recipients(triggers, recent) -> list[dict]`, `render(template, whatsapp) -> str`. Every trigger dict is `{"ref": str, "kind": str, "sim_id": int | None, "to_number": str, "whatsapp": str | None}`.

- [ ] **Step 1: Write the failing tests**

```python
from app.services.sms_auto_reply_rules import (
    drop_recent_recipients, fleet_numbers, is_fleet_number, missed_call_trigger,
    render, sms_triggers, whatsapp_for,
)

FLEET = fleet_numbers([{"phone_number": "0748524199"}, {"phone_number": "0705435020"}])
INDEX = {("CIV-RED-3", 2): 872}


def _call(caller, callee, at, status="MISSED", duration=0, gateway="CIV-RED-3", slot=2):
    return {"ref": f"call:{caller}-{callee}-{at}", "gateway": gateway, "slot": slot,
            "caller": caller, "callee": callee, "status": status, "duration": duration, "at": at}


def test_a_fleet_number_is_recognised_whatever_its_formatting():
    assert is_fleet_number("+2250748524199", FLEET)
    assert is_fleet_number("0748524199", FLEET)
    assert not is_fleet_number("0700003331", FLEET)


def test_the_whatsapp_number_is_the_most_recent_caller_of_that_number():
    calls = [_call("33600000001", "0700003331", "2026-08-28T10:00:00"),
             _call("33600000002", "0700003331", "2026-08-28T12:00:00"),
             _call("33600000003", "0709999999", "2026-08-28T13:00:00")]
    assert whatsapp_for("0700003331", calls) == "33600000002"
    assert whatsapp_for("0711111111", calls) is None


def test_sms_from_the_fleet_never_becomes_a_trigger():
    calls = [_call("33600000002", "0700003331", "2026-08-28T12:00:00")]
    messages = [
        {"ref": "sms:1", "sim_id": 872, "from_number": "0700003331", "text": "?", "at": "x"},
        {"ref": "sms:2", "sim_id": 872, "from_number": "0705435020", "text": "?", "at": "x"},
    ]
    assert [t["ref"] for t in sms_triggers(messages, FLEET, calls)] == ["sms:1"]


def test_an_sms_with_no_resolvable_caller_is_kept_but_marked_unresolved():
    messages = [{"ref": "sms:3", "sim_id": 872, "from_number": "0788888888", "text": "?", "at": "x"}]
    assert sms_triggers(messages, FLEET, [])[0]["whatsapp"] is None


def test_only_the_most_recent_missed_call_is_taken():
    calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00"),
             _call("33600000002", "0700002222", "2026-08-28T12:00:00"),
             _call("33600000003", "0700003333", "2026-08-28T11:00:00", status="COMPLETED", duration=42)]
    trigger = missed_call_trigger(calls, FLEET, INDEX)
    assert trigger["to_number"] == "0700002222"
    assert trigger["whatsapp"] == "33600000002"
    assert trigger["sim_id"] == 872


def test_an_answered_call_is_never_followed_up():
    calls = [_call("33600000003", "0700003333", "2026-08-28T11:00:00", status="COMPLETED", duration=42)]
    assert missed_call_trigger(calls, FLEET, INDEX) is None


def test_every_unanswered_status_counts():
    # MISSED, CANCELLED and REJECTED all describe an attempt that did not
    # become a conversation, and all three are followed up.
    for status in ("MISSED", "CANCELLED", "REJECTED"):
        calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00", status=status)]
        assert missed_call_trigger(calls, FLEET, INDEX) is not None, status


def test_a_completed_call_with_a_duration_wins_over_nothing():
    # Only COMPLETED-with-audio is excluded, and it is excluded even when it is
    # the most recent row.
    calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00", status="CANCELLED"),
             _call("33600000002", "0700002222", "2026-08-28T12:00:00", status="COMPLETED", duration=42)]
    assert missed_call_trigger(calls, FLEET, INDEX)["to_number"] == "0700001111"


def test_a_call_from_an_unknown_gateway_slot_yields_no_sim():
    calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00", gateway="CIV-RED-9", slot=1)]
    assert missed_call_trigger(calls, FLEET, INDEX)["sim_id"] is None


def test_a_recipient_messaged_recently_is_dropped():
    triggers = [{"ref": "call:1", "kind": "missed_call", "sim_id": 872,
                 "to_number": "+2250700002222", "whatsapp": "33600000002"}]
    # Same person, different formatting, already messaged.
    assert drop_recent_recipients(triggers, {"0700002222"}) == []
    assert drop_recent_recipients(triggers, {"0700009999"}) == triggers


def test_the_whatsapp_number_resolves_across_number_formats():
    # The same person: +225... in the CDR, local format in the SMS. Exact
    # equality would silently find nothing and drop the reply.
    calls = [_call("33600000002", "+2250788542981", "2026-08-28T12:00:00")]
    assert whatsapp_for("0788542981", calls) == "33600000002"


def test_a_garbage_fleet_entry_cannot_swallow_real_numbers():
    # One malformed phone_number must not make every number ending in 1 look
    # like one of ours, which would blackhole a gateway's traffic silently.
    assert not is_fleet_number("0700003331", fleet_numbers([{"phone_number": "1"}]))


def test_the_template_is_rendered_verbatim():
    assert render("Ecris-moi au {whatsapp}.", "33600000002") == "Ecris-moi au 33600000002."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_sms_auto_reply_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.sms_auto_reply_rules'`

- [ ] **Step 3: Implement the rules**

```python
"""Who gets an automatic reply, and what it says. No I/O lives here."""
import re

# Every attempt that did not become a conversation. The three differ in how the
# leg ended, not in whether the person was reached. COMPLETED with a duration is
# a real conversation and is never followed up.
UNANSWERED_STATUSES = {"MISSED", "CANCELLED", "REJECTED"}


# Real numbers here are 9 digits in Guinea (614966686) and 10 in Ivory Coast
# (0748524199). A floor of 8 therefore rejects a malformed row without ever
# rejecting a real number — and without it, a stored phone_number of "1" would
# make every customer number ending in 1 look like one of ours.
MIN_MATCH_DIGITS = 8


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def same_number(a, b) -> bool:
    """The single comparison every caller uses. TmLite returns the same person
    as +2250788542981 or 0788542981 depending on the endpoint, so one must be a
    suffix of the other — but only once both are long enough to mean anything."""
    x, y = digits(a), digits(b)
    if len(x) < MIN_MATCH_DIGITS or len(y) < MIN_MATCH_DIGITS:
        return False
    return x.endswith(y) or y.endswith(x)


def fleet_numbers(sims: list[dict]) -> set[str]:
    return {digits(s.get("phone_number")) for s in sims if digits(s.get("phone_number"))}


def is_fleet_number(number: str, fleet: set[str]) -> bool:
    return any(same_number(number, owned) for owned in fleet)


def whatsapp_for(target_number: str, calls: list[dict]) -> str | None:
    matches = [c for c in calls if same_number(c.get("callee"), target_number) and c.get("caller")]
    if not matches:
        return None
    return max(matches, key=lambda c: c.get("at") or "")["caller"]


def sms_triggers(messages: list[dict], fleet: set[str], calls: list[dict]) -> list[dict]:
    triggers = []
    for message in messages:
        if is_fleet_number(message["from_number"], fleet):
            continue
        triggers.append({
            "ref": message["ref"],
            "kind": "sms",
            "sim_id": message["sim_id"],
            "to_number": message["from_number"],
            "whatsapp": whatsapp_for(message["from_number"], calls),
        })
    return triggers


def missed_call_trigger(calls: list[dict], fleet: set[str],
                        index: dict[tuple[str, int], int]) -> dict | None:
    candidates = [
        c for c in calls
        if c.get("status") in UNANSWERED_STATUSES
        and not (c.get("duration") or 0)
        and c.get("callee")
        and not is_fleet_number(c["callee"], fleet)
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda c: c.get("at") or "")
    return {
        "ref": latest["ref"],
        "kind": "missed_call",
        # The CDR has no SIM id; only (gateway, slot) can resolve it.
        "sim_id": index.get((latest.get("gateway"), latest.get("slot"))),
        "to_number": latest["callee"],
        "whatsapp": latest.get("caller"),
    }


def drop_recent_recipients(triggers: list[dict], recent: set[str]) -> list[dict]:
    """One person, one message per cooldown — whatever number format each
    source used, and however many times they were called."""
    kept, seen = [], set()
    for trigger in triggers:
        target = digits(trigger["to_number"])
        if not target or target in seen:
            continue
        if any(same_number(target, r) for r in recent):
            continue
        seen.add(target)
        kept.append(trigger)
    return kept


def render(template: str, whatsapp: str) -> str:
    return template.replace("{whatsapp}", whatsapp)
```

`drop_recent_recipients` also collapses duplicates *within* one run through its `seen` set, which matters because the same person really does appear twice in a single window.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_sms_auto_reply_rules.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sms_auto_reply_rules.py backend/tests/test_sms_auto_reply_rules.py
git commit -m "feat(sms-reply): add reply selection rules"
```

---

### Task 5: The service

**Files:**
- Create: `backend/app/services/sms_auto_reply_service.py`
- Test: `backend/tests/test_sms_auto_reply_service.py`

**Interfaces:**
- Consumes: Task 1 adapters, Task 2 `quiet_hours`, Task 3 `SmsReply` and config fields, Task 4 rules
- Produces: `SmsAutoReplyService.run(session, dry_run: bool = False) -> dict` returning `{"sent", "skipped", "failed"}` plus optional `"reason"` / `"previews"`; `SmsAutoReplyService.stats(session) -> dict`

- [ ] **Step 1: Write the failing tests**

Mirror the mocking style already used in `tests/test_sim_pair_conversation_flow.py`: a `_tmlite` context manager patching `Client` in the service module with a fake that records `send_sms`, and returning `list_sims` / `list_sms` / `list_calls` from arguments. Its `list_sims` must include `gateway_name` and `slot` so `sim_index` can resolve, e.g. `{"id": 872, "phone_number": "0748524199", "gateway_name": "CIV-RED-3", "slot": 2, "state": "IDLE"}`. `_configure(session, **overrides)` inserts a `Config` with `sms_autoreply_enabled=True`, `pairing_quiet_hours_enabled=False` and an enabled TmLite `McpServer`. `_sms(id, sim_card_id, sender)` and `_missed(caller, callee, at, status="MISSED", duration=0)` build raw TmLite rows with the real key names, `_missed` defaulting to `gateway_name="CIV-RED-3"` and `sim_card_slot=2` so the fake `list_sims` row resolves it.

```python
async def test_a_reply_goes_out_from_the_receiving_sim(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0700003331")],
                 calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1
    assert sent[0][1] == {"from_sim_id": 872, "to_number": "0700003331",
                          "text": "Salut, j'essaye de te joindre. Ecris-moi sur WhatsApp au 33600000002."}


async def test_the_same_trigger_is_never_answered_twice(session):
    await _configure(session)
    payload = dict(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")])
    with _tmlite(**payload):
        await SmsAutoReplyService.run(session)
    with _tmlite(**payload) as sent:
        second = await SmsAutoReplyService.run(session)
    assert second["sent"] == 0 and sent == []


async def test_an_unresolvable_whatsapp_number_is_skipped_not_sent(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0788888888")], calls=[]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and result["skipped"] == 1 and sent == []
    row = (await session.execute(select(SmsReply))).scalar_one()
    assert row.status == "skipped" and row.error == "No caller found for this number"


async def test_quiet_hours_stop_every_send(session):
    now = datetime.now(timezone.utc)
    await _configure(session, pairing_quiet_hours_enabled=True,
                     pairing_quiet_start_hour=now.hour, pairing_quiet_end_hour=(now.hour + 1) % 24)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and "Quiet hours" in result["reason"] and sent == []


async def test_disabled_does_nothing(session):
    await _configure(session, sms_autoreply_enabled=False)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []


async def test_one_person_called_twice_receives_a_single_message(session):
    await _configure(session)
    # The same callee, two distinct MISSED calls — the real production pattern.
    calls = [_missed("33321576643", "+2250708243098", "2026-08-28T13:19:53"),
             _missed("33321576643", "+2250708243098", "2026-08-28T13:27:24")]
    with _tmlite(sms=[], calls=calls) as sent:
        first = await SmsAutoReplyService.run(session)
    assert first["sent"] == 1 and len(sent) == 1
    with _tmlite(sms=[], calls=calls) as sent:
        second = await SmsAutoReplyService.run(session)
    assert second["sent"] == 0 and sent == []


async def test_a_cancelled_or_rejected_call_is_followed_up(session):
    await _configure(session)
    calls = [_missed("33600000001", "+2250700001111", "2026-08-28T13:00:00", status="REJECTED")]
    with _tmlite(sms=[], calls=calls) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1 and len(sent) == 1


async def test_an_answered_call_is_not_followed_up(session):
    await _configure(session)
    calls = [_missed("33600000001", "+2250700001111", "2026-08-28T13:00:00",
                     status="COMPLETED", duration=42)]
    with _tmlite(sms=[], calls=calls) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []


async def test_a_dry_run_sends_nothing_and_stores_nothing(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session, dry_run=True)
    assert sent == [] and result["previews"][0]["to_number"] == "0700003331"
    assert (await session.execute(select(SmsReply))).scalars().all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_sms_auto_reply_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.sms_auto_reply_service'`

- [ ] **Step 3: Implement the service**

```python
"""Answer inbound SMS and follow up the most recent unanswered call.

Every reply uses one fixed template. There is deliberately no LLM in this
path: an automatic notification must read the same every time.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from fastmcp import Client
from sqlalchemy import func, select

from app.models import Config, McpServer, SmsReply
from app.services.mcp_service import _build_http_transport
from app.services.sim_pairing_service import SimPairingService
from app.services import sms_auto_reply_rules as rules
from app.services.tmlite_shapes import normalize_call, normalize_sms, sim_index
from app.utils import quiet_hours

log = structlog.get_logger()


class SmsAutoReplyService:
    _run_lock = asyncio.Lock()

    @staticmethod
    async def run(session, dry_run: bool = False) -> dict:
        if SmsAutoReplyService._run_lock.locked():
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "A run is already in progress"}
        async with SmsAutoReplyService._run_lock:
            return await SmsAutoReplyService._run(session, dry_run)

    @staticmethod
    async def _run(session, dry_run: bool) -> dict:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.sms_autoreply_enabled:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "SMS auto-reply is disabled"}

        window = quiet_hours.quiet_window(config)
        if not dry_run and quiet_hours.is_quiet(datetime.now(timezone.utc), window):
            return {"sent": 0, "skipped": 0, "failed": 0,
                    "reason": f"Quiet hours: replies resume at {window[1]:02d}:00 UTC"}

        server = (await session.execute(
            select(McpServer).where(McpServer.name == "TmLite", McpServer.enabled.is_(True))
        )).scalar_one_or_none()
        if not server or server.transport != "http" or not server.url:
            raise RuntimeError("An enabled TmLite HTTP MCP server is required")

        sent = skipped = failed = 0
        previews = []
        since = datetime.now(timezone.utc) - timedelta(minutes=config.sms_autoreply_lookback_minutes)
        async with Client(_build_http_transport(server.url, server.api_key)) as client:
            sims = await SmsAutoReplyService._all_sims(client)
            fleet = rules.fleet_numbers(sims)
            index = sim_index(sims)
            messages = [m for m in (normalize_sms(r) for r in await SmsAutoReplyService._recent_sms(client, since)) if m]
            calls = [c for c in (normalize_call(r) for r in await SmsAutoReplyService._recent_calls(client, since)) if c]

            triggers = rules.sms_triggers(messages, fleet, calls)
            missed = rules.missed_call_trigger(calls, fleet, index)
            if missed:
                triggers.append(missed)

            # Two independent guards. trigger_ref stops the same event being
            # answered twice; the recipient cooldown stops one person receiving
            # several messages because they were called several times.
            refs = [t["ref"] for t in triggers] or [""]
            already = set((await session.execute(
                select(SmsReply.trigger_ref).where(SmsReply.trigger_ref.in_(refs))
            )).scalars())
            triggers = [t for t in triggers if t["ref"] not in already]

            cooldown_since = datetime.now(timezone.utc) - timedelta(hours=config.sms_autoreply_recipient_cooldown_hours)
            recent = set((await session.execute(
                select(SmsReply.to_number).where(SmsReply.created_at >= cooldown_since)
            )).scalars())
            triggers = rules.drop_recent_recipients(triggers, recent)[: config.sms_autoreply_max_per_run]

            for trigger in triggers:
                content = rules.render(config.sms_autoreply_template, trigger["whatsapp"] or "?")
                if dry_run:
                    previews.append({**trigger, "content": content})
                    continue
                reason = (None if trigger["whatsapp"] and trigger["sim_id"]
                          else "No caller found for this number" if not trigger["whatsapp"]
                          else "No SIM recorded for this contact")
                if reason:
                    session.add(SmsReply(trigger_kind=trigger["kind"], trigger_ref=trigger["ref"],
                                         sim_id=trigger["sim_id"] or 0, to_number=trigger["to_number"],
                                         whatsapp_number=trigger["whatsapp"], content="", status="skipped",
                                         error=reason))
                    await session.commit()
                    skipped += 1
                    continue
                reply = SmsReply(trigger_kind=trigger["kind"], trigger_ref=trigger["ref"],
                                 sim_id=trigger["sim_id"], to_number=trigger["to_number"],
                                 whatsapp_number=trigger["whatsapp"], content=content, status="sent")
                session.add(reply)
                try:
                    await session.flush()
                    await client.call_tool("send_sms", {"from_sim_id": trigger["sim_id"],
                                                        "to_number": trigger["to_number"], "text": content})
                    reply.sent_at = datetime.now(timezone.utc)
                    await session.commit()
                    sent += 1
                except Exception as exc:
                    await session.rollback()
                    session.add(SmsReply(trigger_kind=trigger["kind"], trigger_ref=trigger["ref"],
                                         sim_id=trigger["sim_id"], to_number=trigger["to_number"],
                                         whatsapp_number=trigger["whatsapp"], content=content,
                                         status="failed", error=str(exc)))
                    await session.commit()
                    failed += 1

        result = {"sent": sent, "skipped": skipped, "failed": failed}
        if dry_run:
            result["previews"] = previews
        return result

    @staticmethod
    def _naive_iso(when: datetime) -> str:
        """TmLite's from_date rejects an offset with a facade 500, not a
        validation error. It wants naive ISO."""
        return when.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    @staticmethod
    async def _all_sims(client) -> list[dict]:
        """The fleet is small and needed in full for the index. Pages with skip."""
        rows = []
        for index in range(10):
            page = SimPairingService._items(
                await client.call_tool("list_sims", {"limit": 100, "skip": index * 100})
            )
            if not isinstance(page, list) or not page:
                break
            rows.extend(page)
            if len(page) < 100:
                break
        return rows

    @staticmethod
    async def _recent_calls(client, since: datetime) -> list[dict]:
        """Windowed by the server: list_calls honours from_date."""
        rows = []
        for page in range(1, 11):
            batch = SimPairingService._items(await client.call_tool(
                "list_calls",
                {"limit": 100, "page": page, "from_date": SmsAutoReplyService._naive_iso(since)},
            ))
            if not isinstance(batch, list) or not batch:
                break
            rows.extend(batch)
            if len(batch) < 100:
                break
        return rows

    @staticmethod
    async def _recent_sms(client, since: datetime) -> list[dict]:
        """list_sms accepts no date filter — only limit and page. It returns
        newest first, so stop at the first row older than the window rather than
        walking the whole table every fifteen minutes. Both timestamps are naive
        ISO, so a string comparison orders them correctly.
        """
        cutoff = SmsAutoReplyService._naive_iso(since)
        rows = []
        for page in range(1, 11):
            batch = SimPairingService._items(await client.call_tool("list_sms", {"limit": 100, "page": page}))
            if not isinstance(batch, list) or not batch:
                break
            for row in batch:
                if str(row.get("received_at") or "") < cutoff:
                    return rows
                rows.append(row)
            if len(batch) < 100:
                break
        return rows

    @staticmethod
    async def stats(session) -> dict:
        counts = {}
        for status in ("sent", "failed", "skipped"):
            counts[status] = await session.scalar(
                select(func.count()).select_from(SmsReply).where(SmsReply.status == status)
            ) or 0
        counts["last_sent_at"] = await session.scalar(select(func.max(SmsReply.sent_at)))
        return counts
```

The three fetchers are the only place that knows how each tool pages and filters. Note they differ on purpose: `_all_sims` pages with `skip` and fetches everything, `_recent_calls` pages with `page` and lets the server apply `from_date`, `_recent_sms` pages with `page` and applies the window itself because the tool cannot.

Add one test for the windowing, since it is the part that silently degrades into a full-table scan if it regresses:

```python
async def test_the_fetchers_ask_for_only_the_configured_window(session):
    await _configure(session, sms_autoreply_lookback_minutes=30)
    with _tmlite(sms=[], calls=[]) as _, _recorded_args() as args:
        await SmsAutoReplyService.run(session)
    from_dates = [a["from_date"] for tool, a in args if tool == "list_calls"]
    assert from_dates, "list_calls was called without a window"
    assert "+" not in from_dates[0] and from_dates[0].endswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
```

`_recorded_args` extends the `_tmlite` fake to record `(tool, args)` for every `call_tool`. The `"+" not in` assertion is not pedantry: an offset in `from_date` is the difference between a working call and a facade 500.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_sms_auto_reply_service.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sms_auto_reply_service.py backend/tests/test_sms_auto_reply_service.py
git commit -m "feat(sms-reply): add the auto-reply service"
```

---

### Task 6: Router and scheduler

**Files:**
- Create: `backend/app/routers/sms_auto_reply.py`
- Modify: `backend/app/services/scheduler_service.py`, `backend/app/main.py`
- Test: `backend/tests/test_api_sms_auto_reply.py`

**Interfaces:**
- Consumes: `SmsAutoReplyService.run`, `SmsAutoReplyService.stats`
- Produces: `GET /api/v1/sms-autoreply/replies`, `GET /api/v1/sms-autoreply/stats`, `POST /api/v1/sms-autoreply/run`, `POST /api/v1/sms-autoreply/preview`; scheduler job id `sms_auto_reply`

- [ ] **Step 1: Write the failing test**

Follow the `app.dependency_overrides` fixture style of `tests/test_api_sim_pairing.py`.

```python
async def test_the_endpoints_answer_before_anything_is_configured():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/sms-autoreply/replies")).status_code == 200
        stats = await client.get("/api/v1/sms-autoreply/stats")
        assert stats.status_code == 200
        assert stats.json() == {"sent": 0, "failed": 0, "skipped": 0, "last_sent_at": None}
        run = await client.post("/api/v1/sms-autoreply/run")
        assert run.status_code == 200
        assert run.json()["reason"] == "SMS auto-reply is disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_sms_auto_reply.py -v`
Expected: FAIL with 404 — the router is not mounted

- [ ] **Step 3: Write the router and the job**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import SmsReply
from app.schemas.sms_reply import SmsAutoReplyStats, SmsReplyRead
from app.services.sms_auto_reply_service import SmsAutoReplyService

router = APIRouter(prefix="/api/v1/sms-autoreply", tags=["sms-autoreply"])


@router.get("/replies", response_model=list[SmsReplyRead])
async def list_replies(session: AsyncSession = Depends(get_async_session)):
    return list((await session.execute(
        select(SmsReply).order_by(SmsReply.created_at.desc()).limit(100)
    )).scalars())


@router.get("/stats", response_model=SmsAutoReplyStats)
async def stats(session: AsyncSession = Depends(get_async_session)):
    return await SmsAutoReplyService.stats(session)


@router.post("/run")
async def run(session: AsyncSession = Depends(get_async_session)):
    return await SmsAutoReplyService.run(session)


@router.post("/preview")
async def preview(session: AsyncSession = Depends(get_async_session)):
    """Show what would be sent. Reads TmLite, never sends."""
    return await SmsAutoReplyService.run(session, dry_run=True)
```

In `scheduler_service.py`, beside `_execute_sim_pair_conversation`:

```python
async def _execute_sms_auto_reply():
    from app.database import async_session
    from app.services.sms_auto_reply_service import SmsAutoReplyService
    try:
        async with async_session() as session:
            summary = await SmsAutoReplyService.run(session)
        log.info("SMS auto-reply run completed", **summary)
    except Exception as exc:
        log.error("SMS auto-reply run failed", error=str(exc))
```

and on `SchedulerService`:

```python
    SMS_AUTO_REPLY_JOB_ID = "sms_auto_reply"

    def set_sms_auto_reply_job(self):
        self.scheduler.add_job(_execute_sms_auto_reply, trigger=IntervalTrigger(minutes=15),
                               id=self.SMS_AUTO_REPLY_JOB_ID, replace_existing=True)
```

In `main.py`, import the router, `app.include_router(sms_auto_reply_router.router)`, and call `scheduler_service.set_sms_auto_reply_job()` in the lifespan beside the pairing jobs.

- [ ] **Step 4: Run the full suite**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_sms_auto_reply.py -v`
Expected: 1 passed
Run: `cd backend && venv/bin/python -m pytest tests/ -q`
Expected: all pass except the 7 pre-existing `test_script_executor.py` / `test_api_executions.py` failures (`No such file or directory: 'python'`), which are environmental and unrelated.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/sms_auto_reply.py backend/app/main.py \
        backend/app/services/scheduler_service.py backend/tests/test_api_sms_auto_reply.py
git commit -m "feat(sms-reply): expose the API and schedule the job"
```

---

### Task 7: Frontend

A dedicated **`SMS Auto-Reply` tab**, decided by the user on 2026-08-28. It is its own page, not a card on the SIM Pairing page: this feature messages people *outside* the fleet, while SIM Pairing only ever talks to the fleet's own SIMs, and mixing the two on one screen invites the operator to confuse them.

**Files:**
- Create: `frontend/src/pages/SmsAutoReplyPage.tsx`
- Modify: `frontend/src/lib/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/Layout/TabNav.tsx`
- Do **not** modify `frontend/src/pages/PairingPage.tsx`.

**Interfaces:**
- Consumes: the Task 6 endpoints
- Produces: route `/sms-auto-reply` rendering `<SmsAutoReplyPage />`, reachable from a nav tab labelled exactly `SMS Auto-Reply`

**Nav placement:** insert the tab immediately after `SIM Pairing`, giving `Prompts, Reports, Activity, SIM Pairing, SMS Auto-Reply, Stress Call, Chat, Config`. **No emoji** in the label — the nav is text-only throughout this app.

- [ ] **Step 1: Add the API layer**

In `frontend/src/lib/api.ts`, beside the SIM pairing calls:

```typescript
export const listSmsReplies = () => request<SmsReply[]>("/sms-autoreply/replies");
export const getSmsAutoReplyStats = () => request<SmsAutoReplyStats>("/sms-autoreply/stats");
export const runSmsAutoReply = () => request<SmsAutoReplyRun>("/sms-autoreply/run", { method: "POST" });
export const previewSmsAutoReply = () => request<SmsAutoReplyRun>("/sms-autoreply/preview", { method: "POST" });
```

and with the other interfaces:

```typescript
export interface SmsReply { id: string; trigger_kind: string; trigger_ref: string; sim_id: number; to_number: string; whatsapp_number: string | null; content: string; status: string; error: string | null; sent_at: string | null; created_at: string; }
export interface SmsAutoReplyStats { sent: number; failed: number; skipped: number; last_sent_at: string | null; }
export interface SmsAutoReplyRun { sent: number; skipped: number; failed: number; reason?: string; previews?: { kind: string; to_number: string; whatsapp: string | null; content: string }[]; }
```

Add `sms_autoreply_enabled`, `sms_autoreply_template`, `sms_autoreply_max_per_run`, `sms_autoreply_lookback_minutes` and `sms_autoreply_recipient_cooldown_hours` to the `Config` interface, and their optional counterparts to `ConfigUpdate`.

- [ ] **Step 2: Write the page**

`SmsAutoReplyPage.tsx`, following the structure of `PairingPage.tsx` — same `card p-6` / `card-elevated` classes, same CSS custom properties, same header block with the accent bar, `useQuery`/`useMutation` from TanStack Query, no new colours, no emoji, no ad-hoc `fetch`:

1. **Header** — title `SMS Auto-Reply` and one line of subtitle stating what it does: answers inbound SMS from numbers outside the fleet, and follows up the most recent unanswered call.
2. **Settings card**, saved through `updateConfig`: the enable checkbox, the template textarea, max per run, lookback minutes, and the per-recipient cooldown in hours. State follows the existing `value ?? config?.field ?? default` pattern. Include the copy that the text is **identical for every recipient** and that quiet hours are shared with SIM Pairing rather than set here.
3. **Actions card** — "Preview (no send)" and "Run now". Render `reason` verbatim when the run returns one, otherwise `sent / skipped / failed`. A preview entry whose `content` is `null` must render its `skip_reason` instead of a message body — never a blank line, since the whole point is to show what would *not* be sent.
4. **History card** — the counters from `/stats`, then the last 100 replies: recipient, WhatsApp number given, trigger kind, status, timestamp, and `error` when present. Poll `/replies` and `/stats` every 30s, matching `PairingPage.tsx`.

- [ ] **Step 3: Add the route and the tab**

In `App.tsx`, import the page and add `<Route path="sms-auto-reply" element={<SmsAutoReplyPage />} />` inside the existing `AppShell` layout, immediately after the `pairing` route.

In `TabNav.tsx`, add `{ to: "/sms-auto-reply", label: "SMS Auto-Reply" }` immediately after the `SIM Pairing` entry.

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run build`
Expected: `✓ built` with no TypeScript errors
Run: `cd frontend && npm run lint`
Expected: no new warnings — the two pre-existing `no-useless-escape` warnings in `PairingPage.tsx` remain (that file is not touched by this task)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SmsAutoReplyPage.tsx frontend/src/lib/api.ts \
        frontend/src/App.tsx frontend/src/components/Layout/TabNav.tsx
git commit -m "feat(sms-reply): add the SMS Auto-Reply tab"
```

---

## Deployment

Production runs an uncommitted working tree deployed by scp, not `git pull` — never assume `main` is what prod serves.

```bash
H=root@46.225.115.154; D=/opt/mcp-tour-de-control
ssh $H "cd $D && docker compose exec -T postgres pg_dump -U mcp -d mcp_control -t config > /root/backup-before-smsreply.sql"
# scp every created and modified file, then:
ssh $H "cd $D && docker compose build backend frontend && docker compose up -d backend frontend"
ssh $H "cd $D && docker compose exec -T postgres psql -U mcp -d mcp_control -tAc 'select version_num from alembic_version'"
```

Expected: `d4e5f6a7b8c9`.

Leave `sms_autoreply_enabled` **false** on first deploy. Run `POST /api/v1/sms-autoreply/preview`, read every proposed message and recipient, and only then enable. The preview is the last checkpoint before real people receive a message.
