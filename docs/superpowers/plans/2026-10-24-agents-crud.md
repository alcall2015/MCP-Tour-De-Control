# Agents (creation and lifecycle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Agents" tab where a user creates autonomous-agent definitions (name, objective, instructions, allowed MCP servers, limits) and drives their `draft / active / paused / archived` lifecycle. Nothing executes yet.

**Architecture:** One new SQLAlchemy model `Agent` plus an association table to the existing `McpServer` rows, one thin FastAPI router with the status-transition rules inline, and a React list page with a modal form. Everything follows the existing Prompts / McpServer patterns; the only new frontend primitive is `components/ui/Modal.tsx`.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, Pydantic v2, pytest-asyncio (live Postgres), React 18 + TanStack Query + react-router, Tailwind utility classes over the existing `index.css` tokens.

Spec: `docs/superpowers/specs/2026-10-24-agents-crud-design.md`.

## Global Constraints

- Router prefix is exactly `/api/v1/agents`; business rules live in the router, no `agent_service.py` in this sub-project.
- Status values are exactly `draft`, `active`, `paused`, `archived`; creation always yields `draft`.
- `max_steps` default 20, bounds 1..100. `timeout_seconds` default 300, bounds 10..3600. Enforced by Pydantic **and** DB CHECK constraints.
- Tool granularity is per MCP server through table `agent_mcp_server` with `ON DELETE CASCADE` both sides.
- No per-agent model/API key, no versioning, no execution, no scheduler job.
- Every new model is exported from `app/models/__init__.py`; every new schema from `app/schemas/__init__.py`.
- All frontend HTTP calls and shared interfaces go in `frontend/src/lib/api.ts`.
- Code, comments, UI copy in English. No emojis in navigation.
- Conventional Commits, e.g. `feat(agents): ...`. End commit messages with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Backend commands run from `backend/` with `venv/bin/python`; tests need the live test Postgres (`mcp_control_test`).
- The new Alembic revision must chain on the current head. Check with `PYTHONPATH=. venv/bin/alembic heads` before writing it; at planning time the head is `0b1c2d3e4f5a` (uncommitted in the working tree). Never apply autogenerate's spurious drops (see CLAUDE.md).

## File Structure

| Path | Responsibility |
|---|---|
| `backend/app/models/agent.py` | `Agent` model, `agent_mcp_server` association table, CHECK constraints |
| `backend/app/models/__init__.py` | export `Agent` |
| `backend/alembic/versions/1c2d3e4f5a6b_add_agents.py` | create both tables |
| `backend/app/schemas/agent.py` | `AgentServerRef`, `AgentCreate`, `AgentUpdate`, `AgentStatusUpdate`, `AgentRead` |
| `backend/app/schemas/__init__.py` | export the five schemas |
| `backend/app/routers/agents.py` | CRUD + `PUT /{id}/status` with the transition table |
| `backend/app/main.py` | include the router |
| `backend/tests/test_agent_model.py` | model-level tests (defaults, CHECK constraints, cascade) |
| `backend/tests/test_api_agents.py` | HTTP tests for every endpoint and rule |
| `frontend/src/lib/api.ts` | `Agent*` types and the five API functions |
| `frontend/src/components/ui/Modal.tsx` | reusable accessible modal |
| `frontend/src/index.css` | `.modal-overlay` / `.modal-panel` rules |
| `frontend/src/components/Agents/AgentFormModal.tsx` | create / edit form inside the modal |
| `frontend/src/components/Agents/AgentCard.tsx` | one agent, badge, chips, status-dependent actions |
| `frontend/src/components/Agents/AgentList.tsx` | query + mutations + empty state |
| `frontend/src/pages/AgentsPage.tsx` | header, Active/Archived filter, modal state |
| `frontend/src/App.tsx` | `/agents` route |
| `frontend/src/components/Layout/TabNav.tsx` | "Agents" tab, icon, "Active agents" status line |

---

### Task 1: `Agent` model, association table and migration

**Files:**
- Create: `backend/app/models/agent.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/1c2d3e4f5a6b_add_agents.py`
- Test: `backend/tests/test_agent_model.py`

**Interfaces:**
- Produces: `class Agent(Base)` with columns `id, name, objective, instructions, description, status, max_steps, timeout_seconds, created_at, updated_at` and relationship `mcp_servers: list[McpServer]` (`lazy="selectin"`, so every load of an `Agent`, including `session.get`, already carries its servers). Table name `agent`. Association table `agent_mcp_server`.

- [ ] **Step 1: Write the failing model tests**

Create `backend/tests/test_agent_model.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Agent, McpServer


async def _server(session, name="tm", enabled=True) -> McpServer:
    server = McpServer(name=name, transport="http", url="http://example.test/mcp", enabled=enabled)
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


async def test_agent_defaults(session):
    agent = Agent(name="a", objective="o")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    assert agent.status == "draft"
    assert agent.instructions == ""
    assert agent.description is None
    assert agent.max_steps == 20
    assert agent.timeout_seconds == 300
    assert agent.created_at is not None
    assert agent.mcp_servers == []


async def test_agent_links_servers(session):
    s1 = await _server(session, "one")
    s2 = await _server(session, "two")
    agent = Agent(name="a", objective="o", mcp_servers=[s1, s2])
    session.add(agent)
    await session.commit()
    session.expunge_all()

    loaded = (await session.execute(select(Agent))).scalar_one()
    assert sorted(s.name for s in loaded.mcp_servers) == ["one", "two"]


async def test_deleting_server_unlinks_it(session):
    s1 = await _server(session, "one")
    agent = Agent(name="a", objective="o", mcp_servers=[s1])
    session.add(agent)
    await session.commit()
    session.expunge_all()

    server = await session.get(McpServer, s1.id)
    await session.delete(server)
    await session.commit()
    session.expunge_all()

    loaded = (await session.execute(select(Agent))).scalar_one()
    assert loaded.mcp_servers == []


@pytest.mark.parametrize("field,value", [
    ("status", "running"),
    ("max_steps", 0),
    ("max_steps", 101),
    ("timeout_seconds", 9),
    ("timeout_seconds", 3601),
])
async def test_check_constraints(session, field, value):
    agent = Agent(name="a", objective="o")
    setattr(agent, field, value)
    session.add(agent)
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `venv/bin/python -m pytest tests/test_agent_model.py -v`
Expected: FAIL at import with `ImportError: cannot import name 'Agent' from 'app.models'`.

- [ ] **Step 3: Write the model**

Create `backend/app/models/agent.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base
from app.models.mcp_server import McpServer

