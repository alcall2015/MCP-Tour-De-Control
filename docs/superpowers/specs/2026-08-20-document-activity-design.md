# Document Activity — Design Spec

## Overview

Replace the Projects tab with an `Activity` tab: a flat, zero-configuration view of the Google Docs and Sheets inside one shared Drive folder, showing how much each file changed each day and a GitHub-style contribution grid over the last 12 months.

The Projects tab required the user to hand-maintain a `SUIVI` key/value tab in every project Sheet. That discipline will not be sustained. This design derives its signal from the documents themselves: the user works normally, and the activity appears.

## What This Removes

Deleted: the `Projects` nav tab and route, `frontend/src/pages/ProjectsPage.tsx`, every component under `frontend/src/components/Projects/`, `app/routers/projects.py`, `app/services/project_service.py`, `app/services/project_status.py`, `app/utils/suivi_parser.py`, `app/schemas/project.py`, `app/models/project.py`, and their tests. A migration drops `project`, `project_link` and `project_snapshot`.

`app/services/google_service.py` is retained but loses `read_suivi`, which existed only to parse the SUIVI tab; it keeps credential handling, client construction, `parse_file_id` and `detect_kind`, and the new `text_extractor.py` builds on its clients.

Also retained as the substrate for this feature: the Google service account and its encrypted key, the APScheduler cron wiring, the shared `MutationError` component, and the error discipline — a file that cannot be read records its error instead of vanishing.

## Architecture

### Google Access

The service account scopes widen from `spreadsheets.readonly` + `drive.metadata.readonly` to **`spreadsheets.readonly` + `drive.readonly`**. Reading a document's text is what a real diff requires; there is no narrower scope that permits it.

Consequence the user has accepted: the application can read the content of everything shared with the service account, and the current text of each tracked file is stored in the application's own Postgres.

The user shares ONE root folder with the service account. Nothing else is configured.

### Models

**TrackedDocument**
- `id`: UUID PK
- `file_id`: String(100), unique — the Google file id
- `name`: String(500)
- `mime_type`: String(100) — Google's value; `application/vnd.google-apps.document` or `...spreadsheet` are diffable, anything else is listed only
- `section`: String(500), nullable — the name of the root folder's immediate subfolder this file descends from; `null` for files sitting directly in the root, which render together in a trailing section labelled "Ungrouped"
- `web_url`: Text
- `last_modified_at`: DateTime(tz), nullable — Drive `modifiedTime`
- `last_author`: String(200), nullable — Drive `lastModifyingUser.displayName`
- `line_count`: Integer, nullable — lines in the most recent successful extraction
- `is_present`: Boolean, default True — False once the file leaves the folder
- `last_error`: Text, nullable
- `created_at` / `updated_at`: DateTime(tz)

**DocumentContent** — the latest extraction only, never a history
- `document_id`: UUID FK → tracked_document, unique, cascade delete
- `text`: Text
- `captured_at`: DateTime(tz)

**DocumentActivity** — one row per document per day that actually changed
- `id`: UUID PK
- `document_id`: UUID FK → tracked_document, cascade delete
- `day`: Date — the UTC date of the scan
- `added`: Integer
- `removed`: Integer
- `author`: String(200), nullable
- Unique constraint on `(document_id, day)`; index on `(day)`

Days with no change produce no row. The grid fills the gaps with zero.

