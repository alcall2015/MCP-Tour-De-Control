# Agent Execution — Design Spec

Date: 2026-10-25
Status: approved for planning
Builds on: `2026-10-24-agents-crud-design.md` (sub-project 1, merged)

## Overview

Second sub-project of the autonomous-agents platform. An `active` agent can now
be **run**: a task is created (by hand or by cron), queued in Postgres, picked
up by a separate worker process, executed as *plan → tool loop → self-critique
→ report*, and journaled step by step with the exact prompts sent to the model.
The Agents page gains a Run button and a live task page fed by Server-Sent
Events.

Decisions taken during brainstorming:

| Topic | Decision |
|---|---|
| Loop shape | Plan, then ReAct tool loop, then self-critique, then report |
| Triggers | Manual run (with optional objective override) **and** per-agent cron |
| Execution host | Separate worker process; Postgres is the queue (`FOR UPDATE SKIP LOCKED`), no Redis |
| Journal | One row per event (`plan`, `turn`, `tool_call`, `critique`, `report`, `error`), **with the full prompt** on LLM-calling steps |
| Report | Structured JSON; critique scores each success criterion with `met` and a 0–1 confidence; the **code** derives the outcome |
| UI | Everything under the agent: Run on the card, task page on `/agents/:id/tasks/:taskId` |
| Live updates | SSE backed by Postgres `LISTEN` / `NOTIFY` |
| Code sharing | Extract the chat's LLM/tool primitives into `services/llm_runtime.py` |
| LLM | Still the global `Config` provider / model / key |
| Approvals | **None yet.** Every authorised tool executes immediately; sub-project 3 adds risk levels and approvals |

Covers F-003, F-004, F-005, F-011, F-012, F-014 and the cron part of
sub-project 5. Out of scope: approvals, per-tool permissions, memory tables,
workspace on disk, sandbox, resume of interrupted tasks (a lost task is marked
failed, never replayed), retention purge of stored prompts.

## Data model

Single Alembic revision chained on `3e4f5a6b7c8d`.

### `agent` (existing)

Adds `cron_expr` String(100) nullable. Nothing else changes.

### `agent_task`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `agent_id` | UUID FK → `agent.id` | `ON DELETE CASCADE` |
| `trigger` | String(20) | `manual` / `cron`; CHECK |
| `objective` | Text | snapshot: the override or the agent's objective |
| `instructions` | Text | snapshot of `agent.instructions` |
| `max_steps` | Integer | snapshot |
| `timeout_seconds` | Integer | snapshot |
| `status` | String(20) | `queued` / `running` / `completed` / `failed` / `cancelled`; CHECK; default `queued` |
| `outcome` | String(10) nullable | `success` / `partial` / `failed`; CHECK; set with the report |
| `plan` | JSONB nullable | copy of the `plan` step payload |
| `critique` | JSONB nullable | copy of the `critique` step payload |
| `report` | JSONB nullable | copy of the `report` step payload |
| `error` | Text nullable | technical failure reason |
| `cancel_requested` | Boolean | default false |
| `step_count` | Integer | default 0 |
| `tokens_in`, `tokens_out` | Integer | default 0, summed from steps |
| `worker_id` | String(100) nullable | host:pid of the claimer |
| `heartbeat_at` | DateTime(tz) nullable | |
| `created_at`, `started_at`, `finished_at` | DateTime(tz) | `created_at` not null |

Indexes: `ix_agent_task_agent_created (agent_id, created_at DESC)`;
`ix_agent_task_queue (created_at) WHERE status = 'queued'`;
`ix_agent_task_running (agent_id) WHERE status = 'running'` (serves the
per-agent exclusivity check);
`uq_agent_task_open_per_agent (agent_id) UNIQUE WHERE status IN ('queued','running')`
(enforces it).

Snapshots exist so that editing an agent never changes a task already in
flight; the task page shows the snapshot, not the current agent.

`completed` means the loop reached the end and a report exists, whatever the
business outcome. `failed` means a technical failure: exception, LLM
unavailable, invalid plan twice, limits hit and the final phases could not
produce a report, or a lost worker.

### `agent_task_step`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `task_id` | UUID FK → `agent_task.id` | `ON DELETE CASCADE` |
| `seq` | Integer | 1-based, unique with `task_id` |
| `kind` | String(20) | `plan` / `turn` / `tool_call` / `critique` / `report` / `error`; CHECK |
| `payload` | JSONB | kind-specific, see below |
| `prompt` | JSONB nullable | the exact `messages` array sent to the model; present on `plan`, `turn`, `critique`, `report` |
| `tokens_in`, `tokens_out` | Integer nullable | on LLM-calling steps |
| `duration_ms` | Integer nullable | LLM call or tool call duration |
| `created_at` | DateTime(tz) | |

