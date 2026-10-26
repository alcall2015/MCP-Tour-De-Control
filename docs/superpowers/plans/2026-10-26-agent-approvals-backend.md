# Agent Approvals (3a, backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate agent tool calls by a per-tool risk level against a per-agent ceiling, park the task in `waiting_approval` for anything above it, notify the administrator on WhatsApp, accept the decision from the API or a WhatsApp reply, and resume the task from its journal without replaying anything.

**Architecture:** Two new tables (`tool_policy`, `approval`) and three new columns (`agent.max_auto_risk`, the `waiting_approval` status, the `approval_requested` step kind). `tool_policy_service` owns discovery sync and level lookup; `approval_service` owns request / decide / expire and drives `AgentTaskService.park` / `resume`. The runner gains a gate before every tool call, a `Parked` exit, and a resume mode that rebuilds the message history from the stored prompts. A notifier and a reply poller talk to the WhatsApp MCP server through the shared `call_mcp_tool`; two one-minute scheduler jobs run expiry and reply polling.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 + asyncpg, Alembic, Pydantic v2, APScheduler 3, pytest-asyncio on a live Postgres, structlog.

Spec: `docs/superpowers/specs/2026-10-26-agent-approvals-design.md`. Frontend is plan 3b.

## Global Constraints

- Branch `feat/agent-approvals` from `main` (clean checkout, no worktree). Conventional Commits `feat(agents): ...` / `fix(agents): ...`, every commit ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Stage named paths only; never `git add -A`; never bare `git stash`.
- Backend commands from `backend/` with `venv/bin/python`; tests need the test Postgres (`mcp_control_test`); add `-p no:cacheprovider`. One pre-existing `AuthlibDeprecationWarning` from `fastmcp` is known.
- Alembic revision `5a6b7c8d9e0f`, chained on `4f5a6b7c8d9e` (single head), hand-written; never apply autogenerate's spurious drops (see CLAUDE.md).
- Risk levels are integers 0..3; default for an unclassified tool is **2**; `agent.max_auto_risk` is 0..2 (default 1); a tool executes without approval iff `level <= max_auto_risk`. R3 is never automatic.
- Statuses: `agent_task.status` gains `waiting_approval`; `OPEN_STATUSES = ("queued", "running", "waiting_approval")`; `FINAL_STATUSES` unchanged. Approval statuses exactly `pending`, `approved`, `rejected`, `expired`. `decided_by` values: `ui`, `whatsapp:<digits>`, `system:expiry`, `system:cancel`.
- Step kinds gain `approval_requested`; `tool_call` payloads gain `risk_level` and, when applicable, `approval_id`.
- An approval binds one exact action (`args_hash` = sha256 of `json.dumps(args, sort_keys=True, separators=(",", ":"))`); it is consumed once (`consumed_at`); the approved call executes `approval.args`, not the model's current output.
- Resume rebuilds history from the journal with **no LLM call**: `last_turn.prompt` + the assistant message of that turn (ids `call_{turn_seq}_{i}`) + one tool message per `tool_call` step recorded after it. The deadline restarts at each running segment.
- Codes: 6 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, unique among non-final approvals.
- Config fields and defaults: `approval_expiry_hours=24` (1..168), `approval_whatsapp_enabled=False`, `approval_whatsapp_number="+2250700003331"`, `approval_whatsapp_server_id=None`, `approval_whatsapp_session_id=None`, `approval_whatsapp_template` (French default, see Task 1). Setting `PUBLIC_BASE_URL="https://tour.alcall.net"`.
- Notifier and reply poller never raise into the runner or the scheduler; they record (`notified_at` / `notify_error`) and log. Notification only when `approval_whatsapp_enabled`.
- Routers stay thin; every write to `agent_task` goes through `AgentTaskService`; every write to `approval` through `ApprovalService`; every write to `tool_policy` through `ToolPolicyService`. One file per entity; export new models and schemas from the package `__init__`s.
- Code, comments and API messages in English; the WhatsApp template is the one French exception.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/app/config.py` | `PUBLIC_BASE_URL` |
| `backend/app/models/tool_policy.py` | `ToolPolicy` |
| `backend/app/models/approval.py` | `Approval`, `APPROVAL_STATUSES`, `CODE_ALPHABET` |
| `backend/app/models/agent.py` | `+ max_auto_risk` |
| `backend/app/models/agent_task.py` | `waiting_approval`, `approval_requested`, constants |
| `backend/app/models/config.py` | six approval fields |
| `backend/app/models/__init__.py` | exports |
| `backend/alembic/versions/5a6b7c8d9e0f_add_approvals.py` | migration |
| `backend/app/services/tool_policy_service.py` | `sync`, `levels_for`, `discover`, `set_level` |
| `backend/app/services/approval_service.py` | `request`, `decide`, `expire_due`, `expire_for_task`, `decided_unconsumed`, `mark_consumed`, `list_pending` |
| `backend/app/services/agent_task_service.py` | `park`, `resume`, cancel of a waiting task |
| `backend/app/services/agent_runner.py` | gate, `Parked`, resume mode |
| `backend/app/services/approval_notifier.py` | WhatsApp outbound |
| `backend/app/services/approval_replies.py` | WhatsApp inbound decisions |
| `backend/app/services/scheduler_service.py` | `set_approval_jobs()` (expiry + replies, 1-minute intervals) |
| `backend/app/schemas/approval.py`, `tool_policy.py`, `agent.py`, `agent_task.py`, `config.py` | schemas |
| `backend/app/routers/approvals.py` | list / approve / reject |
| `backend/app/routers/mcp_servers.py` | `GET/PUT /{id}/tools[/{tool_name}]`, sync on test |
| `backend/app/routers/agent_tasks.py` | cancel closes the approval; detail carries `approval` |
| `backend/app/routers/agents.py`, `services/agent_service.py` | `max_auto_risk` |
| `backend/app/routers/config.py` | approval fields with validation |
| `backend/app/main.py` | router + jobs |
| tests | `test_approval_models.py`, `test_tool_policy_service.py`, `test_approval_service.py`, `test_agent_runner_approvals.py`, `test_approval_notifier.py`, `test_approval_replies.py`, `test_api_approvals.py`, `test_api_tool_policies.py`, plus edits to `test_api_agents.py`, `test_api_config.py`, `test_api_agent_tasks.py` |

---

### Task 1: Models, config fields, migration

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/models/tool_policy.py`, `backend/app/models/approval.py`
- Modify: `backend/app/models/agent.py`, `backend/app/models/agent_task.py`, `backend/app/models/config.py`, `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/5a6b7c8d9e0f_add_approvals.py`
- Test: `backend/tests/test_approval_models.py`

**Interfaces:**
- Produces:
  ```python
  class ToolPolicy(Base): id, mcp_server_id, tool_name, risk_level, description, first_seen_at, updated_at
  class Approval(Base): id, task_id, agent_id, step_seq, call_index, tool_name, server_name, args, args_hash, risk_level, code, status, consumed_at, requested_at, expires_at, decided_at, decided_by, decision_reason, notified_at, notify_error
  APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired"); CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
  Agent.max_auto_risk: int  # default 1, CHECK 0..2
  OPEN_STATUSES = ("queued", "running", "waiting_approval"); TASK_STATUSES += "waiting_approval"; STEP_KINDS += "approval_requested"
  Config.approval_expiry_hours, approval_whatsapp_enabled, approval_whatsapp_number, approval_whatsapp_server_id (UUID nullable), approval_whatsapp_session_id (String nullable), approval_whatsapp_template
  settings.PUBLIC_BASE_URL
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_approval_models.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config, McpServer, ToolPolicy
from app.models.agent_task import OPEN_STATUSES, STEP_KINDS


async def _agent_and_task(session):
    server = McpServer(name="srv", transport="http", url="http://x", enabled=True)
    agent = Agent(name="a", objective="o", status="active", mcp_servers=[server])
    session.add(agent)
    await session.commit()
    task = AgentTask(agent_id=agent.id, trigger="manual", objective="o", instructions="", max_steps=5, timeout_seconds=60, status="running")
    session.add(task)
    await session.commit()
    return server, agent, task


async def test_constants_include_the_new_states():
    assert "waiting_approval" in OPEN_STATUSES
    assert "approval_requested" in STEP_KINDS


async def test_agent_max_auto_risk_default_and_bounds(session):
    agent = Agent(name="a", objective="o")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    assert agent.max_auto_risk == 1
    agent.max_auto_risk = 3
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_task_accepts_waiting_approval_and_keeps_one_open_per_agent(session):
    _, agent, task = await _agent_and_task(session)
    task.status = "waiting_approval"
    await session.commit()
    session.add(AgentTask(agent_id=agent.id, trigger="manual", objective="o2", instructions="", max_steps=5, timeout_seconds=60))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_step_kind_approval_requested(session):
    _, _, task = await _agent_and_task(session)
    session.add(AgentTaskStep(task_id=task.id, seq=1, kind="approval_requested", payload={"code": "ABC234"}))
    await session.commit()


async def test_tool_policy_unique_and_default_level(session):
    server, _, _ = await _agent_and_task(session)
    session.add(ToolPolicy(mcp_server_id=server.id, tool_name="list_x"))
    await session.commit()
    p = (await session.execute(select(ToolPolicy))).scalar_one()
    assert p.risk_level == 2 and p.first_seen_at is not None
    session.add(ToolPolicy(mcp_server_id=server.id, tool_name="list_x"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_approval_defaults_and_checks(session):
    _, agent, task = await _agent_and_task(session)
    a = Approval(task_id=task.id, agent_id=agent.id, step_seq=2, call_index=0, tool_name="write_x", server_name="srv",
                 args={"a": 1}, args_hash="h", risk_level=2, code="ABC234", expires_at=task.created_at)
    session.add(a)
    await session.commit()
    await session.refresh(a)
    assert a.status == "pending" and a.consumed_at is None and a.requested_at is not None
    a.status = "maybe"
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    await session.delete(await session.get(AgentTask, task.id))
    await session.commit()
    assert (await session.execute(select(Approval))).scalars().all() == []


async def test_config_approval_defaults(session):
    c = Config(llm_provider="openai", llm_model="m", api_key="")
    session.add(c)
    await session.commit()
    await session.refresh(c)
    assert c.approval_expiry_hours == 24 and c.approval_whatsapp_enabled is False
    assert c.approval_whatsapp_number == "+2250700003331"
    assert c.approval_whatsapp_server_id is None and c.approval_whatsapp_session_id is None
    assert "{code}" in c.approval_whatsapp_template and "{link}" in c.approval_whatsapp_template
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_approval_models.py -q -p no:cacheprovider`
Expected: FAIL at import (`cannot import name 'Approval'`).

- [ ] **Step 3: Settings and models**

`backend/app/config.py`, inside `Settings` after the MCP timeout: 

```python
    # Used to build the task links put in WhatsApp approval notifications.
    PUBLIC_BASE_URL: str = "https://tour.alcall.net"
```

`backend/app/models/agent.py`, after `cron_expr`:

```python
    # Tools at or below this risk level run without approval; 3 is never automatic.
    max_auto_risk: Mapped[int] = mapped_column(Integer, default=1)
```
and add to `__table_args__`: `CheckConstraint("max_auto_risk BETWEEN 0 AND 2", name="ck_agent_max_auto_risk"),`.

`backend/app/models/agent_task.py`: 

```python
TASK_STATUSES = ("queued", "running", "waiting_approval", "completed", "failed", "cancelled")
OPEN_STATUSES = ("queued", "running", "waiting_approval")
STEP_KINDS = ("plan", "turn", "tool_call", "critique", "report", "error", "approval_requested")
```
and the two CHECKs: `"status IN ('queued','running','waiting_approval','completed','failed','cancelled')"`, `"kind IN ('plan','turn','tool_call','critique','report','error','approval_requested')"`.

`backend/app/models/config.py`, before `updated_at`:

```python
    # Agent approvals
    approval_expiry_hours: Mapped[int] = mapped_column(Integer, default=24)
    approval_whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_whatsapp_number: Mapped[str] = mapped_column(String(32), default="+2250700003331")
    approval_whatsapp_server_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approval_whatsapp_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_whatsapp_template: Mapped[str] = mapped_column(
        Text,
        default=(
            "Approbation requise · {agent}\n"
            "{tool} sur {server}\n"
            "{args}\n"
            "Répondre OUI {code} ou NON {code}\n"
            "Expire à {expires} · {link}"
        ),
    )
```

