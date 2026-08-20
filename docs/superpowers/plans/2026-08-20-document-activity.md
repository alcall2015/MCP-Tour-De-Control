# Document Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Projects tab with an `Activity` tab that lists the Google Docs and Sheets inside one shared Drive folder, shows how many lines each gained or lost per day, and draws a GitHub-style contribution grid over the last 12 months.

**Architecture:** A daily cron walks one shared Drive folder, extracts each file's plain text, diffs it line-by-line against the copy stored from the previous run, and records two integers per file per day. Only the latest text is kept, so storage stays bounded while the history stays complete. The React page reads the database and never waits on Google.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, APScheduler 3, google-api-python-client, Python `difflib` (stdlib), React 19 + TanStack Query + Tailwind 4, hand-written inline SVG.

**Spec:** `docs/superpowers/specs/2026-08-20-document-activity-design.md`

## Global Constraints

- Business logic lives in `app/services/`; routers stay thin and declare `APIRouter(prefix="/api/v1/<resource>")`.
- Every new model MUST be exported from `app/models/__init__.py` — Alembic autogenerate depends on it. Every schema MUST be exported from `app/schemas/__init__.py`.
- Database changes require an Alembic migration; `PYTHONPATH=.` is mandatory for every alembic command. Current head before this plan: `aa2d4bae63d4`.
- Google scopes become exactly `https://www.googleapis.com/auth/spreadsheets.readonly` and `https://www.googleapis.com/auth/drive.readonly`.
- Every Google call is synchronous — production code MUST reach it through `asyncio.to_thread`.
- Every Google failure surfaces as `GoogleAccessError`; no raw third-party exception escapes to a caller.
- The service account key stays write-only through the API: only `google_sa_key_set: bool` and `google_sa_email` are ever returned.
- The scan is capped at **500 files**; when the cap is hit, `log.warning` states how many were skipped. Silent truncation is forbidden.
- A newly discovered file stores a baseline and writes **no** activity row.
- A file that leaves the folder is marked `is_present = False` and **keeps its activity history**.
- All frontend HTTP calls and shared interfaces go in `frontend/src/lib/api.ts` — no `fetch` in a component.
- **No emojis.** No colour outside the CSS custom properties in `frontend/src/index.css`: `--bg-void`, `--bg-panel`, `--bg-elevated`, `--border`, `--accent`, `--success`, `--error`, `--warning`, `--text-primary`, `--text-secondary`, `--text-muted`. No new CSS file, no new npm dependency.
- Never `window.confirm` / `alert` / `prompt` — a browser modal blocks the page. Deletes act directly.
- Code, comments and UI strings are in English.
- Backend tests need Postgres at `localhost:5432` (`mcp`/`mcp_secret`) with database `mcp_control_test`. No test performs a network call.
- Conventional Commits.

## File Structure

```
backend/app/
├── models/document.py               TrackedDocument, DocumentContent, DocumentActivity
├── schemas/activity.py              Pydantic schemas
├── routers/activity.py              /api/v1/activity
├── utils/line_diff.py               pure added/removed counter
├── services/text_extractor.py       pure shaping of raw API output into text
├── services/google_service.py       + list_folder_tree, export_text, read_all_tabs; − read_suivi
├── services/document_scanner.py     walk, diff, persist
└── main.py                          + activity router, + activity_scan cron

backend/tests/
├── test_line_diff.py
├── test_text_extraction.py
├── test_document_scanner.py
└── test_api_activity.py

frontend/src/
├── lib/api.ts                       + activity types and endpoints
├── pages/ActivityPage.tsx
├── components/Activity/ActivityGrid.tsx
├── components/Activity/SectionList.tsx
└── components/Activity/DocumentRow.tsx
```

---

### Task 1: Remove the Projects feature

**Files:**
- Delete: `backend/app/models/project.py`, `backend/app/schemas/project.py`, `backend/app/routers/projects.py`, `backend/app/services/project_service.py`, `backend/app/services/project_status.py`, `backend/app/utils/suivi_parser.py`
- Delete: `backend/tests/test_project_models.py`, `test_suivi_parser.py`, `test_project_status.py`, `test_project_trends.py`, `test_project_service.py`, `test_api_projects.py`
- Delete: `frontend/src/pages/ProjectsPage.tsx`, the whole `frontend/src/components/Projects/` directory
- Modify: `backend/app/models/__init__.py`, `backend/app/schemas/__init__.py`, `backend/app/main.py`, `backend/app/services/scheduler_service.py`, `backend/app/services/google_service.py`, `backend/app/routers/config.py`, `backend/app/schemas/config.py`, `backend/tests/test_google_service.py`, `backend/tests/test_api_config_google.py`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Layout/TabNav.tsx`, `frontend/src/lib/api.ts`, `frontend/src/components/Config/GoogleConfig.tsx`
- Create: `backend/alembic/versions/<generated>_replace_projects_with_activity_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: a green app with no Projects feature; `Config.drive_folder_id: str`, `Config.activity_cron: str`; `scheduler_service.set_activity_job(cron_expr)`; `GoogleService` without `read_suivi`

`frontend/src/components/ui/MutationError.tsx` is shared and MUST NOT be deleted — the new page uses it.

- [ ] **Step 1: Delete the backend modules and their tests**

```bash
cd /Users/yebe/Desktop/MCP-Tour-De-Control
git rm backend/app/models/project.py backend/app/schemas/project.py \
       backend/app/routers/projects.py backend/app/services/project_service.py \
       backend/app/services/project_status.py backend/app/utils/suivi_parser.py
git rm backend/tests/test_project_models.py backend/tests/test_suivi_parser.py \
       backend/tests/test_project_status.py backend/tests/test_project_trends.py \
       backend/tests/test_project_service.py backend/tests/test_api_projects.py
```

- [ ] **Step 2: Delete the frontend page and components**

```bash
git rm frontend/src/pages/ProjectsPage.tsx
git rm -r frontend/src/components/Projects
```

- [ ] **Step 3: Drop the model and schema exports**

In `backend/app/models/__init__.py`, remove the `from app.models.project import ...` line and the three names `"Project"`, `"ProjectLink"`, `"ProjectSnapshot"` from `__all__`.

In `backend/app/schemas/__init__.py`, remove the whole `from app.schemas.project import (...)` block and the twelve project names from `__all__`.

- [ ] **Step 4: Strip `read_suivi` from the Google service**

In `backend/app/services/google_service.py`: delete the `read_suivi` method, the `SUIVI_RANGE` constant, and the `from app.utils.suivi_parser import parse_suivi_rows` import. Change `SCOPES` to:

```python
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
```

In `backend/tests/test_google_service.py`, delete every test that calls `read_suivi` (`test_read_suivi_parses_rows`, `test_read_suivi_empty_tab_returns_empty_dict`, `test_read_suivi_wraps_api_errors`). Keep the `parse_file_id`, `detect_kind`, `get_modified_time`, credential-failure and build-failure tests untouched.

- [ ] **Step 5: Rename the config field and add the folder**

In `backend/app/models/config.py`, replace the `projects_cron` column with:

```python
    drive_folder_id: Mapped[str] = mapped_column(String(100), default="")
    activity_cron: Mapped[str] = mapped_column(String(100), default="0 6 * * *")
```

In `backend/app/schemas/config.py`, rename `projects_cron` to `activity_cron` in both `ConfigRead` and `ConfigUpdate`, and add `drive_folder_id: str` to `ConfigRead` and `drive_folder_id: str | None = None` to `ConfigUpdate`.

In `backend/app/routers/config.py`, rename every `projects_cron` reference to `activity_cron`, call `scheduler_service.set_activity_job(...)` instead of `set_projects_job(...)`, and handle the new field. A pasted Drive URL is accepted: store `parse_file_id(value) or value` so both a raw id and a folder URL work.

```python
    if data.drive_folder_id is not None:
        config.drive_folder_id = parse_file_id(data.drive_folder_id) or data.drive_folder_id
```

Import `parse_file_id` from `app.services.google_service`. The cron validation that already runs before any assignment stays exactly where it is.

- [ ] **Step 6: Rename the scheduler job**

In `backend/app/services/scheduler_service.py`, rename `_execute_projects_refresh` to `_execute_activity_scan`, `PROJECTS_JOB_ID = "projects_refresh"` to `ACTIVITY_JOB_ID = "activity_scan"`, and `set_projects_job` to `set_activity_job`. The body still imports inside the function; point it at the scanner that Task 5 will create:

```python
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
```

The import sits inside the function, so this does not break until the module exists — and the `lifespan` registration already swallows failures.

