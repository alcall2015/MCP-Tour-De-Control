# Agent Approvals — Design Spec

Date: 2026-10-26
Status: approved for planning
Builds on: `2026-10-25-agent-execution-design.md` (sub-project 2, merged and deployed)

## Overview

Third sub-project of the autonomous-agents platform. Every MCP tool gets a
risk level; an agent runs tools up to its own ceiling without asking, and
parks its task in `waiting_approval` for anything above it. The exact action
(tool, server, arguments) is recorded as an `approval`, the administrator is
notified on WhatsApp through the existing WhatsApp MCP server, and decides
either in the task page or by replying `OUI <code>` / `NON <code>`. On a
decision the task goes back to the queue and the runner **resumes from the
journal** without replaying anything already done. Undecided approvals
expire and fail the task.

Decisions taken during brainstorming:

| Topic | Decision |
|---|---|
| Risk source | Explicit catalogue `tool_policy` per (server, tool), R0–R3, default **R2** for an unclassified tool |
| Granularity | Tool level is global; each agent has `max_auto_risk` 0–2 (default 1); R3 is never automatic |
| On a gated tool | Park the task (`waiting_approval`), free the worker slot, resume from the journal after the decision |
| Decision channels | Task page buttons **and** WhatsApp reply `OUI|YES|NON|NO <code>` from the configured admin number |
| Notification | `MessageSendText` on the enabled WhatsApp MCP server, French template editable in Settings, default recipient `+2250700003331` |
| Expiry | `approval_expiry_hours` (default 24); expired → approval `expired`, task `failed` with `approval expired` |
| Rejection | The runner injects a tool result `{"error": "rejected by operator: <reason>"}` and the loop continues |

Covers F-009, F-010 (the approval case of resume), REC-07, REC-08, and the
R0–R3 table of section 7 of the cahier des charges. Out of scope: per
agent × tool permission matrix, approvals by e-mail, delegation or
multi-approver rules, resume after a worker crash (sub-project 5), memory
tables (sub-project 4).

## Data model

One Alembic revision chained on `4f5a6b7c8d9e`.

### `tool_policy`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `mcp_server_id` | UUID FK → `mcp_server.id` | `ON DELETE CASCADE` |
| `tool_name` | String(200) | |
| `risk_level` | SmallInteger | CHECK 0..3; default 2 |
| `description` | Text nullable | copied from discovery, refreshed on each sync |
| `first_seen_at`, `updated_at` | DateTime(tz) | |

Unique `(mcp_server_id, tool_name)`. Rows are created on discovery with
`risk_level = 2` and are never deleted automatically; a tool that disappears
from a server keeps its row (harmless) so an edited level survives a flaky
discovery. `tool_policy_service.sync(session, server, tools)` is called by
`McpService.test_connection` consumers (the Settings page, the chat's tool
build) and by the runner's prepare step, and only ever inserts missing rows
or refreshes `description`; it never touches `risk_level`.

### `agent`

Adds `max_auto_risk` SmallInteger, default 1, CHECK 0..2. Exposed on create,
update and read.

### `agent_task`

`status` CHECK gains `waiting_approval`; `OPEN_STATUSES` becomes
`("queued", "running", "waiting_approval")`. `FINAL_STATUSES` is unchanged,
so the partial unique index `uq_agent_task_open_per_agent` (predicate
`status NOT IN (final)`) already covers the new state: one open task per
agent still holds, and cron ticks skip while a task waits.

### `approval`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `task_id` | UUID FK → `agent_task.id` | `ON DELETE CASCADE` |
| `agent_id` | UUID FK → `agent.id` | `ON DELETE CASCADE` |
| `step_seq` | Integer | seq of the `turn` step that requested the call |
| `call_index` | Integer | index of the call inside that turn |
| `tool_name`, `server_name` | String(200) | |
| `args` | JSONB | the exact arguments the model requested |
| `args_hash` | String(64) | sha256 of the canonical JSON of `args` |
| `risk_level` | SmallInteger | the level that triggered the gate |
| `code` | String(6) | upper-case, alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, unique among non-final approvals |
| `status` | String(20) | `pending` / `approved` / `rejected` / `expired`; CHECK |
| `consumed_at` | DateTime(tz) nullable | set when the runner has acted on the decision |
| `requested_at`, `expires_at` | DateTime(tz) | |
| `decided_at` | DateTime(tz) nullable | |
| `decided_by` | String(100) nullable | `ui`, `whatsapp:<digits>`, `system:expiry`, `system:cancel` |
| `decision_reason` | Text nullable | |
| `notified_at` | DateTime(tz) nullable | |
| `notify_error` | Text nullable | |

