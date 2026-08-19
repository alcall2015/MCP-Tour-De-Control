# Projects Dashboard — Design Spec

## Overview

Add a `Projects` tab to MCP Tour De Control: a director-facing view that groups Google Docs/Sheets links by project **and** reads live indicators out of those Sheets, so project health is visible without opening any file.

Each project exposes a status (nominal / attention / critical), key metrics with a 7-day trend, a sparkline, and its document links. Two aggregate blocks sit above the project cards: pending decisions collected from all projects, and consolidated budget.

Indicators are read on a daily cron through a Google **service account**, stored as dated snapshots, and rendered from the database — the page never waits on Google.

## Architecture

### Models

**Project**
- `id`: UUID PK
- `name`: String(200)
- `description`: Text, nullable
- `position`: Integer, default 0 — display order
- `stale_days`: Integer, default 14 — days without file modification before "attention"
- `budget_warn_pct`: Integer, default 90 — budget consumption ratio triggering "attention"
- `created_at` / `updated_at`: DateTime(tz)
- `links`: relationship → ProjectLink, cascade all/delete-orphan
- `snapshots`: relationship → ProjectSnapshot, cascade all/delete-orphan

**ProjectLink**
- `id`: UUID PK
- `project_id`: UUID FK → project
- `label`: String(200)
- `url`: Text
- `kind`: String(20) — `doc` | `sheet` | `slide` | `drive` | `other`
- `file_id`: String(100), nullable — Google file id parsed from the URL
- `is_kpi_source`: Boolean, default False — this Sheet carries the SUIVI tab
- `position`: Integer, default 0

**ProjectSnapshot**
- `id`: UUID PK
- `project_id`: UUID FK → project
- `captured_at`: DateTime(tz)
- `metrics`: JSONB, nullable — parsed SUIVI key/value pairs
- `source_modified_at`: DateTime(tz), nullable — Drive `modifiedTime` of the KPI source
- `error`: Text, nullable — read failure message
- Index on `(project_id, captured_at DESC)`

`metrics` is JSONB on purpose: the SUIVI tab is key/value, so the user adds a row in the Sheet and it appears in the UI with no migration and no code change.

**Config** (existing singleton row, two new columns)
- `google_sa_key`: Text, nullable — service account JSON, Fernet-encrypted like `api_key`
- `projects_cron`: String(100), default `0 6 * * *`

API reads expose `google_sa_key_set: bool` only, never the value.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/projects` | List projects with latest snapshot, status and 7-day trends |
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects/{id}` | Project detail with snapshot history |
| PUT | `/api/v1/projects/{id}` | Update project (name, thresholds, position) |
| DELETE | `/api/v1/projects/{id}` | Delete project, its links and snapshots |
| POST | `/api/v1/projects/{id}/links` | Add a link |
| PUT | `/api/v1/projects/links/{link_id}` | Update a link |
| DELETE | `/api/v1/projects/links/{link_id}` | Delete a link |
| POST | `/api/v1/projects/refresh` | Read all KPI sources now, write snapshots |
| POST | `/api/v1/projects/{id}/refresh` | Read one project now |
| GET | `/api/v1/projects/decisions` | Pending decisions across all projects |
| GET | `/api/v1/projects/summary` | Consolidated budget across all projects |

`decisions` and `summary` are static paths and must be declared **before** `/{id}` in the router, otherwise FastAPI matches them as a project UUID and returns 422.

### Google Access

A Google service account key (JSON) is pasted once in Config. The user shares each Google file with the service account email; files stay private and no interactive OAuth or token refresh is involved.

Scopes: `spreadsheets.readonly` and `drive.metadata.readonly` — read-only by construction.

### SUIVI Sheet Contract

Every KPI-source Sheet carries a tab named `SUIVI`, read as range `SUIVI!A:B`:

| A (key) | B (value) |
|---|---|
| avancement | 72 |
| budget_consomme | 8400 |
| budget_total | 12000 |
| prochain_jalon | 2026-08-28 |
| decision_attendue | Arbitrer le renouvellement du contrat X |
| responsable | Fabien |
| risque | moyen |

Parsing rules:
- Keys are normalized: trimmed, lowercased, accents stripped, spaces → underscores.
- Empty rows are skipped. On duplicate keys, the last occurrence wins.
- Numbers accept thousands separators, comma decimals, a trailing `%` and currency symbols (`8 400`, `8,400`, `72%`). Unparsable values are kept verbatim as strings.
- Dates are parsed as ISO `YYYY-MM-DD`; anything else stays a string.

Reserved keys drive the UI: `avancement` (0-100), `budget_consomme`, `budget_total`, `prochain_jalon`, `decision_attendue`, `responsable`, `risque`. **Any other key is stored and displayed as-is**, with a humanized label.

### Status Rules

Evaluated in order, first match wins. Deterministic, no LLM — a budget figure must never depend on an interpretation.