Create `backend/app/models/tool_policy.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base

DEFAULT_RISK_LEVEL = 2


class ToolPolicy(Base):
    """Risk level of one tool on one MCP server. Rows are created on discovery
    with the default level and only ever edited by an operator."""
    __tablename__ = "tool_policy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mcp_server.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(200))
    risk_level: Mapped[int] = mapped_column(SmallInteger, default=DEFAULT_RISK_LEVEL)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("mcp_server_id", "tool_name", name="uq_tool_policy_server_tool"),
        CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_tool_policy_risk_level"),
    )
```

Create `backend/app/models/approval.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.config import Base

APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class Approval(Base):
    """One operator decision bound to one exact tool call of one task."""
    __tablename__ = "approval"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_task.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"))
    step_seq: Mapped[int] = mapped_column(Integer)
    call_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(200))
    server_name: Mapped[str] = mapped_column(String(200))
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    args_hash: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[int] = mapped_column(SmallInteger)
    code: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notify_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','expired')", name="ck_approval_status"),
        CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_approval_risk_level"),
        Index("ix_approval_pending", "expires_at", postgresql_where=text("status = 'pending'")),
        Index("ix_approval_task", "task_id", "step_seq"),
    )
```

`backend/app/models/__init__.py`: add `from app.models.tool_policy import ToolPolicy` and `from app.models.approval import Approval`; append both names to `__all__`.

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_approval_models.py tests/test_agent_task_models.py tests/test_agent_model.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 5: Migration**

Create `backend/alembic/versions/5a6b7c8d9e0f_add_approvals.py`:

```python
"""add tool policies, approvals, agent risk ceiling, waiting_approval

Revision ID: 5a6b7c8d9e0f
Revises: 4f5a6b7c8d9e
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "5a6b7c8d9e0f"
down_revision = "4f5a6b7c8d9e"
branch_labels = None
depends_on = None

OLD_STATUS = "status IN ('queued','running','completed','failed','cancelled')"
NEW_STATUS = "status IN ('queued','running','waiting_approval','completed','failed','cancelled')"
OLD_KIND = "kind IN ('plan','turn','tool_call','critique','report','error')"
NEW_KIND = "kind IN ('plan','turn','tool_call','critique','report','error','approval_requested')"
TEMPLATE = ("Approbation requise · {agent}\n{tool} sur {server}\n{args}\n"
            "Répondre OUI {code} ou NON {code}\nExpire à {expires} · {link}")


def upgrade():
    op.add_column("agent", sa.Column("max_auto_risk", sa.SmallInteger(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_agent_max_auto_risk", "agent", "max_auto_risk BETWEEN 0 AND 2")

    op.drop_constraint("ck_agent_task_status", "agent_task", type_="check")
    op.create_check_constraint("ck_agent_task_status", "agent_task", NEW_STATUS)
    op.drop_constraint("ck_agent_task_step_kind", "agent_task_step", type_="check")
    op.create_check_constraint("ck_agent_task_step_kind", "agent_task_step", NEW_KIND)

    op.add_column("config", sa.Column("approval_expiry_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column("config", sa.Column("approval_whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("config", sa.Column("approval_whatsapp_number", sa.String(length=32), nullable=False, server_default="+2250700003331"))
    op.add_column("config", sa.Column("approval_whatsapp_server_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("config", sa.Column("approval_whatsapp_session_id", sa.String(length=100), nullable=True))
    op.add_column("config", sa.Column("approval_whatsapp_template", sa.Text(), nullable=False, server_default=TEMPLATE))

    op.create_table(
        "tool_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mcp_server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("risk_level", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("mcp_server_id", "tool_name", name="uq_tool_policy_server_tool"),
        sa.CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_tool_policy_risk_level"),
    )
    op.create_table(
        "approval",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=False),
        sa.Column("call_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notify_error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending','approved','rejected','expired')", name="ck_approval_status"),
        sa.CheckConstraint("risk_level BETWEEN 0 AND 3", name="ck_approval_risk_level"),
    )
    op.create_index("ix_approval_pending", "approval", ["expires_at"], postgresql_where=sa.text("status = 'pending'"))
    op.create_index("ix_approval_task", "approval", ["task_id", "step_seq"])


def downgrade():
    op.drop_index("ix_approval_task", table_name="approval")
    op.drop_index("ix_approval_pending", table_name="approval")
    op.drop_table("approval")
    op.drop_table("tool_policy")
    for column in ("approval_whatsapp_template", "approval_whatsapp_session_id", "approval_whatsapp_server_id",
                   "approval_whatsapp_number", "approval_whatsapp_enabled", "approval_expiry_hours"):
        op.drop_column("config", column)
    op.drop_constraint("ck_agent_task_step_kind", "agent_task_step", type_="check")
    op.create_check_constraint("ck_agent_task_step_kind", "agent_task_step", OLD_KIND)
    op.drop_constraint("ck_agent_task_status", "agent_task", type_="check")
    op.create_check_constraint("ck_agent_task_status", "agent_task", OLD_STATUS)
    op.drop_constraint("ck_agent_max_auto_risk", "agent", type_="check")
    op.drop_column("agent", "max_auto_risk")
```

Round-trip on the dev DB from `backend/` (`.env` provides `DATABASE_URL`):

```bash
PYTHONPATH=. venv/bin/alembic heads            # 4f5a6b7c8d9e (head)
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic downgrade -1
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic heads            # 5a6b7c8d9e0f (head), single
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/models/tool_policy.py backend/app/models/approval.py backend/app/models/agent.py backend/app/models/agent_task.py backend/app/models/config.py backend/app/models/__init__.py backend/alembic/versions/5a6b7c8d9e0f_add_approvals.py backend/tests/test_approval_models.py
git commit -m "feat(agents): add tool policies, approvals, the agent risk ceiling and the waiting_approval state

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `ToolPolicyService` and the tool policy API

**Files:**
- Create: `backend/app/services/tool_policy_service.py`
- Create: `backend/app/schemas/tool_policy.py`; modify `backend/app/schemas/__init__.py`
- Modify: `backend/app/routers/mcp_servers.py`
- Test: `backend/tests/test_tool_policy_service.py`, `backend/tests/test_api_tool_policies.py`

**Interfaces:**
- Produces:
  ```python
  class ToolPolicyService:
      @staticmethod async def sync(session, server: McpServer, tools: list[dict]) -> None   # tools = McpToolInfo dicts; inserts missing rows at 2, refreshes description, never touches risk_level
      @staticmethod async def levels_for(session, server_map: dict[str, McpServer]) -> dict[str, int]  # syncs missing names at 2, returns tool_name -> level
      @staticmethod async def discover(session, server) -> list[ToolPolicyRead]  # test_connection + sync + merge; raises ToolDiscoveryError(detail) on failure
      @staticmethod async def set_level(session, server, tool_name, level) -> ToolPolicy  # raises LookupError when unknown
  class ToolPolicyRead(BaseModel): name: str; description: str | None; risk_level: int
  class ToolPolicyUpdate(BaseModel): risk_level: int  # ge=0, le=3
  ```
- Endpoints `GET /api/v1/mcp-servers/{id}/tools`, `PUT /api/v1/mcp-servers/{id}/tools/{tool_name}`; `POST /{id}/test` now syncs policies on success.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_tool_policy_service.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select

from app.models import McpServer, ToolPolicy
from app.services.tool_policy_service import ToolPolicyService


async def _server(session, name="srv"):
    s = McpServer(name=name, transport="http", url="http://x", enabled=True)
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def test_sync_inserts_at_default_and_never_overwrites_a_level(session):
    server = await _server(session)
    await ToolPolicyService.sync(session, server, [{"name": "list_x", "description": "list"}, {"name": "write_x", "description": None}])
    rows = {p.tool_name: p for p in (await session.execute(select(ToolPolicy))).scalars().all()}
    assert rows["list_x"].risk_level == 2 and rows["list_x"].description == "list"
    await ToolPolicyService.set_level(session, server, "list_x", 0)
    await ToolPolicyService.sync(session, server, [{"name": "list_x", "description": "list v2"}])
    await session.refresh(rows["list_x"])
    assert rows["list_x"].risk_level == 0 and rows["list_x"].description == "list v2"


async def test_levels_for_returns_levels_and_creates_missing(session):
    server = await _server(session)
    await ToolPolicyService.sync(session, server, [{"name": "list_x", "description": ""}])
    await ToolPolicyService.set_level(session, server, "list_x", 0)
    levels = await ToolPolicyService.levels_for(session, {"list_x": server, "brand_new": server})
    assert levels == {"list_x": 0, "brand_new": 2}
    assert (await session.execute(select(ToolPolicy).where(ToolPolicy.tool_name == "brand_new"))).scalar_one().risk_level == 2


async def test_set_level_unknown_tool_raises(session):
    server = await _server(session)
    with pytest.raises(LookupError):
        await ToolPolicyService.set_level(session, server, "nope", 1)


async def test_levels_are_per_server(session):
    a = await _server(session, "a")
    b = await _server(session, "b")
    await ToolPolicyService.sync(session, a, [{"name": "t"}])
    await ToolPolicyService.sync(session, b, [{"name": "t"}])
    await ToolPolicyService.set_level(session, a, "t", 0)
    assert await ToolPolicyService.levels_for(session, {"t": b}) == {"t": 2}
```

Create `backend/tests/test_api_tool_policies.py`:

```python
import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Base, McpServer
from app.schemas import McpTestResult, McpToolInfo

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_async_session] = override
    yield factory
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


DISCOVERED = McpTestResult(success=True, tools=[McpToolInfo(name="list_x", description="list"), McpToolInfo(name="write_x", description="write")])


async def make_server(factory) -> str:
    async with factory() as s:
        server = McpServer(name="srv", transport="http", url="http://x", enabled=True)
        s.add(server)
        await s.commit()
        return str(server.id)


async def test_list_tools_discovers_and_merges_policies(setup_test_db):
    sid = await make_server(setup_test_db)
    with patch("app.services.tool_policy_service.McpService.test_connection", AsyncMock(return_value=DISCOVERED)):
        async with client() as c:
            resp = await c.get(f"/api/v1/mcp-servers/{sid}/tools")
            assert resp.status_code == 200, resp.text
            assert resp.json() == [{"name": "list_x", "description": "list", "risk_level": 2},
                                   {"name": "write_x", "description": "write", "risk_level": 2}]
            resp = await c.put(f"/api/v1/mcp-servers/{sid}/tools/list_x", json={"risk_level": 0})
            assert resp.status_code == 200 and resp.json()["risk_level"] == 0
            resp = await c.get(f"/api/v1/mcp-servers/{sid}/tools")
            assert [t["risk_level"] for t in resp.json()] == [0, 2]


async def test_put_validates_and_404s(setup_test_db):
    sid = await make_server(setup_test_db)
    async with client() as c:
        assert (await c.put(f"/api/v1/mcp-servers/{sid}/tools/list_x", json={"risk_level": 4})).status_code == 422
        assert (await c.put(f"/api/v1/mcp-servers/{sid}/tools/unknown", json={"risk_level": 1})).status_code == 404
        assert (await c.put(f"/api/v1/mcp-servers/{uuid.uuid4()}/tools/x", json={"risk_level": 1})).status_code == 404


async def test_discovery_failure_is_502(setup_test_db):
    sid = await make_server(setup_test_db)
    with patch("app.services.tool_policy_service.McpService.test_connection", AsyncMock(return_value=McpTestResult(success=False, error="down"))):
        async with client() as c:
            resp = await c.get(f"/api/v1/mcp-servers/{sid}/tools")
    assert resp.status_code == 502 and "down" in resp.json()["detail"]


async def test_test_endpoint_syncs_policies(setup_test_db):
    sid = await make_server(setup_test_db)
    with patch("app.routers.mcp_servers.McpService.test_connection", AsyncMock(return_value=DISCOVERED)):
        async with client() as c:
            assert (await c.post(f"/api/v1/mcp-servers/{sid}/test")).status_code == 200
    from sqlalchemy import select
    from app.models import ToolPolicy
    async with setup_test_db() as s:
        names = sorted(p.tool_name for p in (await s.execute(select(ToolPolicy))).scalars().all())
    assert names == ["list_x", "write_x"]
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_tool_policy_service.py tests/test_api_tool_policies.py -q -p no:cacheprovider`
Expected: FAIL at import / 404 on the new routes.

- [ ] **Step 3: Schemas**

Create `backend/app/schemas/tool_policy.py`:

```python
from pydantic import BaseModel, Field


class ToolPolicyRead(BaseModel):
    name: str
    description: str | None
    risk_level: int


class ToolPolicyUpdate(BaseModel):
    risk_level: int = Field(ge=0, le=3)
```

Export both from `app/schemas/__init__.py`.

