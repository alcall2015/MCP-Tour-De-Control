# Projects Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Projects` tab that groups Google Docs/Sheets links by project and displays live indicators read from each project's Sheet, with status, 7-day trends, pending decisions and consolidated budget.

**Architecture:** Three new tables (`project`, `project_link`, `project_snapshot`) store projects, their document links and dated metric snapshots. A Google service account reads a `SUIVI!A:B` key/value tab from each project's KPI Sheet; an APScheduler cron writes one snapshot per project per day. All parsing and status logic is pure and I/O-free; the React page reads only the database, so it renders instantly.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, APScheduler 3, google-api-python-client, React 19 + TanStack Query + Tailwind 4.

**Spec:** `docs/superpowers/specs/2026-08-19-projects-dashboard-design.md`

## Global Constraints

- Business logic lives in `app/services/`; routers stay thin and declare `APIRouter(prefix="/api/v1/<resource>")`.
- Every new model MUST be exported from `app/models/__init__.py` — Alembic autogenerate depends on it.
- Every schema MUST be exported from `app/schemas/__init__.py`.
- Database changes require an Alembic migration; `PYTHONPATH=.` is mandatory for every alembic command.
- Secrets are Fernet-encrypted via `app/utils/crypto.py`; API reads expose `<name>_set: bool`, never the value.
- All frontend HTTP calls and shared interfaces go in `frontend/src/lib/api.ts` — no ad-hoc `fetch` in components.
- Code, comments and UI strings are in English. No emojis in the nav.
- Colors come from the CSS variables in `frontend/src/index.css`: `--bg-panel`, `--bg-elevated`, `--border`, `--accent`, `--success`, `--error`, `--warning`, `--text-primary`, `--text-secondary`, `--text-muted`.
- Backend tests require Postgres at `localhost:5432` (`mcp`/`mcp_secret`) with database `mcp_control_test`. No test performs a network call.
- Conventional Commits (`feat(projects): ...`).

## Refinement to the spec's file structure

The spec lists `services/google_service.py` and `services/project_service.py`. This plan adds two extra modules so the pure logic the spec's testing section demands has a home of its own:

- `app/utils/suivi_parser.py` — SUIVI tab parsing (no I/O)
- `app/services/project_status.py` — status rules and trends (no I/O)

`project_service.py` keeps orchestration and database work only.

The spec also lists a separate `LinkList.tsx`; this plan folds the list into `LinkForm.tsx`, since the list and the add form are always shown together and share the same mutations. Everything else follows the spec exactly.

## File Structure

```
backend/app/
├── models/project.py                Project, ProjectLink, ProjectSnapshot
├── models/config.py                 + google_sa_key, projects_cron
├── schemas/project.py               Pydantic schemas
├── schemas/config.py                + google_sa_key_set, projects_cron
├── routers/projects.py              /api/v1/projects
├── routers/config.py                + Google key handling
├── utils/suivi_parser.py            pure SUIVI parsing
├── services/project_status.py       pure status + trend rules
├── services/google_service.py       Sheets/Drive read access
├── services/project_service.py      refresh orchestration + aggregates
└── main.py                          + router, + projects_refresh cron

backend/tests/
├── test_suivi_parser.py
├── test_project_status.py
├── test_project_trends.py
├── test_google_service.py
└── test_api_projects.py

frontend/src/
├── lib/api.ts                       + project endpoints and types
├── pages/ProjectsPage.tsx
├── components/Projects/StatusDot.tsx
├── components/Projects/Sparkline.tsx
├── components/Projects/ProjectCard.tsx
├── components/Projects/DecisionsPanel.tsx
├── components/Projects/BudgetSummary.tsx
├── components/Projects/ProjectForm.tsx
├── components/Projects/LinkForm.tsx
├── components/Layout/TabNav.tsx     + Projects tab
└── App.tsx                          + /projects route
```

---

### Task 1: Database models and migration

**Files:**
- Create: `backend/app/models/project.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/config.py`
- Create: `backend/tests/test_project_models.py`
- Create: `backend/alembic/versions/<generated>_add_project_tables.py`

**Interfaces:**
- Consumes: `app.models.config.Base` (existing declarative base)
- Produces: `Project`, `ProjectLink`, `ProjectSnapshot` importable from `app.models`; `Config.google_sa_key: str`, `Config.projects_cron: str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_project_models.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Config, Project, ProjectLink, ProjectSnapshot


async def test_project_defaults(session):
    project = Project(name="AVA Voice Agent")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    assert isinstance(project.id, uuid.UUID)
    assert project.position == 0
    assert project.stale_days == 14
    assert project.budget_warn_pct == 90


async def test_links_and_snapshots_cascade(session):
    project = Project(name="Tour De Control")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    session.add(
        ProjectLink(
            project_id=project.id,
            label="Suivi hebdo",
            url="https://docs.google.com/spreadsheets/d/ABC123/edit",
            kind="sheet",
            file_id="ABC123",
            is_kpi_source=True,
        )
    )
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=datetime.now(timezone.utc),
            metrics={"avancement": 40, "budget_total": 3000},
        )
    )
    await session.commit()

    await session.delete(project)
    await session.commit()

    links = (await session.execute(select(ProjectLink))).scalars().all()
    snapshots = (await session.execute(select(ProjectSnapshot))).scalars().all()
    assert links == []
    assert snapshots == []


async def test_snapshot_stores_error_without_metrics(session):
    project = Project(name="Broken")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    session.add(ProjectSnapshot(project_id=project.id, error="permission denied"))
    await session.commit()

    snapshot = (await session.execute(select(ProjectSnapshot))).scalar_one()
    assert snapshot.error == "permission denied"
    assert snapshot.metrics is None


async def test_config_has_google_columns(session):
    config = Config()
    session.add(config)
    await session.commit()
    await session.refresh(config)

    assert config.google_sa_key == ""
    assert config.projects_cron == "0 6 * * *"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'Project' from 'app.models'`

- [ ] **Step 3: Create the models**

Create `backend/app/models/project.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class Project(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    stale_days: Mapped[int] = mapped_column(Integer, default=14)
    budget_warn_pct: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    links: Mapped[list["ProjectLink"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectLink.position"
    )
    snapshots: Mapped[list["ProjectSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectLink(Base):
    __tablename__ = "project_link"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    file_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_kpi_source: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship(back_populates="links")


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("ix_project_snapshot_project_captured", "project_id", "captured_at"),
    )
```

- [ ] **Step 4: Export the models**

Replace `backend/app/models/__init__.py` with:

```python
from app.models.config import Base, Config
from app.models.mcp_server import McpServer
from app.models.prompt import Prompt
from app.models.script import Script
from app.models.execution import Execution
from app.models.stress_test import StressTest
from app.models.stress_test_metrics import StressTestMetrics
from app.models.conversation import Conversation, ChatMessage
from app.models.project import Project, ProjectLink, ProjectSnapshot

__all__ = ["Base", "Config", "McpServer", "Prompt", "Script", "Execution", "StressTest", "StressTestMetrics", "Conversation", "ChatMessage", "Project", "ProjectLink", "ProjectSnapshot"]
```

- [ ] **Step 5: Add the Config columns**

In `backend/app/models/config.py`, add `Text` to the sqlalchemy import line and insert the two columns after `api_key`:

```python
from sqlalchemy import String, DateTime, Text
```

```python
    api_key: Mapped[str] = mapped_column(String(500), default="")
    google_sa_key: Mapped[str] = mapped_column(Text, default="")
    projects_cron: Mapped[str] = mapped_column(String(100), default="0 6 * * *")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_models.py -v`
Expected: PASS, 4 tests

- [ ] **Step 7: Generate the migration**

Run: `cd backend && PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "add project tables"`
Expected: a new file under `alembic/versions/`. Open it and confirm `upgrade()` creates `project`, `project_link`, `project_snapshot` with the `ix_project_snapshot_project_captured` index, and adds `google_sa_key` and `projects_cron` to `config`. Confirm `downgrade()` drops them.

- [ ] **Step 8: Apply and verify the migration**

Run: `cd backend && PYTHONPATH=. venv/bin/alembic upgrade head`
Expected: `Running upgrade ... -> <rev>, add project tables` with no error.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/project.py backend/app/models/__init__.py backend/app/models/config.py backend/tests/test_project_models.py backend/alembic/versions/
git commit -m "feat(projects): add project, link and snapshot models"
```

---

### Task 2: SUIVI tab parser

**Files:**
- Create: `backend/app/utils/suivi_parser.py`
- Create: `backend/tests/test_suivi_parser.py`

**Interfaces:**
- Consumes: nothing
- Produces: `normalize_key(raw: str) -> str`, `parse_value(raw: str) -> float | str`, `parse_date(value) -> datetime.date | None`, `parse_suivi_rows(rows: list[list]) -> dict[str, float | str]`

Values are stored in a JSONB column, so `parse_value` never returns a `date` object — ISO dates stay strings and `parse_date` converts on demand.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_suivi_parser.py`:

```python
from datetime import date

import pytest

from app.utils.suivi_parser import normalize_key, parse_date, parse_suivi_rows, parse_value


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("avancement", "avancement"),
        ("  Avancement  ", "avancement"),
        ("Budget consommé", "budget_consomme"),
        ("PROCHAIN JALON", "prochain_jalon"),
        ("décision_attendue", "decision_attendue"),
        ("Coût / mois", "cout_mois"),
    ],
)
def test_normalize_key(raw, expected):
    assert normalize_key(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("72", 72.0),
        ("72%", 72.0),
        ("8400", 8400.0),
        ("8 400", 8400.0),
        ("8\u00a0400", 8400.0),  # non-breaking space, as Sheets exports it
        ("8,400", 8400.0),
        ("8400,50", 8400.5),
        ("8.400,50", 8400.5),
        ("8,400.50", 8400.5),
        ("12000 €", 12000.0),
        ("-250", -250.0),
    ],
)
def test_parse_value_numbers(raw, expected):
    assert parse_value(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-28", "2026-08-28"),
        ("Fabien", "Fabien"),
        ("moyen", "moyen"),
        ("Arbitrer le contrat X", "Arbitrer le contrat X"),
        ("", ""),
        ("  ", ""),
    ],
)
def test_parse_value_strings(raw, expected):
    assert parse_value(raw) == expected


def test_parse_date():
    assert parse_date("2026-08-28") == date(2026, 8, 28)
    assert parse_date("28/08/2026") is None
    assert parse_date("Fabien") is None
    assert parse_date(72.0) is None


def test_parse_suivi_rows():
    rows = [
        ["avancement", "72"],
        ["Budget consommé", "8 400"],
        ["budget_total", "12000"],
        ["prochain_jalon", "2026-08-28"],
        ["responsable", "Fabien"],
    ]
    assert parse_suivi_rows(rows) == {
        "avancement": 72.0,
        "budget_consomme": 8400.0,
        "budget_total": 12000.0,
        "prochain_jalon": "2026-08-28",
        "responsable": "Fabien",
    }


def test_parse_suivi_rows_skips_empty_and_keeps_last_duplicate():
    rows = [
        ["avancement", "40"],
        [],
        ["", "orphan value"],
        ["   ", "blank key"],
        ["missing value column"],
        ["avancement", "55"],
    ]
    assert parse_suivi_rows(rows) == {"avancement": 55.0, "missing_value_column": ""}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_suivi_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.suivi_parser'`