1. Latest snapshot has `error` → **critical** ("read failed")
2. `budget_consomme` > `budget_total` → **critical**
3. `prochain_jalon` is in the past → **critical**
4. `budget_consomme` ≥ `budget_warn_pct`% of `budget_total` → **attention**
5. `source_modified_at` older than `stale_days` → **attention**
6. `avancement` unchanged between the latest snapshot and the most recent snapshot at least 7 days older → **attention** (stagnation). Skipped when no snapshot that old exists.
7. Otherwise → **nominal**

A missing metric skips its rule rather than failing. A project with no `is_kpi_source` link renders as "no source" with a neutral badge and no status.

### Trends

For each numeric metric, the delta is computed between the latest snapshot and the most recent snapshot at least 7 days older (falling back to the oldest available). Metrics with a single snapshot show no trend.

### Refresh and Scheduling

An APScheduler job `projects_refresh` runs `ProjectService.refresh_all()` on `config.projects_cron` (default `0 6 * * *`). It is registered in the FastAPI `lifespan`, alongside the existing prompt cron restore, and rescheduled when `projects_cron` changes in Config. Manual refresh endpoints call the same service function.

Each run writes exactly one snapshot per project that has an `is_kpi_source` link; projects without one are skipped and no snapshot is written for them. A failed read still writes a snapshot, carrying its `error`: the card then shows a warning plus the **last known values with their date**. Stale data is never presented as fresh.

No snapshot purge in v1: one row per project per day is a few thousand rows a year, well below any threshold that would justify retention code.

## Backend

### Google Service (`app/services/google_service.py`)

- `parse_file_id(url)` — extracts the Google file id from a Docs/Sheets/Slides/Drive URL
- `read_suivi(file_id)` — returns the parsed key/value dict from `SUIVI!A:B`
- `get_modified_time(file_id)` — Drive `modifiedTime`
- Credentials built from the decrypted service account JSON; a missing or invalid key raises a typed error surfaced as the snapshot `error`.

### Project Service (`app/services/project_service.py`)

- `refresh_all()` / `refresh_one(project_id)` — read sources, write snapshots
- `compute_status(project, latest, previous)` — the rules above
- `compute_trends(snapshots)` — per-metric deltas
- `pending_decisions()` — non-empty `decision_attendue` across projects
- `budget_summary()` — consumed / total / remaining, all projects

Parsing and status logic live in pure functions with no I/O, so they are testable without network or database.

## Frontend

### New Tab

`Projects` added to `TabNav` — plain text label, no emoji, consistent with the existing nav.

UI strings are in English, per the repo convention that code, docs and UI are English (the French chat assistant being the sole documented exception). The status labels used throughout this spec ("lecture impossible", "aucune source") therefore ship as "read failed" and "no source".

### Layout (`src/pages/ProjectsPage.tsx`)

1. **Pending decisions** — aggregated list, project name + decision text, hidden when empty
2. **Consolidated budget** — consumed / total / remaining with a progress bar
3. **Project cards** — status dot, metrics with trend arrows, sparkline, link chips, last-read timestamp

### Components (`src/components/Projects/`)

`ProjectCard.tsx`, `ProjectForm.tsx`, `LinkList.tsx`, `LinkForm.tsx`, `Sparkline.tsx`, `StatusDot.tsx`, `DecisionsPanel.tsx`, `BudgetSummary.tsx`.

Status is a CSS colored dot with a text label, not an emoji. `Sparkline` is inline SVG — no charting dependency. Data flows through TanStack Query; the refresh mutation invalidates the projects query.

All HTTP calls and shared interfaces go in `src/lib/api.ts`, per repo convention.

### New Dependencies

Backend: `google-api-python-client`, `google-auth`. Frontend: none.

## Alembic Migration

One revision: creates `project`, `project_link`, `project_snapshot` with the `(project_id, captured_at DESC)` index, and adds `google_sa_key` and `projects_cron` to `config`. All three models exported from `app/models/__init__.py`.

## Testing

- `tests/test_suivi_parser.py` — key normalization, number/date parsing, duplicates, empty rows, unparsable values (pure, no I/O)
- `tests/test_project_status.py` — table-driven over the seven rules, including missing metrics and the no-source case
- `tests/test_project_trends.py` — delta computation, single-snapshot and sparse-history cases
- `tests/test_api_projects.py` — CRUD, cascade delete, refresh endpoint with `google_service` mocked at the boundary

No test performs a network call.

## Out of Scope (v2 candidates)

- LLM-written daily briefing over the stored snapshots
- Push alerts (Slack/email) when a project turns critical
- Writing status reports back into a Google Doc
- Per-user OAuth instead of a shared service account

Deferred deliberately: the briefing and alerts are only worth building once the thresholds have been lived with for a few weeks, and they read from the snapshot history rather than from Google — so they cost far less once this spec ships.

## File Structure

```
backend/app/
├── models/project.py               Project, ProjectLink, ProjectSnapshot
├── schemas/project.py              Pydantic schemas
├── routers/projects.py             /api/v1/projects
├── services/google_service.py      Sheets/Drive read access
└── services/project_service.py     refresh, status, trends, aggregates

backend/tests/
├── test_suivi_parser.py
├── test_project_status.py
├── test_project_trends.py
└── test_api_projects.py

frontend/src/
├── pages/ProjectsPage.tsx
└── components/Projects/*.tsx
```