- [ ] **Step 7: Unwire the router and rename the startup job**

In `backend/app/main.py`: remove `from app.routers import projects as projects_router` and its `app.include_router(...)` line. In `lifespan`, change the block that reads `config.projects_cron` to read `config.activity_cron` and call `scheduler_service.set_activity_job(cron_expr)`, keeping its `try/except`.

- [ ] **Step 8: Clean the frontend**

In `frontend/src/App.tsx`, remove the `ProjectsPage` import and the `<Route path="projects" ...>` line. In `frontend/src/components/Layout/TabNav.tsx`, remove the `{ to: "/projects", label: "Projects" }` entry.

In `frontend/src/lib/api.ts`, delete the whole `// Projects` block — every project type and every project endpoint function. In the `Config` interface rename `projects_cron` to `activity_cron` and add `drive_folder_id: string`; in `ConfigUpdate` rename the same field and add `drive_folder_id?: string`.

In `frontend/src/components/Config/GoogleConfig.tsx`, rename the cron state and payload key from `projects_cron` to `activity_cron`. Leave the rest of the panel alone — Task 9 adds the folder field.

- [ ] **Step 9: Update the config tests**

In `backend/tests/test_api_config_google.py`, rename every `projects_cron` occurrence to `activity_cron` and every `set_projects_job` assertion to `set_activity_job`. Do the same in `backend/tests/test_api_config.py` if it references the field. Do not weaken any assertion — only rename.

- [ ] **Step 10: Generate the migration**

Run: `cd backend && PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "replace projects with activity config"`

Open the generated file. Autogenerate will emit a drop of `projects_cron` plus an add of `activity_cron`, which would lose the stored value. Replace that pair with a rename, so `upgrade()` reads:

```python
def upgrade() -> None:
    op.drop_table("project_snapshot")
    op.drop_table("project_link")
    op.drop_table("project")
    op.alter_column("config", "projects_cron", new_column_name="activity_cron")
    op.add_column(
        "config",
        sa.Column("drive_folder_id", sa.String(length=100), nullable=False, server_default=""),
    )
    op.alter_column("config", "drive_folder_id", server_default=None)
```

and `downgrade()` reverses it:

```python
def downgrade() -> None:
    op.drop_column("config", "drive_folder_id")
    op.alter_column("config", "activity_cron", new_column_name="projects_cron")
```

The `downgrade()` does not recreate the project tables — the feature is gone, and a half-restored schema would be worse than none. Say so in a comment in the migration.

- [ ] **Step 11: Apply the migration**

Run: `cd backend && PYTHONPATH=. venv/bin/alembic upgrade head`
Expected: `Running upgrade aa2d4bae63d4 -> <rev>, replace projects with activity config` with no error.

- [ ] **Step 12: Run the full backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: PASS apart from the 7 pre-existing `ScriptExecutor` failures. Every project test is gone; nothing else should have moved.

- [ ] **Step 13: Build the frontend**

Run: `cd frontend && npm run build && npm run lint`
Expected: both clean. A dangling import from a deleted component is exactly what `tsc -b` catches here.

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "refactor(activity): remove the projects feature and prepare activity config"
```

---

### Task 2: Line diff counter

**Files:**
- Create: `backend/app/utils/line_diff.py`
- Create: `backend/tests/test_line_diff.py`

**Interfaces:**
- Consumes: nothing
- Produces: `split_lines(text: str) -> list[str]`, `count_changes(old_lines: list[str], new_lines: list[str]) -> tuple[int, int]` returning `(added, removed)`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_line_diff.py`:

```python
from app.utils.line_diff import count_changes, split_lines


def test_pure_insertion():
    assert count_changes(["a", "b"], ["a", "b", "c", "d"]) == (2, 0)


def test_pure_deletion():
    assert count_changes(["a", "b", "c"], ["a"]) == (0, 2)


def test_replacement_counts_both_sides():
    assert count_changes(["a", "b", "c"], ["a", "x", "c"]) == (1, 1)


def test_identical_content_is_no_change():
    assert count_changes(["a", "b"], ["a", "b"]) == (0, 0)


def test_full_rewrite_at_constant_length():
    """The case a net line count would hide: same length, everything different."""
    old = [f"old line {i}" for i in range(50)]
    new = [f"new line {i}" for i in range(50)]
    assert count_changes(old, new) == (50, 50)


def test_empty_inputs():
    assert count_changes([], []) == (0, 0)
    assert count_changes([], ["a", "b"]) == (2, 0)
    assert count_changes(["a", "b"], []) == (0, 2)


def test_large_repetitive_document_is_not_treated_as_junk():
    """SequenceMatcher's autojunk heuristic must be off, or popular lines are ignored."""
    old = ["" for _ in range(300)] + ["real content"]
    new = ["" for _ in range(300)] + ["different content"]
    assert count_changes(old, new) == (1, 1)


def test_split_lines_strips_trailing_whitespace():
    assert split_lines("a   \nb\t\n") == ["a", "b"]


def test_split_lines_drops_trailing_blank_lines():
    assert split_lines("a\nb\n\n\n\n") == ["a", "b"]


def test_split_lines_keeps_interior_blank_lines():
    assert split_lines("a\n\nb") == ["a", "", "b"]


def test_split_lines_on_empty_text():
    assert split_lines("") == []
    assert split_lines("\n\n\n") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_line_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.line_diff'`

- [ ] **Step 3: Write the module**

Create `backend/app/utils/line_diff.py`:

```python
"""Line-level diff counting. Pure functions, no I/O."""

from difflib import SequenceMatcher


def split_lines(text: str) -> list[str]:
    """Split text into comparable lines.

    Trailing whitespace is stripped per line and trailing blank lines are
    dropped, so an editor leaving empty paragraphs at the end of a document
    does not register as activity.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def count_changes(old_lines: list[str], new_lines: list[str]) -> tuple[int, int]:
    """Return (added, removed) between two versions of a document.

    A replacement counts on both sides, so a rewrite that keeps the line count
    constant reads as `+n −n` rather than as no change at all.
    """
    added = 0
    removed = 0

    # autojunk=False matters: on sequences longer than 200 items SequenceMatcher
    # otherwise treats frequently repeated lines (blank lines, in a real
    # document) as junk and skips them, which silently distorts the counts.
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            added += j2 - j1
            removed += i2 - i1

    return added, removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_line_diff.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/line_diff.py backend/tests/test_line_diff.py
git commit -m "feat(activity): add line-level diff counter"
```

---

### Task 3: Document models and migration

**Files:**
- Create: `backend/app/models/document.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_document_models.py`
- Create: `backend/alembic/versions/<generated>_add_document_activity_tables.py`

**Interfaces:**
- Consumes: `app.models.config.Base`
- Produces: `TrackedDocument`, `DocumentContent`, `DocumentActivity` importable from `app.models`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_document_models.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import DocumentActivity, DocumentContent, TrackedDocument