- [ ] **Step 3: Write the parser**

Create `backend/app/utils/suivi_parser.py`:

```python
"""Parsing of the SUIVI key/value tab. Pure functions, no I/O."""

import re
import unicodedata
from datetime import date, datetime

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMERIC_RE = re.compile(r"^-?[\d.,]+$")


def normalize_key(raw: str) -> str:
    """Lowercase, strip accents, turn any run of non-alphanumerics into a single underscore."""
    text = unicodedata.normalize("NFKD", str(raw).strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def parse_value(raw) -> float | str:
    """Numbers become floats; everything else is returned as a trimmed string.

    ISO dates stay strings so the result is JSON-serialisable for the JSONB column.
    """
    value = str(raw).strip()
    if not value:
        return ""
    if _ISO_DATE_RE.match(value):
        return value
    number = _parse_number(value)
    return value if number is None else number


def parse_date(value) -> date | None:
    """Convert an ISO YYYY-MM-DD string to a date. Anything else returns None."""
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_suivi_rows(rows: list[list]) -> dict[str, float | str]:
    """Turn SUIVI!A:B rows into a metrics dict. Blank keys are skipped, last duplicate wins."""
    metrics: dict[str, float | str] = {}
    for row in rows:
        if not row:
            continue
        key = normalize_key(row[0])
        if not key:
            continue
        raw_value = row[1] if len(row) > 1 else ""
        metrics[key] = parse_value(raw_value)
    return metrics


def _parse_number(value: str) -> float | None:
    """Parse a spreadsheet number: thousands separators, comma decimals, % and currency symbols."""
    # \s is Unicode-aware in Python, so it also strips the non-breaking spaces Sheets emits.
    cleaned = re.sub(r"[€$£%\s]", "", value)
    if not cleaned or not _NUMERIC_RE.match(cleaned):
        return None

    if "." in cleaned and "," in cleaned:
        # Whichever separator comes last is the decimal one.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        # "8400,50" is a decimal; "8,400" is a thousands separator.
        cleaned = f"{head}.{tail}" if len(tail) in (1, 2) else cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_suivi_parser.py -v`
Expected: PASS, 26 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/suivi_parser.py backend/tests/test_suivi_parser.py
git commit -m "feat(projects): parse SUIVI key/value tab"
```

---

### Task 3: Status rules and trends

**Files:**
- Create: `backend/app/services/project_status.py`
- Create: `backend/tests/test_project_status.py`
- Create: `backend/tests/test_project_trends.py`

**Interfaces:**
- Consumes: `app.utils.suivi_parser.parse_date`
- Produces:
  - `compute_status(*, metrics, error, source_modified_at, previous_metrics, stale_days, budget_warn_pct, now) -> dict` returning `{"level": str, "reason": str}` with level in `critical` / `attention` / `nominal` / `unknown`
  - `select_reference(history, latest_captured_at) -> tuple[datetime, dict] | None`
  - `compute_trends(metrics, reference_metrics) -> dict[str, float]`
  - Constants `LEVEL_CRITICAL`, `LEVEL_ATTENTION`, `LEVEL_NOMINAL`, `LEVEL_UNKNOWN`, `TREND_WINDOW_DAYS`

These functions take plain values, never ORM objects, so they stay pure and trivially testable. `history` is a list of `(captured_at, metrics)` tuples ordered newest first.

- [ ] **Step 1: Write the failing status test**

Create `backend/tests/test_project_status.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.services.project_status import (
    LEVEL_ATTENTION,
    LEVEL_CRITICAL,
    LEVEL_NOMINAL,
    LEVEL_UNKNOWN,
    compute_status,
)

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(days=1)


def status(**overrides):
    kwargs = {
        "metrics": {"avancement": 50.0, "budget_consomme": 1000.0, "budget_total": 5000.0},
        "error": None,
        "source_modified_at": FRESH,
        "previous_metrics": None,
        "stale_days": 14,
        "budget_warn_pct": 90,
        "now": NOW,
    }
    kwargs.update(overrides)
    return compute_status(**kwargs)


def test_read_failure_is_critical():
    assert status(metrics=None, error="permission denied")["level"] == LEVEL_CRITICAL


def test_no_source_is_unknown():
    result = status(metrics=None, error=None, source_modified_at=None)
    assert result["level"] == LEVEL_UNKNOWN


def test_budget_overrun_is_critical():
    result = status(metrics={"budget_consomme": 5200.0, "budget_total": 5000.0})
    assert result["level"] == LEVEL_CRITICAL


def test_overdue_milestone_is_critical():
    result = status(metrics={"prochain_jalon": "2026-08-18"})
    assert result["level"] == LEVEL_CRITICAL


def test_milestone_today_is_not_overdue():
    result = status(metrics={"prochain_jalon": "2026-08-19"})
    assert result["level"] == LEVEL_NOMINAL


def test_budget_at_warn_threshold_is_attention():
    result = status(metrics={"budget_consomme": 4500.0, "budget_total": 5000.0})
    assert result["level"] == LEVEL_ATTENTION


def test_stale_file_is_attention():
    result = status(source_modified_at=NOW - timedelta(days=15))
    assert result["level"] == LEVEL_ATTENTION


def test_stagnant_progress_is_attention():
    result = status(
        metrics={"avancement": 40.0},
        previous_metrics={"avancement": 40.0},
    )
    assert result["level"] == LEVEL_ATTENTION


def test_progressing_project_is_nominal():
    result = status(
        metrics={"avancement": 45.0},
        previous_metrics={"avancement": 40.0},
    )
    assert result["level"] == LEVEL_NOMINAL


def test_stagnation_skipped_without_reference():
    result = status(metrics={"avancement": 40.0}, previous_metrics=None)
    assert result["level"] == LEVEL_NOMINAL


def test_missing_metrics_skip_their_rules():
    result = status(metrics={"responsable": "Fabien"})
    assert result["level"] == LEVEL_NOMINAL


def test_critical_wins_over_attention():
    result = status(
        metrics={"budget_consomme": 6000.0, "budget_total": 5000.0},
        source_modified_at=NOW - timedelta(days=40),
    )
    assert result["level"] == LEVEL_CRITICAL


def test_reason_is_human_readable():
    result = status(metrics={"budget_consomme": 5200.0, "budget_total": 5000.0})
    assert "budget" in result["reason"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.project_status'`

- [ ] **Step 3: Write the status module**

Create `backend/app/services/project_status.py`:

```python
"""Project status rules and trend computation. Pure functions, no I/O."""

from datetime import datetime, timedelta

from app.utils.suivi_parser import parse_date

LEVEL_CRITICAL = "critical"
LEVEL_ATTENTION = "attention"
LEVEL_NOMINAL = "nominal"
LEVEL_UNKNOWN = "unknown"

TREND_WINDOW_DAYS = 7


def compute_status(
    *,
    metrics: dict | None,
    error: str | None,
    source_modified_at: datetime | None,
    previous_metrics: dict | None,
    stale_days: int,
    budget_warn_pct: int,
    now: datetime,
) -> dict:
    """Evaluate the status rules in order and return the first match.

    Returns {"level": one of the LEVEL_* constants, "reason": short English explanation}.
    A missing metric skips its rule rather than failing.
    """
    if error:
        return {"level": LEVEL_CRITICAL, "reason": f"read failed: {error}"}

    if not metrics:
        return {"level": LEVEL_UNKNOWN, "reason": "no source"}

    consumed = _number(metrics.get("budget_consomme"))
    total = _number(metrics.get("budget_total"))

    if consumed is not None and total is not None and total > 0:
        if consumed > total:
            return {"level": LEVEL_CRITICAL, "reason": "budget overrun"}

    milestone = parse_date(metrics.get("prochain_jalon"))
    if milestone is not None and milestone < now.date():
        return {"level": LEVEL_CRITICAL, "reason": f"milestone overdue since {milestone.isoformat()}"}

    if consumed is not None and total is not None and total > 0:
        if (consumed / total) * 100 >= budget_warn_pct:
            return {"level": LEVEL_ATTENTION, "reason": f"budget at {round(consumed / total * 100)}% of total"}

    if source_modified_at is not None:
        days = (now - source_modified_at).days
        if days >= stale_days:
            return {"level": LEVEL_ATTENTION, "reason": f"no update for {days} days"}

    current_progress = _number(metrics.get("avancement"))
    previous_progress = _number((previous_metrics or {}).get("avancement"))
    if current_progress is not None and previous_progress is not None:
        if current_progress <= previous_progress:
            return {"level": LEVEL_ATTENTION, "reason": "progress stalled"}

    return {"level": LEVEL_NOMINAL, "reason": "on track"}


def select_reference(history: list[tuple[datetime, dict | None]], latest_captured_at: datetime):
    """Pick the trend reference: newest snapshot at least TREND_WINDOW_DAYS older than the latest.

    Falls back to the oldest available snapshot. `history` is newest-first and excludes the latest.
    Returns the (captured_at, metrics) tuple, or None when there is no history.
    """
    if not history:
        return None
    cutoff = latest_captured_at - timedelta(days=TREND_WINDOW_DAYS)
    for captured_at, metrics in history:
        if captured_at <= cutoff:
            return (captured_at, metrics)
    return history[-1]


def compute_trends(metrics: dict | None, reference_metrics: dict | None) -> dict[str, float]:
    """Delta per numeric metric present in both snapshots. Non-numeric keys are ignored."""
    if not metrics or not reference_metrics:
        return {}
    trends: dict[str, float] = {}
    for key, value in metrics.items():
        current = _number(value)
        previous = _number(reference_metrics.get(key))
        if current is not None and previous is not None:
            trends[key] = round(current - previous, 4)
    return trends


def _number(value) -> float | None:
    """Coerce a metric to float, or None when it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_status.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Write the failing trends test**

Create `backend/tests/test_project_trends.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services.project_status import compute_trends, select_reference

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)