Index `ix_agent_task_step_task_seq (task_id, seq)` (the unique constraint
provides it).

Payloads:

- `plan`: `{"steps": [{"title": str, "tools": [str]}], "success_criteria": [{"id": str, "description": str}], "risks": [str]}`
- `turn`: `{"text": str | null, "tool_calls": [{"name": str, "args": object}]}`
- `tool_call`: `{"tool": str, "server": str, "args": object, "result": str, "ok": bool}` — `result` truncated to `MAX_TOOL_RESULT_LEN` (2000) like the chat
- `critique`: `{"criteria": [{"id": str, "met": bool, "confidence": number, "justification": str}], "limit_hit": "max_steps" | "timeout" | null}`
- `report`: `{"summary": str, "actions": [{"step_seq": int, "description": str}], "evidence": [str], "uncertainties": [str], "next_steps": [str]}`
- `error`: `{"message": str, "phase": "plan" | "loop" | "critique" | "report" | "claim"}`

Prompts never contain secrets: API keys are passed to SDK clients, not to
messages; MCP server keys travel in transport headers (REC-12 holds).

### Notifications

- After every step insert and every status change, the worker runs
  `NOTIFY agent_task_events, '{"task_id": "...", "seq": N, "status": "..."}'`.
- After inserting a task, the API runs `NOTIFY agent_task_queued, '<task_id>'`.

Payloads stay far below the 8000-byte limit; listeners re-read from the DB.

## Queue and worker

`backend/app/worker.py`, started with `python -m app.worker`. Same image and
environment as the backend; `docker-compose.yml` gains a `worker` service.

Settings (via `app.config.settings`): `AGENT_WORKER_CONCURRENCY` (default 2),
`AGENT_TASK_HEARTBEAT_SECONDS` (15), `AGENT_TASK_STALE_SECONDS` (90),
`AGENT_TASK_FINAL_GRACE_SECONDS` (90).

### Claim

```sql
UPDATE agent_task
SET status = 'running', worker_id = :worker_id,
    started_at = now(), heartbeat_at = now()
WHERE id = (
  SELECT t.id FROM agent_task t
  JOIN agent a ON a.id = t.agent_id
  WHERE t.status = 'queued'
    AND NOT EXISTS (SELECT 1 FROM agent_task r
                    WHERE r.agent_id = t.agent_id AND r.status = 'running')
  ORDER BY t.created_at
  FOR UPDATE OF t, a SKIP LOCKED
  LIMIT 1)
RETURNING id;
```

At most one `queued` or `running` task per agent is enforced by the partial
unique index `uq_agent_task_open_per_agent`; the claim query additionally
locks the agent row (`FOR UPDATE OF t, a SKIP LOCKED`) so concurrent claimers
cannot pass the `NOT EXISTS` check together. The worker keeps up to
`AGENT_WORKER_CONCURRENCY` tasks in flight (an `asyncio.Semaphore`), wakes on
`LISTEN agent_task_queued`, and polls every 5 seconds as a fallback.

### Heartbeat and lost workers

While a task runs, the worker updates `heartbeat_at` every
`AGENT_TASK_HEARTBEAT_SECONDS`. A sweep at worker start and then every minute
marks any `running` task whose heartbeat is older than
`AGENT_TASK_STALE_SECONDS` as `failed` with `error = "worker lost"` and an
`error` step. Nothing is replayed: tool calls are not idempotent and resume is
sub-project 5.

### Cancellation

`POST /agent-tasks/{id}/cancel`: a `queued` task becomes `cancelled` at once; a
`running` task gets `cancel_requested = true` and the runner turns it into
`cancelled` at the next check (between loop rounds and between phases). Final
states return 409.

## Shared LLM runtime

`services/llm_runtime.py`, extracted from `chat_service.py` without behaviour
change; the chat imports it and its existing tests are the regression proof.

```python
def clean_schema(schema: dict) -> dict                       # was _clean_schema
async def build_tool_defs(servers: list[McpServer]) -> tuple[list[dict], dict[str, McpServer]]
async def call_llm(provider, model, api_key, messages, tools) -> LlmResult
async def call_mcp_tool(tool_name: str, args: dict, server: McpServer) -> str  # was _call_mcp_tool

@dataclass
class LlmResult:
    text: str
    tool_calls: list[dict]      # [{"name", "args"}]
    tokens_in: int              # 0 when the provider gives no usage
    tokens_out: int
```

`build_tool_defs` flattens names across servers like the chat does; on a
collision the first server wins and a warning is logged.

## Runner

`services/agent_runner.py`: `async def run_task(task_id, *, llm=call_llm, tool=call_mcp_tool, session_factory=async_session)`.
The two callables are injected so tests drive the whole loop without a
provider or an MCP server.