- [ ] **Step 4: Service**

Create `backend/app/services/tool_policy_service.py`:

```python
"""Risk levels of MCP tools. Discovery only ever adds rows at the default
level or refreshes descriptions; levels change only through set_level."""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import McpServer, ToolPolicy
from app.models.tool_policy import DEFAULT_RISK_LEVEL
from app.schemas.tool_policy import ToolPolicyRead
from app.services.mcp_service import McpService

log = structlog.get_logger()


class ToolDiscoveryError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ToolPolicyService:

    @staticmethod
    async def sync(session: AsyncSession, server: McpServer, tools: list[dict]) -> None:
        existing = {p.tool_name: p for p in (await session.execute(
            select(ToolPolicy).where(ToolPolicy.mcp_server_id == server.id))).scalars().all()}
        for t in tools:
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
            if not name:
                continue
            description = t.get("description") if isinstance(t, dict) else getattr(t, "description", None)
            row = existing.get(name)
            if row is None:
                session.add(ToolPolicy(mcp_server_id=server.id, tool_name=name, description=description))
            elif description is not None and row.description != description:
                row.description = description
        await session.commit()

    @staticmethod
    async def levels_for(session: AsyncSession, server_map: dict[str, McpServer]) -> dict[str, int]:
        """tool_name -> risk level for the tools in server_map, creating missing rows at the default."""
        by_server: dict = {}
        for name, server in server_map.items():
            by_server.setdefault(server.id, (server, []))[1].append(name)
        levels: dict[str, int] = {}
        for server, names in by_server.values():
            await ToolPolicyService.sync(session, server, [{"name": n} for n in names])
            rows = (await session.execute(
                select(ToolPolicy.tool_name, ToolPolicy.risk_level)
                .where(ToolPolicy.mcp_server_id == server.id, ToolPolicy.tool_name.in_(names)))).all()
            levels.update({n: int(l) for n, l in rows})
        for name in server_map:
            levels.setdefault(name, DEFAULT_RISK_LEVEL)
        return levels

    @staticmethod
    async def discover(session: AsyncSession, server: McpServer) -> list[ToolPolicyRead]:
        result = await McpService.test_connection(server)
        if not result.success:
            raise ToolDiscoveryError(result.error or "discovery failed")
        tools = [t.model_dump() for t in result.tools]
        await ToolPolicyService.sync(session, server, tools)
        rows = {p.tool_name: p for p in (await session.execute(
            select(ToolPolicy).where(ToolPolicy.mcp_server_id == server.id))).scalars().all()}
        return [ToolPolicyRead(name=t["name"], description=t.get("description"),
                               risk_level=rows[t["name"]].risk_level if t["name"] in rows else DEFAULT_RISK_LEVEL)
                for t in tools]

    @staticmethod
    async def set_level(session: AsyncSession, server: McpServer, tool_name: str, level: int) -> ToolPolicy:
        row = (await session.execute(select(ToolPolicy).where(
            ToolPolicy.mcp_server_id == server.id, ToolPolicy.tool_name == tool_name))).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Tool {tool_name} is not known on server {server.name}")
        row.risk_level = level
        await session.commit()
        await session.refresh(row)
        log.info("tool_policy_set", server=server.name, tool=tool_name, risk_level=level)
        return row
```

- [ ] **Step 5: Router**

In `backend/app/routers/mcp_servers.py`: import `ToolPolicyRead`, `ToolPolicyUpdate`, `ToolPolicyService`, `ToolDiscoveryError`. In `test_server`, after a successful `McpService.test_connection(server)` result, add `if result.success: await ToolPolicyService.sync(session, server, [t.model_dump() for t in result.tools])` before returning. Append:

```python
@router.get("/{server_id}/tools", response_model=list[ToolPolicyRead])
async def list_server_tools(server_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    try:
        return await ToolPolicyService.discover(session, server)
    except ToolDiscoveryError as exc:
        raise HTTPException(status_code=502, detail=f"Tool discovery failed: {exc.detail}")


@router.put("/{server_id}/tools/{tool_name}", response_model=ToolPolicyRead)
async def set_tool_policy(server_id: uuid.UUID, tool_name: str, data: ToolPolicyUpdate, session: AsyncSession = Depends(get_async_session)):
    server = await session.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    try:
        row = await ToolPolicyService.set_level(session, server, tool_name, data.risk_level)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ToolPolicyRead(name=row.tool_name, description=row.description, risk_level=row.risk_level)
```

- [ ] **Step 6: Run and commit**

Run: `venv/bin/python -m pytest tests/test_tool_policy_service.py tests/test_api_tool_policies.py tests/test_api_mcp_servers.py -q -p no:cacheprovider` → all passed.

```bash
git add backend/app/services/tool_policy_service.py backend/app/schemas/tool_policy.py backend/app/schemas/__init__.py backend/app/routers/mcp_servers.py backend/tests/test_tool_policy_service.py backend/tests/test_api_tool_policies.py
git commit -m "feat(agents): classify MCP tools by risk level with a per-server policy catalogue

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Agent ceiling and approval config in schemas, routers and services

**Files:**
- Modify: `backend/app/schemas/agent.py`, `backend/app/services/agent_service.py`, `backend/app/routers/agents.py`
- Modify: `backend/app/schemas/config.py`, `backend/app/routers/config.py`
- Test: append to `backend/tests/test_api_agents.py` and `backend/tests/test_api_config.py`

**Interfaces:**
- `AgentCreate.max_auto_risk: int = Field(default=1, ge=0, le=2)`, `AgentUpdate.max_auto_risk: int | None`, `AgentRead.max_auto_risk: int`; `apply_update` copies it.
- `ConfigRead` / `ConfigUpdate` gain `approval_expiry_hours`, `approval_whatsapp_enabled`, `approval_whatsapp_number`, `approval_whatsapp_server_id: uuid.UUID | None`, `approval_whatsapp_session_id: str | None`, `approval_whatsapp_template`.

- [ ] **Step 1: Append the failing tests**

`backend/tests/test_api_agents.py`:

```python
# ---- risk ceiling -----------------------------------------------------------

async def test_max_auto_risk_defaults_updates_and_bounds():
    async with client() as c:
        data = await create_agent(c)
        assert data["max_auto_risk"] == 1
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"max_auto_risk": 2})
        assert resp.status_code == 200 and resp.json()["max_auto_risk"] == 2
        assert (await c.put(f"/api/v1/agents/{data['id']}", json={"max_auto_risk": 3})).status_code == 422
        resp = await c.post("/api/v1/agents", json={"name": "x", "objective": "y", "mcp_server_ids": [], "max_auto_risk": 0})
        assert resp.status_code == 201 and resp.json()["max_auto_risk"] == 0
```

`backend/tests/test_api_config.py` (use that file's existing fixture and client pattern):

```python
async def test_approval_settings_round_trip(setup_test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        before = (await c.get("/api/v1/config")).json()
        assert before["approval_expiry_hours"] == 24 and before["approval_whatsapp_enabled"] is False
        assert before["approval_whatsapp_number"] == "+2250700003331" and before["approval_whatsapp_server_id"] is None
        resp = await c.put("/api/v1/config", json={"approval_expiry_hours": 48, "approval_whatsapp_enabled": True,
                                                   "approval_whatsapp_number": "+22501020304", "approval_whatsapp_session_id": "sess-1",
                                                   "approval_whatsapp_template": "Hi {agent} {code} {link}"})
        assert resp.status_code == 200, resp.text
        after = resp.json()
        assert after["approval_expiry_hours"] == 48 and after["approval_whatsapp_enabled"] is True
        assert after["approval_whatsapp_number"] == "+22501020304" and after["approval_whatsapp_session_id"] == "sess-1"
        assert (await c.put("/api/v1/config", json={"approval_expiry_hours": 0})).status_code == 422
        assert (await c.put("/api/v1/config", json={"approval_whatsapp_number": "abc"})).status_code == 422
        assert (await c.put("/api/v1/config", json={"approval_whatsapp_template": "no code here"})).status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_api_agents.py tests/test_api_config.py -q -p no:cacheprovider -k "risk or approval_settings"`
Expected: FAIL (`max_auto_risk` missing from the response / 422 on unknown fields).

- [ ] **Step 3: Agent schemas, service, router**

`schemas/agent.py`: add `max_auto_risk: int = Field(default=1, ge=0, le=2)` to `AgentCreate`, `max_auto_risk: int | None = Field(default=None, ge=0, le=2)` to `AgentUpdate`, `max_auto_risk: int` to `AgentRead`. `services/agent_service.py` `apply_update`: add `"max_auto_risk"` to the copied fields tuple. `routers/agents.py`: pass `max_auto_risk=data.max_auto_risk` in `create_agent`'s `Agent(...)` and `max_auto_risk=agent.max_auto_risk` in `_to_read`.

- [ ] **Step 4: Config schemas and router**

`schemas/config.py`: add to `ConfigRead`

```python
    approval_expiry_hours: int
    approval_whatsapp_enabled: bool
    approval_whatsapp_number: str
    approval_whatsapp_server_id: uuid.UUID | None
    approval_whatsapp_session_id: str | None
    approval_whatsapp_template: str
```
and to `ConfigUpdate`

```python
    approval_expiry_hours: int | None = Field(default=None, ge=1, le=168)
    approval_whatsapp_enabled: bool | None = None
    approval_whatsapp_number: str | None = Field(default=None, pattern=r"^\+?\d{8,15}$")
    approval_whatsapp_server_id: uuid.UUID | None = None
    approval_whatsapp_session_id: str | None = None
    approval_whatsapp_template: str | None = None
```
(import `Field`). `routers/config.py` `update_config`: before touching the DB, `if data.approval_whatsapp_template is not None and "{code}" not in data.approval_whatsapp_template: raise HTTPException(422, "approval_whatsapp_template must contain {code}")`; then copy each non-None approval field onto `config` the way the other fields are copied. Note `approval_whatsapp_server_id` and `approval_whatsapp_session_id` are nullable: copy them when the field is in `data.model_fields_set` (so an explicit `null` clears them). Make sure the read path (`_to_read` or `ConfigRead.model_validate`) includes the six fields.

- [ ] **Step 5: Run and commit**

Run: `venv/bin/python -m pytest tests/test_api_agents.py tests/test_api_config.py tests/test_agent_service.py -q -p no:cacheprovider` → all passed.

```bash
git add backend/app/schemas/agent.py backend/app/services/agent_service.py backend/app/routers/agents.py backend/app/schemas/config.py backend/app/routers/config.py backend/tests/test_api_agents.py backend/tests/test_api_config.py
git commit -m "feat(agents): expose the agent risk ceiling and the approval settings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `ApprovalService`, `park` / `resume`, cancel of a waiting task

**Files:**
- Create: `backend/app/services/approval_service.py`
- Modify: `backend/app/services/agent_task_service.py`
- Test: `backend/tests/test_approval_service.py`

**Interfaces:**
- Produces:
  ```python
  class ApprovalConflict(Exception): status_code = 409; detail
  def canonical_hash(args: dict) -> str
  class ApprovalService:
      @staticmethod async def request(session, task, *, step_seq, call_index, tool_name, server_name, args, risk_level) -> Approval
          # creates pending approval (unique code, expires_at = now + config.approval_expiry_hours), writes the approval_requested step, parks the task; returns the approval
      @staticmethod async def decide(session, approval, *, approve: bool, decided_by: str, reason: str | None) -> Approval
          # conditional UPDATE WHERE status='pending' else ApprovalConflict; then: task not waiting → nothing; agent not active → task failed "agent is not active"; else AgentTaskService.resume
      @staticmethod async def decided_unconsumed(session, task_id) -> Approval | None
      @staticmethod async def mark_consumed(session, approval) -> None
      @staticmethod async def expire_due(session) -> int        # pending past expires_at → expired + task failed "approval expired" (+ error step)
      @staticmethod async def expire_for_task(session, task_id, decided_by) -> int   # pending approvals of a task → expired
      @staticmethod async def list_pending(session) -> list[Approval]   # oldest first
      @staticmethod async def set_notified(session, approval, *, error: str | None) -> None
  # AgentTaskService additions
      @staticmethod async def park(session, task) -> bool      # running → waiting_approval (conditional), notify event
      @staticmethod async def resume(session, task) -> bool    # waiting_approval → queued (conditional), notify queued + event
      # request_cancel: waiting_approval behaves like queued (finish cancelled) and expires its pending approvals via a local import of ApprovalService
  ```

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_approval_service.py`:

```python
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy import select

from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config, McpServer
from app.services.agent_task_service import AgentTaskService, TaskConflict
from app.services.approval_service import ApprovalConflict, ApprovalService, canonical_hash


async def running_task(session, *, expiry_hours=24):
    session.add(Config(llm_provider="openai", llm_model="m", api_key="", approval_expiry_hours=expiry_hours))
    agent = Agent(name="a", objective="o", status="active",
                  mcp_servers=[McpServer(name="srv", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    task = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {"a": 1}}]})
    return agent, task