def test_compute_trends_numeric_only():
    current = {"avancement": 45.0, "budget_consomme": 8400.0, "responsable": "Fabien"}
    reference = {"avancement": 40.0, "budget_consomme": 8000.0, "responsable": "Sam"}
    assert compute_trends(current, reference) == {"avancement": 5.0, "budget_consomme": 400.0}


def test_compute_trends_ignores_keys_missing_on_one_side():
    assert compute_trends({"a": 2.0, "b": 1.0}, {"a": 1.0}) == {"a": 1.0}


def test_compute_trends_without_reference():
    assert compute_trends({"a": 1.0}, None) == {}
    assert compute_trends(None, {"a": 1.0}) == {}


def test_select_reference_prefers_snapshot_at_least_a_week_old():
    history = [
        (NOW - timedelta(days=2), {"avancement": 44.0}),
        (NOW - timedelta(days=8), {"avancement": 40.0}),
        (NOW - timedelta(days=30), {"avancement": 10.0}),
    ]
    captured_at, metrics = select_reference(history, NOW)
    assert captured_at == NOW - timedelta(days=8)
    assert metrics == {"avancement": 40.0}


def test_select_reference_falls_back_to_oldest():
    history = [
        (NOW - timedelta(days=1), {"avancement": 44.0}),
        (NOW - timedelta(days=3), {"avancement": 42.0}),
    ]
    captured_at, _ = select_reference(history, NOW)
    assert captured_at == NOW - timedelta(days=3)


def test_select_reference_without_history():
    assert select_reference([], NOW) is None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_trends.py -v`
Expected: PASS, 6 tests

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/project_status.py backend/tests/test_project_status.py backend/tests/test_project_trends.py
git commit -m "feat(projects): add status rules and trend computation"
```

---

### Task 4: Google Sheets/Drive read access

**Files:**
- Create: `backend/app/services/google_service.py`
- Create: `backend/tests/test_google_service.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: `app.utils.suivi_parser.parse_suivi_rows`, `app.utils.crypto.decrypt_value`
- Produces:
  - `parse_file_id(url: str) -> str | None`
  - `detect_kind(url: str) -> str` returning `doc` / `sheet` / `slide` / `drive` / `other`
  - `GoogleService(sa_key_json: str)` with `read_suivi(file_id) -> dict` and `get_modified_time(file_id) -> datetime | None`
  - `GoogleAccessError` raised on any credential or API failure

- [ ] **Step 1: Add the dependencies**

Append to `backend/requirements.txt`:

```
google-api-python-client==2.177.0
google-auth==2.40.3
```

Run: `cd backend && venv/bin/pip install -r requirements.txt`
Expected: both packages installed.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_google_service.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.google_service import (
    GoogleAccessError,
    GoogleService,
    detect_kind,
    parse_file_id,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://docs.google.com/spreadsheets/d/ABC123def/edit#gid=0", "ABC123def"),
        ("https://docs.google.com/document/d/XYZ789/edit", "XYZ789"),
        ("https://drive.google.com/file/d/FILE42/view?usp=sharing", "FILE42"),
        ("https://drive.google.com/open?id=OPEN99", "OPEN99"),
        ("https://example.com/not-google", None),
        ("", None),
    ],
)
def test_parse_file_id(url, expected):
    assert parse_file_id(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://docs.google.com/spreadsheets/d/A/edit", "sheet"),
        ("https://docs.google.com/document/d/A/edit", "doc"),
        ("https://docs.google.com/presentation/d/A/edit", "slide"),
        ("https://drive.google.com/file/d/A/view", "drive"),
        ("https://example.com/x", "other"),
    ],
)
def test_detect_kind(url, expected):
    assert detect_kind(url) == expected


def test_read_suivi_parses_rows():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["avancement", "72"], ["budget_total", "12000"]]
    }
    service._sheets = sheets

    assert service.read_suivi("ABC") == {"avancement": 72.0, "budget_total": 12000.0}


def test_read_suivi_empty_tab_returns_empty_dict():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}
    service._sheets = sheets

    assert service.read_suivi("ABC") == {}


def test_read_suivi_wraps_api_errors():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = RuntimeError(
        "Unable to parse range: SUIVI!A:B"
    )
    service._sheets = sheets

    with pytest.raises(GoogleAccessError) as exc:
        service.read_suivi("ABC")
    assert "SUIVI" in str(exc.value)


def test_get_modified_time_parses_rfc3339():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.get.return_value.execute.return_value = {
        "modifiedTime": "2026-08-17T09:12:44.000Z"
    }
    service._drive = drive

    assert service.get_modified_time("ABC") == datetime(2026, 8, 17, 9, 12, 44, tzinfo=timezone.utc)


def test_invalid_service_account_key_raises():
    with pytest.raises(GoogleAccessError):
        GoogleService("{not valid json")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_google_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.google_service'`

- [ ] **Step 4: Write the service**

Create `backend/app/services/google_service.py`:

```python
"""Read-only Google Sheets/Drive access through a service account."""

import json
import re
from datetime import datetime, timezone

import structlog
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.utils.suivi_parser import parse_suivi_rows

log = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

SUIVI_RANGE = "SUIVI!A:B"

_FILE_ID_PATTERNS = [
    re.compile(r"/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
]


class GoogleAccessError(Exception):
    """Raised when credentials are invalid or a Google API call fails."""


def parse_file_id(url: str) -> str | None:
    """Extract the Google file id from a Docs/Sheets/Slides/Drive URL."""
    if not url:
        return None
    for pattern in _FILE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def detect_kind(url: str) -> str:
    """Classify a Google URL for display purposes."""
    if "/spreadsheets/" in url:
        return "sheet"
    if "/document/" in url:
        return "doc"
    if "/presentation/" in url:
        return "slide"
    if "drive.google.com" in url:
        return "drive"
    return "other"


class GoogleService:
    """Thin wrapper over the Sheets and Drive APIs. One instance per refresh run."""

    def __init__(self, sa_key_json: str):
        try:
            info = json.loads(sa_key_json)
            credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as exc:
            raise GoogleAccessError(f"invalid service account key: {exc}") from exc

        self._sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def read_suivi(self, file_id: str) -> dict:
        """Read SUIVI!A:B and return the parsed metrics dict."""
        try:
            response = (
                self._sheets.spreadsheets()
                .values()
                .get(spreadsheetId=file_id, range=SUIVI_RANGE)
                .execute()
            )
        except Exception as exc:
            raise GoogleAccessError(f"cannot read {SUIVI_RANGE} of {file_id}: {exc}") from exc
        return parse_suivi_rows(response.get("values", []))

    def get_modified_time(self, file_id: str) -> datetime | None:
        """Return the Drive modifiedTime of a file, or None when absent."""
        try:
            response = self._drive.files().get(fileId=file_id, fields="modifiedTime").execute()
        except Exception as exc:
            raise GoogleAccessError(f"cannot read metadata of {file_id}: {exc}") from exc
        raw = response.get("modifiedTime")
        if not raw:
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_google_service.py -v`
Expected: PASS, 16 tests

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/google_service.py backend/tests/test_google_service.py backend/requirements.txt
git commit -m "feat(projects): add Google Sheets/Drive read access"
```

---

### Task 5: Project service — refresh, views and aggregates

**Files:**
- Create: `backend/app/services/project_service.py`
- Create: `backend/tests/test_project_service.py`

**Interfaces:**
- Consumes: `GoogleService`, `GoogleAccessError`, `parse_file_id`, `compute_status`, `compute_trends`, `select_reference`, models `Project`, `ProjectLink`, `ProjectSnapshot`, `Config`
- Produces:
  - `ProjectService.refresh_all(session) -> int` — number of projects refreshed
  - `ProjectService.refresh_one(session, project_id) -> bool`
  - `ProjectService.build_views(session, now=None) -> list[dict]`
  - `pending_decisions(views) -> list[dict]`
  - `budget_summary(views) -> dict`
  - Constant `SPARKLINE_POINTS = 30`

The Google client is synchronous; every call goes through `asyncio.to_thread` so the event loop is never blocked.

A view dict is the API contract consumed by the frontend:

```python
{
  "id": UUID, "name": str, "description": str | None,
  "position": int, "stale_days": int, "budget_warn_pct": int,
  "links": [{"id", "label", "url", "kind", "is_kpi_source", "position"}],
  "status": {"level": str, "reason": str},
  "metrics": dict | None, "trends": dict, "sparkline": [float],
  "captured_at": datetime | None, "source_modified_at": datetime | None,
  "error": str | None,
}
```

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_project_service.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import Config, Project, ProjectLink, ProjectSnapshot
from app.services.google_service import GoogleAccessError
from app.services.project_service import (
    ProjectService,
    budget_summary,
    pending_decisions,
)
from app.utils.crypto import encrypt_value

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)


async def _project_with_source(session, name="AVA", file_id="SHEET1"):
    project = Project(name=name)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    session.add(
        ProjectLink(
            project_id=project.id,
            label="Suivi",
            url=f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
            kind="sheet",
            file_id=file_id,
            is_kpi_source=True,
        )
    )
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}')))
    await session.commit()
    return project


def _fake_google(metrics=None, modified_at=None, error=None):
    google = MagicMock()
    if error:
        google.read_suivi.side_effect = GoogleAccessError(error)
    else:
        google.read_suivi.return_value = metrics or {}
    google.get_modified_time.return_value = modified_at
    return google


async def test_refresh_all_writes_one_snapshot_per_project(session):
    project = await _project_with_source(session)
    google = _fake_google({"avancement": 72.0}, NOW - timedelta(days=1))

    with patch("app.services.project_service.GoogleService", return_value=google):
        count = await ProjectService.refresh_all(session)

    assert count == 1
    snapshots = (await session.execute(select(ProjectSnapshot))).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].metrics == {"avancement": 72.0}
    assert snapshots[0].project_id == project.id
    assert snapshots[0].error is None


async def test_refresh_all_skips_projects_without_kpi_source(session):
    session.add(Project(name="No source"))
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}')))
    await session.commit()

    with patch("app.services.project_service.GoogleService", return_value=_fake_google()):
        count = await ProjectService.refresh_all(session)

    assert count == 0
    assert (await session.execute(select(ProjectSnapshot))).scalars().all() == []


async def test_refresh_all_records_read_errors(session):
    await _project_with_source(session)
    google = _fake_google(error="permission denied")

    with patch("app.services.project_service.GoogleService", return_value=google):
        await ProjectService.refresh_all(session)

    snapshot = (await session.execute(select(ProjectSnapshot))).scalar_one()
    assert snapshot.metrics is None
    assert "permission denied" in snapshot.error


async def test_refresh_all_without_google_key_raises(session):
    await _project_with_source(session)
    config = (await session.execute(select(Config))).scalar_one()
    config.google_sa_key = ""
    await session.commit()

    with pytest.raises(GoogleAccessError):
        await ProjectService.refresh_all(session)


async def test_build_views_exposes_status_trends_and_sparkline(session):
    project = await _project_with_source(session)
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=NOW - timedelta(days=8),
            metrics={"avancement": 40.0},
            source_modified_at=NOW - timedelta(days=8),
        )
    )
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=NOW,
            metrics={"avancement": 48.0},
            source_modified_at=NOW - timedelta(days=1),
        )
    )
    await session.commit()

    views = await ProjectService.build_views(session, now=NOW)

    assert len(views) == 1
    view = views[0]
    assert view["name"] == "AVA"
    assert view["status"]["level"] == "nominal"
    assert view["trends"]["avancement"] == 8.0
    assert view["sparkline"] == [40.0, 48.0]
    assert view["captured_at"] == NOW
    assert len(view["links"]) == 1


async def test_build_views_without_snapshot_is_unknown(session):
    await _project_with_source(session)

    views = await ProjectService.build_views(session, now=NOW)

    assert views[0]["status"]["level"] == "unknown"
    assert views[0]["metrics"] is None
    assert views[0]["sparkline"] == []


def test_pending_decisions_collects_non_empty_values():
    views = [
        {"id": "1", "name": "A", "metrics": {"decision_attendue": "Arbitrer X"}},
        {"id": "2", "name": "B", "metrics": {"decision_attendue": "  "}},
        {"id": "3", "name": "C", "metrics": {"avancement": 10.0}},
        {"id": "4", "name": "D", "metrics": None},
    ]
    assert pending_decisions(views) == [
        {"project_id": "1", "project_name": "A", "decision": "Arbitrer X"}
    ]


def test_budget_summary_sums_latest_metrics():
    views = [
        {"metrics": {"budget_consomme": 8400.0, "budget_total": 12000.0}},
        {"metrics": {"budget_consomme": 3100.0, "budget_total": 3000.0}},
        {"metrics": {"avancement": 10.0}},
        {"metrics": None},
    ]
    assert budget_summary(views) == {
        "consumed": 11500.0,
        "total": 15000.0,
        "remaining": 3500.0,
        "projects_counted": 2,
    }


def test_budget_summary_without_data():
    assert budget_summary([{"metrics": None}]) == {
        "consumed": 0.0,
        "total": 0.0,
        "remaining": 0.0,
        "projects_counted": 0,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.project_service'`