1. **Prepare.** Load task, agent (with servers), global `Config`. No `api_key`
   → `failed` with `error` step, phase `claim`. Build tools from the agent's
   servers that are `enabled` (a disabled server contributes nothing). System
   prompt in English: role, the task objective, the agent's instructions
   verbatim, the output rules of each phase. No language is forced; the agent
   follows its instructions.
2. **Plan.** One call without tools asking for the `plan` JSON. Fences are
   stripped, JSON parsed and shape-checked (`steps` non-empty list,
   `success_criteria` non-empty list with unique ids). Invalid → one retry with
   the parse error quoted; invalid again → `failed`, phase `plan`. Step `plan`
   written, `task.plan` set.
3. **Loop.** Up to `max_steps` rounds with tools. Each round: heartbeat; check
   `cancel_requested` → `cancelled`; check `now() > started_at + timeout_seconds`
   → stop with `limit_hit = "timeout"`; call the model; write a `turn` step;
   for each requested tool, execute it, write a `tool_call` step, append the
   truncated result to the history. A round with no tool call ends the loop.
   Exhausting the rounds sets `limit_hit = "max_steps"`.
4. **Critique.** One call without tools: the plan's criteria, the full
   history, and `limit_hit` when set. Expects the `critique` JSON; invalid →
   one retry; invalid again → `failed`, phase `critique`.
5. **Report.** One call without tools expecting the `report` JSON; same retry
   rule, phase `report`.
6. **Verdict by code.** A criterion counts as met when `met` is true and
   `confidence >= 0.5`. All met → `outcome = success`; none → `failed`; else
   `partial`. Task becomes `completed`, `finished_at` set, token totals summed.

Phases 4 and 5 run even when a limit stopped the loop, within a fixed grace
of `AGENT_TASK_FINAL_GRACE_SECONDS` after the deadline; if they cannot finish,
the task is `failed` with the reason, and every step already written stays
readable. Any unexpected exception anywhere → `error` step and `failed`.

`max_steps` counts loop rounds only; plan, critique and report are extra
calls. Total wall time is therefore bounded by
`timeout_seconds + AGENT_TASK_FINAL_GRACE_SECONDS` plus one in-flight call.

## Cron

- `agent.cron_expr` optional. Scheduler job id `agent_{uuid}`; on tick,
  `_execute_agent_cron(agent_id)` inserts a `queued` task with `trigger =
  "cron"` **if** the agent is `active` and has no task `queued` or `running`;
  otherwise it logs and skips.
- Kept in sync inline, like prompts: `draft/paused → active` with a cron →
  `add_job`; `active → paused/archived` → `remove_job`; `PUT` changing the cron
  of an `active` agent → `reschedule_job` (or add/remove when the cron appears
  or disappears). `main.py` lifespan re-adds jobs for every `active` agent with
  a cron. Jobs use the same `coalesce=True, max_instances=1,
  misfire_grace_time=3600` as prompts.
- The transition table and this synchronisation move from `routers/agents.py`
  into a new `services/agent_service.py`; the router becomes thin again.

## API

Task creation and listing live under the agent; item operations under
`/api/v1/agent-tasks`.

| Method | Path | Behaviour |
|---|---|---|
| POST | `/api/v1/agents/{id}/tasks` | body `{"objective": str \| null}`; 201 with `AgentTaskRead` in `queued`; 404 unknown agent; 409 if the agent is not `active`; 409 if a task of this agent is already `queued` or `running` |
| GET | `/api/v1/agents/{id}/tasks?limit=20&offset=0` | newest first, no steps |
| GET | `/api/v1/agent-tasks/{task_id}` | `AgentTaskDetail`: task plus steps **without** `prompt` |
| GET | `/api/v1/agent-tasks/{task_id}/steps/{seq}` | one step **with** `prompt` |
| GET | `/api/v1/agent-tasks/{task_id}/events` | SSE, see below |
| POST | `/api/v1/agent-tasks/{task_id}/cancel` | 202; 409 if already final |

`AgentRead` gains `cron_expr`, `running_task_id: UUID | null` and
`last_task: {id, status, outcome, finished_at} | null`.

Schemas (`schemas/agent_task.py`): `AgentTaskCreate`, `AgentTaskRead`,
`AgentTaskStepRead` (no prompt), `AgentTaskStepDetail` (with prompt),
`AgentTaskDetail` (`AgentTaskRead` + `steps: list[AgentTaskStepRead]`).

### SSE

