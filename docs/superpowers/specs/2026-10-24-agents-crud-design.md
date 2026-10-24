# Agents (creation and lifecycle) — Design Spec

Date: 2026-10-24
Status: approved for planning

## Overview

First sub-project of the autonomous-agents platform described in
`cahier_des_charges_plateforme_agents_ia_mcp.docx`. It delivers the page where a
user defines an autonomous agent — name, objective, instructions, allowed MCP
servers, execution limits — and manages its lifecycle. **Nothing executes in this
version.** The data model is shaped so that the next sub-projects (execution,
approvals, memory) attach to it without a data migration.

Decisions taken during brainstorming:

| Topic | Decision |
|---|---|
| Scope | CRUD + lifecycle only, no task execution |
| Tool granularity | Per MCP server (reuse `McpServer` rows), not per tool |
| LLM model | Inherited from the global `Config` at run time; no per-agent field |
| Lifecycle | Full `draft / active / paused / archived` from day one |
| Versioning | None; edits are in place |
| Limits | `max_steps` and `timeout_seconds` only |
| UI | New "Agents" tab, list page + modal form |
| Server link | Association table with FK cascades |

Covers requirements F-001, F-005 (the authorised-server allowlist), REC-01.
Everything else in the cahier des charges is a later sub-project:

1. **Agents** (this spec)
2. Execution: tasks, tool loop reusing `chat_service`, tool-call journal, report
3. Approvals: per-tool `risk_level`, `waiting_approval`, approve/deny screen
4. Memory and workspace: observations, hypotheses, validated solutions, project folders
5. Sandbox, cron-triggered agents, resume after interruption

## Data model

New file `backend/app/models/agent.py`, exported from `app/models/__init__.py`.

### `agent`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `uuid.uuid4` default |
| `name` | String(200) | required |
| `objective` | Text | required; what the agent is for |
| `instructions` | Text | the agent's system prompt; may be empty string |
| `description` | Text nullable | free-form note for humans |
| `status` | String(20) | `draft` / `active` / `paused` / `archived`; default `draft`; DB CHECK constraint |
| `max_steps` | Integer | default 20; DB CHECK 1..100 |
| `timeout_seconds` | Integer | default 300; DB CHECK 10..3600 |
| `created_at` | DateTime(tz) | same pattern as `Prompt` |
| `updated_at` | DateTime(tz) | `onupdate` like `Prompt` |

### `agent_mcp_server`

| Column | Type | Notes |
|---|---|---|
| `agent_id` | UUID FK → `agent.id` | `ON DELETE CASCADE` |
| `mcp_server_id` | UUID FK → `mcp_server.id` | `ON DELETE CASCADE` |

Composite primary key `(agent_id, mcp_server_id)`. Exposed as
`Agent.mcp_servers: list[McpServer]` through a `secondary=` relationship, loaded
with `selectinload`. Deleting an MCP server silently drops the authorisation;
nothing else references the link.

### Migration

One Alembic revision creating both tables and the CHECK constraints. It must
chain on whatever the head is when implementation starts — the working tree
currently holds two uncommitted revisions (`0a1b2c3d4e5f`, `0b1c2d3e4f5a`) that
should be committed or stashed first. Strip the spurious index/`apscheduler_jobs`
drops that autogenerate always proposes (see CLAUDE.md).

## Status transitions

The only business logic in this sub-project. Lives in the router (pure CRUD, no
`agent_service.py` yet — that file arrives with execution).

| From | To | Rule |
|---|---|---|
| `draft` | `active` | requires at least one authorised server with `enabled = true`, else 400 |
| `active` | `paused` | always |
| `paused` | `active` | same server requirement as `draft → active` |
| any non-archived | `archived` | always |
| `archived` | `draft` | restore |
| anything else | | 409 Conflict |

Additional rules:

- `POST` always creates in `draft`; the client cannot choose a status.
- `PUT /{id}` on an `archived` agent returns 409; restore it first.
- `DELETE /{id}` is allowed only for `draft` and `archived`; `active` and
  `paused` return 409 (archive instead).
- The server requirement is checked only on the transition, not continuously:
  disabling an MCP server later leaves the agent `active`. The UI shows the
  server as disabled; the execution sub-project will decide what a run does.

## API

`backend/app/routers/agents.py`, `APIRouter(prefix="/api/v1/agents", tags=["agents"])`,
included from `main.py` next to the other routers. Schemas in
`backend/app/schemas/agent.py`, exported from `app/schemas/__init__.py`.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `` | `?status=` optional | `list[AgentRead]`; default excludes `archived`; `?status=archived` lists only those; any other value filters exactly |
| POST | `` | `AgentCreate` | `AgentRead`, 201 |
| GET | `/{id}` | | `AgentRead`, 404 |
| PUT | `/{id}` | `AgentUpdate` | `AgentRead`; 404, 409 if archived |
| DELETE | `/{id}` | | 204; 404; 409 if active/paused |
| PUT | `/{id}/status` | `AgentStatusUpdate` | `AgentRead`; 400 / 404 / 409 |

Schemas:

```python
class AgentServerRef(BaseModel):   # denormalised so the list needs no second call
    id: uuid.UUID
    name: str
    enabled: bool

class AgentCreate(BaseModel):
    name: str                       # min_length=1
    objective: str                  # min_length=1
    instructions: str = ""
    description: str | None = None
    max_steps: int = 20             # ge=1, le=100
    timeout_seconds: int = 300      # ge=10, le=3600
    mcp_server_ids: list[uuid.UUID] = []

class AgentUpdate(BaseModel):       # every field optional; mcp_server_ids replaces the whole set
    name: str | None = None
    objective: str | None = None
    instructions: str | None = None
    description: str | None = None
    max_steps: int | None = None
    timeout_seconds: int | None = None
    mcp_server_ids: list[uuid.UUID] | None = None

class AgentStatusUpdate(BaseModel):
    status: Literal["draft", "active", "paused", "archived"]

class AgentRead(BaseModel):
    id, name, objective, instructions, description, status,
    max_steps, timeout_seconds, created_at, updated_at,
    mcp_servers: list[AgentServerRef]
```

Unknown `mcp_server_ids` return 404 with the offending id, matching Prompts.
Pydantic enforces the numeric bounds before the DB CHECK does; both exist so a
future writer that bypasses the API still cannot store an invalid row.

## Frontend

### Navigation

- `TabNav.tsx`: new tab `{ to: "/agents", label: "Agents", eyebrow: "Autonomous runs", icon: "agent" }`
  inserted after Automations and before Reports. The "Automate" section becomes
  four entries (`tabs.slice(0, 4)`), the following slices shift accordingly;
  `primaryTabs` for the mobile bar stays the first four.
- New inline SVG icon `agent`, same stroke style as the others. No emoji.
- `SystemStatus` gains a third line "Active agents" counting `status === "active"`
  from `listAgents()`.
- `App.tsx`: `<Route path="agents" element={<AgentsPage />} />`.

### `api.ts`

```ts
export type AgentStatus = "draft" | "active" | "paused" | "archived";
export interface AgentServerRef { id: string; name: string; enabled: boolean }
export interface Agent { id; name; objective; instructions; description: string | null; status: AgentStatus;
  max_steps: number; timeout_seconds: number; created_at; updated_at; mcp_servers: AgentServerRef[] }
export interface AgentCreate { name; objective; instructions?; description?; max_steps?; timeout_seconds?; mcp_server_ids: string[] }
export type AgentUpdate = Partial<AgentCreate>;
listAgents(status?: AgentStatus): Promise<Agent[]>
createAgent(data: AgentCreate): Promise<Agent>
updateAgent(id: string, data: AgentUpdate): Promise<Agent>
deleteAgent(id: string): Promise<void>
setAgentStatus(id: string, status: AgentStatus): Promise<Agent>
```