**Config** (existing singleton row)
- `drive_folder_id`: String(100), default `""` — the shared root folder
- `projects_cron` is renamed `activity_cron` by the same migration, keeping its stored value and its `0 6 * * *` default
- `google_sa_key` and `google_sa_email` are unchanged

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/activity/documents` | Sections, each with its documents and their latest daily change |
| GET | `/api/v1/activity/heatmap` | One entry per day covering exactly the grid's span: from the Monday 52 weeks before the current week through today — 53 aligned columns, so the grid never renders a partial first column |
| POST | `/api/v1/activity/scan` | Run a scan now |

`heatmap` is a static path and must be declared before any parameterised route added later.

### Text Extraction

- **Google Doc** — `drive.files().export(fileId, mimeType="text/plain")`, split on newlines.
- **Google Sheet** — the tab list from `spreadsheets().get`, then `values().batchGet` across every tab. Each spreadsheet row becomes one text line, cells joined by tabs, prefixed by the tab name so a row moving between tabs reads as a change. This covers all tabs; Drive's CSV export would silently return only the first.
- **Anything else** — listed with its metadata, never extracted, rendered as `—`.

Trailing whitespace is stripped per line; trailing blank lines are dropped, so an editor adding empty paragraphs at the end does not register as activity.

### Diff

`difflib.SequenceMatcher` over the two line lists, walking `get_opcodes()`:
- `insert` → `added += len(new lines)`
- `delete` → `removed += len(old lines)`
- `replace` → `added += len(new)`, `removed += len(old)`
- `equal` → ignored

Pure stdlib, no new dependency. The function takes two lists of strings and returns `(added, removed)` — no I/O, independently testable.

**A newly discovered file records no activity.** Its text is stored as the baseline and no `DocumentActivity` row is written. Counting a pre-existing file's whole content as "added" on the day it was shared would put a false spike in the grid.

### Scan Flow

1. Read `Config`: the service account key and `drive_folder_id`. Either missing raises `GoogleAccessError`, surfaced as HTTP 400.
2. Walk the folder recursively. Each file's `section` is the name of the root's immediate subfolder it descends from.
3. Cap the walk at **500 files**. If the cap is hit, stop and `log.warning` the count skipped — a silent truncation would present partial coverage as complete.
4. For each diffable file: extract text, compare to the stored content, write a `DocumentActivity` row when either count is non-zero, then replace the stored content.
5. Files previously tracked but absent from the walk are marked `is_present = False`. **Their activity history is kept** — deleting it would rewrite the past of the grid.
6. One commit at the end of the run.

Every Google call is synchronous and goes through `asyncio.to_thread`. A per-file failure records `last_error`, leaves the stored content untouched, and the walk continues to the next file.

### Scheduling

The APScheduler job is renamed `activity_scan`, driven by `config.activity_cron`, registered in `lifespan` and rescheduled when the cron changes. The cron is validated by the existing `is_valid_cron` before being persisted.

## Frontend

### Layout (`src/pages/ActivityPage.tsx`)

1. **Header** — the total number of lines changed over 12 months, the date of the last scan, and a "Scan now" button.
2. **Grid** — 53 columns × 7 rows of inline SVG, one cell per day, five intensity steps derived from `--accent` against `--bg-elevated`. Month labels along the top, weekday labels down the left. Each cell carries a `<title>` giving the date and the counts.
3. **Sections** — one per folder, each listing its documents: name linking to the file, a `DOC` / `SHEET` / `FILE` type label, `+142 −5` taken from its most recent `DocumentActivity` row together with that row's date (so a file last touched three days ago reads "+142 −5 · il y a 3 j", never today's silence dressed as change), the last author, and the relative date of the last modification.

Documents sort by last modification, most recent first. Sections sort by their most recently modified document.

### Components (`src/components/Activity/`)

`ActivityGrid.tsx`, `DocumentRow.tsx`, `SectionList.tsx`, `ScanButton.tsx`. All presentational except the page, which owns the two queries and the scan mutation. Types and calls go in `src/lib/api.ts` as always.

Type labels are text, not emoji. No new colour outside the existing custom properties. No new npm dependency — the grid is hand-written SVG.

### Config panel

`GoogleConfig.tsx` gains a field for the root folder id, accepting either a raw id or a pasted Drive folder URL, from which the id is extracted server-side by the existing `parse_file_id`.

## Error Handling

- No key or no folder configured → 400 with a message naming what is missing.
- A file that fails extraction → `last_error` stored, its row rendered with a warning and its previous counts intact; it stays in the totals.
- A scan that fails entirely → the error surfaces on the page through `MutationError`; the previous data remains displayed.

## Testing

- `test_line_diff.py` — the diff counter: insertions, deletions, replacements, identical input, empty input, whole-file rewrite (must read as `+n −m`, not zero).
- `test_text_extraction.py` — Doc export and Sheet tab joining, with the Google client mocked; trailing-blank-line handling.
- `test_document_scanner.py` — first sighting writes a baseline and no activity row; a changed file writes one row; an unchanged file writes none; a vanished file is marked absent and keeps its history; a per-file failure does not abort the walk; the 500-file cap logs what it skipped.
- `test_api_activity.py` — the three endpoints, including 400 when the folder is unconfigured, and the heatmap filling absent days with zero.

No test performs a network call.

## Out of Scope

Per-folder grids, per-author breakdowns, a single-document detail view, period filters, and any comparison window other than day-over-day. Each is easy to add once the page has been lived with.

## File Structure

```
backend/app/
├── models/document.py            TrackedDocument, DocumentContent, DocumentActivity
├── schemas/activity.py           Pydantic schemas
├── routers/activity.py           /api/v1/activity
├── utils/line_diff.py            pure added/removed counter
├── services/text_extractor.py    Doc and Sheet text extraction
└── services/document_scanner.py  walk, diff, persist

frontend/src/
├── pages/ActivityPage.tsx
└── components/Activity/*.tsx
```