async def request(session, task, **over):
    kw = dict(step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={"a": 1}, risk_level=2)
    kw.update(over)
    return await ApprovalService.request(session, task, **kw)


def test_canonical_hash_is_order_independent():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


async def test_request_creates_pending_approval_and_parks(session):
    agent, task = await running_task(session, expiry_hours=2)
    before = datetime.now(timezone.utc)
    approval = await request(session, task)
    await session.refresh(task)
    assert task.status == "waiting_approval"
    assert approval.status == "pending" and len(approval.code) == 6 and approval.code.isupper()
    assert approval.args_hash == canonical_hash({"a": 1})
    assert timedelta(hours=1, minutes=59) < approval.expires_at - before < timedelta(hours=2, minutes=1)
    steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq))).scalars().all()
    assert steps[-1].kind == "approval_requested" and steps[-1].payload["code"] == approval.code
    assert steps[-1].payload["approval_id"] == str(approval.id) and steps[-1].payload["risk_level"] == 2


async def test_codes_are_unique_among_open_approvals(session):
    agent, task = await running_task(session)
    first = await request(session, task)
    # a second task of another agent, to get a second pending approval
    agent2 = Agent(name="b", objective="o", status="active", mcp_servers=[McpServer(name="s2", transport="http", url="http://y", enabled=True)])
    session.add(agent2)
    await session.commit()
    await AgentTaskService.enqueue(session, agent2, objective=None, trigger="manual")
    task2 = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task2, "turn", {"text": None, "tool_calls": []})
    import app.services.approval_service as mod
    codes = iter([first.code, first.code, "ZZZZZ9"])
    original = mod._new_code
    mod._new_code = lambda: next(codes)
    try:
        second = await request(session, task2)
    finally:
        mod._new_code = original
    assert second.code == "ZZZZZ9"