- [ ] **Step 3: Write the service**

Create `backend/app/services/project_service.py`:

```python
"""Project refresh orchestration and read models."""

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Config, Project, ProjectSnapshot
from app.services.google_service import GoogleAccessError, GoogleService
from app.services.project_status import compute_status, compute_trends, select_reference
from app.utils.crypto import decrypt_value

log = structlog.get_logger()

SPARKLINE_POINTS = 30
SPARKLINE_METRIC = "avancement"


class ProjectService:
    @staticmethod
    async def refresh_all(session: AsyncSession) -> int:
        """Read every project's KPI source and write one snapshot each. Returns the count."""
        google = await ProjectService._build_google(session)
        projects = await ProjectService._list_projects(session)

        refreshed = 0
        for project in projects:
            if await ProjectService._snapshot(session, project, google):
                refreshed += 1

        await session.commit()
        log.info("Projects refreshed", count=refreshed)
        return refreshed

    @staticmethod
    async def refresh_one(session: AsyncSession, project_id: uuid.UUID) -> bool:
        """Refresh a single project. Returns False when it has no KPI source."""
        google = await ProjectService._build_google(session)
        result = await session.execute(
            select(Project).options(selectinload(Project.links)).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return False

        written = await ProjectService._snapshot(session, project, google)
        await session.commit()
        return written

    @staticmethod
    async def build_views(session: AsyncSession, now: datetime | None = None) -> list[dict]:
        """Assemble one view dict per project: status, metrics, trends and sparkline."""
        now = now or datetime.now(timezone.utc)
        projects = await ProjectService._list_projects(session)

        views = []
        for project in projects:
            snapshots = await ProjectService._recent_snapshots(session, project.id)
            views.append(ProjectService._build_view(project, snapshots, now))
        return views

    @staticmethod
    async def _build_google(session: AsyncSession) -> GoogleService:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.google_sa_key:
            raise GoogleAccessError("Google service account key not configured")
        return GoogleService(decrypt_value(config.google_sa_key))

    @staticmethod
    async def _list_projects(session: AsyncSession) -> list[Project]:
        result = await session.execute(
            select(Project).options(selectinload(Project.links)).order_by(Project.position, Project.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _recent_snapshots(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectSnapshot]:
        """Newest first, capped at SPARKLINE_POINTS."""
        result = await session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .order_by(ProjectSnapshot.captured_at.desc())
            .limit(SPARKLINE_POINTS)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _snapshot(session: AsyncSession, project: Project, google: GoogleService) -> bool:
        """Read the KPI source and add a snapshot. Returns False when there is no source."""
        source = next((link for link in project.links if link.is_kpi_source and link.file_id), None)
        if not source:
            return False

        metrics, modified_at, error = None, None, None
        try:
            # The Google client is blocking — keep it off the event loop.
            metrics = await asyncio.to_thread(google.read_suivi, source.file_id)
            modified_at = await asyncio.to_thread(google.get_modified_time, source.file_id)
        except GoogleAccessError as exc:
            error = str(exc)
            log.warning("Project source read failed", project=project.name, error=error)

        session.add(
            ProjectSnapshot(
                project_id=project.id,
                metrics=metrics,
                source_modified_at=modified_at,
                error=error,
            )
        )
        return True

    @staticmethod
    def _build_view(project: Project, snapshots: list[ProjectSnapshot], now: datetime) -> dict:
        latest = snapshots[0] if snapshots else None
        history = [(s.captured_at, s.metrics) for s in snapshots[1:]]
        reference = select_reference(history, latest.captured_at) if latest else None
        reference_metrics = reference[1] if reference else None

        status = compute_status(
            metrics=latest.metrics if latest else None,
            error=latest.error if latest else None,
            source_modified_at=latest.source_modified_at if latest else None,
            previous_metrics=reference_metrics,
            stale_days=project.stale_days,
            budget_warn_pct=project.budget_warn_pct,
            now=now,
        )

        sparkline = [
            value
            for value in (
                (s.metrics or {}).get(SPARKLINE_METRIC) for s in reversed(snapshots)
            )
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]

        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "position": project.position,
            "stale_days": project.stale_days,
            "budget_warn_pct": project.budget_warn_pct,
            "links": [
                {
                    "id": link.id,
                    "label": link.label,
                    "url": link.url,
                    "kind": link.kind,
                    "is_kpi_source": link.is_kpi_source,
                    "position": link.position,
                }
                for link in project.links
            ],
            "status": status,
            "metrics": latest.metrics if latest else None,
            "trends": compute_trends(latest.metrics if latest else None, reference_metrics),
            "sparkline": sparkline,
            "captured_at": latest.captured_at if latest else None,
            "source_modified_at": latest.source_modified_at if latest else None,
            "error": latest.error if latest else None,
        }


def pending_decisions(views: list[dict]) -> list[dict]:
    """Collect non-empty `decision_attendue` values across all project views."""
    decisions = []
    for view in views:
        raw = (view.get("metrics") or {}).get("decision_attendue")
        text = str(raw).strip() if raw is not None else ""
        if text:
            decisions.append(
                {
                    "project_id": view["id"],
                    "project_name": view["name"],
                    "decision": text,
                }
            )
    return decisions


def budget_summary(views: list[dict]) -> dict:
    """Sum consumed and total budget across projects that report both."""
    consumed = 0.0
    total = 0.0
    counted = 0
    for view in views:
        metrics = view.get("metrics") or {}
        project_consumed = metrics.get("budget_consomme")
        project_total = metrics.get("budget_total")
        if isinstance(project_consumed, (int, float)) and isinstance(project_total, (int, float)):
            consumed += float(project_consumed)
            total += float(project_total)
            counted += 1
    return {
        "consumed": consumed,
        "total": total,
        "remaining": total - consumed,
        "projects_counted": counted,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_project_service.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/project_service.py backend/tests/test_project_service.py
git commit -m "feat(projects): add refresh orchestration, views and aggregates"
```

---

### Task 6: Schemas and API routes

**Files:**
- Create: `backend/app/schemas/project.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `backend/app/routers/projects.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api_projects.py`

**Interfaces:**
- Consumes: `ProjectService.build_views`, `ProjectService.refresh_all`, `ProjectService.refresh_one`, `pending_decisions`, `budget_summary`, `parse_file_id`, `detect_kind`
- Produces: the `/api/v1/projects` endpoints listed in the spec; schemas `ProjectCreate`, `ProjectUpdate`, `ProjectView`, `ProjectDetail`, `ProjectLinkCreate`, `ProjectLinkUpdate`, `ProjectLinkRead`, `ProjectStatusRead`, `ProjectSnapshotRead`, `PendingDecision`, `BudgetSummary`, `RefreshResult`

**Route ordering matters:** `/refresh`, `/decisions`, `/summary` and `/links/{link_id}` MUST be declared before `/{project_id}`, otherwise FastAPI tries to parse those literals as a UUID and returns 422.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_projects.py`:

```python
import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, Project, ProjectLink, ProjectSnapshot

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


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_create_and_list_project(client):
    response = await client.post("/api/v1/projects", json={"name": "AVA Voice Agent"})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "AVA Voice Agent"
    assert created["stale_days"] == 14
    assert created["budget_warn_pct"] == 90

    listed = await client.get("/api/v1/projects")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["status"]["level"] == "unknown"
    assert body[0]["links"] == []


async def test_update_and_delete_project(client):
    created = (await client.post("/api/v1/projects", json={"name": "Tmp"})).json()

    updated = await client.put(
        f"/api/v1/projects/{created['id']}", json={"name": "Renamed", "stale_days": 7}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["stale_days"] == 7

    deleted = await client.delete(f"/api/v1/projects/{created['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/projects")).json() == []


async def test_add_link_derives_kind_and_file_id(client):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()

    response = await client.post(
        f"/api/v1/projects/{project['id']}/links",
        json={
            "label": "Suivi hebdo",
            "url": "https://docs.google.com/spreadsheets/d/SHEET42/edit#gid=0",
            "is_kpi_source": True,
        },
    )
    assert response.status_code == 201
    link = response.json()
    assert link["kind"] == "sheet"
    assert link["is_kpi_source"] is True

    listed = (await client.get("/api/v1/projects")).json()
    assert listed[0]["links"][0]["label"] == "Suivi hebdo"


async def test_delete_link(client):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()
    link = (
        await client.post(
            f"/api/v1/projects/{project['id']}/links",
            json={"label": "Doc", "url": "https://docs.google.com/document/d/D1/edit"},
        )
    ).json()

    response = await client.delete(f"/api/v1/projects/links/{link['id']}")
    assert response.status_code == 204
    assert (await client.get("/api/v1/projects")).json()[0]["links"] == []


async def test_decisions_and_summary_are_not_parsed_as_project_ids(client, setup_test_db):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()

    async with setup_test_db() as session:
        session.add(
            ProjectSnapshot(
                project_id=uuid.UUID(project["id"]),
                captured_at=datetime.now(timezone.utc),
                metrics={
                    "decision_attendue": "Arbitrer le contrat X",
                    "budget_consomme": 8400.0,
                    "budget_total": 12000.0,
                },
            )
        )
        await session.commit()

    decisions = await client.get("/api/v1/projects/decisions")
    assert decisions.status_code == 200
    assert decisions.json() == [
        {
            "project_id": project["id"],
            "project_name": "P",
            "decision": "Arbitrer le contrat X",
        }
    ]

    summary = await client.get("/api/v1/projects/summary")
    assert summary.status_code == 200
    assert summary.json() == {
        "consumed": 8400.0,
        "total": 12000.0,
        "remaining": 3600.0,
        "projects_counted": 1,
    }


async def test_refresh_endpoint_calls_the_service(client):
    with patch(
        "app.routers.projects.ProjectService.refresh_all", new=AsyncMock(return_value=3)
    ) as refresh:
        response = await client.post("/api/v1/projects/refresh")

    assert response.status_code == 200
    assert response.json() == {"refreshed": 3}
    refresh.assert_awaited_once()


async def test_refresh_reports_google_errors_as_400(client):
    from app.services.google_service import GoogleAccessError

    with patch(
        "app.routers.projects.ProjectService.refresh_all",
        new=AsyncMock(side_effect=GoogleAccessError("key not configured")),
    ):
        response = await client.post("/api/v1/projects/refresh")

    assert response.status_code == 400
    assert "key not configured" in response.json()["detail"]


async def test_project_detail_returns_history(client, setup_test_db):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()
    now = datetime.now(timezone.utc)

    async with setup_test_db() as session:
        session.add(
            ProjectSnapshot(project_id=uuid.UUID(project["id"]), captured_at=now, metrics={"avancement": 20.0})
        )
        session.add(
            ProjectSnapshot(
                project_id=uuid.UUID(project["id"]),
                captured_at=now - timedelta(days=9),
                metrics={"avancement": 10.0},
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/projects/{project['id']}")
    assert response.status_code == 200
    body = response.json()
    assert len(body["history"]) == 2
    assert body["trends"]["avancement"] == 10.0


async def test_get_unknown_project_returns_404(client):
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_projects.py -v`
Expected: FAIL — the `/api/v1/projects` routes return 404 because the router does not exist yet.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/project.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    position: int = 0
    stale_days: int = 14
    budget_warn_pct: int = 90


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    position: int | None = None
    stale_days: int | None = None
    budget_warn_pct: int | None = None


class ProjectLinkCreate(BaseModel):
    label: str
    url: str
    is_kpi_source: bool = False
    position: int = 0


class ProjectLinkUpdate(BaseModel):
    label: str | None = None
    url: str | None = None
    is_kpi_source: bool | None = None
    position: int | None = None


class ProjectLinkRead(BaseModel):
    id: uuid.UUID
    label: str
    url: str
    kind: str
    is_kpi_source: bool
    position: int

    model_config = {"from_attributes": True}


class ProjectStatusRead(BaseModel):
    level: str
    reason: str


class ProjectSnapshotRead(BaseModel):
    captured_at: datetime
    metrics: dict | None
    error: str | None

    model_config = {"from_attributes": True}


class ProjectView(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    position: int
    stale_days: int
    budget_warn_pct: int
    links: list[ProjectLinkRead]
    status: ProjectStatusRead
    metrics: dict | None
    trends: dict
    sparkline: list[float]
    captured_at: datetime | None
    source_modified_at: datetime | None
    error: str | None


class ProjectDetail(ProjectView):
    history: list[ProjectSnapshotRead]


class PendingDecision(BaseModel):
    project_id: uuid.UUID
    project_name: str
    decision: str


class BudgetSummary(BaseModel):
    consumed: float
    total: float
    remaining: float
    projects_counted: int


class RefreshResult(BaseModel):
    refreshed: int
```

- [ ] **Step 4: Export the schemas**

In `backend/app/schemas/__init__.py`, add the import line after the chat import and extend `__all__`:

```python
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectView, ProjectDetail,
    ProjectLinkCreate, ProjectLinkUpdate, ProjectLinkRead,
    ProjectStatusRead, ProjectSnapshotRead,
    PendingDecision, BudgetSummary, RefreshResult,
)
```

```python
    "ProjectCreate", "ProjectUpdate", "ProjectView", "ProjectDetail",
    "ProjectLinkCreate", "ProjectLinkUpdate", "ProjectLinkRead",
    "ProjectStatusRead", "ProjectSnapshotRead",
    "PendingDecision", "BudgetSummary", "RefreshResult",
```

- [ ] **Step 5: Write the router**

Create `backend/app/routers/projects.py`:

```python
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_session
from app.models import Project, ProjectLink, ProjectSnapshot
from app.schemas import (
    BudgetSummary,
    PendingDecision,
    ProjectCreate,
    ProjectDetail,
    ProjectLinkCreate,
    ProjectLinkRead,
    ProjectLinkUpdate,
    ProjectUpdate,
    ProjectView,
    RefreshResult,
)
from app.services.google_service import GoogleAccessError, detect_kind, parse_file_id
from app.services.project_service import ProjectService, budget_summary, pending_decisions

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


# --- Collection routes -------------------------------------------------------
# Literal paths MUST stay above /{project_id}, otherwise FastAPI parses them as a UUID.


@router.get("", response_model=list[ProjectView])
async def list_projects(session: AsyncSession = Depends(get_async_session)):
    return await ProjectService.build_views(session)


@router.post("", response_model=ProjectView, status_code=201)
async def create_project(data: ProjectCreate, session: AsyncSession = Depends(get_async_session)):
    project = Project(**data.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)

    views = await ProjectService.build_views(session)
    return next(view for view in views if view["id"] == project.id)


@router.get("/decisions", response_model=list[PendingDecision])
async def list_decisions(session: AsyncSession = Depends(get_async_session)):
    return pending_decisions(await ProjectService.build_views(session))


@router.get("/summary", response_model=BudgetSummary)
async def get_summary(session: AsyncSession = Depends(get_async_session)):
    return budget_summary(await ProjectService.build_views(session))


@router.post("/refresh", response_model=RefreshResult)
async def refresh_projects(session: AsyncSession = Depends(get_async_session)):
    try:
        refreshed = await ProjectService.refresh_all(session)
    except GoogleAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RefreshResult(refreshed=refreshed)


# --- Link routes (also literal, keep above /{project_id}) --------------------