`GET /agent-tasks/{task_id}/events` uses the chat's `_sse()` framing. On
connect it sends every existing step as `step` events, then a `status` event.
It then `LISTEN`s on `agent_task_events` and, for each notification about
this task, loads steps with `seq` greater than the last one sent and emits
them, plus a `status` event when the status changed. When the status is
final it emits `done` and closes. If the task is already final on connect it
sends the backlog, `status`, `done`. A keep-alive comment is written every
20 seconds so proxies keep the connection open. Event names: `step`,
`status`, `done`, `error`.

## Frontend

### `api.ts`

Types `AgentTask`, `AgentTaskStep`, `AgentTaskDetail`, `AgentPlan`,
`AgentCritique`, `AgentReport`, `AgentTaskStatus`, `AgentOutcome`;
functions `createAgentTask(agentId, objective?)`, `listAgentTasks(agentId,
params)`, `getAgentTask(taskId)`, `getAgentTaskStep(taskId, seq)`,
`cancelAgentTask(taskId)`, `streamAgentTask(taskId, onEvent)` built on the
same SSE reader the chat uses. `Agent` gains `cron_expr`, `running_task_id`,
`last_task`.

### Agent card

- `Run` button on `active` agents: opens the existing `Modal` with a textarea
  pre-filled with the agent's objective (editable) and a `Start` button. On
  success navigates to the task page.
- While a task runs the card shows a `Running` badge, a `Cancel` button and a
  link to the task.
- Last task summary (status, outcome, relative time) and a `Tasks (N)` toggle
  that expands the five most recent tasks, each linking to its page.

### Agent form

Optional schedule using the `CronPicker` from the Automations page, with a
"No schedule" switch that sends `cron_expr: null`.

### Task page `/agents/:agentId/tasks/:taskId`

- Header: agent name (link back), objective, trigger, status badge, outcome
  badge, started/finished/duration, tokens, `Cancel` while not final.
- A persistent notice: "No approval step yet: every authorised tool runs
  immediately."
- Plan panel: steps and success criteria.
- Timeline: steps in `seq` order; `turn` shows the text, `tool_call` reuses
  the chat's `ToolCallBlock`, `error` is red. Each LLM step has a
  "Show prompt" disclosure that fetches `/steps/{seq}` on demand.
- Critique table: criterion, met, confidence (0–1 as a bar), justification.
- Report panel: summary, actions linking to their step, evidence,
  uncertainties, next steps.
- Live: subscribes to the SSE stream while the status is not final, appends
  steps as they arrive, then unsubscribes.

### Shell

Route added in `App.tsx`. `AppShell`'s page-context lookup matches by path
prefix so `/agents/...` keeps the Agents title.

## Error handling

- Router: 404/409 as above with short English messages naming the state.
- Runner: every failure path writes an `error` step with `phase`, sets
  `task.error`, status `failed`, `finished_at`.
- SSE: a DB error during streaming emits `error` then closes.
- Worker: an exception escaping `run_task` is caught by the worker, logged
  with structlog, and the task is marked `failed` (phase `claim`).

## Testing

Backend (live test Postgres, as today):

- Models: defaults, CHECK constraints, cascade on agent delete, step `seq`
  uniqueness.
- Queue: two concurrent claimers on three queued tasks of two agents get two
  distinct tasks of distinct agents and the third waits; a second task of an
  agent is not claimed while the first runs; stale sweep marks a task with an
  old heartbeat `failed` and leaves a fresh one alone.
- Runner (fake `llm` and `tool` callables): nominal plan → two tool rounds →
  critique → report, with step kinds, seqs, prompts and token sums asserted;
  `max_steps` hit sets `limit_hit`; timeout hit; cancel between rounds →
  `cancelled`; invalid plan twice → `failed` phase `plan`; outcome derivation
  for all-met / none / mixed / low confidence; tool failure recorded with
  `ok = false` and the loop continues; disabled server contributes no tool.
- API: create 201 / 404 / both 409s; list; detail has no prompts; step
  detail has the prompt; cancel on queued, running, final; SSE backlog then
  `done` for a final task.
- Cron: tick inserts a `queued` task; tick skips when one is queued; job
  added on activation and removed on pause.
- `llm_runtime`: the existing chat tests stay green after the extraction.

Frontend: `npm run lint`, `npm run build`, and one manual end-to-end run in
the browser against a real dev MCP server.

## Deployment

- `docker-compose.yml`: `worker` service (same build, `command: python -m
  app.worker`, same env, depends on postgres). Production:
  `docker compose up --build -d backend worker frontend`.
- New settings with defaults, so no `.env` change is required.
- Stored prompts grow the database; a retention purge is planned with
  sub-project 4, not here.

## Plans

One spec, two implementation plans executed in order:

- **2a backend**: `llm_runtime` extraction, migration and models, queue and
  worker, runner, `agent_service` with cron, task API and SSE, compose.
- **2b frontend**: API client, card and form changes, task page, shell
  routing, browser check.