async def test_approve_resumes_and_is_single_shot(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    decided = await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    await session.refresh(task)
    assert decided.status == "approved" and decided.decided_by == "ui" and decided.decided_at is not None
    assert task.status == "queued"
    with pytest.raises(ApprovalConflict):
        await ApprovalService.decide(session, approval, approve=False, decided_by="ui", reason="late")
    pending = await ApprovalService.decided_unconsumed(session, task.id)
    assert pending is not None and pending.id == approval.id
    await ApprovalService.mark_consumed(session, approval)
    assert await ApprovalService.decided_unconsumed(session, task.id) is None


async def test_reject_resumes_with_reason(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    decided = await ApprovalService.decide(session, approval, approve=False, decided_by="whatsapp:2250700003331", reason="NON ABC234")
    await session.refresh(task)
    assert decided.status == "rejected" and decided.decision_reason == "NON ABC234" and task.status == "queued"


async def test_decide_on_inactive_agent_fails_the_task(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    agent.status = "paused"
    await session.commit()
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    await session.refresh(task)
    assert task.status == "failed" and task.error == "agent is not active"
    assert await ApprovalService.decided_unconsumed(session, task.id) is not None  # decided, never consumed


async def test_cancel_waiting_task_expires_its_approval(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    await AgentTaskService.request_cancel(session, task)
    await session.refresh(task)
    await session.refresh(approval)
    assert task.status == "cancelled" and approval.status == "expired" and approval.decided_by == "system:cancel"
    with pytest.raises(TaskConflict):
        await AgentTaskService.request_cancel(session, task)


async def test_decide_after_cancel_changes_nothing_on_the_task(session):
    # request_cancel is what normally expires the approval; here the task was
    # finished directly so the approval is still pending while the task is final.
    agent, task = await running_task(session)
    approval = await request(session, task)
    await AgentTaskService.finish(session, task, "cancelled")
    decided = await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    await session.refresh(task)
    assert decided.status == "approved" and task.status == "cancelled"


async def test_expire_due_fails_the_task(session):
    agent, task = await running_task(session, expiry_hours=1)
    approval = await request(session, task)
    approval.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()
    assert await ApprovalService.expire_due(session) == 1
    await session.refresh(task)
    await session.refresh(approval)
    assert approval.status == "expired" and approval.decided_by == "system:expiry"
    assert task.status == "failed" and task.error == "approval expired"
    steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq))).scalars().all()
    assert steps[-1].kind == "error" and steps[-1].payload["phase"] == "approval"
    assert await ApprovalService.expire_due(session) == 0


async def test_list_pending_oldest_first_and_set_notified(session):
    agent, task = await running_task(session)
    approval = await request(session, task)
    assert [a.id for a in await ApprovalService.list_pending(session)] == [approval.id]
    await ApprovalService.set_notified(session, approval, error=None)
    await session.refresh(approval)
    assert approval.notified_at is not None and approval.notify_error is None
    await ApprovalService.set_notified(session, approval, error="boom")
    await session.refresh(approval)
    assert approval.notify_error == "boom"
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_approval_service.py -q -p no:cacheprovider`
Expected: FAIL at import.

- [ ] **Step 3: `park` / `resume` / cancel in `AgentTaskService`**

Add to `backend/app/services/agent_task_service.py`:

```python
    @staticmethod
    async def park(session: AsyncSession, task: AgentTask) -> bool:
        """running -> waiting_approval. The worker slot is freed by the runner returning."""
        result = await session.execute(
            update(AgentTask).where(AgentTask.id == task.id, AgentTask.status == "running").values(status="waiting_approval")
        )
        if result.rowcount == 0:
            await session.rollback()
            await session.refresh(task)
            log.warning("agent_task_park_skipped", task_id=str(task.id), current=task.status)
            return False
        await session.refresh(task)
        await _notify_event(session, task, None)
        await session.commit()
        log.info("agent_task_parked", task_id=str(task.id))
        return True

    @staticmethod
    async def resume(session: AsyncSession, task: AgentTask) -> bool:
        """waiting_approval -> queued; the worker claims it like any queued task."""
        result = await session.execute(
            update(AgentTask).where(AgentTask.id == task.id, AgentTask.status == "waiting_approval")
            .values(status="queued", worker_id=None, heartbeat_at=None)
        )
        if result.rowcount == 0:
            await session.rollback()
            await session.refresh(task)
            log.warning("agent_task_resume_skipped", task_id=str(task.id), current=task.status)
            return False
        await session.refresh(task)
        await _notify_event(session, task, None)
        await _notify(session, QUEUED_CHANNEL, str(task.id))
        await session.commit()
        log.info("agent_task_resumed", task_id=str(task.id))
        return True
```

Change `request_cancel`:

```python
    @staticmethod
    async def request_cancel(session: AsyncSession, task: AgentTask) -> None:
        if task.status in FINAL_STATUSES:
            raise TaskConflict(f"Task is already {task.status}")
        if task.status in ("queued", "waiting_approval"):
            await AgentTaskService.finish(session, task, "cancelled")
            # Local import: approval_service imports this module.
            from app.services.approval_service import ApprovalService
            await ApprovalService.expire_for_task(session, task.id, decided_by="system:cancel")
            return
        task.cancel_requested = True
        await session.commit()
```

- [ ] **Step 4: Create `approval_service.py`**

```python
"""Operator approvals of gated tool calls: request, decide, expire.

Every write to the approval table goes through here; task status changes go
through AgentTaskService (park / resume / finish)."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentTask, Approval, Config
from app.models.approval import CODE_ALPHABET
from app.services.agent_task_service import AgentTaskService

log = structlog.get_logger()

CODE_LENGTH = 6
NON_FINAL_APPROVAL = ("pending",)


class ApprovalConflict(Exception):
    status_code = 409

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def canonical_hash(args: dict) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:

    @staticmethod
    async def _unique_code(session: AsyncSession) -> str:
        for _ in range(20):
            code = _new_code()
            taken = (await session.execute(
                select(Approval.id).where(Approval.code == code, Approval.status.in_(NON_FINAL_APPROVAL)).limit(1)
            )).scalar_one_or_none()
            if taken is None:
                return code
        raise RuntimeError("could not allocate a unique approval code")

    @staticmethod
    async def request(session: AsyncSession, task: AgentTask, *, step_seq: int, call_index: int, tool_name: str,
                      server_name: str, args: dict, risk_level: int) -> Approval:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        hours = config.approval_expiry_hours if config else 24
        approval = Approval(
            task_id=task.id, agent_id=task.agent_id, step_seq=step_seq, call_index=call_index,
            tool_name=tool_name, server_name=server_name, args=args, args_hash=canonical_hash(args),
            risk_level=risk_level, code=await ApprovalService._unique_code(session),
            expires_at=_now() + timedelta(hours=hours),
        )
        session.add(approval)
        await session.flush()
        await AgentTaskService.record_step(session, task, "approval_requested", {
            "approval_id": str(approval.id), "tool": tool_name, "server": server_name, "args": args,
            "risk_level": risk_level, "code": approval.code, "expires_at": approval.expires_at.isoformat(),
        })
        await AgentTaskService.park(session, task)
        await session.refresh(approval)
        log.info("approval_requested", approval_id=str(approval.id), task_id=str(task.id), tool=tool_name, code=approval.code)
        return approval

    @staticmethod
    async def decide(session: AsyncSession, approval: Approval, *, approve: bool, decided_by: str,
                     reason: str | None) -> Approval:
        new_status = "approved" if approve else "rejected"
        result = await session.execute(
            update(Approval).where(Approval.id == approval.id, Approval.status == "pending")
            .values(status=new_status, decided_at=func.now(), decided_by=decided_by, decision_reason=reason)
        )
        if result.rowcount == 0:
            await session.rollback()
            await session.refresh(approval)
            raise ApprovalConflict(f"Approval is already {approval.status}")
        await session.commit()
        await session.refresh(approval)
        log.info("approval_decided", approval_id=str(approval.id), status=new_status, decided_by=decided_by)

        task = await session.get(AgentTask, approval.task_id)
        if task is None or task.status != "waiting_approval":
            return approval
        agent = await session.get(Agent, task.agent_id)
        if agent is None or agent.status != "active":
            await AgentTaskService.record_step(session, task, "error", {"message": "agent is not active", "phase": "approval"})
            await AgentTaskService.finish(session, task, "failed", error="agent is not active")
            return approval
        await AgentTaskService.resume(session, task)
        return approval

    @staticmethod
    async def decided_unconsumed(session: AsyncSession, task_id: uuid.UUID) -> Approval | None:
        return (await session.execute(
            select(Approval).where(Approval.task_id == task_id, Approval.status.in_(("approved", "rejected")),
                                   Approval.consumed_at.is_(None)).order_by(Approval.requested_at.desc()).limit(1)
        )).scalar_one_or_none()

    @staticmethod
    async def mark_consumed(session: AsyncSession, approval: Approval) -> None:
        await session.execute(update(Approval).where(Approval.id == approval.id, Approval.consumed_at.is_(None))
                              .values(consumed_at=func.now()))
        await session.commit()
        await session.refresh(approval)

    @staticmethod
    async def expire_for_task(session: AsyncSession, task_id: uuid.UUID, decided_by: str) -> int:
        result = await session.execute(
            update(Approval).where(Approval.task_id == task_id, Approval.status == "pending")
            .values(status="expired", decided_at=func.now(), decided_by=decided_by)
        )
        await session.commit()
        return result.rowcount

    @staticmethod
    async def expire_due(session: AsyncSession) -> int:
        due = (await session.execute(
            select(Approval.id).where(Approval.status == "pending", Approval.expires_at < func.now()).with_for_update(skip_locked=True)
        )).scalars().all()
        count = 0
        for aid in due:
            try:
                approval = await session.get(Approval, aid)
                if approval is None or approval.status != "pending":
                    continue
                await session.execute(update(Approval).where(Approval.id == aid)
                                      .values(status="expired", decided_at=func.now(), decided_by="system:expiry"))
                await session.commit()
                task = await session.get(AgentTask, approval.task_id)
                if task is not None and task.status == "waiting_approval":
                    await AgentTaskService.record_step(session, task, "error", {"message": "approval expired", "phase": "approval"})
                    await AgentTaskService.finish(session, task, "failed", error="approval expired")
                count += 1
            except Exception:
                log.exception("approval_expire_failed", approval_id=str(aid))
                await session.rollback()
        return count

    @staticmethod
    async def list_pending(session: AsyncSession) -> list[Approval]:
        return list((await session.execute(
            select(Approval).where(Approval.status == "pending").order_by(Approval.requested_at)
        )).scalars().all())

    @staticmethod
    async def set_notified(session: AsyncSession, approval: Approval, *, error: str | None) -> None:
        values = {"notify_error": error} if error else {"notified_at": func.now(), "notify_error": None}
        await session.execute(update(Approval).where(Approval.id == approval.id).values(**values))
        await session.commit()
```

Note `finish(..., "failed", error="approval expired")` is called while the task is `waiting_approval`, which is in `OPEN_STATUSES`, so the conditional update applies.

- [ ] **Step 5: Run and commit**

Run: `venv/bin/python -m pytest tests/test_approval_service.py tests/test_agent_task_service.py -q -p no:cacheprovider` → all passed (10 new + the existing service tests; `test_claim...` and friends still green because `OPEN_STATUSES` grew).

```bash
git add backend/app/services/approval_service.py backend/app/services/agent_task_service.py backend/tests/test_approval_service.py
git commit -m "feat(agents): add the approval service with park, resume, decision and expiry

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Runner gate and resume mode

**Files:**
- Modify: `backend/app/services/agent_runner.py`
- Test: `backend/tests/test_agent_runner_approvals.py`

**Interfaces:**
- `run_task(..., policy_levels=ToolPolicyService.levels_for, notify=None)` — `policy_levels(session, server_map) -> dict[str, int]`; `notify(session, approval)` awaited after a park (default `ApprovalNotifier.notify`, Task 6; until then `None` means skip).
- New exception `Parked(approval)`; `run_task` catches it, calls `notify` inside `try/except Exception` (logged), and returns without `finish`.
- Resume mode as specified; helper `_rebuild_history(steps) -> (messages, last_turn_seq, rounds)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_runner_approvals.py`:

```python
import json
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, AgentTask, AgentTaskStep, Approval, Config, McpServer
from app.services.agent_runner import run_task
from app.services.agent_task_service import AgentTaskService
from app.services.approval_service import ApprovalService
from app.services.llm_runtime import LlmResult
from app.utils.crypto import encrypt_value

PLAN = {"steps": [{"title": "do", "tools": ["list_x", "write_x"]}],
        "success_criteria": [{"id": "c1", "description": "done"}], "risks": []}
CRITIQUE = {"criteria": [{"id": "c1", "met": True, "confidence": 0.9, "justification": "ok"}]}
REPORT = {"summary": "done", "actions": [], "evidence": [], "uncertainties": [], "next_steps": []}
LEVELS = {"list_x": 0, "write_x": 2, "purge_x": 3}


def J(obj):
    return LlmResult(json.dumps(obj), [])


def scripted(*results):
    queue = list(results)
    calls = []

    async def llm(provider, model, api_key, messages, tools):
        calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        return queue.pop(0)
    llm.calls = calls
    return llm


async def fake_tool_defs(servers):
    return ([{"type": "function", "function": {"name": n, "description": n, "parameters": {"type": "object", "properties": {}}}} for n in LEVELS],
            {n: servers[0] for n in LEVELS})


async def fake_levels(session, server_map):
    return {n: LEVELS[n] for n in server_map}


def recording_tool():
    calls = []

    async def tool(name, args, server):
        calls.append((name, args))
        return json.dumps({"ok": name})
    tool.calls = calls
    return tool


async def setup(session, *, ceiling=1):
    session.add(Config(llm_provider="openai", llm_model="m", api_key=encrypt_value("sk-live-SENTINEL")))
    agent = Agent(name="a", objective="Inspect x", instructions="Be terse", status="active", max_auto_risk=ceiling,
                  mcp_servers=[McpServer(name="srv", transport="http", url="http://x", enabled=True)])
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    return agent, await AgentTaskService.claim(session, "w")


def factory_of(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def steps_of(session, task_id):
    return (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task_id).order_by(AgentTaskStep.seq))).scalars().all()


TWO_CALLS = LlmResult("go", [{"name": "list_x", "args": {"q": 1}}, {"name": "write_x", "args": {"v": 2}}])
DONE = LlmResult("finished", [])


async def test_tool_at_or_below_ceiling_runs_and_records_risk(setup_db, session):
    agent, task = await setup(session, ceiling=2)
    tool = recording_tool()
    llm = scripted(J(PLAN), TWO_CALLS, DONE, J(CRITIQUE), J(REPORT))
    await run_task(task.id, llm=llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory_of(setup_db))
    await session.refresh(task)
    assert task.status == "completed" and [c[0] for c in tool.calls] == ["list_x", "write_x"]
    tool_steps = [s for s in await steps_of(session, task.id) if s.kind == "tool_call"]
    assert [s.payload["risk_level"] for s in tool_steps] == [0, 2]
    assert (await session.execute(select(Approval))).scalars().all() == []


async def test_gated_tool_parks_after_executing_earlier_calls(setup_db, session):
    agent, task = await setup(session, ceiling=1)
    tool = recording_tool()
    llm = scripted(J(PLAN), TWO_CALLS)
    notified = []

    async def notify(sess, approval):
        notified.append(approval.code)
    await run_task(task.id, llm=llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels,
                   session_factory=factory_of(setup_db), notify=notify)
    await session.refresh(task)
    assert task.status == "waiting_approval" and task.finished_at is None
    assert [c[0] for c in tool.calls] == ["list_x"]                       # the R0 call ran, the R2 call did not
    kinds = [s.kind for s in await steps_of(session, task.id)]
    assert kinds == ["plan", "turn", "tool_call", "approval_requested"]
    approval = (await session.execute(select(Approval))).scalar_one()
    assert approval.tool_name == "write_x" and approval.args == {"v": 2} and approval.step_seq == 2 and approval.call_index == 1
    assert notified == [approval.code]


async def test_notify_failure_does_not_break_the_park(setup_db, session):
    agent, task = await setup(session, ceiling=1)

    async def notify(sess, approval):
        raise RuntimeError("whatsapp down")
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=recording_tool(), tool_defs=fake_tool_defs,
                   policy_levels=fake_levels, session_factory=factory_of(setup_db), notify=notify)
    await session.refresh(task)
    assert task.status == "waiting_approval"


async def test_approved_resume_executes_exact_args_and_history_matches_a_continuous_run(setup_db, session):
    factory = factory_of(setup_db)
    # Reference: same scenario with no gate, capture the prompt the model saw after both tools.
    ref_agent, ref_task = await setup(session, ceiling=2)
    ref_llm = scripted(J(PLAN), TWO_CALLS, DONE, J(CRITIQUE), J(REPORT))
    await run_task(ref_task.id, llm=ref_llm, tool=recording_tool(), tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    reference_prompt = ref_llm.calls[2]["messages"]
    # Gated run: park, approve with the model's args, resume.
    await session.delete(await session.get(Agent, ref_agent.id))
    await session.commit()
    agent, task = await setup(session, ceiling=1)
    tool = recording_tool()
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    approval = (await session.execute(select(Approval))).scalar_one()
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    claimed = await AgentTaskService.claim(session, "w2")
    assert claimed.id == task.id
    resumed_llm = scripted(DONE, J(CRITIQUE), J(REPORT))
    await run_task(task.id, llm=resumed_llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "completed" and task.outcome == "success"
    assert tool.calls == [("list_x", {"q": 1}), ("write_x", {"v": 2})]
    assert resumed_llm.calls[0]["messages"] == reference_prompt           # the rebuilt history is the real one
    steps = await steps_of(session, task.id)
    kinds = [s.kind for s in steps]
    assert kinds == ["plan", "turn", "tool_call", "approval_requested", "tool_call", "turn", "critique", "report"]
    assert steps[4].payload["approval_id"] == str(approval.id) and steps[4].payload["risk_level"] == 2
    await session.refresh(approval)
    assert approval.consumed_at is not None


async def test_rejected_resume_injects_the_refusal(setup_db, session):
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)
    tool = recording_tool()
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    approval = (await session.execute(select(Approval))).scalar_one()
    await ApprovalService.decide(session, approval, approve=False, decided_by="ui", reason="not now")
    await AgentTaskService.claim(session, "w2")
    resumed_llm = scripted(DONE, J(CRITIQUE), J(REPORT))
    await run_task(task.id, llm=resumed_llm, tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "completed" and [c[0] for c in tool.calls] == ["list_x"]
    refusal = next(m for m in resumed_llm.calls[0]["messages"] if m.get("role") == "tool" and m["tool_call_id"].endswith("_1"))
    assert json.loads(refusal["content"]) == {"error": "rejected by operator: not now"}
    tool_steps = [s for s in await steps_of(session, task.id) if s.kind == "tool_call"]
    assert tool_steps[-1].payload["ok"] is False and tool_steps[-1].payload["approval_id"] == str(approval.id)


async def test_second_gated_call_in_the_same_turn_parks_again(setup_db, session):
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)
    three = LlmResult("go", [{"name": "list_x", "args": {}}, {"name": "write_x", "args": {"v": 1}}, {"name": "purge_x", "args": {}}])
    tool = recording_tool()
    await run_task(task.id, llm=scripted(J(PLAN), three), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    first = (await session.execute(select(Approval))).scalar_one()
    await ApprovalService.decide(session, first, approve=True, decided_by="ui", reason=None)
    await AgentTaskService.claim(session, "w2")
    await run_task(task.id, llm=scripted(), tool=tool, tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "waiting_approval"
    approvals = (await session.execute(select(Approval).order_by(Approval.requested_at))).scalars().all()
    assert [a.tool_name for a in approvals] == ["write_x", "purge_x"] and approvals[1].call_index == 2
    assert [c[0] for c in tool.calls] == ["list_x", "write_x"]


async def test_resume_without_a_decision_fails_cleanly(setup_db, session):
    factory = factory_of(setup_db)
    agent, task = await setup(session, ceiling=1)
    await run_task(task.id, llm=scripted(J(PLAN), TWO_CALLS), tool=recording_tool(), tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    # Force an inconsistent state: queued again with steps but no decided approval.
    await AgentTaskService.resume(session, task)
    await AgentTaskService.claim(session, "w2")
    await run_task(task.id, llm=scripted(), tool=recording_tool(), tool_defs=fake_tool_defs, policy_levels=fake_levels, session_factory=factory)
    await session.refresh(task)
    assert task.status == "failed" and task.error.startswith("resume:")
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_agent_runner_approvals.py -q -p no:cacheprovider`
Expected: FAIL (`run_task` has no `policy_levels` / `notify` keyword).

- [ ] **Step 3: Implement the gate and resume mode**

Edit `backend/app/services/agent_runner.py`:

1. Imports: add `from app.models import Approval` (already `Agent, AgentTask, Config`), `from app.services.approval_service import ApprovalService`, `from app.services.tool_policy_service import ToolPolicyService`, `from app.models.tool_policy import DEFAULT_RISK_LEVEL`.
2. New exception after `Cancelled`:
   ```python
   class Parked(Exception):
       """The task is waiting for an operator decision; the runner exits without finishing it."""
       def __init__(self, approval):
           super().__init__(approval.code)
           self.approval = approval
   ```
3. `_Run.__init__` takes `policy_levels` and stores `self.policy_levels`; `self.levels: dict[str, int] = {}`; `self.ceiling = 1`.
4. Extract the per-call execution into a method and add the gate:
   ```python
   async def _execute_call(self, session, task, turn_seq: int, i: int, tc: dict, *, approval=None):
       server = self.server_map.get(tc["name"])
       level = self.levels.get(tc["name"], DEFAULT_RISK_LEVEL)
       t1 = self.clock()
       payload = {"tool": tc["name"], "server": server.name if server else None, "args": tc["args"], "risk_level": level}
       if server is None:
           text, ok = json.dumps({"error": f"Unknown tool: {tc['name']}"}), False
       elif approval is not None and approval.status == "rejected":
           text, ok = json.dumps({"error": f"rejected by operator: {approval.decision_reason or 'no reason given'}"}), False
       elif approval is None and level > self.ceiling:
           created = await ApprovalService.request(session, task, step_seq=turn_seq, call_index=i, tool_name=tc["name"],
                                                   server_name=server.name, args=tc["args"], risk_level=level)
           raise Parked(created)
       else:
           args = approval.args if approval is not None else tc["args"]
           text = await self.tool(tc["name"], args, server)
           ok = not _looks_like_error(text)
           payload["args"] = args
       if approval is not None:
           payload["approval_id"] = str(approval.id)
       await AgentTaskService.record_step(session, task, "tool_call", {**payload, "result": text, "ok": ok},
                                          duration_ms=int((self.clock() - t1) * 1000))
       if approval is not None:
           await ApprovalService.mark_consumed(session, approval)
       self.messages.append({"role": "tool", "tool_call_id": f"call_{turn_seq}_{i}", "content": text})
   ```
5. Split `run()` so the fresh path and the resume path share the loop. `run()` becomes:
   ```python
   async def run(self):
       async with self.sf() as session:
           task = await self._task(session)
           agent = await session.get(Agent, task.agent_id)
           config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
           if not config or not config.api_key:
               raise RunFailed("claim", "LLM not configured. Set API key in Config.")
           self.provider, self.model, self.api_key = config.llm_provider, config.llm_model, decrypt_value(config.api_key)
           servers = [s for s in agent.mcp_servers if s.enabled]
           self.tools, self.server_map = await self.tool_defs(servers)
           self.levels = await self.policy_levels(session, self.server_map)
           self.ceiling = agent.max_auto_risk
           self.started = self.clock()
           self.deadline = self.started + task.timeout_seconds

           decided = await ApprovalService.decided_unconsumed(session, task.id)
           if decided is not None:
               await self._resume(session, task, decided)
               return
           if task.step_count > 0:
               raise RunFailed("resume", "task has steps but no decided approval to resume from")

           self.messages = [{"role": "system", "content": SYSTEM_PROMPT.format(objective=task.objective, instructions=task.instructions or "(none)")}]
           # Phase 1: plan  (unchanged: _llm_json, record_step "plan", set_phase_output)
           ...
           # Phase 2: tool loop
           self.messages.append({"role": "user", "content": EXECUTE_PROMPT + "\nPlan:\n" + json.dumps(plan)})
           await self._loop(session, task, rounds=0)
           # Phases 3-4 run even after a limit, within a fixed grace.
           await self._finalize(session, task, plan)

   async def _loop(self, session, task, *, rounds: int):
       """The tool loop, from the given number of rounds already used."""
       while True:
           if rounds >= task.max_steps:
               self.limit_hit = LimitHit.MAX_STEPS
               break
           await AgentTaskService.heartbeat(session, task.id)
           if not await self._check_cancel_and_deadline(session):
               break
           rounds += 1
           t0 = self.clock()
           prompt_snapshot = json.loads(json.dumps(self.messages))
           result = await self.llm(self.provider, self.model, self.api_key, self.messages, self.tools)
           await AgentTaskService.record_step(session, task, "turn", {"text": result.text or None, "tool_calls": result.tool_calls},
                                              prompt=prompt_snapshot, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                                              duration_ms=int((self.clock() - t0) * 1000))
           if not result.tool_calls:
               if result.text:
                   self.messages.append({"role": "assistant", "content": result.text})
               break
           turn_seq = task.step_count  # seq of the turn step just written; ids must match between the two messages
           self.messages.append({"role": "assistant", "content": result.text or None, "tool_calls": [
               {"id": f"call_{turn_seq}_{i}", "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
               for i, tc in enumerate(result.tool_calls)]})
           for i, tc in enumerate(result.tool_calls):
               await self._execute_call(session, task, turn_seq, i, tc)

   async def _resume(self, session, task, approval):
       """Continue after an operator decision: rebuild the history from the journal, no LLM call."""
       steps = (await session.execute(select(AgentTaskStep).where(AgentTaskStep.task_id == task.id).order_by(AgentTaskStep.seq))).scalars().all()
       self.messages, turn_seq, rounds, tool_calls = _rebuild_history(steps)
       plan = task.plan
       if plan is None or turn_seq is None or approval.call_index >= len(tool_calls):
           raise RunFailed("resume", "journal has no plan or no turn to resume from")
       await AgentTaskService.heartbeat(session, task.id)
       # Apply the decision to its call, then re-gate the rest of that turn.
       await self._execute_call(session, task, turn_seq, approval.call_index, tool_calls[approval.call_index], approval=approval)
       for i in range(approval.call_index + 1, len(tool_calls)):
           await self._execute_call(session, task, turn_seq, i, tool_calls[i])
       await self._loop(session, task, rounds=rounds)
       await self._finalize(session, task, plan)
   ```
   The deadline restarts at every running segment because `self.started` is set before the resume branch. Import `AgentTaskStep` from `app.models`.
6. Module-level helper:
   ```python
   def _rebuild_history(steps) -> tuple[list[dict], int | None, int, list[dict]]:
       """Messages as the model last saw them, the seq of the last turn, the number of turns so far, and that turn's tool calls."""
       turns = [s for s in steps if s.kind == "turn"]
       if not turns:
           return [], None, 0, []
       last = turns[-1]
       messages = json.loads(json.dumps(last.prompt or []))
       tool_calls = list(last.payload.get("tool_calls") or [])
       messages.append({"role": "assistant", "content": last.payload.get("text"), "tool_calls": [
           {"id": f"call_{last.seq}_{i}", "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
           for i, tc in enumerate(tool_calls)]})
       # Tool results recorded after that turn, in execution order: calls run
       # in index order and the gated one is always the first not yet recorded,
       # so the i-th recorded result belongs to call i.
       recorded = [s for s in steps if s.kind == "tool_call" and s.seq > last.seq]
       for i, s in enumerate(recorded):
           messages.append({"role": "tool", "tool_call_id": f"call_{last.seq}_{i}", "content": s.payload.get("result", "")})
       return messages, last.seq, len(turns), tool_calls
   ```
7. `run_task` signature: `async def run_task(task_id, *, llm=call_llm, tool=call_mcp_tool, tool_defs=build_tool_defs, policy_levels=ToolPolicyService.levels_for, notify=None, session_factory=async_session, clock=time.monotonic)`; pass `policy_levels` to `_Run`; add before `except Cancelled`:
   ```python
   except Parked as parked:
       if notify is not None:
           try:
               async with session_factory() as session:
                   await notify(session, parked.approval)
           except Exception as exc:  # noqa: BLE001 - notification never decides the task's fate
               log.warning("approval_notify_failed", approval_id=str(parked.approval.id), error=str(exc))
       return
   ```
   In Task 6 the default becomes `ApprovalNotifier.notify`.
8. Existing tests: `tests/test_agent_runner.py` uses the default `policy_levels`, which creates a level-2 `ToolPolicy` row for `list_x`, while its agents keep the default ceiling of 1 — every legacy scenario would park instead of calling the tool. In its `setup()` helper, create the agent with `max_auto_risk=2` (one argument added to the `Agent(...)` constructor; nothing else changes). Any assertion there comparing a whole `tool_call` payload must now expect the extra `"risk_level": 2` key.

- [ ] **Step 4: Run and commit**

Run: `venv/bin/python -m pytest tests/test_agent_runner_approvals.py tests/test_agent_runner.py tests/test_worker.py -q -p no:cacheprovider` → all passed.

```bash
git add backend/app/services/agent_runner.py backend/tests/test_agent_runner_approvals.py backend/tests/test_agent_runner.py
git commit -m "feat(agents): gate tool calls by risk level, park for approval and resume from the journal

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: WhatsApp notifier, reply poller, scheduler jobs

**Files:**
- Create: `backend/app/services/approval_notifier.py`, `backend/app/services/approval_replies.py`
- Modify: `backend/app/services/scheduler_service.py`, `backend/app/main.py`, `backend/app/services/agent_runner.py` (default `notify`)
- Test: `backend/tests/test_approval_notifier.py`, `backend/tests/test_approval_replies.py`

**Interfaces:**
- `ApprovalNotifier.notify(session, approval, *, tool=call_mcp_tool) -> None`; `render_message(template, *, agent, tool, server, args, code, expires_at, link) -> str`; `admin_chat_id(number) -> str` (`"+225 07..."` → `"2250700003331@c.us"`); `resolve_whatsapp_server(session, config) -> McpServer | None`; `resolve_session_id(config, server, tool) -> str | None`.
- `ApprovalReplies.poll(session, *, tool=call_mcp_tool) -> int` (decisions applied); `parse_reply(text) -> tuple[bool, str] | None`; `extract_messages(raw: str) -> list[dict]` normalising `{body, from_me, timestamp}`.
- Scheduler: `_execute_approval_expiry()`, `_execute_approval_replies()`, `SchedulerService.set_approval_jobs()`; `main.py` calls it in lifespan.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_approval_notifier.py`:

```python
import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from app.models import Agent, AgentTask, Approval, Config, McpServer
from app.services.agent_task_service import AgentTaskService
from app.services.approval_notifier import ApprovalNotifier, admin_chat_id, render_message
from app.services.approval_service import ApprovalService


def test_admin_chat_id_strips_formatting():
    assert admin_chat_id("+225 07 00 00 33 31") == "2250700003331@c.us"
    assert admin_chat_id("2250700003331") == "2250700003331@c.us"


def test_render_message_fills_every_variable_and_truncates_args():
    text = render_message("A {agent} {tool} {server} {args} {code} {expires} {link}", agent="Bot", tool="write_x", server="srv",
                          args={"big": "x" * 1000}, code="ABC234", expires_at=datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc), link="https://t/x")
    assert "Bot write_x srv" in text and "ABC234" in text and "10:30 UTC" in text and "https://t/x" in text
    assert len(text) < 800 and text.count("x") <= 600


async def _pending(session, *, enabled=True, server_id=None, session_id=None, whatsapp_name="Whatsapp (OpenWa)"):
    wa = McpServer(name=whatsapp_name, transport="http", url="http://wa", enabled=True)
    srv = McpServer(name="srv", transport="http", url="http://x", enabled=True)
    session.add_all([wa, srv])
    await session.commit()
    session.add(Config(llm_provider="openai", llm_model="m", api_key="", approval_whatsapp_enabled=enabled,
                       approval_whatsapp_server_id=server_id, approval_whatsapp_session_id=session_id))
    agent = Agent(name="Bot", objective="o", status="active", mcp_servers=[srv])
    session.add(agent)
    await session.commit()
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    task = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {"v": 1}}]})
    approval = await ApprovalService.request(session, task, step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={"v": 1}, risk_level=2)
    return wa, approval