@router.put("/links/{link_id}", response_model=ProjectLinkRead)
async def update_link(
    link_id: uuid.UUID, data: ProjectLinkUpdate, session: AsyncSession = Depends(get_async_session)
):
    link = await session.get(ProjectLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(link, field, value)
    if data.url is not None:
        link.kind = detect_kind(data.url)
        link.file_id = parse_file_id(data.url)

    await session.commit()
    await session.refresh(link)
    return link


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    link = await session.get(ProjectLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await session.delete(link)
    await session.commit()


# --- Single-project routes ---------------------------------------------------


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    views = await ProjectService.build_views(session)
    view = next((v for v in views if v["id"] == project_id), None)
    if not view:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await session.execute(
        select(ProjectSnapshot)
        .where(ProjectSnapshot.project_id == project_id)
        .order_by(ProjectSnapshot.captured_at.desc())
    )
    return {**view, "history": list(result.scalars().all())}


@router.put("/{project_id}", response_model=ProjectView)
async def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, session: AsyncSession = Depends(get_async_session)
):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await session.commit()

    views = await ProjectService.build_views(session)
    return next(view for view in views if view["id"] == project_id)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/refresh", response_model=RefreshResult)
async def refresh_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    try:
        written = await ProjectService.refresh_one(session, project_id)
    except GoogleAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RefreshResult(refreshed=1 if written else 0)


@router.post("/{project_id}/links", response_model=ProjectLinkRead, status_code=201)
async def add_link(
    project_id: uuid.UUID, data: ProjectLinkCreate, session: AsyncSession = Depends(get_async_session)
):
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    link = ProjectLink(
        project_id=project_id,
        label=data.label,
        url=data.url,
        kind=detect_kind(data.url),
        file_id=parse_file_id(data.url),
        is_kpi_source=data.is_kpi_source,
        position=data.position,
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link
```

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, add the import next to the other routers:

```python
from app.routers import projects as projects_router
```

and the registration after `chat_router`:

```python
app.include_router(projects_router.router)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_projects.py -v`
Expected: PASS, 9 tests

- [ ] **Step 8: Run the whole backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: PASS, no regression in the existing tests.

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/project.py backend/app/schemas/__init__.py backend/app/routers/projects.py backend/app/main.py backend/tests/test_api_projects.py
git commit -m "feat(projects): add projects API"
```

---

### Task 7: Google key in Config and the daily refresh cron

**Files:**
- Modify: `backend/app/schemas/config.py`
- Modify: `backend/app/routers/config.py`
- Modify: `backend/app/services/scheduler_service.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api_config_google.py`

**Interfaces:**
- Consumes: `ProjectService.refresh_all`, `Config.google_sa_key`, `Config.projects_cron`
- Produces: `scheduler_service.set_projects_job(cron_expr)`; `ConfigRead.google_sa_key_set: bool`; `ConfigRead.projects_cron: str`; `ConfigUpdate.google_sa_key`, `ConfigUpdate.projects_cron`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_config_google.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, Config
from app.utils.crypto import decrypt_value

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


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_google_key_is_encrypted_and_never_returned(client, setup_test_db):
    with patch("app.routers.config.scheduler_service"):
        response = await client.put(
            "/api/v1/config", json={"google_sa_key": '{"type": "service_account"}'}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["google_sa_key_set"] is True
    assert "google_sa_key" not in body

    async with setup_test_db() as session:
        config = (await session.execute(select(Config))).scalar_one()
        assert config.google_sa_key != '{"type": "service_account"}'
        assert decrypt_value(config.google_sa_key) == '{"type": "service_account"}'


async def test_default_projects_cron_is_exposed(client):
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["projects_cron"] == "0 6 * * *"
    assert response.json()["google_sa_key_set"] is False


async def test_changing_cron_reschedules_the_job(client):
    with patch("app.routers.config.scheduler_service") as scheduler:
        response = await client.put("/api/v1/config", json={"projects_cron": "30 7 * * 1-5"})

    assert response.status_code == 200
    assert response.json()["projects_cron"] == "30 7 * * 1-5"
    scheduler.set_projects_job.assert_called_once_with("30 7 * * 1-5")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_config_google.py -v`
Expected: FAIL — `ConfigRead` has no `google_sa_key_set` field.

- [ ] **Step 3: Extend the config schemas**

Replace `backend/app/schemas/config.py` with:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ConfigRead(BaseModel):
    id: uuid.UUID
    llm_provider: str
    llm_model: str
    api_key_set: bool  # never expose the key, just whether it's set
    google_sa_key_set: bool  # same rule for the Google service account key
    projects_cron: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    api_key: str | None = None  # plaintext, will be encrypted before storage
    google_sa_key: str | None = None  # plaintext JSON, will be encrypted before storage
    projects_cron: str | None = None
```

- [ ] **Step 4: Update the config router**

Replace `backend/app/routers/config.py` with:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Config
from app.schemas import ConfigRead, ConfigUpdate
from app.services.scheduler_service import scheduler_service
from app.utils.crypto import encrypt_value

router = APIRouter(prefix="/api/v1/config", tags=["config"])


async def _get_or_create_config(session: AsyncSession) -> Config:
    result = await session.execute(select(Config).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        config = Config()
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


def _to_read(config: Config) -> ConfigRead:
    return ConfigRead(
        id=config.id,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
        api_key_set=bool(config.api_key),
        google_sa_key_set=bool(config.google_sa_key),
        projects_cron=config.projects_cron,
        updated_at=config.updated_at,
    )


@router.get("", response_model=ConfigRead)
async def get_config(session: AsyncSession = Depends(get_async_session)):
    return _to_read(await _get_or_create_config(session))


@router.put("", response_model=ConfigRead)
async def update_config(data: ConfigUpdate, session: AsyncSession = Depends(get_async_session)):
    config = await _get_or_create_config(session)
    if data.llm_provider is not None:
        config.llm_provider = data.llm_provider
    if data.llm_model is not None:
        config.llm_model = data.llm_model
    if data.api_key is not None:
        config.api_key = encrypt_value(data.api_key)
    if data.google_sa_key is not None:
        config.google_sa_key = encrypt_value(data.google_sa_key)

    cron_changed = data.projects_cron is not None and data.projects_cron != config.projects_cron
    if data.projects_cron is not None:
        config.projects_cron = data.projects_cron

    await session.commit()
    await session.refresh(config)

    if cron_changed:
        scheduler_service.set_projects_job(config.projects_cron)

    return _to_read(config)
```

- [ ] **Step 5: Add the scheduler job**

In `backend/app/services/scheduler_service.py`, add this callback after `_execute_prompt_job`:

```python
async def _execute_projects_refresh():
    """Callback executed by APScheduler to refresh every project's indicators."""
    from app.database import async_session
    from app.services.project_service import ProjectService

    log.info("Projects refresh triggered")
    try:
        async with async_session() as session:
            count = await ProjectService.refresh_all(session)
        log.info("Projects refresh completed", count=count)
    except Exception as exc:
        log.error("Projects refresh failed", error=str(exc))
```

and this method inside `SchedulerService`, after `reschedule_job`:

```python
    PROJECTS_JOB_ID = "projects_refresh"

    def set_projects_job(self, cron_expr: str):
        """Create or reschedule the daily projects refresh."""
        self.scheduler.add_job(
            _execute_projects_refresh,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=self.PROJECTS_JOB_ID,
            replace_existing=True,
        )
        log.info("Projects job scheduled", cron=cron_expr)
```

- [ ] **Step 6: Register the job at startup**

In `backend/app/main.py`, inside `lifespan`, add this block right after the cron restore loop and before the sipp-stress auto-registration:

```python
    # Schedule the daily projects refresh from the stored cron expression
    try:
        async with async_session() as session:
            from app.models import Config

            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            cron_expr = config.projects_cron if config else "0 6 * * *"
            scheduler_service.set_projects_job(cron_expr)
            log.info("Projects refresh scheduled", cron=cron_expr)
    except Exception as exc:
        log.error("Failed to schedule projects refresh", error=str(exc))
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_config_google.py tests/test_api_config.py -v`
Expected: PASS. If `test_api_config.py` asserts the exact shape of the config payload, update those assertions to include `google_sa_key_set` and `projects_cron`.

- [ ] **Step 8: Run the whole backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/config.py backend/app/routers/config.py backend/app/services/scheduler_service.py backend/app/main.py backend/tests/test_api_config_google.py backend/tests/test_api_config.py
git commit -m "feat(projects): store Google service account key and schedule daily refresh"
```

---

### Task 8: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: the `/api/v1/projects` and `/api/v1/config` endpoints from Tasks 6 and 7
- Produces: types `ProjectLink`, `ProjectStatus`, `Project`, `ProjectDetail`, `PendingDecision`, `BudgetSummary`; functions `listProjects`, `getProject`, `createProject`, `updateProject`, `deleteProject`, `addProjectLink`, `updateProjectLink`, `deleteProjectLink`, `refreshProjects`, `refreshProject`, `listDecisions`, `getBudgetSummary`

- [ ] **Step 1: Add the types and endpoints**

Append to `frontend/src/lib/api.ts`:

```ts
// Projects
export type ProjectStatusLevel = "critical" | "attention" | "nominal" | "unknown";

export interface ProjectStatus {
  level: ProjectStatusLevel;
  reason: string;
}

export interface ProjectLink {
  id: string;
  label: string;
  url: string;
  kind: "doc" | "sheet" | "slide" | "drive" | "other";
  is_kpi_source: boolean;
  position: number;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  position: number;
  stale_days: number;
  budget_warn_pct: number;
  links: ProjectLink[];
  status: ProjectStatus;
  metrics: Record<string, number | string> | null;
  trends: Record<string, number>;
  sparkline: number[];
  captured_at: string | null;
  source_modified_at: string | null;
  error: string | null;
}

export interface ProjectSnapshot {
  captured_at: string;
  metrics: Record<string, number | string> | null;
  error: string | null;
}

export interface ProjectDetail extends Project {
  history: ProjectSnapshot[];
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  position?: number;
  stale_days?: number;
  budget_warn_pct?: number;
}

export interface ProjectLinkCreate {
  label: string;
  url: string;
  is_kpi_source?: boolean;
  position?: number;
}

export interface PendingDecision {
  project_id: string;
  project_name: string;
  decision: string;
}

export interface BudgetSummary {
  consumed: number;
  total: number;
  remaining: number;
  projects_counted: number;
}

export const listProjects = () => request<Project[]>("/projects");
export const getProject = (id: string) => request<ProjectDetail>(`/projects/${id}`);
export const createProject = (data: ProjectCreate) =>
  request<Project>("/projects", { method: "POST", body: JSON.stringify(data) });
export const updateProject = (id: string, data: Partial<ProjectCreate>) =>
  request<Project>(`/projects/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteProject = (id: string) =>
  request<void>(`/projects/${id}`, { method: "DELETE" });
export const addProjectLink = (projectId: string, data: ProjectLinkCreate) =>
  request<ProjectLink>(`/projects/${projectId}/links`, { method: "POST", body: JSON.stringify(data) });
export const updateProjectLink = (linkId: string, data: Partial<ProjectLinkCreate>) =>
  request<ProjectLink>(`/projects/links/${linkId}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteProjectLink = (linkId: string) =>
  request<void>(`/projects/links/${linkId}`, { method: "DELETE" });
export const refreshProjects = () =>
  request<{ refreshed: number }>("/projects/refresh", { method: "POST" });
export const refreshProject = (id: string) =>
  request<{ refreshed: number }>(`/projects/${id}/refresh`, { method: "POST" });
export const listDecisions = () => request<PendingDecision[]>("/projects/decisions");
export const getBudgetSummary = () => request<BudgetSummary>("/projects/summary");
```

- [ ] **Step 2: Extend the Config type**

In `frontend/src/lib/api.ts`, find the `Config` interface and add the two fields returned by Task 7:

```ts
  google_sa_key_set: boolean;
  projects_cron: string;
```

and add to the `ConfigUpdate` interface:

```ts
  google_sa_key?: string;
  projects_cron?: string;
```

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build`
Expected: `tsc -b` reports no error and vite writes `dist/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(projects): add projects API client"
```

---

### Task 9: Projects dashboard page (read-only)

**Files:**
- Create: `frontend/src/components/Projects/StatusDot.tsx`
- Create: `frontend/src/components/Projects/Sparkline.tsx`
- Create: `frontend/src/components/Projects/ProjectCard.tsx`
- Create: `frontend/src/components/Projects/DecisionsPanel.tsx`
- Create: `frontend/src/components/Projects/BudgetSummary.tsx`
- Create: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/TabNav.tsx`

**Interfaces:**
- Consumes: everything exported in Task 8
- Produces: route `/projects`; components `StatusDot`, `Sparkline`, `ProjectCard`, `DecisionsPanel`, `BudgetSummaryPanel`

- [ ] **Step 1: Create the status dot**

Create `frontend/src/components/Projects/StatusDot.tsx`:

```tsx
import type { ProjectStatus, ProjectStatusLevel } from "../../lib/api";

const COLORS: Record<ProjectStatusLevel, string> = {
  critical: "var(--error)",
  attention: "var(--warning)",
  nominal: "var(--success)",
  unknown: "var(--text-muted)",
};

const LABELS: Record<ProjectStatusLevel, string> = {
  critical: "Critical",
  attention: "Attention",
  nominal: "On track",
  unknown: "No source",
};

export function StatusDot({ status }: { status: ProjectStatus }) {
  const color = COLORS[status.level];
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium" title={status.reason}>
      <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <span style={{ color }}>{LABELS[status.level]}</span>
    </span>
  );
}
```

- [ ] **Step 2: Create the sparkline**

Create `frontend/src/components/Projects/Sparkline.tsx`:

```tsx
export function Sparkline({
  values,
  width = 96,
  height = 24,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const points = values
    .map((value, index) => {
      const x = index * step;
      const y = height - ((value - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
```

- [ ] **Step 3: Create the project card**

Create `frontend/src/components/Projects/ProjectCard.tsx`:

```tsx
import type { Project } from "../../lib/api";
import { Sparkline } from "./Sparkline";
import { StatusDot } from "./StatusDot";

// Rendered by DecisionsPanel instead of the metric grid.
const HIDDEN_METRICS = new Set(["decision_attendue"]);
const BUDGET_KEYS = new Set(["budget_consomme", "budget_total"]);

function formatNumber(value: number): string {
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function Trend({ delta }: { delta: number | undefined }) {
  if (delta === undefined || delta === 0) return null;
  const up = delta > 0;
  return (
    <span className="ml-1.5 text-xs" style={{ color: up ? "var(--success)" : "var(--error)" }}>
      {up ? "▲" : "▼"} {formatNumber(Math.abs(delta))}
    </span>
  );
}

function relativeDate(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function ProjectCard({ project }: { project: Project }) {
  const metrics = project.metrics ?? {};
  const consumed = metrics.budget_consomme;
  const total = metrics.budget_total;
  const extraKeys = Object.keys(metrics).filter(
    (key) => !HIDDEN_METRICS.has(key) && !BUDGET_KEYS.has(key) && key !== "avancement",
  );

  return (
    <div className="card p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3
            className="text-base font-semibold"
            style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}
          >
            {project.name}
          </h3>
          {project.description && (
            <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
              {project.description}
            </p>
          )}
        </div>
        <StatusDot status={project.status} />
      </div>

      {project.error && (
        <p className="mb-3 text-xs" style={{ color: "var(--error)" }}>
          Read failed — showing last known values from {relativeDate(project.captured_at)}.
        </p>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        {typeof metrics.avancement === "number" && (
          <div>
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Progress
            </span>
            <div className="text-sm" style={{ color: "var(--text-primary)" }}>
              {formatNumber(metrics.avancement)}%
              <Trend delta={project.trends.avancement} />
            </div>
          </div>
        )}

        {typeof consumed === "number" && typeof total === "number" && (
          <div>
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Budget
            </span>
            <div className="text-sm" style={{ color: "var(--text-primary)" }}>
              {formatNumber(consumed)} / {formatNumber(total)}
              <Trend delta={project.trends.budget_consomme} />
            </div>
          </div>
        )}

        {project.sparkline.length > 1 && <Sparkline values={project.sparkline} />}
      </div>

      {extraKeys.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1">
          {extraKeys.map((key) => (
            <span key={key} className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {humanize(key)}:{" "}
              <span style={{ color: "var(--text-primary)" }}>
                {typeof metrics[key] === "number" ? formatNumber(metrics[key] as number) : String(metrics[key])}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {project.links.map((link) => (
          <a
            key={link.id}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded px-2 py-1 text-xs transition-colors"
            style={{ backgroundColor: "var(--bg-elevated)", color: "var(--text-secondary)" }}
            title={link.is_kpi_source ? "KPI source" : link.url}
          >
            {link.label}
            {link.is_kpi_source ? " *" : ""}
          </a>
        ))}
        {project.links.length === 0 && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            No links yet
          </span>
        )}
      </div>

      <p className="mt-3 text-xs" style={{ color: "var(--text-muted)" }}>
        Last read {relativeDate(project.captured_at)}
        {project.source_modified_at && ` · file modified ${relativeDate(project.source_modified_at)}`}
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Create the decisions panel**

Create `frontend/src/components/Projects/DecisionsPanel.tsx`:

```tsx
import type { PendingDecision } from "../../lib/api";

export function DecisionsPanel({ decisions }: { decisions: PendingDecision[] }) {
  if (decisions.length === 0) return null;

  return (
    <div className="card p-5" style={{ borderColor: "var(--warning)" }}>
      <h3
        className="mb-3 text-sm font-semibold uppercase tracking-wider"
        style={{ color: "var(--warning)" }}
      >
        Pending decisions ({decisions.length})
      </h3>
      <ul className="grid gap-2">
        {decisions.map((decision) => (
          <li key={decision.project_id} className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span style={{ color: "var(--text-muted)" }}>{decision.project_name} — </span>
            {decision.decision}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: Create the budget summary**

Create `frontend/src/components/Projects/BudgetSummary.tsx`:

```tsx
import type { BudgetSummary } from "../../lib/api";

function format(value: number): string {
  return Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(0);
}

export function BudgetSummaryPanel({ summary }: { summary: BudgetSummary }) {
  if (summary.projects_counted === 0) return null;

  const ratio = summary.total > 0 ? Math.min(summary.consumed / summary.total, 1) : 0;
  const over = summary.consumed > summary.total;

  return (
    <div className="card p-5">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          Consolidated budget
        </h3>
        <span className="text-sm" style={{ color: "var(--text-primary)" }}>
          {format(summary.consumed)} / {format(summary.total)}
          <span style={{ color: "var(--text-muted)" }}> · {format(summary.remaining)} left</span>
        </span>
      </div>
      <div className="h-1.5 w-full rounded" style={{ backgroundColor: "var(--bg-elevated)" }}>
        <div
          className="h-1.5 rounded"
          style={{
            width: `${ratio * 100}%`,
            backgroundColor: over ? "var(--error)" : "var(--accent)",
          }}
        />
      </div>
      <p className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>
        Across {summary.projects_counted} project{summary.projects_counted !== 1 ? "s" : ""} reporting a budget
      </p>
    </div>
  );
}
```

- [ ] **Step 6: Create the page**

Create `frontend/src/pages/ProjectsPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { getBudgetSummary, listDecisions, listProjects } from "../lib/api";
import { BudgetSummaryPanel } from "../components/Projects/BudgetSummary";
import { DecisionsPanel } from "../components/Projects/DecisionsPanel";
import { ProjectCard } from "../components/Projects/ProjectCard";
import { Spinner } from "../components/ui/Spinner";

export function ProjectsPage() {
  const { data: projects = [], isLoading } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: decisions = [] } = useQuery({ queryKey: ["project-decisions"], queryFn: listDecisions });
  const { data: summary } = useQuery({ queryKey: ["project-summary"], queryFn: getBudgetSummary });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <DecisionsPanel decisions={decisions} />
      {summary && <BudgetSummaryPanel summary={summary} />}

      {projects.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          No project yet.
        </p>
      ) : (
        <div className="grid gap-4">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Register the route**

In `frontend/src/App.tsx`, add the import and the route:

```tsx
import { ProjectsPage } from "./pages/ProjectsPage";
```

```tsx
            <Route path="projects" element={<ProjectsPage />} />
```

- [ ] **Step 8: Add the nav tab**

In `frontend/src/components/Layout/TabNav.tsx`, add the entry to the `tabs` array, after Reports:

```tsx
  { to: "/projects", label: "Projects" },
```

- [ ] **Step 9: Verify build and lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: build succeeds, oxlint reports no error.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/Projects frontend/src/pages/ProjectsPage.tsx frontend/src/App.tsx frontend/src/components/Layout/TabNav.tsx
git commit -m "feat(projects): add projects dashboard page"
```

---

### Task 10: Project and link management, refresh button, Google key in Config

**Files:**
- Create: `frontend/src/components/Projects/ProjectForm.tsx`
- Create: `frontend/src/components/Projects/LinkForm.tsx`
- Create: `frontend/src/components/Config/GoogleConfig.tsx`
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/components/Projects/ProjectCard.tsx`
- Modify: `frontend/src/pages/ConfigPage.tsx`

**Interfaces:**
- Consumes: `createProject`, `updateProject`, `deleteProject`, `addProjectLink`, `deleteProjectLink`, `refreshProjects`, `getConfig`, `updateConfig`
- Produces: components `ProjectForm`, `LinkForm`, `GoogleConfig`; `ProjectCard` gains an optional `onManage` affordance

- [ ] **Step 1: Create the project form**

Create `frontend/src/components/Projects/ProjectForm.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createProject, updateProject, type Project } from "../../lib/api";

export function ProjectForm({ project, onDone }: { project?: Project; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [staleDays, setStaleDays] = useState(project?.stale_days ?? 14);
  const [budgetWarnPct, setBudgetWarnPct] = useState(project?.budget_warn_pct ?? 90);

  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        name,
        description: description || null,
        stale_days: staleDays,
        budget_warn_pct: budgetWarnPct,
      };
      return project ? updateProject(project.id, payload) : createProject(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onDone();
    },
  });

  return (
    <div className="card p-5">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {project ? "Edit project" : "New project"}
      </h3>
      <div className="grid gap-3">
        <input
          className="input-field"
          placeholder="Project name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <input
          className="input-field"
          placeholder="Description (optional)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <div className="flex gap-3">
          <label className="flex-1 text-xs" style={{ color: "var(--text-muted)" }}>
            Stale after (days)
            <input
              className="input-field mt-1"
              type="number"
              min={1}
              value={staleDays}
              onChange={(event) => setStaleDays(Number(event.target.value))}
            />
          </label>
          <label className="flex-1 text-xs" style={{ color: "var(--text-muted)" }}>
            Budget warning (%)
            <input
              className="input-field mt-1"
              type="number"
              min={1}
              max={100}
              value={budgetWarnPct}
              onChange={(event) => setBudgetWarnPct(Number(event.target.value))}
            />
          </label>
        </div>
        {mutation.isError && (
          <p className="text-xs" style={{ color: "var(--error)" }}>
            {(mutation.error as Error).message}
          </p>
        )}
        <div className="flex gap-2">
          <button className="btn-primary" disabled={!name || mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Saving..." : "Save"}
          </button>
          <button className="btn-secondary" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
```

`btn-primary`, `btn-secondary`, `input-field` and `card` are all defined in `frontend/src/index.css` (lines 58-150). Use them; do not add new styles.

- [ ] **Step 2: Create the link form**

Create `frontend/src/components/Projects/LinkForm.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addProjectLink, deleteProjectLink, type Project } from "../../lib/api";

export function LinkForm({ project, onDone }: { project: Project; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [isKpiSource, setIsKpiSource] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["projects"] });

  const addMutation = useMutation({
    mutationFn: () => addProjectLink(project.id, { label, url, is_kpi_source: isKpiSource }),
    onSuccess: () => {
      invalidate();
      setLabel("");
      setUrl("");
      setIsKpiSource(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (linkId: string) => deleteProjectLink(linkId),
    onSuccess: invalidate,
  });

  return (
    <div className="card p-5">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        Links — {project.name}
      </h3>

      <ul className="mb-4 grid gap-2">
        {project.links.map((link) => (
          <li key={link.id} className="flex items-center justify-between gap-3 text-sm">
            <span style={{ color: "var(--text-primary)" }}>
              {link.label}
              {link.is_kpi_source && (
                <span style={{ color: "var(--accent)" }}> · KPI source</span>
              )}
            </span>
            <button
              className="text-xs"
              style={{ color: "var(--error)" }}
              onClick={() => deleteMutation.mutate(link.id)}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="grid gap-3">
        <input
          className="input-field"
          placeholder="Label (e.g. Weekly tracking)"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <input
          className="input-field"
          placeholder="https://docs.google.com/spreadsheets/d/..."
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          <input
            type="checkbox"
            checked={isKpiSource}
            onChange={(event) => setIsKpiSource(event.target.checked)}
          />
          This Sheet carries the SUIVI tab (KPI source)
        </label>
        {addMutation.isError && (
          <p className="text-xs" style={{ color: "var(--error)" }}>
            {(addMutation.error as Error).message}
          </p>
        )}
        <div className="flex gap-2">
          <button
            className="btn-primary"
            disabled={!label || !url || addMutation.isPending}
            onClick={() => addMutation.mutate()}
          >
            Add link
          </button>
          <button className="btn-secondary" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire management and refresh into the page**

Replace `frontend/src/pages/ProjectsPage.tsx` with:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteProject,
  getBudgetSummary,
  listDecisions,
  listProjects,
  refreshProjects,
  type Project,
} from "../lib/api";
import { BudgetSummaryPanel } from "../components/Projects/BudgetSummary";
import { DecisionsPanel } from "../components/Projects/DecisionsPanel";
import { LinkForm } from "../components/Projects/LinkForm";
import { ProjectCard } from "../components/Projects/ProjectCard";
import { ProjectForm } from "../components/Projects/ProjectForm";
import { Spinner } from "../components/ui/Spinner";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [managingLinks, setManagingLinks] = useState<Project | null>(null);

  const { data: projects = [], isLoading } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: decisions = [] } = useQuery({ queryKey: ["project-decisions"], queryFn: listDecisions });
  const { data: summary } = useQuery({ queryKey: ["project-summary"], queryFn: getBudgetSummary });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["projects"] });
    queryClient.invalidateQueries({ queryKey: ["project-decisions"] });
    queryClient.invalidateQueries({ queryKey: ["project-summary"] });
  };

  const refreshMutation = useMutation({ mutationFn: refreshProjects, onSuccess: invalidateAll });
  const deleteMutation = useMutation({ mutationFn: deleteProject, onSuccess: invalidateAll });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <div className="flex items-center justify-between gap-3">
        <button className="btn-primary" onClick={() => setCreating(true)}>
          New project
        </button>
        <div className="flex items-center gap-3">
          {refreshMutation.isError && (
            <span className="text-xs" style={{ color: "var(--error)" }}>
              {(refreshMutation.error as Error).message}
            </span>
          )}
          <button
            className="btn-secondary"
            disabled={refreshMutation.isPending}
            onClick={() => refreshMutation.mutate()}
          >
            {refreshMutation.isPending ? "Refreshing..." : "Refresh now"}
          </button>
        </div>
      </div>

      {creating && <ProjectForm onDone={() => setCreating(false)} />}
      {editing && <ProjectForm project={editing} onDone={() => setEditing(null)} />}
      {managingLinks && <LinkForm project={managingLinks} onDone={() => setManagingLinks(null)} />}

      <DecisionsPanel decisions={decisions} />
      {summary && <BudgetSummaryPanel summary={summary} />}

      {projects.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          No project yet.
        </p>
      ) : (
        <div className="grid gap-4">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onEdit={() => setEditing(project)}
              onManageLinks={() => setManagingLinks(project)}
              onDelete={() => deleteMutation.mutate(project.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the management row to the card**

In `frontend/src/components/Projects/ProjectCard.tsx`, change the component signature and append a management row just before the closing `</div>` of the card:

```tsx
export function ProjectCard({
  project,
  onEdit,
  onManageLinks,
  onDelete,
}: {
  project: Project;
  onEdit?: () => void;
  onManageLinks?: () => void;
  onDelete?: () => void;
}) {
```

```tsx
      {(onEdit || onManageLinks || onDelete) && (
        <div className="mt-3 flex gap-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          {onEdit && (
            <button className="text-xs" style={{ color: "var(--text-secondary)" }} onClick={onEdit}>
              Edit
            </button>
          )}
          {onManageLinks && (
            <button className="text-xs" style={{ color: "var(--text-secondary)" }} onClick={onManageLinks}>
              Links
            </button>
          )}
          {onDelete && (
            <button className="text-xs" style={{ color: "var(--error)" }} onClick={onDelete}>
              Delete
            </button>
          )}
        </div>
      )}
```

Do NOT use `window.confirm` for the delete — a browser modal blocks the page. The button deletes directly; the project can be recreated.

- [ ] **Step 5: Create the Google config panel**

Create `frontend/src/components/Config/GoogleConfig.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "../../lib/api";
import { Spinner } from "../ui/Spinner";

export function GoogleConfig() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [saKey, setSaKey] = useState("");
  const [cron, setCron] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      updateConfig({
        google_sa_key: saKey || undefined,
        projects_cron: cron ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaKey("");
      setCron(null);
    },
  });

  return (
    <div className="card p-6">
      <h3
        className="mb-5 text-base font-semibold"
        style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}
      >
        Google Projects Access
      </h3>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="grid gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Service account key (JSON)
            </label>
            <textarea
              className="input-field"
              rows={4}
              placeholder={config?.google_sa_key_set ? "Key set — paste a new one to replace it" : '{"type": "service_account", ...}'}
              value={saKey}
              onChange={(event) => setSaKey(event.target.value)}
            />
            <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
              Share every project Sheet with this service account email, then keep the files private.
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Refresh schedule (cron)
            </label>
            <input
              className="input-field"
              value={cron ?? config?.projects_cron ?? "0 6 * * *"}
              onChange={(event) => setCron(event.target.value)}
            />
          </div>

          {mutation.isError && (
            <p className="text-xs" style={{ color: "var(--error)" }}>
              {(mutation.error as Error).message}
            </p>
          )}

          <button
            className="btn-primary"
            disabled={mutation.isPending || (!saKey && cron === null)}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Render it in the Config page**

In `frontend/src/pages/ConfigPage.tsx`, add the import and render `<GoogleConfig />` directly after `<LlmConfig />`:

```tsx
import { GoogleConfig } from "../components/Config/GoogleConfig";
```

- [ ] **Step 7: Verify build and lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: build succeeds, oxlint reports no error.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Projects frontend/src/components/Config/GoogleConfig.tsx frontend/src/pages/ProjectsPage.tsx frontend/src/pages/ConfigPage.tsx
git commit -m "feat(projects): manage projects, links and Google access from the UI"
```

---

### Task 11: End-to-end verification and documentation

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: everything built in Tasks 1-10
- Produces: nothing — this task proves the feature works and records it

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: all tests pass, including the pre-existing ones.

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && npm run build && npm run lint`
Expected: no TypeScript error, no lint error.

- [ ] **Step 3: Start the stack**

Run: `docker compose up --build -d postgres backend`
Then: `curl -s http://localhost:8000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 4: Verify the API end to end**

```bash
# Create a project
curl -s -X POST http://localhost:8000/api/v1/projects \
  -H 'Content-Type: application/json' \
  -d '{"name": "Tour De Control"}'
# Expected: 201 with a JSON project, status.level == "unknown"

# List projects
curl -s http://localhost:8000/api/v1/projects
# Expected: an array with one project, empty links

# The literal routes must not be parsed as UUIDs
curl -s http://localhost:8000/api/v1/projects/decisions
# Expected: []
curl -s http://localhost:8000/api/v1/projects/summary
# Expected: {"consumed":0.0,"total":0.0,"remaining":0.0,"projects_counted":0}

# Refresh without a Google key configured
curl -s -X POST http://localhost:8000/api/v1/projects/refresh
# Expected: 400 with detail "Google service account key not configured"
```

- [ ] **Step 5: Verify the cron is registered**

Run: `docker compose logs backend | grep "Projects refresh scheduled"`
Expected: one line showing `cron=0 6 * * *`.

- [ ] **Step 6: Manual UI check**

Open `http://localhost:3000/projects` with the frontend dev server running.
Expected: the Projects tab appears in the nav, the project card renders with a grey "No source" badge, "New project" and "Refresh now" work, and the Config page shows the Google Projects Access panel.

- [ ] **Step 7: Document the feature**

In `AGENTS.md`, add `Projects` to the frontend page list in the Repository Layout section, and add this bullet to the feature list in Project Overview:

```markdown
- **Projects**: director dashboard. Google Docs/Sheets links grouped by project, with indicators read daily from a `SUIVI` key/value tab in each project's Sheet through a Google service account, stored as snapshots for trend display.
```

- [ ] **Step 8: Commit**

```bash
git add AGENTS.md
git commit -m "docs: document the projects dashboard"
```

---

## Verification Summary

| Layer | Command | Expectation |
|---|---|---|
| Pure logic | `venv/bin/python -m pytest tests/test_suivi_parser.py tests/test_project_status.py tests/test_project_trends.py -v` | 45 tests pass, no I/O |
| Services | `venv/bin/python -m pytest tests/test_google_service.py tests/test_project_service.py -v` | 25 tests pass, Google mocked |
| API | `venv/bin/python -m pytest tests/test_api_projects.py tests/test_api_config_google.py -v` | 12 tests pass |
| Whole backend | `venv/bin/python -m pytest tests/ -v` | no regression |
| Frontend | `npm run build && npm run lint` | no TypeScript or lint error |
| End to end | Task 11 | curl checks and UI render as described |