async def _document(session, file_id="FILE1", name="Recherche GoogleFlow"):
    doc = TrackedDocument(
        file_id=file_id,
        name=name,
        mime_type="application/vnd.google-apps.document",
        section="Soutien-Scolaire",
        web_url=f"https://docs.google.com/document/d/{file_id}/edit",
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def test_document_defaults(session):
    doc = await _document(session)
    assert isinstance(doc.id, uuid.UUID)
    assert doc.is_present is True
    assert doc.line_count is None
    assert doc.last_error is None


async def test_file_id_is_unique(session):
    await _document(session)
    session.add(
        TrackedDocument(
            file_id="FILE1",
            name="Duplicate",
            mime_type="application/vnd.google-apps.document",
            web_url="https://example.com",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_content_and_activity_cascade(session):
    doc = await _document(session)
    session.add(DocumentContent(document_id=doc.id, text="a\nb\nc"))
    session.add(
        DocumentActivity(document_id=doc.id, day=date(2026, 8, 20), added=142, removed=5)
    )
    await session.commit()

    await session.delete(doc)
    await session.commit()

    assert (await session.execute(select(DocumentContent))).scalars().all() == []
    assert (await session.execute(select(DocumentActivity))).scalars().all() == []


async def test_one_activity_row_per_document_per_day(session):
    doc = await _document(session)
    session.add(DocumentActivity(document_id=doc.id, day=date(2026, 8, 20), added=1, removed=0))
    await session.commit()

    session.add(DocumentActivity(document_id=doc.id, day=date(2026, 8, 20), added=9, removed=9))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_absent_document_keeps_its_history(session):
    doc = await _document(session)
    session.add(DocumentActivity(document_id=doc.id, day=date(2026, 8, 19), added=3, removed=1))
    await session.commit()

    doc.is_present = False
    await session.commit()

    rows = (await session.execute(select(DocumentActivity))).scalars().all()
    assert len(rows) == 1
    assert rows[0].added == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'TrackedDocument' from 'app.models'`

- [ ] **Step 3: Create the models**

Create `backend/app/models/document.py`:

```python
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.config import Base


class TrackedDocument(Base):
    __tablename__ = "tracked_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    web_url: Mapped[str] = mapped_column(Text)
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    content: Mapped["DocumentContent"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    activity: Mapped[list["DocumentActivity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentContent(Base):
    """The latest extraction only. Never a history — that is what bounds storage."""

    __tablename__ = "document_content"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracked_document.id", ondelete="CASCADE"), unique=True
    )
    text: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    document: Mapped["TrackedDocument"] = relationship(back_populates="content")


class DocumentActivity(Base):
    """One row per document per day that actually changed. Days with no change have no row."""

    __tablename__ = "document_activity"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracked_document.id", ondelete="CASCADE")
    )
    day: Mapped[date] = mapped_column(Date)
    added: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)

    document: Mapped["TrackedDocument"] = relationship(back_populates="activity")

    __table_args__ = (
        UniqueConstraint("document_id", "day", name="uq_document_activity_document_day"),
        Index("ix_document_activity_day", "day"),
    )
```

- [ ] **Step 4: Export the models**

In `backend/app/models/__init__.py`, add after the conversation import:

```python
from app.models.document import TrackedDocument, DocumentContent, DocumentActivity
```

and add `"TrackedDocument"`, `"DocumentContent"`, `"DocumentActivity"` to `__all__`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_models.py -v`
Expected: PASS, 5 tests

- [ ] **Step 6: Generate and apply the migration**

Run: `cd backend && PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "add document activity tables"`

Open the file and confirm `upgrade()` creates `tracked_document` (with the unique `file_id`), `document_content` (with the unique `document_id`), and `document_activity` (with `uq_document_activity_document_day` and `ix_document_activity_day`), and that `downgrade()` drops all three.

Run: `cd backend && PYTHONPATH=. venv/bin/alembic upgrade head`
Expected: the upgrade runs with no error.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/document.py backend/app/models/__init__.py \
        backend/tests/test_document_models.py backend/alembic/versions/
git commit -m "feat(activity): add tracked document, content and activity models"
```

---

### Task 4: Drive folder walk and text extraction

**Files:**
- Modify: `backend/app/services/google_service.py`
- Create: `backend/app/services/text_extractor.py`
- Modify: `backend/tests/test_google_service.py`
- Create: `backend/tests/test_text_extraction.py`

**Interfaces:**
- Consumes: `GoogleService.__init__`, `GoogleAccessError` (already exist)
- Produces:
  - `GoogleService.list_folder_tree(folder_id: str, max_files: int) -> tuple[list[dict], int]` returning `(files, skipped)`, each file dict carrying `id`, `name`, `mimeType`, `webViewLink`, `modifiedTime`, `author`, `section`
  - `GoogleService.export_text(file_id: str) -> str`
  - `GoogleService.read_all_tabs(file_id: str) -> list[tuple[str, list[list]]]`
  - `text_extractor.DOC_MIME`, `SHEET_MIME`, `FOLDER_MIME`, `is_diffable(mime_type) -> bool`, `sheet_text(tabs) -> str`

The split is deliberate: every HTTP call lives in `google_service.py`, every text-shaping rule lives in `text_extractor.py` as pure functions that can be tested without a mock.

- [ ] **Step 1: Write the failing extraction test**

Create `backend/tests/test_text_extraction.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import MagicMock

import pytest

from app.services.google_service import GoogleAccessError, GoogleService
from app.services.text_extractor import DOC_MIME, SHEET_MIME, is_diffable, sheet_text


def test_is_diffable():
    assert is_diffable(DOC_MIME) is True
    assert is_diffable(SHEET_MIME) is True
    assert is_diffable("application/pdf") is False
    assert is_diffable("application/vnd.google-apps.folder") is False


def test_sheet_text_prefixes_every_row_with_its_tab():
    tabs = [("SUIVI", [["avancement", "72"], ["budget", "8400"]])]
    assert sheet_text(tabs) == "SUIVI\tavancement\t72\nSUIVI\tbudget\t8400"


def test_sheet_text_covers_every_tab():
    tabs = [("Notes", [["a"]]), ("Budget", [["b"]])]
    assert sheet_text(tabs) == "Notes\ta\nBudget\tb"


def test_sheet_text_skips_fully_blank_rows():
    tabs = [("T", [["a"], ["", "  "], [], ["b"]])]
    assert sheet_text(tabs) == "T\ta\nT\tb"


def test_sheet_text_on_empty_input():
    assert sheet_text([]) == ""
    assert sheet_text([("T", [])]) == ""


def test_export_text_decodes_bytes():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.return_value = b"ligne 1\nligne 2"
    service._drive = drive

    assert service.export_text("DOC1") == "ligne 1\nligne 2"


def test_export_text_wraps_api_errors():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    drive.files.return_value.export.return_value.execute.side_effect = RuntimeError("403 denied")
    service._drive = drive

    with pytest.raises(GoogleAccessError) as exc:
        service.export_text("DOC1")
    assert "DOC1" in str(exc.value)


def test_read_all_tabs_returns_title_and_rows():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": "Notes"}}, {"properties": {"title": "Budget"}}]
    }
    sheets.spreadsheets.return_value.values.return_value.batchGet.return_value.execute.return_value = {
        "valueRanges": [{"values": [["a"]]}, {"values": [["b"]]}]
    }
    service._sheets = sheets

    assert service.read_all_tabs("SHEET1") == [("Notes", [["a"]]), ("Budget", [["b"]])]


def test_read_all_tabs_on_a_spreadsheet_with_no_tabs():
    service = GoogleService.__new__(GoogleService)
    sheets = MagicMock()
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {}
    service._sheets = sheets

    assert service.read_all_tabs("SHEET1") == []


def test_list_folder_tree_assigns_the_top_subfolder_as_section():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()

    def children(q, **kwargs):
        page = MagicMock()
        if "'ROOT' in parents" in q:
            page.execute.return_value = {
                "files": [
                    {"id": "SUB", "name": "Soutien-Scolaire", "mimeType": "application/vnd.google-apps.folder"},
                    {"id": "TOP", "name": "Note racine", "mimeType": DOC_MIME, "webViewLink": "u1"},
                ]
            }
        elif "'SUB' in parents" in q:
            page.execute.return_value = {
                "files": [
                    {"id": "DEEP", "name": "Sous-dossier", "mimeType": "application/vnd.google-apps.folder"},
                ]
            }
        else:
            page.execute.return_value = {
                "files": [{"id": "F1", "name": "Recherche", "mimeType": DOC_MIME, "webViewLink": "u2"}]
            }
        return page

    drive.files.return_value.list.side_effect = children
    service._drive = drive

    files, skipped = service.list_folder_tree("ROOT", max_files=100)

    by_id = {f["id"]: f for f in files}
    assert skipped == 0
    assert by_id["TOP"]["section"] is None
    assert by_id["F1"]["section"] == "Soutien-Scolaire"


def test_list_folder_tree_reports_what_the_cap_skipped():
    service = GoogleService.__new__(GoogleService)
    drive = MagicMock()
    page = MagicMock()
    page.execute.return_value = {
        "files": [
            {"id": f"F{i}", "name": f"doc {i}", "mimeType": DOC_MIME, "webViewLink": "u"}
            for i in range(10)
        ]
    }
    drive.files.return_value.list.return_value = page
    service._drive = drive

    files, skipped = service.list_folder_tree("ROOT", max_files=4)

    assert len(files) == 4
    assert skipped == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_text_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.text_extractor'`

- [ ] **Step 3: Write the pure extractor**

Create `backend/app/services/text_extractor.py`:

```python
"""Shape raw Google API output into comparable plain text. Pure functions, no I/O."""

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def is_diffable(mime_type: str) -> bool:
    """Only Docs and Sheets yield text we can diff; everything else is listed only."""
    return mime_type in (DOC_MIME, SHEET_MIME)


def sheet_text(tabs: list[tuple[str, list[list]]]) -> str:
    """Turn every tab's rows into one text block, one line per spreadsheet row.

    Each line is prefixed with its tab name, so a row moved from one tab to
    another reads as a real change rather than as no change at all.
    """
    lines = []
    for title, rows in tabs:
        for row in rows:
            cells = [str(cell) for cell in row]
            if any(cell.strip() for cell in cells):
                lines.append("\t".join([title, *cells]))
    return "\n".join(lines)
```

- [ ] **Step 4: Add the three Google calls**

In `backend/app/services/google_service.py`, add the import at the top:

```python
from app.services.text_extractor import FOLDER_MIME
```

and add these methods to `GoogleService`:

```python
    _LIST_FIELDS = "nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime, lastModifyingUser/displayName)"

    def list_folder_tree(self, folder_id: str, max_files: int) -> tuple[list[dict], int]:
        """Walk a folder breadth-first. Returns (files, number skipped by the cap).

        `section` is the name of the root's immediate subfolder a file descends
        from, or None for files sitting directly in the root.
        """
        queue: list[tuple[str, str | None]] = [(folder_id, None)]
        files: list[dict] = []
        skipped = 0

        while queue:
            parent, section = queue.pop(0)
            for entry in self._list_children(parent):
                if entry.get("mimeType") == FOLDER_MIME:
                    # The first subfolder level names the section; deeper folders inherit it.
                    queue.append((entry["id"], section or entry.get("name")))
                elif len(files) < max_files:
                    files.append(
                        {
                            "id": entry["id"],
                            "name": entry.get("name", ""),
                            "mimeType": entry.get("mimeType", ""),
                            "webViewLink": entry.get("webViewLink", ""),
                            "modifiedTime": entry.get("modifiedTime"),
                            "author": (entry.get("lastModifyingUser") or {}).get("displayName"),
                            "section": section,
                        }
                    )
                else:
                    skipped += 1

        return files, skipped

    def _list_children(self, parent_id: str) -> list[dict]:
        """Every non-trashed child of a folder, following pagination."""
        entries: list[dict] = []
        page_token = None
        while True:
            try:
                response = (
                    self._drive.files()
                    .list(
                        q=f"'{parent_id}' in parents and trashed = false",
                        fields=self._LIST_FIELDS,
                        pageSize=1000,
                        pageToken=page_token,
                    )
                    .execute()
                )
            except Exception as exc:
                raise GoogleAccessError(f"cannot list folder {parent_id}: {exc}") from exc
            entries.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return entries

    def export_text(self, file_id: str) -> str:
        """Export a Google Doc as plain text."""
        try:
            data = self._drive.files().export(fileId=file_id, mimeType="text/plain").execute()
        except Exception as exc:
            raise GoogleAccessError(f"cannot export {file_id} as text: {exc}") from exc
        return data.decode("utf-8") if isinstance(data, bytes) else str(data)

    def read_all_tabs(self, file_id: str) -> list[tuple[str, list[list]]]:
        """Every tab of a spreadsheet as (title, rows).

        Drive's CSV export would silently return only the first tab, so this
        goes through the Sheets API instead.
        """
        try:
            meta = (
                self._sheets.spreadsheets()
                .get(spreadsheetId=file_id, fields="sheets.properties.title")
                .execute()
            )
            titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
            if not titles:
                return []
            result = (
                self._sheets.spreadsheets()
                .values()
                .batchGet(spreadsheetId=file_id, ranges=titles)
                .execute()
            )
        except Exception as exc:
            raise GoogleAccessError(f"cannot read tabs of {file_id}: {exc}") from exc

        ranges = result.get("valueRanges", [])
        return [(title, ranges[i].get("values", []) if i < len(ranges) else []) for i, title in enumerate(titles)]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_text_extraction.py tests/test_google_service.py -v`
Expected: PASS. `test_google_service.py` still covers `parse_file_id`, `detect_kind`, `get_modified_time` and the two constructor failure paths.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/text_extractor.py backend/app/services/google_service.py \
        backend/tests/test_text_extraction.py backend/tests/test_google_service.py
git commit -m "feat(activity): walk a Drive folder and extract Doc and Sheet text"
```

---

### Task 5: Document scanner

**Files:**
- Create: `backend/app/services/document_scanner.py`
- Create: `backend/tests/test_document_scanner.py`

**Interfaces:**
- Consumes: `GoogleService` (`list_folder_tree`, `export_text`, `read_all_tabs`), `GoogleAccessError`, `text_extractor.is_diffable`/`sheet_text`/`DOC_MIME`/`SHEET_MIME`, `line_diff.split_lines`/`count_changes`, models `TrackedDocument`, `DocumentContent`, `DocumentActivity`, `Config`, `app.utils.crypto.decrypt_value`
- Produces: `DocumentScanner.scan_all(session) -> int` (number of files walked), constant `DocumentScanner.MAX_FILES = 500`

**The accumulation rule:** a manual scan can run a second time on the same day. The second diff compares against the content the first scan stored, so it only sees the delta since then. The day's row must therefore **accumulate** — `added += `, not `added = ` — or the morning's work disappears the moment someone clicks "Scan now" in the afternoon.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_document_scanner.py`:

```python
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import Config, DocumentActivity, DocumentContent, TrackedDocument
from app.services.google_service import GoogleAccessError
from app.services.document_scanner import DocumentScanner
from app.services.text_extractor import DOC_MIME, SHEET_MIME
from app.utils.crypto import encrypt_value


async def _configured(session, folder="ROOT"):
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}'), drive_folder_id=folder))
    await session.commit()


def _google(files, text="a\nb\nc", skipped=0, export_error=None):
    google = MagicMock()
    google.list_folder_tree.return_value = (files, skipped)
    if export_error:
        google.export_text.side_effect = GoogleAccessError(export_error)
    else:
        google.export_text.return_value = text
    google.read_all_tabs.return_value = [("Feuille1", [["x"]])]
    return google


def _doc(file_id="F1", name="Recherche", section="Soutien-Scolaire"):
    return {
        "id": file_id,
        "name": name,
        "mimeType": DOC_MIME,
        "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
        "modifiedTime": "2026-08-20T09:12:44.000Z",
        "author": "Fabien",
        "section": section,
    }


async def test_first_sighting_stores_a_baseline_and_no_activity(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()])):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 1
    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.name == "Recherche"
    assert doc.section == "Soutien-Scolaire"
    assert doc.last_author == "Fabien"
    assert doc.line_count == 3
    assert (await session.execute(select(DocumentContent))).scalar_one().text == "a\nb\nc"
    assert (await session.execute(select(DocumentActivity))).scalars().all() == []


async def test_second_scan_with_changes_records_them(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb\nc")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nZ\nc\nd")):
        await DocumentScanner.scan_all(session)

    row = (await session.execute(select(DocumentActivity))).scalar_one()
    assert (row.added, row.removed) == (2, 1)
    assert row.author == "Fabien"


async def test_unchanged_document_writes_no_row(session):
    await _configured(session)
    for _ in range(2):
        with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()])):
            await DocumentScanner.scan_all(session)

    assert (await session.execute(select(DocumentActivity))).scalars().all() == []


async def test_same_day_rescan_accumulates_instead_of_replacing(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb\nc")):
        await DocumentScanner.scan_all(session)

    row = (await session.execute(select(DocumentActivity))).scalar_one()
    assert row.added == 2, "the morning's line must survive the afternoon rescan"


async def test_vanished_document_is_marked_absent_and_keeps_history(session):
    await _configured(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([_doc()], text="a\nb")):
        await DocumentScanner.scan_all(session)
    with patch("app.services.document_scanner.GoogleService", return_value=_google([])):
        await DocumentScanner.scan_all(session)

    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.is_present is False
    assert len((await session.execute(select(DocumentActivity))).scalars().all()) == 1


async def test_a_failing_file_does_not_abort_the_walk(session):
    await _configured(session)
    google = _google([_doc("F1"), _doc("F2", name="Autre")], export_error="permission denied")
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        walked = await DocumentScanner.scan_all(session)

    assert walked == 2
    docs = (await session.execute(select(TrackedDocument))).scalars().all()
    assert len(docs) == 2
    assert all("permission denied" in (d.last_error or "") for d in docs)


async def test_non_diffable_file_is_listed_but_not_extracted(session):
    await _configured(session)
    pdf = {**_doc("P1", name="Facture"), "mimeType": "application/pdf"}
    google = _google([pdf])
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        await DocumentScanner.scan_all(session)

    doc = (await session.execute(select(TrackedDocument))).scalar_one()
    assert doc.line_count is None
    google.export_text.assert_not_called()
    assert (await session.execute(select(DocumentContent))).scalars().all() == []


async def test_spreadsheet_goes_through_read_all_tabs(session):
    await _configured(session)
    sheet = {**_doc("S1", name="Planning"), "mimeType": SHEET_MIME}
    google = _google([sheet])
    with patch("app.services.document_scanner.GoogleService", return_value=google):
        await DocumentScanner.scan_all(session)

    google.read_all_tabs.assert_called_once_with("S1")
    google.export_text.assert_not_called()
    assert (await session.execute(select(DocumentContent))).scalar_one().text == "Feuille1\tx"


async def test_missing_folder_raises(session):
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}'), drive_folder_id=""))
    await session.commit()

    with pytest.raises(GoogleAccessError):
        await DocumentScanner.scan_all(session)


async def test_missing_key_raises(session):
    session.add(Config(google_sa_key="", drive_folder_id="ROOT"))
    await session.commit()

    with pytest.raises(GoogleAccessError):
        await DocumentScanner.scan_all(session)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.document_scanner'`

- [ ] **Step 3: Write the scanner**

Create `backend/app/services/document_scanner.py`:

```python
"""Walk the tracked Drive folder, diff each file against its stored copy, persist."""

import asyncio
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config, DocumentActivity, DocumentContent, TrackedDocument
from app.services.google_service import GoogleAccessError, GoogleService
from app.services.text_extractor import DOC_MIME, SHEET_MIME, is_diffable, sheet_text
from app.utils.crypto import decrypt_value
from app.utils.line_diff import count_changes, split_lines

log = structlog.get_logger()


class DocumentScanner:
    MAX_FILES = 500

    @staticmethod
    async def scan_all(session: AsyncSession) -> int:
        """Rescan the whole folder. Returns the number of files walked."""
        google, folder_id = await DocumentScanner._build_google(session)

        files, skipped = await asyncio.to_thread(
            google.list_folder_tree, folder_id, DocumentScanner.MAX_FILES
        )
        if skipped:
            # Never truncate silently: partial coverage must not read as complete.
            log.warning("Scan cap reached", cap=DocumentScanner.MAX_FILES, skipped=skipped)

        today = datetime.now(timezone.utc).date()
        seen: set[str] = set()

        for entry in files:
            seen.add(entry["id"])
            await DocumentScanner._process(session, google, entry, today)

        await DocumentScanner._mark_absent(session, seen)
        await session.commit()
        log.info("Activity scan finished", walked=len(files), skipped=skipped)
        return len(files)

    @staticmethod
    async def _build_google(session: AsyncSession) -> tuple[GoogleService, str]:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.google_sa_key:
            raise GoogleAccessError("Google service account key not configured")
        if not config.drive_folder_id:
            raise GoogleAccessError("No Drive folder configured")
        return GoogleService(decrypt_value(config.google_sa_key)), config.drive_folder_id

    @staticmethod
    async def _process(session: AsyncSession, google: GoogleService, entry: dict, today: date) -> None:
        doc = await DocumentScanner._upsert_document(session, entry)

        if not is_diffable(entry["mimeType"]):
            return

        try:
            text = await DocumentScanner._extract(google, entry)
        except GoogleAccessError as exc:
            doc.last_error = str(exc)
            log.warning("Extraction failed", document=doc.name, error=str(exc))
            return

        new_lines = split_lines(text)
        stored = (
            await session.execute(
                select(DocumentContent).where(DocumentContent.document_id == doc.id)
            )
        ).scalar_one_or_none()

        if stored is None:
            # First sighting: record a baseline. Counting a pre-existing file's
            # whole content as "added" would put a false spike in the grid.
            session.add(DocumentContent(document_id=doc.id, text=text))
            doc.line_count = len(new_lines)
            return

        added, removed = count_changes(split_lines(stored.text), new_lines)
        if added or removed:
            await DocumentScanner._record_activity(session, doc, today, added, removed, entry.get("author"))
            stored.text = text
            stored.captured_at = datetime.now(timezone.utc)
            doc.line_count = len(new_lines)

    @staticmethod
    async def _extract(google: GoogleService, entry: dict) -> str:
        if entry["mimeType"] == DOC_MIME:
            return await asyncio.to_thread(google.export_text, entry["id"])
        tabs = await asyncio.to_thread(google.read_all_tabs, entry["id"])
        return sheet_text(tabs)

    @staticmethod
    async def _upsert_document(session: AsyncSession, entry: dict) -> TrackedDocument:
        doc = (
            await session.execute(
                select(TrackedDocument).where(TrackedDocument.file_id == entry["id"])
            )
        ).scalar_one_or_none()

        modified = entry.get("modifiedTime")
        modified_at = (
            datetime.fromisoformat(modified.replace("Z", "+00:00")).astimezone(timezone.utc)
            if modified
            else None
        )

        if doc is None:
            doc = TrackedDocument(file_id=entry["id"], name=entry["name"], mime_type=entry["mimeType"])
            session.add(doc)

        doc.name = entry["name"]
        doc.mime_type = entry["mimeType"]
        doc.section = entry.get("section")
        doc.web_url = entry.get("webViewLink", "")
        doc.last_modified_at = modified_at
        doc.last_author = entry.get("author")
        doc.is_present = True
        doc.last_error = None

        await session.flush()
        return doc

    @staticmethod
    async def _record_activity(
        session: AsyncSession,
        doc: TrackedDocument,
        day: date,
        added: int,
        removed: int,
        author: str | None,
    ) -> None:
        """Accumulate into today's row.

        A manual rescan later the same day only sees the delta since the
        previous scan, so replacing the row would erase the morning's work.
        """
        row = (
            await session.execute(
                select(DocumentActivity).where(
                    DocumentActivity.document_id == doc.id, DocumentActivity.day == day
                )
            )
        ).scalar_one_or_none()

        if row is None:
            session.add(
                DocumentActivity(
                    document_id=doc.id, day=day, added=added, removed=removed, author=author
                )
            )
        else:
            row.added += added
            row.removed += removed
            if author:
                row.author = author

    @staticmethod
    async def _mark_absent(session: AsyncSession, seen: set[str]) -> None:
        """Flag documents that left the folder. Their history is deliberately kept."""
        statement = update(TrackedDocument).where(TrackedDocument.is_present.is_(True)).values(is_present=False)
        if seen:
            statement = statement.where(TrackedDocument.file_id.not_in(seen))
        await session.execute(statement)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && venv/bin/python -m pytest tests/test_document_scanner.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: PASS apart from the 7 pre-existing `ScriptExecutor` failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/document_scanner.py backend/tests/test_document_scanner.py
git commit -m "feat(activity): scan the tracked folder and record daily line changes"
```

---

### Task 6: Read model, schemas and API routes

**Files:**
- Create: `backend/app/services/activity_view.py`
- Create: `backend/app/schemas/activity.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `backend/app/routers/activity.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/config.py`, `backend/app/services/document_scanner.py`
- Create: `backend/tests/test_api_activity.py`
- Create: `backend/alembic/versions/<generated>_add_config_last_scan_at.py`

**Refinements to the spec:** three, all recorded here rather than left implicit.
1. The spec lists only `document_scanner.py`; this plan adds `activity_view.py` so the read model has its own home — the scanner writes, the view reads, and neither grows into the other.
2. The spec has no way to report when the last scan ran, so this task adds `Config.last_scan_at` and stamps it at the end of every scan. Deriving it from `updated_at` would not work: a scan where nothing changed issues no UPDATE, so the timestamp would silently go stale.
3. The spec lists a `ScanButton.tsx` component; Task 9 puts the button directly in `ActivityPage.tsx`, since it owns the mutation and the queries it invalidates, and a one-button component would only forward props.

**Interfaces:**
- Consumes: models `TrackedDocument`, `DocumentActivity`, `Config`; `DocumentScanner.scan_all`; `GoogleAccessError`
- Produces:
  - `ActivityView.sections(session) -> list[dict]`, `ActivityView.heatmap(session, today=None) -> dict`
  - `heatmap_span(today: date) -> tuple[date, date]`
  - Schemas `DocumentRead`, `SectionRead`, `HeatmapDay`, `HeatmapRead`, `ScanResult`
  - `Config.last_scan_at: datetime | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_activity.py`:

```python
import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, DocumentActivity, TrackedDocument
from app.services.activity_view import heatmap_span
from app.services.text_extractor import DOC_MIME

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


async def _seed(async_session, section="Soutien-Scolaire", days_ago=1, added=142, removed=5):
    async with async_session() as session:
        doc = TrackedDocument(
            file_id=f"F{uuid.uuid4().hex[:8]}",
            name="Recherche GoogleFlow",
            mime_type=DOC_MIME,
            section=section,
            web_url="https://docs.google.com/document/d/F1/edit",
            last_modified_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            last_author="Fabien",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        session.add(
            DocumentActivity(
                document_id=doc.id,
                day=date.today() - timedelta(days=days_ago),
                added=added,
                removed=removed,
                author="Fabien",
            )
        )
        await session.commit()
        return doc.id


def test_heatmap_span_starts_on_a_monday_53_columns_back():
    start, end = heatmap_span(date(2026, 8, 20))  # a Thursday
    assert start.weekday() == 0
    assert end == date(2026, 8, 20)
    assert (end - start).days == 52 * 7 + 3


async def test_documents_groups_by_section(client, setup_test_db):
    await _seed(setup_test_db)
    response = await client.get("/api/v1/activity/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Soutien-Scolaire"
    doc = body[0]["documents"][0]
    assert doc["last_added"] == 142
    assert doc["last_removed"] == 5
    assert doc["last_author"] == "Fabien"


async def test_documents_without_a_section_land_in_ungrouped(client, setup_test_db):
    await _seed(setup_test_db, section=None)
    body = (await client.get("/api/v1/activity/documents")).json()
    assert body[0]["name"] == "Ungrouped"


async def test_document_with_no_activity_reports_zero(client, setup_test_db):
    async with setup_test_db() as session:
        session.add(
            TrackedDocument(
                file_id="P1",
                name="Facture",
                mime_type="application/pdf",
                section="Admin",
                web_url="https://drive.google.com/file/d/P1/view",
            )
        )
        await session.commit()

    doc = (await client.get("/api/v1/activity/documents")).json()[0]["documents"][0]
    assert doc["last_added"] == 0
    assert doc["last_removed"] == 0
    assert doc["last_activity_day"] is None


async def test_heatmap_fills_absent_days_with_zero(client, setup_test_db):
    await _seed(setup_test_db, days_ago=2, added=10, removed=3)
    body = (await client.get("/api/v1/activity/heatmap")).json()

    start, end = heatmap_span(date.today())
    assert len(body["days"]) == (end - start).days + 1
    assert body["total_changes"] == 13

    by_day = {d["day"]: d for d in body["days"]}
    active = by_day[(date.today() - timedelta(days=2)).isoformat()]
    assert (active["added"], active["removed"], active["total"]) == (10, 3, 13)
    quiet = by_day[(date.today() - timedelta(days=1)).isoformat()]
    assert quiet["total"] == 0


async def test_scan_endpoint_calls_the_scanner(client):
    with patch(
        "app.routers.activity.DocumentScanner.scan_all", new=AsyncMock(return_value=7)
    ) as scan:
        response = await client.post("/api/v1/activity/scan")

    assert response.status_code == 200
    assert response.json() == {"walked": 7}
    scan.assert_awaited_once()


async def test_scan_reports_configuration_errors_as_400(client):
    from app.services.google_service import GoogleAccessError

    with patch(
        "app.routers.activity.DocumentScanner.scan_all",
        new=AsyncMock(side_effect=GoogleAccessError("No Drive folder configured")),
    ):
        response = await client.post("/api/v1/activity/scan")

    assert response.status_code == 400
    assert "No Drive folder configured" in response.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_activity.py -v`
Expected: FAIL — `app.services.activity_view` does not exist and the routes 404.

- [ ] **Step 3: Add the last-scan timestamp**

In `backend/app/models/config.py`, add after `activity_cron`:

```python
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

At the end of `DocumentScanner.scan_all` in `backend/app/services/document_scanner.py`, before the commit, stamp it:

```python
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if config:
            config.last_scan_at = datetime.now(timezone.utc)

        await DocumentScanner._mark_absent(session, seen)
        await session.commit()
```

- [ ] **Step 4: Write the read model**

Create `backend/app/services/activity_view.py`:

```python
"""Read model for the activity page. Queries only — the scanner does the writing."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config, DocumentActivity, TrackedDocument

UNGROUPED = "Ungrouped"
WEEKS_BACK = 52

# Timezone-aware sentinel: every stored timestamp is aware, and mixing a naive
# datetime.min into the same sort would raise as soon as the two are compared.
NEVER = datetime.min.replace(tzinfo=timezone.utc)


def heatmap_span(today: date) -> tuple[date, date]:
    """The grid's exact span: the Monday 52 weeks before this week, through today.

    Aligning on a Monday is what keeps the first column whole; a span of plain
    365 days would render a partial column on the left.
    """
    week_start = today - timedelta(days=today.weekday())
    return week_start - timedelta(weeks=WEEKS_BACK), today


class ActivityView:
    @staticmethod
    async def sections(session: AsyncSession) -> list[dict]:
        """Documents grouped by section, each with its most recent activity."""
        documents = (
            await session.execute(select(TrackedDocument).order_by(TrackedDocument.name))
        ).scalars().all()

        latest = await ActivityView._latest_activity(session)

        grouped: dict[str, list[dict]] = {}
        for doc in documents:
            row = latest.get(doc.id)
            grouped.setdefault(doc.section or UNGROUPED, []).append(
                {
                    "id": doc.id,
                    "name": doc.name,
                    "mime_type": doc.mime_type,
                    "web_url": doc.web_url,
                    "section": doc.section,
                    "last_modified_at": doc.last_modified_at,
                    "last_author": doc.last_author,
                    "line_count": doc.line_count,
                    "is_present": doc.is_present,
                    "last_error": doc.last_error,
                    "last_activity_day": row.day if row else None,
                    "last_added": row.added if row else 0,
                    "last_removed": row.removed if row else 0,
                }
            )

        # Most recently modified first; never-modified documents fall to the end.
        for docs in grouped.values():
            docs.sort(key=lambda d: d["last_modified_at"] or NEVER, reverse=True)

        # Ungrouped always trails; the named sections lead, most recently touched first.
        named = sorted(
            (name for name in grouped if name != UNGROUPED),
            key=lambda name: max(
                (d["last_modified_at"] for d in grouped[name] if d["last_modified_at"]),
                default=NEVER,
            ),
            reverse=True,
        )
        ordered = named + ([UNGROUPED] if UNGROUPED in grouped else [])
        return [{"name": name, "documents": grouped[name]} for name in ordered]

    @staticmethod
    async def _latest_activity(session: AsyncSession) -> dict:
        """The most recent activity row per document, keyed by document id."""
        rows = (
            await session.execute(
                select(DocumentActivity).order_by(DocumentActivity.day.desc())
            )
        ).scalars().all()
        latest: dict = {}
        for row in rows:
            latest.setdefault(row.document_id, row)
        return latest

    @staticmethod
    async def heatmap(session: AsyncSession, today: date | None = None) -> dict:
        """One entry per day across the grid's span, absent days filled with zero."""
        today = today or date.today()
        start, end = heatmap_span(today)

        result = await session.execute(
            select(
                DocumentActivity.day,
                func.sum(DocumentActivity.added),
                func.sum(DocumentActivity.removed),
            )
            .where(DocumentActivity.day >= start, DocumentActivity.day <= end)
            .group_by(DocumentActivity.day)
        )
        totals = {day: (int(added or 0), int(removed or 0)) for day, added, removed in result.all()}

        days = []
        total_changes = 0
        cursor = start
        while cursor <= end:
            added, removed = totals.get(cursor, (0, 0))
            days.append({"day": cursor, "added": added, "removed": removed, "total": added + removed})
            total_changes += added + removed
            cursor += timedelta(days=1)

        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        return {
            "days": days,
            "total_changes": total_changes,
            "last_scan_at": config.last_scan_at if config else None,
        }
```

- [ ] **Step 5: Write the schemas**

Create `backend/app/schemas/activity.py`:

```python
import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    id: uuid.UUID
    name: str
    mime_type: str
    web_url: str
    section: str | None
    last_modified_at: datetime | None
    last_author: str | None
    line_count: int | None
    is_present: bool
    last_error: str | None
    last_activity_day: date | None
    last_added: int
    last_removed: int


class SectionRead(BaseModel):
    name: str
    documents: list[DocumentRead]


class HeatmapDay(BaseModel):
    day: date
    added: int
    removed: int
    total: int


class HeatmapRead(BaseModel):
    days: list[HeatmapDay]
    total_changes: int
    last_scan_at: datetime | None


class ScanResult(BaseModel):
    walked: int
```

In `backend/app/schemas/__init__.py`, add:

```python
from app.schemas.activity import DocumentRead, SectionRead, HeatmapDay, HeatmapRead, ScanResult
```

and the five names to `__all__`.

- [ ] **Step 6: Write the router**

Create `backend/app/routers/activity.py`:

```python
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.schemas import HeatmapRead, ScanResult, SectionRead
from app.services.activity_view import ActivityView
from app.services.document_scanner import DocumentScanner
from app.services.google_service import GoogleAccessError

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


@router.get("/documents", response_model=list[SectionRead])
async def list_documents(session: AsyncSession = Depends(get_async_session)):
    return await ActivityView.sections(session)


@router.get("/heatmap", response_model=HeatmapRead)
async def get_heatmap(session: AsyncSession = Depends(get_async_session)):
    return await ActivityView.heatmap(session)


@router.post("/scan", response_model=ScanResult)
async def scan_now(session: AsyncSession = Depends(get_async_session)):
    try:
        walked = await DocumentScanner.scan_all(session)
    except GoogleAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ScanResult(walked=walked)
```

Every path here is a literal, so no route-ordering hazard exists yet — but if a parameterised route is ever added, it must be declared after these three.

- [ ] **Step 7: Register the router**

In `backend/app/main.py`, add `from app.routers import activity as activity_router` beside the other router imports and `app.include_router(activity_router.router)` beside the other registrations.

- [ ] **Step 8: Generate and apply the migration**

Run: `cd backend && PYTHONPATH=. venv/bin/alembic revision --autogenerate -m "add config last scan at"`

Confirm `upgrade()` adds a nullable `last_scan_at` to `config` and `downgrade()` drops it. Then:

Run: `cd backend && PYTHONPATH=. venv/bin/alembic upgrade head`

- [ ] **Step 9: Run the tests**

Run: `cd backend && venv/bin/python -m pytest tests/test_api_activity.py -v`
Expected: PASS, 7 tests

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: PASS apart from the 7 pre-existing `ScriptExecutor` failures.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/activity_view.py backend/app/schemas/activity.py \
        backend/app/schemas/__init__.py backend/app/routers/activity.py \
        backend/app/main.py backend/app/models/config.py \
        backend/app/services/document_scanner.py backend/tests/test_api_activity.py \
        backend/alembic/versions/
git commit -m "feat(activity): expose the activity read model over HTTP"
```

---

### Task 7: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: the three `/api/v1/activity` endpoints from Task 6
- Produces: types `ActivityDocument`, `ActivitySection`, `HeatmapDay`, `Heatmap`; functions `listActivityDocuments`, `getHeatmap`, `scanActivity`

- [ ] **Step 1: Append the types and endpoints**

Add to `frontend/src/lib/api.ts`:

```ts
// Activity
export interface ActivityDocument {
  id: string;
  name: string;
  mime_type: string;
  web_url: string;
  section: string | null;
  last_modified_at: string | null;
  last_author: string | null;
  line_count: number | null;
  is_present: boolean;
  last_error: string | null;
  last_activity_day: string | null;
  last_added: number;
  last_removed: number;
}

export interface ActivitySection {
  name: string;
  documents: ActivityDocument[];
}

export interface HeatmapDay {
  day: string;
  added: number;
  removed: number;
  total: number;
}

export interface Heatmap {
  days: HeatmapDay[];
  total_changes: number;
  last_scan_at: string | null;
}

export const listActivityDocuments = () => request<ActivitySection[]>("/activity/documents");
export const getHeatmap = () => request<Heatmap>("/activity/heatmap");
export const scanActivity = () =>
  request<{ walked: number }>("/activity/scan", { method: "POST" });
```

- [ ] **Step 2: Verify the build**

Run: `cd frontend && npm run build && npm run lint`
Expected: both clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(activity): add activity API client"
```

---

### Task 8: The Activity page

**Files:**
- Create: `frontend/src/components/Activity/ActivityGrid.tsx`
- Create: `frontend/src/components/Activity/DocumentRow.tsx`
- Create: `frontend/src/components/Activity/SectionList.tsx`
- Create: `frontend/src/pages/ActivityPage.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Layout/TabNav.tsx`

**Interfaces:**
- Consumes: everything exported in Task 7, plus `Spinner` from `../ui/Spinner`
- Produces: route `/activity`; components `ActivityGrid`, `DocumentRow`, `SectionList`

This task is read-only. The scan button and the Config field belong to Task 9.

- [ ] **Step 1: Create the grid**

Create `frontend/src/components/Activity/ActivityGrid.tsx`:

```tsx
import type { HeatmapDay } from "../../lib/api";

const CELL = 11;
const GAP = 3;
const STEP = CELL + GAP;
const ROWS = 7;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Four filled steps plus an empty one, so a quiet day is visibly different from a light one. */
function level(total: number, max: number): number {
  if (total <= 0 || max <= 0) return 0;
  return Math.min(4, Math.ceil((total / max) * 4));
}

export function ActivityGrid({ days }: { days: HeatmapDay[] }) {
  if (days.length === 0) return null;

  const max = Math.max(...days.map((d) => d.total));
  const columns = Math.ceil(days.length / ROWS);
  const width = columns * STEP;
  const height = ROWS * STEP;

  // A month label sits above the first column that starts a new month.
  const monthLabels: { x: number; label: string }[] = [];
  let previousMonth = -1;
  for (let column = 0; column < columns; column += 1) {
    const day = days[column * ROWS];
    if (!day) continue;
    const month = new Date(day.day).getMonth();
    if (month !== previousMonth) {
      monthLabels.push({ x: column * STEP, label: MONTHS[month] });
      previousMonth = month;
    }
  }

  return (
    <div className="overflow-x-auto">
      <svg
        width={width + 30}
        height={height + 20}
        role="img"
        aria-label={`Activity over the last 12 months, ${max} lines on the busiest day`}
      >
        {monthLabels.map((m) => (
          <text
            key={`${m.label}-${m.x}`}
            x={m.x + 30}
            y={10}
            fontSize="9"
            fill="var(--text-muted)"
          >
            {m.label}
          </text>
        ))}

        {["Mon", "Wed", "Fri"].map((label, index) => (
          <text
            key={label}
            x={0}
            y={20 + (index * 2 + 1) * STEP - GAP}
            fontSize="9"
            fill="var(--text-muted)"
          >
            {label}
          </text>
        ))}

        {days.map((day, index) => {
          const intensity = level(day.total, max);
          return (
            <rect
              key={day.day}
              x={Math.floor(index / ROWS) * STEP + 30}
              y={(index % ROWS) * STEP + 20}
              width={CELL}
              height={CELL}
              rx={2}
              fill={intensity === 0 ? "var(--bg-elevated)" : "var(--accent)"}
              fillOpacity={intensity === 0 ? 1 : 0.25 * intensity}
            >
              <title>
                {day.day} — +{day.added} −{day.removed}
              </title>
            </rect>
          );
        })}
      </svg>
    </div>
  );
}
```

- [ ] **Step 2: Create the document row**

Create `frontend/src/components/Activity/DocumentRow.tsx`:

```tsx
import type { ActivityDocument } from "../../lib/api";

const DOC_MIME = "application/vnd.google-apps.document";
const SHEET_MIME = "application/vnd.google-apps.spreadsheet";

function typeLabel(mimeType: string): string {
  if (mimeType === DOC_MIME) return "DOC";
  if (mimeType === SHEET_MIME) return "SHEET";
  return "FILE";
}

function relativeDate(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function DocumentRow({ document }: { document: ActivityDocument }) {
  const hasActivity = document.last_activity_day !== null;

  return (
    <div
      className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2"
      style={{ borderBottom: "1px solid var(--border)" }}
    >
      <span
        className="font-mono text-xs"
        style={{ color: "var(--text-muted)", minWidth: "3.2rem" }}
      >
        {typeLabel(document.mime_type)}
      </span>

      <a
        href={document.web_url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex-1 text-sm"
        style={{ color: "var(--text-primary)", minWidth: "12rem" }}
      >
        {document.name}
        {!document.is_present && (
          <span style={{ color: "var(--text-muted)" }}> · removed from the folder</span>
        )}
      </a>

      {hasActivity ? (
        <span className="font-mono text-xs" style={{ whiteSpace: "nowrap" }}>
          <span style={{ color: "var(--success)" }}>+{document.last_added}</span>{" "}
          <span style={{ color: "var(--error)" }}>−{document.last_removed}</span>{" "}
          <span style={{ color: "var(--text-muted)" }}>
            {relativeDate(document.last_activity_day)}
          </span>
        </span>
      ) : (
        <span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
          —
        </span>
      )}

      <span className="text-xs" style={{ color: "var(--text-muted)", minWidth: "9rem" }}>
        {document.last_author ?? "unknown"} · {relativeDate(document.last_modified_at)}
      </span>

      {document.last_error && (
        <span className="w-full text-xs" style={{ color: "var(--error)" }}>
          Read failed — {document.last_error}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create the section list**

Create `frontend/src/components/Activity/SectionList.tsx`:

```tsx
import type { ActivitySection } from "../../lib/api";
import { DocumentRow } from "./DocumentRow";

export function SectionList({ sections }: { sections: ActivitySection[] }) {
  if (sections.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        Nothing tracked yet. Share a Drive folder with the service account, set it in Config, then scan.
      </p>
    );
  }

  return (
    <div className="grid gap-5">
      {sections.map((section) => (
        <div key={section.name} className="card p-5">
          <div className="mb-2 flex items-baseline justify-between">
            <h3
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              {section.name}
            </h3>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {section.documents.length} file{section.documents.length !== 1 ? "s" : ""}
            </span>
          </div>
          {section.documents.map((doc) => (
            <DocumentRow key={doc.id} document={doc} />
          ))}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create the page**

Create `frontend/src/pages/ActivityPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { getHeatmap, listActivityDocuments } from "../lib/api";
import { ActivityGrid } from "../components/Activity/ActivityGrid";
import { SectionList } from "../components/Activity/SectionList";
import { Spinner } from "../components/ui/Spinner";

function relativeDate(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function ActivityPage() {
  const { data: sections = [], isLoading } = useQuery({
    queryKey: ["activity-documents"],
    queryFn: listActivityDocuments,
  });
  const { data: heatmap } = useQuery({ queryKey: ["activity-heatmap"], queryFn: getHeatmap });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <div className="card p-5">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Activity — last 12 months
          </h3>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {heatmap?.total_changes ?? 0} lines changed · last scan{" "}
            {relativeDate(heatmap?.last_scan_at ?? null)}
          </span>
        </div>
        {heatmap && <ActivityGrid days={heatmap.days} />}
      </div>

      <SectionList sections={sections} />
    </div>
  );
}
```

- [ ] **Step 5: Register the route and the tab**

In `frontend/src/App.tsx`, add the import and the route — additive only, do not reorder existing routes:

```tsx
import { ActivityPage } from "./pages/ActivityPage";
```
```tsx
            <Route path="activity" element={<ActivityPage />} />
```

In `frontend/src/components/Layout/TabNav.tsx`, add to `tabs` after Reports:

```tsx
  { to: "/activity", label: "Activity" },
```

- [ ] **Step 6: Verify build and lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Activity frontend/src/pages/ActivityPage.tsx \
        frontend/src/App.tsx frontend/src/components/Layout/TabNav.tsx
git commit -m "feat(activity): add the activity page and contribution grid"
```

---

### Task 9: Scan button and the folder field

**Files:**
- Modify: `frontend/src/pages/ActivityPage.tsx`
- Modify: `frontend/src/components/Config/GoogleConfig.tsx`

**Interfaces:**
- Consumes: `scanActivity`, `getConfig`, `updateConfig`, `MutationError` from `../ui/MutationError`
- Produces: nothing new — this completes the page

- [ ] **Step 1: Add the scan control to the page**

In `frontend/src/pages/ActivityPage.tsx`, add the imports:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getHeatmap, listActivityDocuments, scanActivity } from "../lib/api";
import { MutationError } from "../components/ui/MutationError";
```

Inside the component, before the `isLoading` guard:

```tsx
  const queryClient = useQueryClient();
  const scanMutation = useMutation({
    mutationFn: scanActivity,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["activity-documents"] });
      queryClient.invalidateQueries({ queryKey: ["activity-heatmap"] });
    },
  });
```

Both queries are invalidated because a scan changes what both of them show; refreshing only the list would leave the grid showing yesterday's picture.

Then, in the header card, replace the `<span>` holding the counts with:

```tsx
          <div className="flex items-center gap-3">
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {heatmap?.total_changes ?? 0} lines changed · last scan{" "}
              {relativeDate(heatmap?.last_scan_at ?? null)}
            </span>
            <button
              className="btn-secondary"
              disabled={scanMutation.isPending}
              onClick={() => scanMutation.mutate()}
            >
              {scanMutation.isPending ? "Scanning..." : "Scan now"}
            </button>
          </div>
```

and add, directly under the header row inside the same card:

```tsx
        <MutationError error={scanMutation.error} />
```

- [ ] **Step 2: Add the folder field to Config**

In `frontend/src/components/Config/GoogleConfig.tsx`, add a state value beside the existing ones:

```tsx
  const [folder, setFolder] = useState<string | null>(null);
```

Add the field after the service account key textarea:

```tsx
          <div>
            <label
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Tracked Drive folder
            </label>
            <input
              className="input-field"
              placeholder="Folder id, or paste the folder URL"
              value={folder ?? config?.drive_folder_id ?? ""}
              onChange={(event) => setFolder(event.target.value)}
            />
            <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
              Share this folder with the service account above. Every Doc and Sheet inside it is tracked.
            </p>
          </div>
```

Include it in the mutation payload and reset it on success:

```tsx
    mutationFn: () =>
      updateConfig({
        google_sa_key: saKey || undefined,
        activity_cron: cron ?? undefined,
        drive_folder_id: folder ?? undefined,
      }),
```

and extend the save button's disabled condition so the folder counts as a change:

```tsx
            disabled={mutation.isPending || (!saKey && cron === null && folder === null)}
```

- [ ] **Step 3: Verify build and lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ActivityPage.tsx frontend/src/components/Config/GoogleConfig.tsx
git commit -m "feat(activity): add the scan control and the tracked folder field"
```

---

### Task 10: End-to-end verification and documentation

**Files:**
- Modify: `AGENTS.md`, `CLAUDE.md`

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -v`
Expected: PASS apart from the 7 pre-existing `ScriptExecutor` failures. Record the exact counts.

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && npm run build && npm run lint`
Expected: no TypeScript error, no lint error.

- [ ] **Step 3: Bring the stack up**

Run: `docker compose up --build -d postgres backend`
Then: `curl -s http://localhost:8000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 4: Verify the API against a live container**

```bash
# The old feature must be gone
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/projects
# Expected: 404

# Empty but well-formed
curl -s http://localhost:8000/api/v1/activity/documents
# Expected: []

curl -s http://localhost:8000/api/v1/activity/heatmap | head -c 200
# Expected: a days array, total_changes 0, last_scan_at null

# The grid spans whole weeks
curl -s http://localhost:8000/api/v1/activity/heatmap \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['days']), 'days'); print(d['days'][0]['day'], '->', d['days'][-1]['day'])"
# Expected: 365..372 days, the first a Monday

# Scanning with no folder configured
curl -s -X POST http://localhost:8000/api/v1/activity/scan
# Expected: 400 with detail "No Drive folder configured" (or the key message if no key is set)
```

- [ ] **Step 5: Confirm the cron registered**

Run: `docker compose logs backend | grep -i "activity"`
Expected: a line showing the activity scan scheduled with its cron expression.

- [ ] **Step 6: Update the documentation**

In `AGENTS.md`, replace the Projects bullet in the Project Overview feature list with:

```markdown
- **Activity**: director dashboard. One shared Drive folder is walked daily; every Google Doc and Sheet inside it is exported to text, diffed line-by-line against the previous run, and the daily added/removed counts feed a GitHub-style contribution grid. Only the latest text is stored, so history stays complete while storage stays bounded.
```

and change `Projects` to `Activity` in the frontend page list.

In `CLAUDE.md`, replace the "Prompt → script → execution" sibling sections that mention Projects with an Activity section describing the same flow: walk, extract, diff, accumulate per day, and the read model split between `document_scanner.py` (writes) and `activity_view.py` (reads).

- [ ] **Step 7: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document the activity dashboard"
```

---

## Verification Summary

| Layer | Command | Expectation |
|---|---|---|
| Pure logic | `venv/bin/python -m pytest tests/test_line_diff.py tests/test_text_extraction.py -v` | 23 tests, no I/O |
| Models | `venv/bin/python -m pytest tests/test_document_models.py -v` | 5 tests |
| Scanner | `venv/bin/python -m pytest tests/test_document_scanner.py -v` | 10 tests, Google mocked |
| API | `venv/bin/python -m pytest tests/test_api_activity.py -v` | 7 tests |
| Whole backend | `venv/bin/python -m pytest tests/ -v` | only the 7 known pre-existing failures |
| Frontend | `npm run build && npm run lint` | clean |
| End to end | Task 10 | curl checks as described |