async def test_notify_sends_to_the_admin_with_the_code(session):
    wa, approval = await _pending(session)
    calls = []

    async def tool(name, args, server):
        calls.append((name, args, server.name))
        if name == "SessionFindAll":
            return json.dumps([{"id": "s-dead", "status": "disconnected"}, {"id": "s-ok", "status": "ready"}])
        return json.dumps({"id": "msg1"})
    await ApprovalNotifier.notify(session, approval, tool=tool)
    await session.refresh(approval)
    assert approval.notified_at is not None and approval.notify_error is None
    name, args, server = calls[-1]
    assert name == "MessageSendText" and server == "Whatsapp (OpenWa)"
    assert args["sessionId"] == "s-ok" and args["chatId"] == "2250700003331@c.us"
    assert approval.code in args["text"] and "write_x" in args["text"] and f"/tasks/{approval.task_id}" in args["text"]


async def test_notify_uses_configured_session_and_server(session):
    wa, approval = await _pending(session, session_id="s-cfg")
    cfg = (await session.execute(__import__("sqlalchemy").select(Config))).scalar_one()
    cfg.approval_whatsapp_server_id = wa.id
    await session.commit()
    calls = []

    async def tool(name, args, server):
        calls.append(name)
        return "{}"
    await ApprovalNotifier.notify(session, approval, tool=tool)
    assert calls == ["MessageSendText"]  # no SessionFindAll round trip


async def test_notify_records_errors_and_never_raises(session):
    wa, approval = await _pending(session)

    async def tool(name, args, server):
        return json.dumps({"error": "boom"})
    await ApprovalNotifier.notify(session, approval, tool=tool)
    await session.refresh(approval)
    assert approval.notified_at is None and "boom" in approval.notify_error


async def test_notify_disabled_or_no_server(session):
    wa, approval = await _pending(session, enabled=False)
    sent = []

    async def tool(name, args, server):
        sent.append(name)
        return "{}"
    await ApprovalNotifier.notify(session, approval, tool=tool)
    assert sent == []
    await session.refresh(approval)
    assert approval.notified_at is None and approval.notify_error == "notifications disabled"
```

Create `backend/tests/test_approval_replies.py`:

```python
import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from app.models import Agent, AgentTask, Approval, Config, McpServer
from app.services.agent_task_service import AgentTaskService
from app.services.approval_replies import ApprovalReplies, extract_messages, parse_reply
from app.services.approval_service import ApprovalService


def test_parse_reply_accepts_both_languages_and_case():
    assert parse_reply("OUI ABC234") == (True, "ABC234")
    assert parse_reply("  non abc234 merci") == (False, "ABC234")
    assert parse_reply("YES ABC234") == (True, "ABC234")
    assert parse_reply("No ABC234") == (False, "ABC234")
    assert parse_reply("ok ABC234") is None and parse_reply("OUI") is None and parse_reply("OUI ABC23") is None