AGENT_STATUSES = ("draft", "active", "paused", "archived")

agent_mcp_server = Table(
    "agent_mcp_server",
    Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"), primary_key=True),
    Column("mcp_server_id", UUID(as_uuid=True), ForeignKey("mcp_server.id", ondelete="CASCADE"), primary_key=True),
)


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    max_steps: Mapped[int] = mapped_column(Integer, default=20)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Authorised MCP servers. Rows in agent_mcp_server vanish with either side (DB cascade).
    mcp_servers: Mapped[list[McpServer]] = relationship(McpServer, secondary=agent_mcp_server, lazy="selectin")

    __table_args__ = (
        CheckConstraint("status IN ('draft','active','paused','archived')", name="ck_agent_status"),
        CheckConstraint("max_steps BETWEEN 1 AND 100", name="ck_agent_max_steps"),
        CheckConstraint("timeout_seconds BETWEEN 10 AND 3600", name="ck_agent_timeout_seconds"),
    )
```

In `backend/app/models/__init__.py` add after the `SmsReply` import:

```python
from app.models.agent import Agent
```

and append `"Agent"` to `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_agent_model.py -v`
Expected: 8 passed (3 behaviour tests + 5 parametrized constraint cases).

- [ ] **Step 5: Write the migration by hand**

First confirm the head: `PYTHONPATH=. venv/bin/alembic heads` → expect `0b1c2d3e4f5a (head)`. If it differs, use that value for `down_revision`.

Create `backend/alembic/versions/1c2d3e4f5a6b_add_agents.py`:

```python
"""add agents and agent_mcp_server

Revision ID: 1c2d3e4f5a6b
Revises: 0b1c2d3e4f5a
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "1c2d3e4f5a6b"
down_revision = "0b1c2d3e4f5a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','active','paused','archived')", name="ck_agent_status"),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 100", name="ck_agent_max_steps"),
        sa.CheckConstraint("timeout_seconds BETWEEN 10 AND 3600", name="ck_agent_timeout_seconds"),
    )
    op.create_table(
        "agent_mcp_server",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mcp_server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_server.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade():
    op.drop_table("agent_mcp_server")
    op.drop_table("agent")
```

- [ ] **Step 6: Apply the migration against the dev database and check it round-trips**

Run (from `backend/`, with `DATABASE_URL` pointing at the dev DB as in `.env`):

```bash
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic downgrade -1
PYTHONPATH=. venv/bin/alembic upgrade head
PYTHONPATH=. venv/bin/alembic heads
```

Expected: no errors, last line `1c2d3e4f5a6b (head)`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/agent.py backend/app/models/__init__.py backend/alembic/versions/1c2d3e4f5a6b_add_agents.py backend/tests/test_agent_model.py
git commit -m "feat(agents): add Agent model, server allowlist table and migration

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Schemas and router — list, create, get

**Files:**
- Create: `backend/app/schemas/agent.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `backend/app/routers/agents.py`
- Modify: `backend/app/main.py:15-19` (imports) and `:107-116` (include_router)
- Test: `backend/tests/test_api_agents.py`

**Interfaces:**
- Consumes: `Agent`, `McpServer` from Task 1.
- Produces: schemas `AgentServerRef`, `AgentCreate`, `AgentUpdate`, `AgentStatusUpdate`, `AgentRead`; router helpers `_to_read(agent) -> AgentRead`, `_load_servers(session, ids) -> list[McpServer]` (raises 404), `_get_agent(session, agent_id) -> Agent` (raises 404). Tasks 3 and 4 add endpoints to this same file and reuse these helpers.

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/test_api_agents.py`:

```python
import os
import uuid

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_async_session
from app.models import Base, McpServer

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_async_session
    yield async_session
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def create_server(async_session, name="tm", enabled=True) -> str:
    async with async_session() as session:
        server = McpServer(name=name, transport="http", url="http://example.test/mcp", enabled=enabled)
        session.add(server)
        await session.commit()
        return str(server.id)


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def create_agent(c: AsyncClient, **overrides) -> dict:
    payload = {"name": "Log analyst", "objective": "Find the root cause", "mcp_server_ids": []}
    payload.update(overrides)
    resp = await c.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---- list / create / get -------------------------------------------------

async def test_list_agents_empty():
    async with client() as c:
        resp = await c.get("/api/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_agent_defaults_to_draft(setup_test_db):
    sid = await create_server(setup_test_db, "TmLite")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[sid], instructions="Be terse")
    assert data["status"] == "draft"
    assert data["max_steps"] == 20
    assert data["timeout_seconds"] == 300
    assert data["instructions"] == "Be terse"
    assert data["description"] is None
    assert data["mcp_servers"] == [{"id": sid, "name": "TmLite", "enabled": True}]


async def test_create_agent_ignores_client_status():
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={
            "name": "x", "objective": "y", "mcp_server_ids": [], "status": "active",
        })
    assert resp.status_code == 201
    assert resp.json()["status"] == "draft"


async def test_create_agent_unknown_server_404():
    missing = str(uuid.uuid4())
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={"name": "x", "objective": "y", "mcp_server_ids": [missing]})
    assert resp.status_code == 404
    assert missing in resp.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"name": "", "objective": "y"},
    {"name": "x", "objective": ""},
    {"name": "x", "objective": "y", "max_steps": 0},
    {"name": "x", "objective": "y", "max_steps": 101},
    {"name": "x", "objective": "y", "timeout_seconds": 9},
    {"name": "x", "objective": "y", "timeout_seconds": 5000},
])
async def test_create_agent_validation_422(payload):
    async with client() as c:
        resp = await c.post("/api/v1/agents", json={**payload, "mcp_server_ids": []})
    assert resp.status_code == 422


async def test_get_agent_and_not_found():
    async with client() as c:
        data = await create_agent(c)
        resp = await c.get(f"/api/v1/agents/{data['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Log analyst"
        resp = await c.get(f"/api/v1/agents/{uuid.uuid4()}")
        assert resp.status_code == 404


async def test_list_orders_newest_first():
    async with client() as c:
        await create_agent(c, name="first")
        await create_agent(c, name="second")
        resp = await c.get("/api/v1/agents")
    assert [a["name"] for a in resp.json()] == ["second", "first"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_api_agents.py -v`
Expected: every test FAILS with `404` on `/api/v1/agents` (route does not exist yet), or `assert 404 == 201`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/agent.py`:

```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentStatus = Literal["draft", "active", "paused", "archived"]


class AgentServerRef(BaseModel):
    """Denormalised server summary so the agent list needs no second request."""
    id: uuid.UUID
    name: str
    enabled: bool


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    instructions: str = ""
    description: str | None = None
    max_steps: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    mcp_server_ids: list[uuid.UUID] = []


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, min_length=1)
    instructions: str | None = None
    description: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=100)
    timeout_seconds: int | None = Field(default=None, ge=10, le=3600)
    mcp_server_ids: list[uuid.UUID] | None = None  # replaces the whole set when present


class AgentStatusUpdate(BaseModel):
    status: AgentStatus


class AgentRead(BaseModel):
    id: uuid.UUID
    name: str
    objective: str
    instructions: str
    description: str | None
    status: AgentStatus
    max_steps: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime
    mcp_servers: list[AgentServerRef]

    model_config = {"from_attributes": True}
```

In `backend/app/schemas/__init__.py` add:

```python
from app.schemas.agent import AgentServerRef, AgentCreate, AgentUpdate, AgentStatusUpdate, AgentRead
```

and add to `__all__`:

```python
    "AgentServerRef", "AgentCreate", "AgentUpdate", "AgentStatusUpdate", "AgentRead",
```

- [ ] **Step 4: Write the router with list / create / get**

Create `backend/app/routers/agents.py`:

```python
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Agent, McpServer
from app.schemas import AgentCreate, AgentRead, AgentServerRef, AgentStatusUpdate, AgentUpdate
from app.schemas.agent import AgentStatus

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _to_read(agent: Agent) -> AgentRead:
    return AgentRead(
        id=agent.id,
        name=agent.name,
        objective=agent.objective,
        instructions=agent.instructions,
        description=agent.description,
        status=agent.status,
        max_steps=agent.max_steps,
        timeout_seconds=agent.timeout_seconds,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        mcp_servers=[AgentServerRef(id=s.id, name=s.name, enabled=s.enabled) for s in agent.mcp_servers],
    )


async def _load_servers(session: AsyncSession, ids: list[uuid.UUID]) -> list[McpServer]:
    servers = []
    for sid in ids:
        server = await session.get(McpServer, sid)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server {sid} not found")
        servers.append(server)
    return servers


async def _get_agent(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("", response_model=list[AgentRead])
async def list_agents(
    status: AgentStatus | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Agent).order_by(Agent.created_at.desc())
    if status is None:
        stmt = stmt.where(Agent.status != "archived")
    else:
        stmt = stmt.where(Agent.status == status)
    agents = (await session.execute(stmt)).scalars().all()
    return [_to_read(a) for a in agents]


@router.post("", response_model=AgentRead, status_code=201)
async def create_agent(data: AgentCreate, session: AsyncSession = Depends(get_async_session)):
    servers = await _load_servers(session, data.mcp_server_ids)
    agent = Agent(
        name=data.name,
        objective=data.objective,
        instructions=data.instructions,
        description=data.description,
        max_steps=data.max_steps,
        timeout_seconds=data.timeout_seconds,
        mcp_servers=servers,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    log.info("agent_created", agent_id=str(agent.id), name=agent.name)
    return _to_read(agent)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return _to_read(await _get_agent(session, agent_id))
```

`datetime`, `timezone`, `AgentUpdate` and `AgentStatusUpdate` are imported now because Tasks 3 and 4 use them; oxlint does not run on Python, and Ruff is not configured, so the unused imports do not fail anything in between.

In `backend/app/main.py` add the import next to the others (alphabetical, first):

```python
from app.routers import agents as agents_router
```

and the include before `config_router`:

```python
app.include_router(agents_router.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_api_agents.py -v`
Expected: 12 passed (7 tests, one of them 6 parametrized cases).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/agent.py backend/app/schemas/__init__.py backend/app/routers/agents.py backend/app/main.py backend/tests/test_api_agents.py
git commit -m "feat(agents): list, create and read agents over the API

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Router — update and delete

**Files:**
- Modify: `backend/app/routers/agents.py` (append)
- Test: `backend/tests/test_api_agents.py` (append)

**Interfaces:**
- Consumes: `_get_agent`, `_load_servers`, `_to_read` from Task 2.
- Produces: `PUT /api/v1/agents/{id}` and `DELETE /api/v1/agents/{id}`.

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/test_api_agents.py`. The status tests in this block pre-set the DB row directly because `PUT /status` does not exist until Task 4; the helper `set_status` is reused there.

```python
# ---- update / delete -----------------------------------------------------

async def set_status(async_session, agent_id: str, status: str) -> None:
    from app.models import Agent
    async with async_session() as session:
        agent = await session.get(Agent, uuid.UUID(agent_id))
        agent.status = status
        await session.commit()


async def test_update_fields_and_replace_servers(setup_test_db):
    s1 = await create_server(setup_test_db, "one")
    s2 = await create_server(setup_test_db, "two")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[s1])
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={
            "name": "Renamed", "max_steps": 5, "mcp_server_ids": [s2],
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["max_steps"] == 5
    assert body["objective"] == "Find the root cause"          # untouched
    assert [s["id"] for s in body["mcp_servers"]] == [s2]        # replaced, not merged
    assert body["updated_at"] > data["updated_at"]


async def test_update_without_server_ids_keeps_servers(setup_test_db):
    s1 = await create_server(setup_test_db, "one")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[s1])
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"description": "note"})
    assert resp.status_code == 200
    assert [s["id"] for s in resp.json()["mcp_servers"]] == [s1]
    assert resp.json()["description"] == "note"


async def test_update_unknown_server_404_and_not_found():
    async with client() as c:
        data = await create_agent(c)
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"mcp_server_ids": [str(uuid.uuid4())]})
        assert resp.status_code == 404
        resp = await c.put(f"/api/v1/agents/{uuid.uuid4()}", json={"name": "x"})
        assert resp.status_code == 404


async def test_update_archived_409(setup_test_db):
    async with client() as c:
        data = await create_agent(c)
        await set_status(setup_test_db, data["id"], "archived")
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"name": "x"})
    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"]


async def test_update_validation_422():
    async with client() as c:
        data = await create_agent(c)
        resp = await c.put(f"/api/v1/agents/{data['id']}", json={"timeout_seconds": 5000})
    assert resp.status_code == 422


@pytest.mark.parametrize("status", ["draft", "archived"])
async def test_delete_allowed_statuses(setup_test_db, status):
    async with client() as c:
        data = await create_agent(c)
        await set_status(setup_test_db, data["id"], status)
        resp = await c.delete(f"/api/v1/agents/{data['id']}")
        assert resp.status_code == 204
        resp = await c.get(f"/api/v1/agents/{data['id']}")
        assert resp.status_code == 404


@pytest.mark.parametrize("status", ["active", "paused"])
async def test_delete_blocked_statuses(setup_test_db, status):
    async with client() as c:
        data = await create_agent(c)
        await set_status(setup_test_db, data["id"], status)
        resp = await c.delete(f"/api/v1/agents/{data['id']}")
    assert resp.status_code == 409


async def test_delete_not_found():
    async with client() as c:
        resp = await c.delete(f"/api/v1/agents/{uuid.uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_api_agents.py -v -k "update or delete"`
Expected: FAIL with `405 Method Not Allowed` on PUT / DELETE.

- [ ] **Step 3: Append the endpoints**

Append to `backend/app/routers/agents.py`:

```python
@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(agent_id: uuid.UUID, data: AgentUpdate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    if agent.status == "archived":
        raise HTTPException(status_code=409, detail="Agent is archived; restore it before editing")

    for field in ("name", "objective", "instructions", "description", "max_steps", "timeout_seconds"):
        value = getattr(data, field)
        if value is not None:
            setattr(agent, field, value)
    if data.mcp_server_ids is not None:
        agent.mcp_servers = await _load_servers(session, data.mcp_server_ids)
    # Changing only the server set touches no column on `agent`, so onupdate would not fire.
    agent.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(agent)
    return _to_read(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    if agent.status not in ("draft", "archived"):
        raise HTTPException(status_code=409, detail=f"Cannot delete a {agent.status} agent; archive it first")
    await session.delete(agent)
    await session.commit()
    log.info("agent_deleted", agent_id=str(agent_id))
```

Note: `description` cannot be cleared back to `null` through `PUT` because `None` means "not provided" in `AgentUpdate`. The UI sends an empty string for an empty description field, which the API stores as `""`. This is acceptable for v1 and documented here so nobody "fixes" it by accident.

- [ ] **Step 4: Run the full agents test file**

Run: `venv/bin/python -m pytest tests/test_api_agents.py -v`
Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/agents.py backend/tests/test_api_agents.py
git commit -m "feat(agents): update and delete agents with lifecycle guards

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Router — status transitions

**Files:**
- Modify: `backend/app/routers/agents.py` (append)
- Test: `backend/tests/test_api_agents.py` (append)

**Interfaces:**
- Consumes: `_get_agent`, `_to_read`, `AgentStatusUpdate`.
- Produces: `PUT /api/v1/agents/{id}/status` with body `{"status": "..."}`; module constant `ALLOWED_TRANSITIONS: dict[str, set[str]]`.

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/test_api_agents.py`:

```python
# ---- status transitions --------------------------------------------------

async def change(c: AsyncClient, agent_id: str, status: str):
    return await c.put(f"/api/v1/agents/{agent_id}/status", json={"status": status})


@pytest.mark.parametrize("start,target", [
    ("draft", "active"),
    ("active", "paused"),
    ("paused", "active"),
    ("draft", "archived"),
    ("active", "archived"),
    ("paused", "archived"),
    ("archived", "draft"),
])
async def test_valid_transitions(setup_test_db, start, target):
    sid = await create_server(setup_test_db, "TmLite", enabled=True)
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[sid])
        await set_status(setup_test_db, data["id"], start)
        resp = await change(c, data["id"], target)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == target
    assert resp.json()["updated_at"] > data["updated_at"]


@pytest.mark.parametrize("start,target", [
    ("draft", "paused"),
    ("draft", "draft"),
    ("active", "draft"),
    ("active", "active"),
    ("paused", "draft"),
    ("archived", "active"),
    ("archived", "paused"),
    ("archived", "archived"),
])
async def test_invalid_transitions_409(setup_test_db, start, target):
    sid = await create_server(setup_test_db, "TmLite", enabled=True)
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[sid])
        await set_status(setup_test_db, data["id"], start)
        resp = await change(c, data["id"], target)
    assert resp.status_code == 409
    assert start in resp.json()["detail"] and target in resp.json()["detail"]


async def test_activate_requires_enabled_server(setup_test_db):
    disabled = await create_server(setup_test_db, "off", enabled=False)
    async with client() as c:
        no_servers = await create_agent(c)
        resp = await change(c, no_servers["id"], "active")
        assert resp.status_code == 400
        assert "enabled MCP server" in resp.json()["detail"]

        only_disabled = await create_agent(c, mcp_server_ids=[disabled])
        resp = await change(c, only_disabled["id"], "active")
        assert resp.status_code == 400


async def test_resume_requires_enabled_server(setup_test_db):
    disabled = await create_server(setup_test_db, "off", enabled=False)
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[disabled])
        await set_status(setup_test_db, data["id"], "paused")
        resp = await change(c, data["id"], "active")
    assert resp.status_code == 400


async def test_status_unknown_value_422_and_not_found():
    async with client() as c:
        data = await create_agent(c)
        resp = await change(c, data["id"], "running")
        assert resp.status_code == 422
        resp = await change(c, str(uuid.uuid4()), "active")
        assert resp.status_code == 404


async def test_list_filters(setup_test_db):
    async with client() as c:
        a = await create_agent(c, name="a")
        b = await create_agent(c, name="b")
        await set_status(setup_test_db, b["id"], "archived")

        default = await c.get("/api/v1/agents")
        assert [x["name"] for x in default.json()] == ["a"]

        archived = await c.get("/api/v1/agents", params={"status": "archived"})
        assert [x["name"] for x in archived.json()] == ["b"]

        drafts = await c.get("/api/v1/agents", params={"status": "draft"})
        assert [x["name"] for x in drafts.json()] == ["a"]

        bad = await c.get("/api/v1/agents", params={"status": "running"})
        assert bad.status_code == 422


async def test_deleting_server_removes_it_from_agent(setup_test_db):
    sid = await create_server(setup_test_db, "TmLite")
    async with client() as c:
        data = await create_agent(c, mcp_server_ids=[sid])
        resp = await c.delete(f"/api/v1/mcp-servers/{sid}")
        assert resp.status_code == 204
        resp = await c.get(f"/api/v1/agents/{data['id']}")
    assert resp.status_code == 200
    assert resp.json()["mcp_servers"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_api_agents.py -v -k "transition or activate or resume or status_unknown or filters or deleting_server"`
Expected: transition tests FAIL with `405` (or `404`, because `/{agent_id}/status` currently matches nothing); `test_list_filters` and `test_deleting_server_removes_it_from_agent` already PASS.

- [ ] **Step 3: Append the endpoint**

Append to `backend/app/routers/agents.py`:

```python
# from -> allowed targets. `archived` is terminal except for restore to draft.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": {"draft"},
}


@router.put("/{agent_id}/status", response_model=AgentRead)
async def set_agent_status(agent_id: uuid.UUID, data: AgentStatusUpdate, session: AsyncSession = Depends(get_async_session)):
    agent = await _get_agent(session, agent_id)
    target = data.status
    if target not in ALLOWED_TRANSITIONS[agent.status]:
        raise HTTPException(status_code=409, detail=f"Cannot move agent from {agent.status} to {target}")
    if target == "active" and not any(s.enabled for s in agent.mcp_servers):
        raise HTTPException(status_code=400, detail="Agent needs at least one enabled MCP server to be activated")

    previous = agent.status
    agent.status = target
    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(agent)
    log.info("agent_status_changed", agent_id=str(agent.id), previous=previous, status=target)
    return _to_read(agent)
```

- [ ] **Step 4: Run the whole backend suite**

Run: `venv/bin/python -m pytest tests/test_agent_model.py tests/test_api_agents.py tests/test_api_mcp_servers.py tests/test_api_prompts.py -v`
Expected: all passed; `test_api_agents.py` alone is 42 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/agents.py backend/tests/test_api_agents.py
git commit -m "feat(agents): enforce draft/active/paused/archived transitions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Frontend API client and the `Modal` primitive

**Files:**
- Modify: `frontend/src/lib/api.ts` (append after the Prompts block, around line 83, and after the `Prompt*` interfaces around line 250)
- Create: `frontend/src/components/ui/Modal.tsx`
- Modify: `frontend/src/index.css` (append at end)

**Interfaces:**
- Produces in `api.ts`: `AgentStatus`, `AgentServerRef`, `Agent`, `AgentCreate`, `AgentUpdate`, `listAgents(status?)`, `createAgent`, `updateAgent`, `deleteAgent`, `setAgentStatus`.
- Produces: `<Modal open title onClose>{children}</Modal>`.

- [ ] **Step 1: Add the API functions and types**

In `frontend/src/lib/api.ts`, after the `regenerateScript` line in the Prompts block, add:

```ts
// Agents
export const listAgents = (status?: AgentStatus) =>
  request<Agent[]>(`/agents${status ? `?status=${status}` : ""}`);
export const createAgent = (data: AgentCreate) =>
  request<Agent>("/agents", { method: "POST", body: JSON.stringify(data) });
export const updateAgent = (id: string, data: AgentUpdate) =>
  request<Agent>(`/agents/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteAgent = (id: string) =>
  request<void>(`/agents/${id}`, { method: "DELETE" });
export const setAgentStatus = (id: string, status: AgentStatus) =>
  request<Agent>(`/agents/${id}/status`, { method: "PUT", body: JSON.stringify({ status }) });
```

After the `PromptCreate` interface (in the types section), add:

```ts
export type AgentStatus = "draft" | "active" | "paused" | "archived";
export interface AgentServerRef {
  id: string;
  name: string;
  enabled: boolean;
}
export interface Agent {
  id: string;
  name: string;
  objective: string;
  instructions: string;
  description: string | null;
  status: AgentStatus;
  max_steps: number;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
  mcp_servers: AgentServerRef[];
}
export interface AgentCreate {
  name: string;
  objective: string;
  instructions?: string;
  description?: string;
  max_steps?: number;
  timeout_seconds?: number;
  mcp_server_ids: string[];
}
export type AgentUpdate = Partial<AgentCreate>;
```

- [ ] **Step 2: Create the Modal component**

Create `frontend/src/components/ui/Modal.tsx`:

```tsx
import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

const FOCUSABLE = 'input, textarea, select, button:not([data-modal-close]), [href], [tabindex]:not([tabindex="-1"])';

export function Modal({ open, title, onClose, children }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panelRef} className="modal-panel card-elevated" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h3 style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>{title}</h3>
          <button type="button" data-modal-close className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add the modal styles**

Append to `frontend/src/index.css`:

```css
/* ─── Modal ───────────────────────────────────────────────────── */
.modal-overlay { position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(5, 8, 14, .62); backdrop-filter: blur(6px); }
.modal-panel { display: flex; flex-direction: column; width: min(640px, 100%); max-height: calc(100vh - 48px); box-shadow: 0 24px 60px rgba(0,0,0,.45); }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 22px 12px; border-bottom: 1px solid var(--border); }
.modal-head h3 { margin: 0; font-size: 1.05rem; font-weight: 600; }
.modal-close { width: 30px; height: 30px; border: 1px solid var(--border); border-radius: 8px; background: transparent; color: var(--text-secondary); font-size: 18px; line-height: 1; cursor: pointer; }
.modal-close:hover { color: var(--text-primary); background: rgba(255,255,255,.05); }
.modal-body { padding: 18px 22px 22px; overflow-y: auto; }
:root[data-theme="light"] .modal-overlay { background: rgba(23, 35, 53, .35); }
@media (max-width: 640px) { .modal-overlay { padding: 0; align-items: stretch; } .modal-panel { width: 100%; max-height: 100vh; border-radius: 0; } }

/* Compact variant for row actions; declared after the base button rules so it wins at equal specificity. */
.btn-sm { padding: 0.3rem 0.7rem; font-size: 0.75rem; }
```

- [ ] **Step 4: Type-check and lint**

Run (from `frontend/`): `npm run lint && npm run build`
Expected: lint clean; build succeeds (the new exports are simply unused for now).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/ui/Modal.tsx frontend/src/index.css
git commit -m "feat(agents): add agents API client and a reusable Modal primitive

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `AgentFormModal` (create and edit)

**Files:**
- Create: `frontend/src/components/Agents/AgentFormModal.tsx`

**Interfaces:**
- Consumes: `Modal`, `listMcpServers`, `createAgent`, `updateAgent`, types `Agent`, `AgentCreate`, `McpServer` from `api.ts`.
- Produces: `<AgentFormModal open agent? onClose />`. It owns its own mutation and invalidates `["agents"]` on success, then calls `onClose()`.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/Agents/AgentFormModal.tsx`:

```tsx
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAgent, listMcpServers, updateAgent } from "../../lib/api";
import type { Agent, AgentCreate } from "../../lib/api";
import { Modal } from "../ui/Modal";
import { MutationError } from "../ui/MutationError";

interface Props {
  open: boolean;
  agent?: Agent | null;
  onClose: () => void;
}

const LIMITS = { steps: { min: 1, max: 100, def: 20 }, timeout: { min: 10, max: 3600, def: 300 } };

const labelStyle = { color: "var(--text-muted)" } as const;
const labelClass = "mb-1.5 block text-xs font-medium uppercase tracking-wider";

export function AgentFormModal({ open, agent, onClose }: Props) {
  const queryClient = useQueryClient();
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });

  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [instructions, setInstructions] = useState("");
  const [description, setDescription] = useState("");
  const [serverIds, setServerIds] = useState<string[]>([]);
  const [maxSteps, setMaxSteps] = useState<number>(LIMITS.steps.def);
  const [timeoutSeconds, setTimeoutSeconds] = useState<number>(LIMITS.timeout.def);

  // Re-seed the fields each time the modal opens, for a new agent or an existing one.
  useEffect(() => {
    if (!open) return;
    setName(agent?.name ?? "");
    setObjective(agent?.objective ?? "");
    setInstructions(agent?.instructions ?? "");
    setDescription(agent?.description ?? "");
    setServerIds(agent?.mcp_servers.map((s) => s.id) ?? []);
    setMaxSteps(agent?.max_steps ?? LIMITS.steps.def);
    setTimeoutSeconds(agent?.timeout_seconds ?? LIMITS.timeout.def);
  }, [open, agent]);

  const mutation = useMutation({
    mutationFn: (data: AgentCreate) => (agent ? updateAgent(agent.id, data) : createAgent(data)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      onClose();
    },
  });

  const inRange = (v: number, r: { min: number; max: number }) => Number.isInteger(v) && v >= r.min && v <= r.max;
  const valid = name.trim() !== "" && objective.trim() !== "" && inRange(maxSteps, LIMITS.steps) && inRange(timeoutSeconds, LIMITS.timeout);

  const toggleServer = (id: string) =>
    setServerIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    mutation.mutate({
      name: name.trim(),
      objective: objective.trim(),
      instructions,
      description: description.trim(),
      max_steps: maxSteps,
      timeout_seconds: timeoutSeconds,
      mcp_server_ids: serverIds,
    });
  };

  return (
    <Modal open={open} title={agent ? "Edit agent" : "New agent"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label className={labelClass} style={labelStyle}>Name</label>
          <input className="input-field" placeholder="Log analyst" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Objective</label>
          <textarea rows={3} className="input-field" placeholder="What this agent is responsible for achieving" value={objective} onChange={(e) => setObjective(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Instructions</label>
          <textarea rows={5} className="input-field" placeholder="System prompt: how the agent should behave, what it must never do, how to report" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Description</label>
          <input className="input-field" placeholder="Optional note for humans" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Authorised MCP servers</label>
          {servers.length === 0 ? (
            <p className="text-sm rounded-lg px-3 py-2" style={{ color: "var(--text-muted)", backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              No MCP servers configured. Add one in Settings first.
            </p>
          ) : (
            <div className="space-y-1.5">
              {servers.map((s) => (
                <label key={s.id} className="flex items-center gap-2.5 text-sm cursor-pointer" style={{ color: "var(--text-primary)" }}>
                  <input type="checkbox" checked={serverIds.includes(s.id)} onChange={() => toggleServer(s.id)} />
                  <span>{s.name}</span>
                  {!s.enabled && <span className="text-xs" style={{ color: "var(--text-muted)" }}>disabled</span>}
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass} style={labelStyle}>Max steps</label>
            <input type="number" min={LIMITS.steps.min} max={LIMITS.steps.max} className="input-field" value={maxSteps} onChange={(e) => setMaxSteps(Number(e.target.value))} />
            <p className="mt-1 text-xs" style={labelStyle}>{LIMITS.steps.min} to {LIMITS.steps.max} tool rounds per task</p>
          </div>
          <div>
            <label className={labelClass} style={labelStyle}>Timeout (s)</label>
            <input type="number" min={LIMITS.timeout.min} max={LIMITS.timeout.max} className="input-field" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} />
            <p className="mt-1 text-xs" style={labelStyle}>{LIMITS.timeout.min} to {LIMITS.timeout.max} seconds per task</p>
          </div>
        </div>

        <MutationError error={mutation.error} />

        <div className="flex justify-end gap-3 pt-1">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!valid || mutation.isPending}>
            {mutation.isPending ? "Saving..." : agent ? "Save changes" : "Create agent"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
```

- [ ] **Step 2: Type-check and lint**

Run (from `frontend/`): `npm run lint && npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Agents/AgentFormModal.tsx
git commit -m "feat(agents): add the create/edit agent modal form

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `AgentCard`, `AgentList`, `AgentsPage`, route and navigation

**Files:**
- Create: `frontend/src/components/Agents/AgentCard.tsx`
- Create: `frontend/src/components/Agents/AgentList.tsx`
- Create: `frontend/src/pages/AgentsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/TabNav.tsx`

**Interfaces:**
- Consumes: `AgentFormModal` (Task 6), `listAgents`, `setAgentStatus`, `deleteAgent`, types from Task 5.
- Produces: `<AgentList status onEdit />` where `status` is `"active" | "archived"` in the page's sense ("active" = the API default list, i.e. everything but archived), `<AgentsPage />`, route `/agents`.

- [ ] **Step 1: Create `AgentCard`**

Create `frontend/src/components/Agents/AgentCard.tsx`:

```tsx
import { useState, type ReactNode } from "react";
import type { Agent, AgentStatus } from "../../lib/api";
import { MutationError } from "../ui/MutationError";

interface Props {
  agent: Agent;
  busy: boolean;
  error: unknown;
  onEdit: (agent: Agent) => void;
  onStatus: (agent: Agent, status: AgentStatus) => void;
  onDelete: (agent: Agent) => void;
}

const BADGE: Record<AgentStatus, { color: string; bg: string; border: string; label: string }> = {
  draft:    { color: "var(--text-secondary)", bg: "rgba(148, 163, 184, 0.12)", border: "rgba(148, 163, 184, 0.25)", label: "Draft" },
  active:   { color: "var(--success)",        bg: "rgba(52, 211, 153, 0.10)",  border: "rgba(52, 211, 153, 0.20)",  label: "Active" },
  paused:   { color: "var(--warning)",        bg: "rgba(251, 191, 36, 0.12)",  border: "rgba(251, 191, 36, 0.25)",  label: "Paused" },
  archived: { color: "var(--text-muted)",     bg: "rgba(100, 116, 139, 0.10)", border: "rgba(100, 116, 139, 0.20)", label: "Archived" },
};

export function AgentCard({ agent, busy, error, onEdit, onStatus, onDelete }: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const badge = BADGE[agent.status];
  const updated = new Date(agent.updated_at).toLocaleString();

  const action = (label: string, onClick: () => void, cls = "btn-secondary") => (
    <button key={label} type="button" className={`${cls} btn-sm`} disabled={busy} onClick={onClick}>{label}</button>
  );

  const deleteButton = confirmDelete
    ? [action("Confirm delete", () => { setConfirmDelete(false); onDelete(agent); }, "btn-danger"), action("Keep", () => setConfirmDelete(false))]
    : [action("Delete", () => setConfirmDelete(true), "btn-danger")];

  const actions: ReactNode[] = {
    draft:    [action("Activate", () => onStatus(agent, "active"), "btn-primary"), action("Edit", () => onEdit(agent)), ...deleteButton],
    active:   [action("Pause", () => onStatus(agent, "paused")), action("Edit", () => onEdit(agent)), action("Archive", () => onStatus(agent, "archived"))],
    paused:   [action("Resume", () => onStatus(agent, "active"), "btn-primary"), action("Edit", () => onEdit(agent)), action("Archive", () => onStatus(agent, "archived"))],
    archived: [action("Restore", () => onStatus(agent, "draft")), ...deleteButton],
  }[agent.status];

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className={`h-2 w-2 flex-shrink-0 rounded-full ${agent.status === "active" ? "pulse-dot" : ""}`} style={{ backgroundColor: badge.color }} />
            <span className="font-semibold truncate" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)", fontSize: "0.9375rem" }}>{agent.name}</span>
            <span className="badge flex-shrink-0" style={{ color: badge.color, backgroundColor: badge.bg, border: `1px solid ${badge.border}` }}>{badge.label}</span>
          </div>
          <p className="mt-1.5 text-sm line-clamp-2" style={{ color: "var(--text-secondary)" }}>{agent.objective}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-2 flex-shrink-0">{actions}</div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
        {agent.mcp_servers.length === 0 ? (
          <span>No MCP servers</span>
        ) : (
          agent.mcp_servers.map((s) => (
            <span key={s.id} className="rounded-md px-2 py-0.5" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)", color: s.enabled ? "var(--text-secondary)" : "var(--text-muted)", textDecoration: s.enabled ? "none" : "line-through" }} title={s.enabled ? s.name : `${s.name} (disabled)`}>
              {s.name}
            </span>
          ))
        )}
        <span className="font-mono">{agent.max_steps} steps · {agent.timeout_seconds} s</span>
        <span className="ml-auto">Updated {updated}</span>
      </div>

      <MutationError error={error} />
    </div>
  );
}
```

- [ ] **Step 2: Create `AgentList`**

Create `frontend/src/components/Agents/AgentList.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteAgent, listAgents, setAgentStatus } from "../../lib/api";
import type { Agent, AgentStatus } from "../../lib/api";
import { AgentCard } from "./AgentCard";
import { Spinner } from "../ui/Spinner";

interface Props {
  view: "active" | "archived";
  onEdit: (agent: Agent) => void;
  onCreate: () => void;
}

export function AgentList({ view, onEdit, onCreate }: Props) {
  const queryClient = useQueryClient();
  const status: AgentStatus | undefined = view === "archived" ? "archived" : undefined;
  const { data: agents = [], isLoading } = useQuery({ queryKey: ["agents", status ?? "all"], queryFn: () => listAgents(status) });
  const [errors, setErrors] = useState<Record<string, unknown>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const statusMut = useMutation({ mutationFn: ({ id, status }: { id: string; status: AgentStatus }) => setAgentStatus(id, status) });
  const deleteMut = useMutation({ mutationFn: (id: string) => deleteAgent(id) });

  // Tracks busy state and the per-card error around one mutation; `mutateAsync` rejects on failure.
  const run = async (id: string, call: () => Promise<unknown>) => {
    setBusyId(id);
    setErrors((prev) => ({ ...prev, [id]: null }));
    try {
      await call();
    } catch (err) {
      setErrors((prev) => ({ ...prev, [id]: err }));
    } finally {
      setBusyId(null);
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    }
  };

  if (isLoading) {
    return <div className="flex justify-center py-12"><Spinner /></div>;
  }

  if (agents.length === 0) {
    return (
      <div className="rounded-xl py-16 text-center" style={{ backgroundColor: "var(--bg-panel)", border: "1px dashed var(--border)" }}>
        <p className="text-base font-medium" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
          {view === "archived" ? "No archived agents" : "No agents yet"}
        </p>
        <p className="mt-1 text-sm max-w-xs mx-auto" style={{ color: "var(--text-muted)" }}>
          {view === "archived" ? "Archived agents will show up here." : "Define an objective, pick the MCP servers it may use, and set its limits."}
        </p>
        {view !== "archived" && <button type="button" className="btn-primary mt-4" onClick={onCreate}>+ New Agent</button>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {agents.map((agent) => (
        <AgentCard
          key={agent.id}
          agent={agent}
          busy={busyId === agent.id}
          error={errors[agent.id]}
          onEdit={onEdit}
          onStatus={(a, s) => run(a.id, () => statusMut.mutateAsync({ id: a.id, status: s }))}
          onDelete={(a) => run(a.id, () => deleteMut.mutateAsync(a.id))}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `AgentsPage`**

Create `frontend/src/pages/AgentsPage.tsx`:

```tsx
import { useState } from "react";
import type { Agent } from "../lib/api";
import { AgentList } from "../components/Agents/AgentList";
import { AgentFormModal } from "../components/Agents/AgentFormModal";

export function AgentsPage() {
  const [view, setView] = useState<"active" | "archived">("active");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);

  const openCreate = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (agent: Agent) => { setEditing(agent); setModalOpen(true); };
  const close = () => { setModalOpen(false); setEditing(null); };

  const tab = (value: "active" | "archived", label: string) => (
    <button type="button" className={value === view ? "btn-primary btn-sm" : "btn-secondary btn-sm"} onClick={() => setView(value)}>
      {label}
    </button>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-5 w-1 rounded-full flex-shrink-0" style={{ backgroundColor: "var(--accent)" }} />
          <h2 className="text-2xl font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
            Agents
          </h2>
        </div>
        <button type="button" onClick={openCreate} className="btn-primary">+ New Agent</button>
      </div>

      <div className="flex gap-2">
        {tab("active", "Active")}
        {tab("archived", "Archived")}
      </div>

      <AgentList view={view} onEdit={openEdit} onCreate={openCreate} />
      <AgentFormModal open={modalOpen} agent={editing} onClose={close} />
    </div>
  );
}
```

- [ ] **Step 4: Register the route**

In `frontend/src/App.tsx` add the import after `PromptsPage`:

```tsx
import { AgentsPage } from "./pages/AgentsPage";
```

and the route right after the index route:

```tsx
            <Route path="agents" element={<AgentsPage />} />
```

- [ ] **Step 5: Add the tab, icon and status line in `TabNav.tsx`**

In `frontend/src/components/Layout/TabNav.tsx`:

1. Import: change line 4 to `import { listAgents, listPrompts, listMcpServers } from "../../lib/api";`
2. `IconName`: add `"agent"` → `type IconName = "automation" | "agent" | "reports" | ...`.
3. `tabs`: insert as the second entry:
   ```ts
   { to: "/agents", label: "Agents", eyebrow: "Autonomous runs", icon: "agent" },
   ```
4. `Icon` paths: add
   ```tsx
   agent: <><rect x="5" y="8" width="14" height="11" rx="2.5"/><path d="M12 3.5v4.5M9 12.5h.01M15 12.5h.01M9.5 16h5"/><path d="M3 12.5h2M19 12.5h2"/></>,
   ```
5. `SystemStatus`: add the query and the line:
   ```tsx
   const { data: agents = [] } = useQuery({ queryKey: ["agents", "all"], queryFn: () => listAgents(), refetchInterval: 30000 });
   const activeAgents = agents.filter((agent) => agent.status === "active").length;
   ```
   and inside the returned JSX, after the "Active flows" line:
   ```tsx
   <div className="system-status-line"><i className={activeAgents ? "is-live" : ""}/><span>Active agents</span><b>{activeAgents}</b></div>
   ```
6. Section slices in `TabNav`: the sidebar renders three groups. Change them to
   `tabs.slice(0, 4)` (Automate), `tabs.slice(4, 7)` (Telephony), `tabs.slice(7)` (Support).
   `primaryTabs = tabs.slice(0, 4)` and `secondaryTabs = tabs.slice(4)` already read the first four, so the mobile bar keeps its five cells (four tabs + More).

- [ ] **Step 6: Lint, build, and check the page in a browser**

Run (from `frontend/`): `npm run lint && npm run build`
Expected: clean.

Then with the backend running (`venv/bin/uvicorn app.main:app --reload` from `backend/`, migration applied) and `npm run dev`, open `http://localhost:3000/agents` and check:

- Empty state shows, `+ New Agent` opens the modal, Escape closes it, focus lands in the Name field.
- Creating with no servers yields a `Draft` card; Activate shows the "needs at least one enabled MCP server" error under the card.
- Edit → tick a server → Save → Activate works, badge turns green, "Active agents" in the sidebar goes to 1.
- Pause, Resume, Archive; the Archived view shows it with Restore / Delete; Delete needs the confirm step.
- No horizontal scroll at 375px width; the modal is full-screen there.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Agents/AgentCard.tsx frontend/src/components/Agents/AgentList.tsx frontend/src/pages/AgentsPage.tsx frontend/src/App.tsx frontend/src/components/Layout/TabNav.tsx
git commit -m "feat(agents): add the Agents page, list, lifecycle actions and nav tab

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Final verification and docs touch

**Files:**
- Modify: `CLAUDE.md` (Architecture section, one new short paragraph)

- [ ] **Step 1: Run the whole backend suite**

Run (from `backend/`): `venv/bin/python -m pytest tests/ -v`
Expected: everything passes, including the pre-existing suites. If a pre-existing test fails for a reason unrelated to agents (e.g. TmLite fixtures), report it rather than touching it.

- [ ] **Step 2: Run the frontend checks once more**

Run (from `frontend/`): `npm run lint && npm run build`
Expected: clean.

- [ ] **Step 3: Confirm autogenerate sees nothing new for agents**

Run (from `backend/`):

```bash
PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "check agents"
grep -il "agent" alembic/versions/*check_agents*.py || echo "no agent diff"
rm alembic/versions/*check_agents*.py
```

Expected: `no agent diff`. The generated file will still contain the usual spurious index and `apscheduler_jobs` drops for other tables; that noise is pre-existing and the file is deleted on the last line regardless. Confirm with `git status` that no `check_agents` revision remains.

- [ ] **Step 4: Document the module in CLAUDE.md**

In `CLAUDE.md`, under `## Architecture`, add before `### Scheduling`:

```markdown
### Agents

`Agent` rows (`models/agent.py`) describe autonomous agents: objective, instructions, allowed MCP servers through the `agent_mcp_server` association table (cascade both sides), `max_steps` and `timeout_seconds`. Nothing executes them yet — this is the P0 "socle" of `docs/superpowers/specs/2026-10-24-agents-crud-design.md`. Lifecycle is `draft → active ⇄ paused → archived → draft`, enforced by `ALLOWED_TRANSITIONS` in `routers/agents.py`; activation requires at least one **enabled** authorised server, deletion is only allowed for `draft` and `archived`. The LLM model is inherited from the global `Config`, not stored per agent.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agents): describe the Agents module in CLAUDE.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