Indexes: partial `ix_approval_pending (expires_at) WHERE status = 'pending'`;
`ix_approval_task (task_id, step_seq)`. An approval binds one action: same
tool with different arguments is a new approval. A decided approval is
consumed exactly once (`consumed_at`); a second resume attempt for the same
approval is a no-op.

### `Config`

| Field | Default |
|---|---|
| `approval_expiry_hours` | 24 (CHECK 1..168) |
| `approval_whatsapp_enabled` | false |
| `approval_whatsapp_number` | `+2250700003331` |
| `approval_whatsapp_server_id` | null → the enabled `McpServer` whose name contains `whatsapp` (case-insensitive) |
| `approval_whatsapp_session_id` | null → first session reported `ready` by `SessionFindAll` |
| `approval_whatsapp_template` | French text below |

Default template:

```
Approbation requise · {agent}
{tool} sur {server}
{args}
Répondre OUI {code} ou NON {code}
Expire à {expires} · {link}
```

`{args}` is the pretty JSON truncated to 600 characters; `{expires}` is
`HH:MM UTC` of `expires_at`; `{link}` is
`https://<host>/agents/{agent_id}/tasks/{task_id}` with the host taken from
a new setting `PUBLIC_BASE_URL` (default `https://tour.alcall.net`).

### Journal

New step kind `approval_requested` with payload
`{"approval_id", "tool", "server", "args", "risk_level", "code", "expires_at"}`.
When the decision is applied, the resulting `tool_call` step carries
`approval_id`, `risk_level` and, for a rejection, `ok: false` and the
operator's reason inside `result`. Every `tool_call` step now also carries
`risk_level`.

## The gate in the runner

In `prepare`, the runner loads the policy levels for the agent's enabled
servers (`tool_policy_service.levels_for(session, server_map)` →
`dict[tool_name, int]`, syncing missing rows at R2) and the agent's current
`max_auto_risk` (read at run time, not snapshotted: a policy change must
apply to the next call).

Before each tool call: `level = levels.get(tool, 2)`.

- `level <= max_auto_risk` → execute as today; the `tool_call` step records
  `risk_level`.
- otherwise → `ApprovalService.request(session, task, step_seq, call_index,
  tool, server, args, level)` creates the approval (code, `expires_at =
  now + approval_expiry_hours`), writes the `approval_requested` step,
  `AgentTaskService.park(session, task)` sets `waiting_approval` and
  notifies the events channel, the notifier is invoked (errors recorded,
  never raised), and the runner raises `Parked`. `run_task` catches
  `Parked` and returns **without** `finish`: the worker slot is freed, the
  heartbeat stops, and the stale sweep ignores the task because it only
  looks at `running`.

Calls of the same turn that precede the gated one have already executed
and are in the journal; calls after it are re-evaluated at resume time.

## Decision and resume

`ApprovalService.decide(session, approval, status, decided_by, reason)`:

1. 409 unless the approval is `pending`.
2. Sets `status`, `decided_at`, `decided_by`, `decision_reason`.
3. If the task is no longer `waiting_approval` (cancelled meanwhile) → nothing
   else. If the agent is no longer `active` → task `failed` with
   `agent is not active`, approval stays decided and unconsumed.
4. Otherwise `AgentTaskService.resume(session, task)` sets `queued`
   (notifying both channels) in the same transaction. The worker claims it
   like any queued task.

In `prepare`, a task with `step_count > 0` **and** a decided unconsumed
approval runs in **resume mode**:

- History rebuilt from the journal, no LLM call: `messages = last_turn.prompt
  + assistant message built from last_turn.payload (text, tool_calls with
  ids call_{turn_seq}_{i}) + one tool message per tool_call step recorded
  after that turn`, in `seq` order, with the same id scheme.