Query key `["agents", status]`; every mutation invalidates `["agents"]`.

### `pages/AgentsPage.tsx`

- Header identical to `PromptsPage`: accent bar, title "Agents", `+ New Agent`
  button (`btn-primary`).
- Segmented filter `Active | Archived` under the header. "Active" calls
  `listAgents()` (default, i.e. everything but archived); "Archived" calls
  `listAgents("archived")`.
- Renders `AgentList`, and `AgentFormModal` when creating or editing.
- Empty state: "No agents yet" plus a create button.

### `components/Agents/AgentList.tsx` and `AgentCard.tsx`

Each card shows: name, status badge, objective clamped to two lines, chips for
authorised servers (a disabled server is struck through with a "disabled"
hint), limits as `20 steps · 300 s`, relative `updated_at`.

Badge colours reuse existing tokens: `draft` neutral, `active` live (green),
`paused` warm (amber), `archived` muted.

Actions by status:

| Status | Buttons |
|---|---|
| `draft` | Activate · Edit · Delete |
| `active` | Pause · Edit · Archive |
| `paused` | Resume · Edit · Archive |
| `archived` | Restore · Delete |

Delete asks for confirmation inline (two-step button, no `window.confirm`).
A 400/409 from the API is shown under the card with `MutationError`.

### `components/ui/Modal.tsx` (new primitive)

Props `{ open, title, onClose, children }`. Full-screen overlay, centred
`card-elevated` panel, `role="dialog"` + `aria-modal="true"`, closes on Escape,
overlay click and a Close button, moves focus to the first focusable element on
open and restores it on close, internal scroll when taller than the viewport,
full-screen on narrow widths. The accompanying `.modal-overlay` / `.modal-panel`
rules are the only addition to `index.css`.

### `components/Agents/AgentFormModal.tsx`

One component for create and edit (`agent?: Agent` prop pre-fills). Fields, in
order:

1. Name (text, required)
2. Objective (textarea, required)
3. Instructions (textarea; placeholder explains it is the agent's system prompt)
4. Description (text, optional)
5. Authorised MCP servers — checkbox list fed by `listMcpServers()`, same data
   source as `PromptForm`; disabled servers remain selectable but are labelled
   "disabled"
6. Max steps and Timeout (s) side by side, with the bounds shown as helper text

Client validation mirrors the API: non-empty name and objective, limits within
bounds. Save is disabled while invalid or while the mutation is pending. On
success the modal closes and the list refreshes.

## Error handling

- Router raises `HTTPException` with the codes above; messages are short English
  sentences the UI displays verbatim.
- Transition errors name both states (`"Cannot move agent from active to draft"`).
- Activation failure says why (`"Agent needs at least one enabled MCP server"`).

## Testing

`backend/tests/test_api_agents.py`, modelled on `test_api_prompts.py` (live test
Postgres, tables created per test by `conftest.py`):

- create returns 201 in `draft` with denormalised servers
- create with an unknown server id returns 404
- `PUT` with `mcp_server_ids` replaces the whole set
- each valid transition succeeds; each invalid one returns 409
- `draft → active` with no enabled server returns 400; with one enabled server succeeds
- `PUT` on an archived agent returns 409
- `DELETE` on `active` returns 409; on `draft` and `archived` returns 204
- default list excludes archived; `?status=archived` returns only archived
- deleting an MCP server removes it from the agent's `mcp_servers`
- bounds: `max_steps=0` and `timeout_seconds=5000` are rejected with 422

Frontend has no test suite; `npm run lint` and `npm run build` are the checks.

## Out of scope (explicit)

Task execution, tool-call journal, reports, per-tool permissions and risk
levels, approvals, configuration versions, per-agent model or API key,
scheduler jobs, workspaces on disk, memory tables. Each is a later spec.