def test_extract_messages_tolerates_shapes():
    raw = json.dumps({"items": [{"body": "OUI ABC234", "fromMe": False, "timestamp": 1_800_000_000},
                                {"text": "x", "fromMe": True, "timestamp": 1_800_000_000_000},
                                {"message": "y", "from_me": False, "created_at": "2027-01-01T00:00:00Z"}]})
    msgs = extract_messages(raw)
    assert [m["body"] for m in msgs] == ["OUI ABC234", "x", "y"]
    assert [m["from_me"] for m in msgs] == [False, True, False]
    assert all(isinstance(m["timestamp"], datetime) for m in msgs)
    assert extract_messages(json.dumps([{"body": "z"}]))[0]["timestamp"] is None


async def _pending(session):
    wa = McpServer(name="Whatsapp (OpenWa)", transport="http", url="http://wa", enabled=True)
    srv = McpServer(name="srv", transport="http", url="http://x", enabled=True)
    session.add_all([wa, srv])
    await session.commit()
    session.add(Config(llm_provider="openai", llm_model="m", api_key="", approval_whatsapp_enabled=True, approval_whatsapp_session_id="s1"))
    agent = Agent(name="Bot", objective="o", status="active", mcp_servers=[srv])
    session.add(agent)
    await session.commit()
    await AgentTaskService.enqueue(session, agent, objective=None, trigger="manual")
    task = await AgentTaskService.claim(session, "w")
    await AgentTaskService.record_step(session, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {}}]})
    return await ApprovalService.request(session, task, step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={}, risk_level=2)


def tool_returning(messages):
    seen = []

    async def tool(name, args, server):
        seen.append((name, args))
        return json.dumps(messages)
    tool.seen = seen
    return tool


def ts(dt):
    return int(dt.timestamp())


async def test_yes_reply_approves_once(session):
    approval = await _pending(session)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    tool = tool_returning([{"body": f"oui {approval.code}", "fromMe": False, "timestamp": ts(later)}])
    assert await ApprovalReplies.poll(session, tool=tool) == 1
    await session.refresh(approval)
    assert approval.status == "approved" and approval.decided_by == "whatsapp:2250700003331" and approval.decision_reason == f"oui {approval.code}"
    assert tool.seen[0][0] == "MessageList" and tool.seen[0][1]["chatId"] == "2250700003331@c.us"
    assert await ApprovalReplies.poll(session, tool=tool) == 0          # same messages again: nothing pending any more


async def test_no_reply_rejects(session):
    approval = await _pending(session)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert await ApprovalReplies.poll(session, tool=tool_returning([{"body": f"NON {approval.code}", "fromMe": False, "timestamp": ts(later)}])) == 1
    await session.refresh(approval)
    assert approval.status == "rejected"


async def test_ignores_old_fromme_and_unknown_codes(session):
    approval = await _pending(session)
    earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    tool = tool_returning([
        {"body": f"OUI {approval.code}", "fromMe": False, "timestamp": ts(earlier)},   # before the request
        {"body": f"OUI {approval.code}", "fromMe": True, "timestamp": ts(later)},      # our own message
        {"body": "OUI ZZZZZ9", "fromMe": False, "timestamp": ts(later)},               # unknown code
    ])
    assert await ApprovalReplies.poll(session, tool=tool) == 0
    await session.refresh(approval)
    assert approval.status == "pending"


async def test_poll_skips_when_nothing_pending_or_disabled(session):
    approval = await _pending(session)
    await ApprovalService.decide(session, approval, approve=True, decided_by="ui", reason=None)
    tool = tool_returning([])
    assert await ApprovalReplies.poll(session, tool=tool) == 0 and tool.seen == []
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_approval_notifier.py tests/test_approval_replies.py -q -p no:cacheprovider`
Expected: FAIL at import.

- [ ] **Step 3: Notifier**

Create `backend/app/services/approval_notifier.py`:

```python
"""Tell the administrator on WhatsApp that an approval is waiting.

Best effort by design: failures are recorded on the approval and logged, and
nothing in the task's fate depends on the message having left."""
import json
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, Approval, Config, McpServer
from app.services.approval_service import ApprovalService
from app.services.llm_runtime import call_mcp_tool

log = structlog.get_logger()

ARGS_MAX_CHARS = 600


def admin_chat_id(number: str) -> str:
    return re.sub(r"\D", "", number or "") + "@c.us"


def render_message(template: str, *, agent: str, tool: str, server: str, args: dict, code: str, expires_at, link: str) -> str:
    pretty = json.dumps(args, ensure_ascii=False, indent=None, default=str)
    if len(pretty) > ARGS_MAX_CHARS:
        pretty = pretty[:ARGS_MAX_CHARS] + "…"
    return template.format(agent=agent, tool=tool, server=server, args=pretty, code=code,
                           expires=expires_at.strftime("%H:%M UTC"), link=link)


async def resolve_whatsapp_server(session: AsyncSession, config: Config) -> McpServer | None:
    if config.approval_whatsapp_server_id:
        server = await session.get(McpServer, config.approval_whatsapp_server_id)
        return server if server and server.enabled else None
    rows = (await session.execute(select(McpServer).where(McpServer.enabled == True))).scalars().all()
    return next((s for s in rows if "whatsapp" in s.name.lower()), None)


async def resolve_session_id(config: Config, server: McpServer, tool) -> str | None:
    if config.approval_whatsapp_session_id:
        return config.approval_whatsapp_session_id
    raw = await tool("SessionFindAll", {"limit": 50}, server)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    items = data.get("items") if isinstance(data, dict) else data
    for item in items or []:
        if isinstance(item, dict) and str(item.get("status", "")).lower() == "ready" and item.get("id"):
            return str(item["id"])
    return None