- `rounds` = number of `turn` steps so far; the deadline restarts:
  `timeout_seconds` bounds each running segment, human waiting time never
  counts.
- For the approved call: execute with `approval.args` exactly (not the
  model's current output), record the `tool_call` step with `approval_id`,
  mark the approval consumed. For a rejected call: record a `tool_call`
  step with `ok: false` and `result = {"error": "rejected by operator: <reason>"}`,
  mark consumed, append the tool message.
- Remaining calls of that turn (index > `call_index`) pass through the gate
  again, which may park the task again. Then the normal loop continues.

Idempotency: if the worker dies between executing the approved tool and
marking the approval consumed, the stale sweep fails the task; the approval
is not replayed (consistent with "nothing is replayed" from sub-project 2).

## Expiry, cancellation, lifecycle

- Scheduler job `approval_expiry` every minute: every `pending` approval
  past `expires_at` → `expired` (`decided_by = system:expiry`), its task →
  `failed` with `error = "approval expired"` and an `error` step.
- `POST /agent-tasks/{id}/cancel` on a `waiting_approval` task → task
  `cancelled` immediately and its pending approval → `expired` with
  `decided_by = system:cancel`.
- Pausing or archiving an agent does not touch a waiting task; the decision
  path above handles an inactive agent.
- `DELETE /agents/{id}` keeps its 409 while a task is open (`waiting_approval`
  is open).

## Notification

`services/approval_notifier.py`, `notify(session, approval) -> None`:

1. Resolve the server: `approval_whatsapp_server_id` or the first enabled
   `McpServer` whose name contains `whatsapp`; none → `notify_error = "no
   WhatsApp MCP server"`.
2. Resolve the session: `approval_whatsapp_session_id` or `SessionFindAll`
   → first entry with status `ready`; none → `notify_error`.
3. `chatId = <digits of approval_whatsapp_number>@c.us`; render the template;
   `call_mcp_tool("MessageSendText", {sessionId, chatId, text}, server)`.
4. On success `notified_at = now()`; on any failure `notify_error = <text>`
   and a warning log. Nothing else depends on the outcome.

Runs inside the worker right after `park`, before `run_task` returns, under
`asyncio.wait_for(…, MCP_TOOL_TIMEOUT_SECONDS)`. Disabled when
`approval_whatsapp_enabled` is false (the approval is still created and
visible in the UI).

## WhatsApp replies

`services/approval_replies.py`, scheduler job `approval_replies` every 60 s
with its own offset in the 15-minute cycle table (interval 1 minute, not
15: it gets its own `IntervalTrigger(minutes=1, start_date=now+20s)`):

1. Short-circuit when `approval_whatsapp_enabled` is false or no approval is
   `pending`.
2. `MessageList(sessionId, chatId = admin JID, limit = 20)`.
3. Keep inbound messages (not `fromMe`) whose timestamp is after the oldest
   pending approval's `requested_at`.
4. Parse `^\s*(OUI|YES|NON|NO)\s+([A-Z0-9]{6})\b` case-insensitively on the
   message body; look up a `pending` approval by code; decide with
   `decided_by = whatsapp:<digits>` and `decision_reason = <message body>`.
   A code that is not pending is ignored, which makes re-reading the same
   messages idempotent without a seen-table.
5. Any error is logged and the tick ends; the next tick retries.

Accepted weakness, stated in Settings next to the toggle: a spoofed sender
plus the code is enough; the code exists only in the outgoing WhatsApp and
in the UI.

## API

| Method | Path | Behaviour |
|---|---|---|
| GET | `/api/v1/approvals?status=pending` | newest first; each item joins `agent_name`, `task_objective`, `seconds_left` |
| POST | `/api/v1/approvals/{id}/approve` | body `{reason?: str}`; 200 `ApprovalRead`; 409 if not pending; `decided_by = ui` |
| POST | `/api/v1/approvals/{id}/reject` | same, `rejected` |
| GET | `/api/v1/mcp-servers/{id}/tools` | discovery result merged with policies: `[{name, description, risk_level}]`; syncs missing rows |
| PUT | `/api/v1/mcp-servers/{id}/tools/{tool_name}` | body `{risk_level: 0..3}`; 200 the policy; 404 unknown server or tool |
| GET/PUT | `/api/v1/config` | the six approval fields (`approval_whatsapp_server_id` as UUID or null) |

`AgentCreate`/`AgentUpdate`/`AgentRead` gain `max_auto_risk`.
`AgentTaskRead` gains `approval: ApprovalRead | null` (the pending one).
SSE protocol unchanged: `waiting_approval` arrives as a `status` event and is
not final, so the page stays subscribed; `queued`/`running` follow after the
decision.

## Frontend

- **Settings → MCP servers**: the tools preview becomes an editable list
  (name, description, R0–R3 select per tool, text filter, "Refresh" to
  re-discover) with the rule text "R0 and R1 run without approval up to the
  agent's ceiling; R2 and R3 require approval."
- **Settings → Approvals**: the six fields; the template textarea lists its
  variables; the toggle carries the spoofing note.
- **Agent form**: "Automatic up to" select — R0 read-only, R1 limited writes
  (default), R2 significant changes — with one explanatory sentence.
- **Task page**: `Waiting approval` badge; an "Approval required" card at the
  top with tool, server, pretty JSON arguments, risk level, code, countdown,
  notification state (sent / failed / disabled), Approve and Reject with an
  optional reason. After the decision the open stream receives `queued`
  then `running` and the card disappears. `approval_requested` steps show
  the decision once taken; `tool_call` steps show a risk badge.
- **Agents page**: a "N approvals pending" strip at the top (agent, tool,
  time left, link); the card's open-task badge reads `Waiting approval`.
  Sidebar status gains "Pending approvals".
- `api.ts`: `Approval`, `ToolPolicy`, `listApprovals`, `approveApproval`,
  `rejectApproval`, `listServerTools`, `setToolPolicy`, config fields,
  `AgentTask.approval`, `Agent.max_auto_risk`.

## Error handling

- Gate failures (policy load error) fail the task with phase `claim`; they
  never silently execute.
- Notifier and reply poller never raise into the runner or the scheduler;
  they record and log.
- Decisions race-safe: `decide` uses a conditional `UPDATE … WHERE status =
  'pending'` and treats zero rows as 409.

## Testing

Backend, live Postgres, fake LLM/tool callables as in sub-project 2:

- Policy sync creates R2 rows, refreshes descriptions, never overwrites an
  edited level; `PUT` validates 0..3; `max_auto_risk` CHECK 0..2.
- Gate: level ≤ ceiling executes; above → approval row, `approval_requested`
  step, task `waiting_approval`, `run_task` returns without `finish`, earlier
  calls of the turn preserved, worker slot freed (worker test).
- Resume: rebuilt history equals the one a continuous run would have sent
  (compare the next turn's stored prompt against a reference run); approved
  executes `approval.args` exactly and marks consumed; rejected injects the
  refusal; a second gated call in the same turn parks again; an approval
  cannot be consumed twice; expiry fails the task; cancel while waiting;
  inactive agent on approve → `failed`.
- Notifier: fake `call_mcp_tool` receives `MessageSendText` with the admin
  JID and a text containing the code; failure sets `notify_error` only.
- Replies: `OUI 4F2A` approves, `non 4f2a` rejects, unknown code ignored,
  message older than the request ignored, re-read idempotent, `fromMe`
  ignored.
- API: approvals list, approve/reject 200 and 409, server tools with
  policy, `PUT` level, config round-trip.

Frontend: lint, build, and one browser pass in production with a read-only
agent capped at R0 that requests an R2 tool, decided once by WhatsApp and
once in the UI.

## Deployment

Migration at startup; no new environment variable except the optional
`PUBLIC_BASE_URL`; all behaviour toggles live in `Config`, WhatsApp
notification off by default until the session is confirmed in Settings.

## Plans

- **3a backend**: migration and models, `tool_policy_service`,
  `approval_service` (request, decide, expire), `park`/`resume`, runner
  gate and resume mode, notifier, reply poller, scheduler jobs, API, config.
- **3b frontend**: API client, Settings tools list and approvals section,
  agent form ceiling, task page approval card and badges, Agents page strip,
  sidebar counter, browser pass.