class ApprovalNotifier:

    @staticmethod
    async def notify(session: AsyncSession, approval: Approval, *, tool=call_mcp_tool) -> None:
        try:
            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            if not config or not config.approval_whatsapp_enabled:
                await ApprovalService.set_notified(session, approval, error="notifications disabled")
                return
            server = await resolve_whatsapp_server(session, config)
            if server is None:
                await ApprovalService.set_notified(session, approval, error="no WhatsApp MCP server")
                return
            session_id = await resolve_session_id(config, server, tool)
            if not session_id:
                await ApprovalService.set_notified(session, approval, error="no ready WhatsApp session")
                return
            agent = await session.get(Agent, approval.agent_id)
            link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/agents/{approval.agent_id}/tasks/{approval.task_id}"
            text = render_message(config.approval_whatsapp_template, agent=agent.name if agent else "agent",
                                  tool=approval.tool_name, server=approval.server_name, args=approval.args,
                                  code=approval.code, expires_at=approval.expires_at, link=link)
            raw = await tool("MessageSendText", {"sessionId": session_id, "chatId": admin_chat_id(config.approval_whatsapp_number), "text": text}, server)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict) and set(data.keys()) == {"error"}:
                await ApprovalService.set_notified(session, approval, error=str(data["error"]))
                return
            await ApprovalService.set_notified(session, approval, error=None)
            log.info("approval_notified", approval_id=str(approval.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("approval_notify_failed", approval_id=str(approval.id), error=str(exc))
            try:
                await ApprovalService.set_notified(session, approval, error=str(exc))
            except Exception:
                log.exception("approval_notify_record_failed", approval_id=str(approval.id))
```

In `agent_runner.py` set the default: `from app.services.approval_notifier import ApprovalNotifier` and `notify=ApprovalNotifier.notify` in `run_task`'s signature (keep `None` meaning skip for tests that pass it explicitly).

- [ ] **Step 4: Reply poller**

Create `backend/app/services/approval_replies.py`:

```python
"""Read the administrator's WhatsApp chat and apply `OUI <code>` / `NON <code>` replies."""
import json
import re
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approval, Config
from app.services.approval_notifier import admin_chat_id, resolve_session_id, resolve_whatsapp_server
from app.services.approval_service import ApprovalConflict, ApprovalService
from app.services.llm_runtime import call_mcp_tool

log = structlog.get_logger()

REPLY = re.compile(r"^\s*(OUI|YES|NON|NO)\s+([A-Z0-9]{6})\b", re.IGNORECASE)
PAGE = 20


def parse_reply(text: str) -> tuple[bool, str] | None:
    m = REPLY.match(text or "")
    if not m:
        return None
    return m.group(1).upper() in ("OUI", "YES"), m.group(2).upper()


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def extract_messages(raw: str) -> list[dict]:
    """Normalise the WhatsApp server's message list into {body, from_me, timestamp}."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    out = []
    for m in items or []:
        if not isinstance(m, dict):
            continue
        body = next((m[k] for k in ("body", "text", "content", "message") if isinstance(m.get(k), str)), "")
        from_me = bool(m.get("fromMe", m.get("from_me", False)))
        timestamp = _to_datetime(next((m[k] for k in ("timestamp", "t", "created_at", "createdAt") if k in m), None))
        out.append({"body": body, "from_me": from_me, "timestamp": timestamp})
    return out


class ApprovalReplies:

    @staticmethod
    async def poll(session: AsyncSession, *, tool=call_mcp_tool) -> int:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.approval_whatsapp_enabled:
            return 0
        pending = await ApprovalService.list_pending(session)
        if not pending:
            return 0
        server = await resolve_whatsapp_server(session, config)
        if server is None:
            return 0
        session_id = await resolve_session_id(config, server, tool)
        if not session_id:
            return 0
        chat_id = admin_chat_id(config.approval_whatsapp_number)
        decided_by = "whatsapp:" + re.sub(r"\D", "", config.approval_whatsapp_number)
        raw = await tool("MessageList", {"sessionId": session_id, "chatId": chat_id, "limit": PAGE}, server)
        oldest = min(a.requested_at for a in pending)
        by_code = {a.code: a for a in pending}
        decided = 0
        for msg in extract_messages(raw):
            if msg["from_me"] or (msg["timestamp"] is not None and msg["timestamp"] < oldest):
                continue
            parsed = parse_reply(msg["body"])
            if not parsed:
                continue
            approve, code = parsed
            approval = by_code.get(code)
            if approval is None:
                continue
            try:
                await ApprovalService.decide(session, approval, approve=approve, decided_by=decided_by,
                                             reason=msg["body"].strip())
                decided += 1
                by_code.pop(code, None)
            except ApprovalConflict:
                continue
        return decided
```

- [ ] **Step 5: Scheduler jobs and lifespan**

In `scheduler_service.py` add job functions next to `_execute_agent_cron`:

```python
async def _execute_approval_expiry():
    from app.database import async_session
    from app.services.approval_service import ApprovalService
    try:
        async with async_session() as session:
            expired = await ApprovalService.expire_due(session)
        if expired:
            log.info("approvals_expired", count=expired)
    except Exception as exc:
        log.error("Approval expiry failed", error=str(exc))


async def _execute_approval_replies():
    from app.database import async_session
    from app.services.approval_replies import ApprovalReplies
    try:
        async with async_session() as session:
            decided = await ApprovalReplies.poll(session)
        if decided:
            log.info("approvals_decided_by_whatsapp", count=decided)
    except Exception as exc:
        log.error("Approval reply poll failed", error=str(exc))
```

and in `SchedulerService`:

```python
    APPROVAL_EXPIRY_JOB_ID = "approval_expiry"
    APPROVAL_REPLIES_JOB_ID = "approval_replies"

    def set_approval_jobs(self):
        # One-minute cadence, offset so the two never fire on the same tick.
        for job_id, fn, offset in ((self.APPROVAL_EXPIRY_JOB_ID, _execute_approval_expiry, 20),
                                   (self.APPROVAL_REPLIES_JOB_ID, _execute_approval_replies, 40)):
            self.scheduler.add_job(fn, trigger=IntervalTrigger(minutes=1, start_date=datetime.now(timezone.utc) + timedelta(seconds=offset)),
                                   id=job_id, replace_existing=True)
```

`main.py` lifespan: `scheduler_service.set_approval_jobs()` after `set_pair_call_job()`.

- [ ] **Step 6: Run and commit**

Run: `venv/bin/python -m pytest tests/test_approval_notifier.py tests/test_approval_replies.py tests/test_agent_runner_approvals.py tests/test_scheduler_service.py -q -p no:cacheprovider` → all passed.

```bash
git add backend/app/services/approval_notifier.py backend/app/services/approval_replies.py backend/app/services/scheduler_service.py backend/app/main.py backend/app/services/agent_runner.py backend/tests/test_approval_notifier.py backend/tests/test_approval_replies.py
git commit -m "feat(agents): notify approvals on WhatsApp and accept OUI/NON replies

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Approvals API and task detail

**Files:**
- Create: `backend/app/schemas/approval.py`; modify `backend/app/schemas/__init__.py`, `backend/app/schemas/agent_task.py`
- Create: `backend/app/routers/approvals.py`; modify `backend/app/routers/agent_tasks.py`, `backend/app/main.py`
- Test: `backend/tests/test_api_approvals.py`; append to `backend/tests/test_api_agent_tasks.py`

**Interfaces:**
- `ApprovalRead`: `id, task_id, agent_id, agent_name, task_objective, step_seq, call_index, tool_name, server_name, args, risk_level, code, status, requested_at, expires_at, seconds_left, decided_at, decided_by, decision_reason, notified_at, notify_error, consumed_at`; `ApprovalDecision {reason: str | None}`.
- `GET /api/v1/approvals?status=pending|approved|rejected|expired` (default pending, newest first), `POST /api/v1/approvals/{id}/approve`, `POST /api/v1/approvals/{id}/reject` → 200 `ApprovalRead`, 404, 409.
- `AgentTaskRead.approval: ApprovalRead | None` (the pending one); `AgentTaskStatus`/`StepKind` literals extended.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_approvals.py` (reuse the fixture/`client()` shape of `test_api_agent_tasks.py`):

```python
import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Agent, AgentTask, Base, Config, McpServer
from app.services.agent_task_service import AgentTaskService
from app.services.approval_service import ApprovalService

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_async_session] = override
    yield factory
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def pending_approval(factory):
    async with factory() as s:
        s.add(Config(llm_provider="openai", llm_model="m", api_key=""))
        agent = Agent(name="Bot", objective="Inspect", status="active",
                      mcp_servers=[McpServer(name="srv", transport="http", url="http://x", enabled=True)])
        s.add(agent)
        await s.commit()
        await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        task = await AgentTaskService.claim(s, "w")
        await AgentTaskService.record_step(s, task, "turn", {"text": None, "tool_calls": [{"name": "write_x", "args": {"v": 1}}]})
        approval = await ApprovalService.request(s, task, step_seq=1, call_index=0, tool_name="write_x", server_name="srv", args={"v": 1}, risk_level=2)
        return str(approval.id), str(task.id)


async def test_list_pending_and_approve(setup_test_db):
    aid, tid = await pending_approval(setup_test_db)
    async with client() as c:
        items = (await c.get("/api/v1/approvals")).json()
        assert [i["id"] for i in items] == [aid]
        assert items[0]["agent_name"] == "Bot" and items[0]["task_objective"] == "Inspect" and items[0]["seconds_left"] > 0
        assert items[0]["args"] == {"v": 1} and len(items[0]["code"]) == 6
        task = (await c.get(f"/api/v1/agent-tasks/{tid}")).json()
        assert task["status"] == "waiting_approval" and task["approval"]["id"] == aid
        resp = await c.post(f"/api/v1/approvals/{aid}/approve", json={"reason": "fine"})
        assert resp.status_code == 200 and resp.json()["status"] == "approved" and resp.json()["decided_by"] == "ui"
        assert (await c.get("/api/v1/approvals")).json() == []
        assert [i["id"] for i in (await c.get("/api/v1/approvals?status=approved")).json()] == [aid]
        task = (await c.get(f"/api/v1/agent-tasks/{tid}")).json()
        assert task["status"] == "queued" and task["approval"] is None
        assert (await c.post(f"/api/v1/approvals/{aid}/reject", json={})).status_code == 409


async def test_reject_and_404s(setup_test_db):
    aid, tid = await pending_approval(setup_test_db)
    async with client() as c:
        resp = await c.post(f"/api/v1/approvals/{aid}/reject", json={"reason": "no"})
        assert resp.status_code == 200 and resp.json()["status"] == "rejected" and resp.json()["decision_reason"] == "no"
        assert (await c.post(f"/api/v1/approvals/{uuid.uuid4()}/approve", json={})).status_code == 404
        assert (await c.get("/api/v1/approvals?status=bogus")).status_code == 422
```

Append to `backend/tests/test_api_agent_tasks.py`:

```python
async def test_cancel_waiting_task_closes_its_approval(setup_test_db):
    from app.models import Config
    from app.services.approval_service import ApprovalService
    aid = await make_agent(setup_test_db)
    async with setup_test_db() as s:
        s.add(Config(llm_provider="openai", llm_model="m", api_key=""))
        await s.commit()
        agent = await s.get(Agent, uuid.UUID(aid))
        await AgentTaskService.enqueue(s, agent, objective=None, trigger="manual")
        task = await AgentTaskService.claim(s, "w")
        await AgentTaskService.record_step(s, task, "turn", {"text": None, "tool_calls": [{"name": "t", "args": {}}]})
        approval = await ApprovalService.request(s, task, step_seq=1, call_index=0, tool_name="t", server_name="s", args={}, risk_level=2)
    async with client() as c:
        resp = await c.post(f"/api/v1/agent-tasks/{task.id}/cancel")
        assert resp.status_code == 202 and resp.json()["status"] == "cancelled"
        assert (await c.get(f"/api/v1/approvals?status=expired")).json()[0]["id"] == str(approval.id)
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_api_approvals.py tests/test_api_agent_tasks.py -q -p no:cacheprovider -k "approv"`
Expected: FAIL with 404 on `/api/v1/approvals` and a missing `approval` key.

- [ ] **Step 3: Schemas**

Create `backend/app/schemas/approval.py`:

```python
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class ApprovalRead(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None = None
    task_objective: str | None = None
    step_seq: int
    call_index: int
    tool_name: str
    server_name: str
    args: dict[str, Any]
    risk_level: int
    code: str
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime
    seconds_left: int
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    notified_at: datetime | None
    notify_error: str | None
    consumed_at: datetime | None


    @classmethod
    def from_model(cls, approval, *, agent_name: str | None = None, task_objective: str | None = None) -> "ApprovalRead":
        left = int((approval.expires_at - datetime.now(timezone.utc)).total_seconds())
        return cls(
            id=approval.id, task_id=approval.task_id, agent_id=approval.agent_id, agent_name=agent_name, task_objective=task_objective,
            step_seq=approval.step_seq, call_index=approval.call_index, tool_name=approval.tool_name, server_name=approval.server_name,
            args=approval.args, risk_level=approval.risk_level, code=approval.code, status=approval.status,
            requested_at=approval.requested_at, expires_at=approval.expires_at, seconds_left=max(0, left),
            decided_at=approval.decided_at, decided_by=approval.decided_by, decision_reason=approval.decision_reason,
            notified_at=approval.notified_at, notify_error=approval.notify_error, consumed_at=approval.consumed_at,
        )


class ApprovalDecision(BaseModel):
    reason: str | None = None
```
(`from datetime import datetime, timezone`.)

In `schemas/agent_task.py`: `AgentTaskStatus = Literal["queued", "running", "waiting_approval", "completed", "failed", "cancelled"]`, `StepKind` gains `"approval_requested"`, and `AgentTaskRead` gains `approval: ApprovalRead | None = None` (import from `app.schemas.approval`). Export `ApprovalRead`, `ApprovalDecision` from `schemas/__init__.py`.

- [ ] **Step 4: Router and task detail**

Create `backend/app/routers/approvals.py`:

```python
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Agent, AgentTask, Approval
from app.schemas import ApprovalDecision, ApprovalRead
from app.services.approval_service import ApprovalConflict, ApprovalService

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


async def _enrich(session: AsyncSession, approvals: list[Approval]) -> list[ApprovalRead]:
    if not approvals:
        return []
    agents = {a.id: a.name for a in (await session.execute(select(Agent).where(Agent.id.in_({x.agent_id for x in approvals})))).scalars().all()}
    tasks = {t.id: t.objective for t in (await session.execute(select(AgentTask).where(AgentTask.id.in_({x.task_id for x in approvals})))).scalars().all()}
    return [ApprovalRead.from_model(a, agent_name=agents.get(a.agent_id), task_objective=tasks.get(a.task_id)) for a in approvals]


@router.get("", response_model=list[ApprovalRead])
async def list_approvals(status: Literal["pending", "approved", "rejected", "expired"] = Query(default="pending"),
                         session: AsyncSession = Depends(get_async_session)):
    rows = (await session.execute(select(Approval).where(Approval.status == status).order_by(Approval.requested_at.desc()).limit(200))).scalars().all()
    return await _enrich(session, list(rows))


async def _decide(approval_id: uuid.UUID, approve: bool, data: ApprovalDecision, session: AsyncSession) -> ApprovalRead:
    approval = await session.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    try:
        approval = await ApprovalService.decide(session, approval, approve=approve, decided_by="ui", reason=data.reason)
    except ApprovalConflict as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return (await _enrich(session, [approval]))[0]


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
async def approve(approval_id: uuid.UUID, data: ApprovalDecision, session: AsyncSession = Depends(get_async_session)):
    return await _decide(approval_id, True, data, session)


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
async def reject(approval_id: uuid.UUID, data: ApprovalDecision, session: AsyncSession = Depends(get_async_session)):
    return await _decide(approval_id, False, data, session)
```

`main.py`: import and include `approvals_router.router`.

In `routers/agent_tasks.py`, `get_task` becomes (import `Approval` from `app.models` and `ApprovalRead` from `app.schemas`):

```python
@router.get("/{task_id}", response_model=AgentTaskDetail)
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    task = await _get_task(session, task_id, with_steps=True)
    pending = (await session.execute(
        select(Approval).where(Approval.task_id == task.id, Approval.status == "pending")
        .order_by(Approval.requested_at.desc()).limit(1)
    )).scalar_one_or_none()
    detail = AgentTaskDetail.model_validate(task)
    detail.approval = ApprovalRead.from_model(pending) if pending else None
    return detail
```

The SSE stream needs no change: `waiting_approval` is not final, so the stream stays open across the park and the resume, and the status frame already carries the new status.

- [ ] **Step 5: Run and commit**

Run: `venv/bin/python -m pytest tests/test_api_approvals.py tests/test_api_agent_tasks.py tests/test_api_agents.py -q -p no:cacheprovider` → all passed.

```bash
git add backend/app/schemas/approval.py backend/app/schemas/__init__.py backend/app/schemas/agent_task.py backend/app/routers/approvals.py backend/app/routers/agent_tasks.py backend/app/main.py backend/tests/test_api_approvals.py backend/tests/test_api_agent_tasks.py
git commit -m "feat(agents): expose approvals over the API and on the task detail

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Docs, full verification, autogenerate check

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Full suite** — `venv/bin/python -m pytest tests/ -q -p no:cacheprovider` from `backend/`; everything green (≥ 425 + the new files). Report any failure rather than fixing unrelated tests.
- [ ] **Step 2: Autogenerate** — `PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "check approvals"`; `grep -il "approval\|tool_policy\|max_auto_risk\|waiting_approval" alembic/versions/*check_approvals*.py || echo "no approvals diff"`; delete the file; `git status` clean.
- [ ] **Step 3: Docs** — In `CLAUDE.md`'s Agents paragraph replace the sentence "**There is no approval step yet: every authorised tool runs immediately.**" with:

```markdown
Tool calls are gated: every tool on a server has a `ToolPolicy` risk level (0–3, default 2, edited in Settings per server; `tool_policy_service.py` syncs rows on discovery and never changes a level), and an agent runs a tool without asking only when the level is ≤ its `max_auto_risk` (0–2, default 1; level 3 is never automatic). Anything above parks the task in `waiting_approval` with an `Approval` row bound to the exact arguments (`approval_service.py`), frees the worker slot, notifies the admin on the WhatsApp MCP server (`approval_notifier.py`, French template in `Config`, off until `approval_whatsapp_enabled`), and resumes from the journal after a decision taken in the UI or by a WhatsApp reply `OUI|NON <code>` (`approval_replies.py`, one-minute job). Undecided approvals expire after `approval_expiry_hours` and fail the task. The resume rebuilds the message history from the last `turn` step's stored prompt — this is why prompts are kept.
```

In the paragraph starting "Three extra jobs are not cron-driven", append this sentence at the end:

```markdown
Two more fixed jobs, `approval_expiry` and `approval_replies` (`set_approval_jobs()`), run every minute, offset by 20 s and 40 s; both are no-ops when nothing is pending, and the reply poller also returns early unless `approval_whatsapp_enabled`.
```

and change its first words to "Five extra jobs".

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agents): describe tool risk levels, approvals and WhatsApp decisions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
