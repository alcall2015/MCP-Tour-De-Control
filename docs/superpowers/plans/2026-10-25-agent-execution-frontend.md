# Agent Execution (2b, frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user run an `active` agent from its card (with an optional objective override), give it a cron schedule in the form, and follow a task live on `/agents/:agentId/tasks/:taskId`: plan, step timeline with on-demand prompts, critique table and report, streamed over SSE until the task is final.

**Architecture:** All HTTP and types stay in `frontend/src/lib/api.ts`, including a generic SSE frame reader shared with the chat and a `streamAgentTask` helper driven by an `AbortController`. The Agents page gains a Run modal and per-card task summaries; a new page composes four presentational panels (plan, timeline, critique, report) around a small hook that merges the initial task fetch with the live stream. No new dependencies.

**Tech Stack:** React 19, TanStack Query 5, react-router 7, Tailwind v4 utilities over the existing `index.css` classes (`card`, `badge`, `btn-*`, `input-field`, `modal-*`), `cronstrue` via the existing `CronPicker`. Checks are `npm run lint` and `npm run build` (no frontend test suite), plus one manual browser run.

Spec: `docs/superpowers/specs/2026-10-25-agent-execution-design.md` (Frontend section). Backend 2a is merged and deployed; the API is live.

## Global Constraints

- Branch `feat/agent-execution-ui` from `main` (clean checkout). Conventional Commits `feat(agents): ...`, every commit ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Stage named paths only; never `git add -A`.
- Frontend commands from `frontend/`: `npm run lint` (oxlint; two pre-existing `no-useless-escape` warnings in `PairingPage.tsx` are known) and `npm run build` (`tsc -b && vite build`, the type check). No new warnings or errors.
- All HTTP calls and shared interfaces go in `frontend/src/lib/api.ts`; no ad-hoc `fetch` in components except through helpers defined there. Routes are declared in `src/App.tsx` under the single `AppShell` layout.
- UI copy in English, no emojis. The chat's `ToolCallBlock` has French labels and is **not** reused; the task page gets its own English tool-call block.
- API contract (from 2a): `POST /api/v1/agents/{id}/tasks` `{objective: string | null}` → 201 task, 409 when not `active` or a task is already open; `GET /api/v1/agents/{id}/tasks?limit&offset`; `GET /api/v1/agent-tasks/{id}` (steps without `prompt`); `GET /api/v1/agent-tasks/{id}/steps/{seq}` (with `prompt`); `POST /api/v1/agent-tasks/{id}/cancel` → 202; `GET /api/v1/agent-tasks/{id}/events` SSE with events `step`, `status` (`{status, outcome, error, finished_at}`, status may be `"gone"`), `done`, `error`. `Agent` now carries `cron_expr`, `running_task_id`, `last_task {id, status, outcome, finished_at} | null`; `AgentCreate`/`AgentUpdate` accept `cron_expr: string | null`.
- Task statuses `queued | running | completed | failed | cancelled`; outcomes `success | partial | failed`; step kinds `plan | turn | tool_call | critique | report | error`. Final statuses: `completed`, `failed`, `cancelled`.
- A persistent notice on the task page: "No approval step yet: every authorised tool runs immediately."
- Query keys: `["agents", ...]` for agents (already used by the list and the sidebar counter), `["agent-tasks", agentId]` for an agent's task list, `["agent-task", taskId]` for a task detail. Every mutation that creates or cancels a task invalidates `["agents"]` and the relevant task keys.

## File Structure

| Path | Responsibility |
|---|---|
| `frontend/src/lib/api.ts` | task types, five task functions, generic `parseSSE`, `streamAgentTask`; `Agent` gains three fields |
| `frontend/src/components/Agents/AgentFormModal.tsx` | cron schedule field with "No schedule" switch |
| `frontend/src/components/Agents/RunAgentModal.tsx` | objective override + Start, navigates to the task page |
| `frontend/src/components/Agents/AgentTaskBadges.tsx` | `TaskStatusBadge`, `OutcomeBadge`, shared colours |
| `frontend/src/components/Agents/AgentTaskRow.tsx` | one compact task line for the card's recent-tasks list |
| `frontend/src/components/Agents/AgentCard.tsx` | Run / Running+Cancel, last task, recent tasks toggle |
| `frontend/src/components/Agents/AgentList.tsx` | wires Run modal and cancel into the card |
| `frontend/src/components/Agents/useAgentTaskStream.ts` | hook: initial fetch merged with the SSE stream until final |
| `frontend/src/components/Agents/TaskPlan.tsx` | plan panel |
| `frontend/src/components/Agents/TaskTimeline.tsx` | ordered steps, `StepCard` with prompt disclosure, English tool-call block |
| `frontend/src/components/Agents/TaskCritique.tsx` | criteria table with confidence bars |
| `frontend/src/components/Agents/TaskReport.tsx` | summary, actions (links to steps), evidence, uncertainties, next steps |
| `frontend/src/pages/AgentTaskPage.tsx` | route component: header, notice, panels, cancel |
| `frontend/src/App.tsx` | route `agents/:agentId/tasks/:taskId` |
| `frontend/src/components/Layout/AppShell.tsx` | page context by path prefix |
| `CLAUDE.md` | one sentence on the task page and the stream helper |

---

### Task 1: API client — task types, functions, generic SSE reader

**Files:**
- Modify: `frontend/src/lib/api.ts` (Agents block near line 86; `Agent` types near line 270; SSE helpers near line 440)

**Interfaces:**
- Produces:
  ```ts
  export type AgentTaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
  export type AgentOutcome = "success" | "partial" | "failed";
  export type StepKind = "plan" | "turn" | "tool_call" | "critique" | "report" | "error";
  export const FINAL_TASK_STATUSES: ReadonlySet<string>;
  export interface AgentTaskSummary { id: string; status: AgentTaskStatus; outcome: AgentOutcome | null; finished_at: string | null }
  export interface AgentPlan { steps: { title: string; tools: string[] }[]; success_criteria: { id: string; description: string }[]; risks: string[] }
  export interface AgentCritique { criteria: { id: string; met: boolean; confidence: number; justification: string }[]; limit_hit: "max_steps" | "timeout" | null }
  export interface AgentReport { summary: string; actions: { step_seq: number; description: string }[]; evidence: string[]; uncertainties: string[]; next_steps: string[] }
  export interface AgentTask  // all task columns of the API's AgentTaskRead (full definition in Step 2)
  export interface AgentTaskStep { seq; kind: StepKind; payload: Record<string, unknown>; tokens_in; tokens_out; duration_ms; created_at }
  export interface AgentTaskStepDetail extends AgentTaskStep { prompt: Record<string, unknown>[] | null }
  export interface AgentTaskDetail extends AgentTask { steps: AgentTaskStep[] }
  export interface TaskStatusEvent { status: AgentTaskStatus | "gone"; outcome: AgentOutcome | null; error: string | null; finished_at: string | null }
  export type AgentTaskEvent = { event: "step"; data: AgentTaskStep } | { event: "status"; data: TaskStatusEvent } | { event: "done"; data: Record<string, never> } | { event: "error"; data: { message: string } };
  export const createAgentTask: (agentId: string, objective: string | null) => Promise<AgentTask>;
  export const listAgentTasks: (agentId: string, params?: { limit?: number; offset?: number }) => Promise<AgentTask[]>;
  export const getAgentTask: (taskId: string) => Promise<AgentTaskDetail>;
  export const getAgentTaskStep: (taskId: string, seq: number) => Promise<AgentTaskStepDetail>;
  export const cancelAgentTask: (taskId: string) => Promise<AgentTask>;
  export function parseSSE(reader, onEvent: (event: string, data: Record<string, unknown>) => void): Promise<void>;
  export function streamAgentTask(taskId: string, onEvent: (e: AgentTaskEvent) => void, signal: AbortSignal): Promise<void>;
  ```
  The existing `parseSSEStream` keeps its signature and becomes a thin wrapper over `parseSSE`, so the chat is untouched.

- [ ] **Step 1: Extend the `Agent` types**

In `frontend/src/lib/api.ts`, inside `export interface Agent { ... }` add after `mcp_servers`:

```ts
  cron_expr: string | null;
  running_task_id: string | null;
  last_task: AgentTaskSummary | null;
```

In `AgentCreate` add `cron_expr?: string | null;`. (`AgentUpdate = Partial<AgentCreate>` follows.)

- [ ] **Step 2: Add the task types**

Right after `export type AgentUpdate = Partial<AgentCreate>;` add:

```ts
// Agent tasks (execution)
export type AgentTaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type AgentOutcome = "success" | "partial" | "failed";
export type StepKind = "plan" | "turn" | "tool_call" | "critique" | "report" | "error";
export const FINAL_TASK_STATUSES: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);
export interface AgentTaskSummary {
  id: string;
  status: AgentTaskStatus;
  outcome: AgentOutcome | null;
  finished_at: string | null;
}
export interface AgentPlan {
  steps: { title: string; tools: string[] }[];
  success_criteria: { id: string; description: string }[];
  risks: string[];
}
export interface AgentCritique {
  criteria: { id: string; met: boolean; confidence: number; justification: string }[];
  limit_hit: "max_steps" | "timeout" | null;
}
export interface AgentReport {
  summary: string;
  actions: { step_seq: number; description: string }[];
  evidence: string[];
  uncertainties: string[];
  next_steps: string[];
}
export interface AgentTask {
  id: string;
  agent_id: string;
  trigger: "manual" | "cron";
  objective: string;
  instructions: string;
  max_steps: number;
  timeout_seconds: number;
  status: AgentTaskStatus;
  outcome: AgentOutcome | null;
  plan: AgentPlan | null;
  critique: AgentCritique | null;
  report: AgentReport | null;
  error: string | null;
  cancel_requested: boolean;
  step_count: number;
  tokens_in: number;
  tokens_out: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
export interface AgentTaskStep {
  seq: number;
  kind: StepKind;
  payload: Record<string, unknown>;
  tokens_in: number | null;
  tokens_out: number | null;
  duration_ms: number | null;
  created_at: string;
}
export interface AgentTaskStepDetail extends AgentTaskStep {
  prompt: Record<string, unknown>[] | null;
}
export interface AgentTaskDetail extends AgentTask {
  steps: AgentTaskStep[];
}
export interface TaskStatusEvent {
  status: AgentTaskStatus | "gone";
  outcome: AgentOutcome | null;
  error: string | null;
  finished_at: string | null;
}
export type AgentTaskEvent =
  | { event: "step"; data: AgentTaskStep }
  | { event: "status"; data: TaskStatusEvent }
  | { event: "done"; data: Record<string, never> }
  | { event: "error"; data: { message: string } };
```

- [ ] **Step 3: Add the task functions**

After `setAgentStatus` in the Agents block add:

```ts
export const createAgentTask = (agentId: string, objective: string | null) =>
  request<AgentTask>(`/agents/${agentId}/tasks`, { method: "POST", body: JSON.stringify({ objective }) });
export const listAgentTasks = (agentId: string, params: { limit?: number; offset?: number } = {}) => {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset) query.set("offset", String(params.offset));
  const qs = query.toString();
  return request<AgentTask[]>(`/agents/${agentId}/tasks${qs ? `?${qs}` : ""}`);
};
export const getAgentTask = (taskId: string) => request<AgentTaskDetail>(`/agent-tasks/${taskId}`);
export const getAgentTaskStep = (taskId: string, seq: number) =>
  request<AgentTaskStepDetail>(`/agent-tasks/${taskId}/steps/${seq}`);
export const cancelAgentTask = (taskId: string) =>
  request<AgentTask>(`/agent-tasks/${taskId}/cancel`, { method: "POST" });
```

- [ ] **Step 4: Generalise the SSE reader and add `streamAgentTask`**

Replace the existing `parseSSEStream` function with:

```ts
/** Reads SSE frames (`event:` + `data:` JSON) and calls onEvent per frame; comment lines (`: keep-alive`) are ignored. */
export function parseSSE(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";

  return reader.read().then(function process({ done, value }): Promise<void> {
    if (done) return Promise.resolve();
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent(currentEvent, data);
        } catch { /* skip malformed */ }
        currentEvent = "";
      }
    }

    return reader.read().then(process);
  });
}

/** Chat-typed wrapper kept for the existing chat components. */
export function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  return parseSSE(reader, (event, data) => onEvent({ event: event as SSEEvent["event"], data }));
}

/** Streams a task's steps and status until the server sends `done` or `signal` aborts. */
export async function streamAgentTask(
  taskId: string,
  onEvent: (e: AgentTaskEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/agent-tasks/${taskId}/events`, { headers: { Accept: "text/event-stream" }, signal });
  if (!res.ok || !res.body) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
  const reader = res.body.getReader();
  try {
    await parseSSE(reader, (event, data) => onEvent({ event, data } as AgentTaskEvent));
  } finally {
    reader.releaseLock();
  }
}
```

Place `parseSSE`/`parseSSEStream` where `parseSSEStream` was, and `streamAgentTask` right after them (it needs `BASE`, declared at the top of the file).

- [ ] **Step 5: Lint and build**

Run (from `frontend/`): `npm run lint && npm run build`
Expected: lint shows only the two pre-existing warnings; build succeeds. The chat still compiles against `parseSSEStream`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(agents): add the task API client and a shared SSE frame reader

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Cron schedule in the agent form

**Files:**
- Modify: `frontend/src/components/Agents/AgentFormModal.tsx`

**Interfaces:**
- Consumes `CronPicker({ value, onChange })` from `components/Prompts/CronPicker.tsx`, `Agent.cron_expr`, `AgentCreate.cron_expr`.
- Produces: the form sends `cron_expr: string | null` on create and edit (`null` clears it).

- [ ] **Step 1: Add the schedule state and field**

In `AgentFormModal.tsx`:

1. Import: `import { CronPicker } from "../Prompts/CronPicker";`
2. State, after `timeoutSeconds`:
   ```tsx
   const [scheduled, setScheduled] = useState(false);
   const [cronExpr, setCronExpr] = useState("0 8 * * *");
   ```
3. In the re-seed effect add:
   ```tsx
   setScheduled(Boolean(agent?.cron_expr));
   setCronExpr(agent?.cron_expr ?? "0 8 * * *");
   ```
4. In `submit`'s payload add `cron_expr: scheduled ? cronExpr : null,`.
5. Insert this block between the "Authorised MCP servers" block and the limits grid:
   ```tsx
   <div>
     <label className="flex items-center gap-2.5 text-sm cursor-pointer" style={{ color: "var(--text-primary)" }}>
       <input type="checkbox" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
       <span>Run on a schedule</span>
       <span className="text-xs" style={labelStyle}>{scheduled ? "" : "No schedule: manual runs only"}</span>
     </label>
     {scheduled && (
       <div className="mt-3">
         <CronPicker value={cronExpr} onChange={setCronExpr} />
         <p className="mt-1 text-xs" style={labelStyle}>Each tick queues one task; ticks are skipped while a task is already queued or running.</p>
       </div>
     )}
   </div>
   ```

The API validates the expression (422 on an invalid one) and `MutationError` already surfaces it under the form; the `CronPicker` shows "Invalid cron expression" inline as the user types.

- [ ] **Step 2: Lint and build**

Run: `npm run lint && npm run build` → clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Agents/AgentFormModal.tsx
git commit -m "feat(agents): add an optional cron schedule to the agent form

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Badges, Run modal, task rows, and the card's run controls

**Files:**
- Create: `frontend/src/components/Agents/AgentTaskBadges.tsx`
- Create: `frontend/src/components/Agents/RunAgentModal.tsx`
- Create: `frontend/src/components/Agents/AgentTaskRow.tsx`
- Modify: `frontend/src/components/Agents/AgentCard.tsx`
- Modify: `frontend/src/components/Agents/AgentList.tsx`

**Interfaces:**
- Produces: `TaskStatusBadge({ status })`, `OutcomeBadge({ outcome })`, `relativeTime(iso) => string` (exported from `AgentTaskBadges.tsx`); `RunAgentModal({ open, agent, onClose })`; `AgentTaskRow({ agentId, task })`.
- `AgentCard` gains props `onRun: (agent) => void` and `onCancelTask: (agent) => void`.

- [ ] **Step 1: Create `AgentTaskBadges.tsx`**

```tsx
import type { AgentOutcome, AgentTaskStatus } from "../../lib/api";

const STATUS: Record<AgentTaskStatus | "gone", { color: string; bg: string; label: string; pulse?: boolean }> = {
  queued:    { color: "var(--text-secondary)", bg: "rgba(148, 163, 184, 0.12)", label: "Queued" },
  running:   { color: "var(--running)",        bg: "rgba(96, 165, 250, 0.12)",  label: "Running", pulse: true },
  completed: { color: "var(--success)",        bg: "rgba(52, 211, 153, 0.10)",  label: "Completed" },
  failed:    { color: "var(--error)",          bg: "rgba(248, 113, 113, 0.12)", label: "Failed" },
  cancelled: { color: "var(--text-muted)",     bg: "rgba(100, 116, 139, 0.10)", label: "Cancelled" },
  gone:      { color: "var(--text-muted)",     bg: "rgba(100, 116, 139, 0.10)", label: "Gone" },
};

const OUTCOME: Record<AgentOutcome, { color: string; bg: string; label: string }> = {
  success: { color: "var(--success)", bg: "rgba(52, 211, 153, 0.10)",  label: "Success" },
  partial: { color: "var(--warning)", bg: "rgba(251, 191, 36, 0.12)",  label: "Partial" },
  failed:  { color: "var(--error)",   bg: "rgba(248, 113, 113, 0.12)", label: "Failed" },
};

export function TaskStatusBadge({ status }: { status: AgentTaskStatus | "gone" }) {
  const s = STATUS[status];
  return (
    <span className="badge" style={{ color: s.color, backgroundColor: s.bg, border: `1px solid ${s.color}40` }}>
      <span className={`h-1.5 w-1.5 rounded-full inline-block ${s.pulse ? "pulse-dot" : ""}`} style={{ backgroundColor: s.color }} />
      {s.label}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: AgentOutcome | null }) {
  if (!outcome) return null;
  const o = OUTCOME[outcome];
  return <span className="badge" style={{ color: o.color, backgroundColor: o.bg, border: `1px solid ${o.color}40` }}>{o.label}</span>;
}

/** "3 min ago" / "2 h ago" / "yesterday" style label for a timestamp. */
export function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function formatDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso) return "";
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const sec = Math.max(0, Math.round((end - new Date(startIso).getTime()) / 1000));
  return sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min ${sec % 60} s`;
}
```

- [ ] **Step 2: Create `RunAgentModal.tsx`**

```tsx
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { createAgentTask } from "../../lib/api";
import type { Agent } from "../../lib/api";
import { Modal } from "../ui/Modal";
import { MutationError } from "../ui/MutationError";

interface Props {
  open: boolean;
  agent: Agent | null;
  onClose: () => void;
}

export function RunAgentModal({ open, agent, onClose }: Props) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [objective, setObjective] = useState("");

  useEffect(() => {
    if (open) setObjective(agent?.objective ?? "");
  }, [open, agent]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!agent) throw new Error("No agent selected");
      const override = objective.trim();
      return createAgentTask(agent.id, override && override !== agent.objective ? override : null);
    },
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-tasks", task.agent_id] });
      onClose();
      navigate(`/agents/${task.agent_id}/tasks/${task.id}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (objective.trim()) mutation.mutate();
  };

  return (
    <Modal open={open} title={agent ? `Run ${agent.name}` : "Run agent"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Objective for this run</label>
          <textarea rows={4} className="input-field" value={objective} onChange={(e) => setObjective(e.target.value)} />
          <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>Pre-filled with the agent's objective. Edit it to run a one-off variant; the agent itself is not changed.</p>
        </div>
        <p className="text-xs rounded-lg px-3 py-2" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.08)", border: "1px solid rgba(251, 191, 36, 0.25)" }}>
          No approval step yet: every authorised tool runs immediately, including tools that write.
        </p>
        <MutationError error={mutation.error} />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!objective.trim() || mutation.isPending}>
            {mutation.isPending ? "Starting..." : "Start"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
```

- [ ] **Step 3: Create `AgentTaskRow.tsx`**

```tsx
import { Link } from "react-router-dom";
import type { AgentTask } from "../../lib/api";
import { OutcomeBadge, TaskStatusBadge, relativeTime } from "./AgentTaskBadges";

export function AgentTaskRow({ agentId, task }: { agentId: string; task: AgentTask }) {
  return (
    <Link to={`/agents/${agentId}/tasks/${task.id}`} className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)", textDecoration: "none" }}>
      <TaskStatusBadge status={task.status} />
      <OutcomeBadge outcome={task.outcome} />
      <span className="truncate" style={{ color: "var(--text-primary)" }}>{task.objective}</span>
      <span className="ml-auto flex-shrink-0" style={{ color: "var(--text-muted)" }}>{task.trigger} · {relativeTime(task.finished_at ?? task.created_at)}</span>
    </Link>
  );
}
```

- [ ] **Step 4: Extend `AgentCard.tsx`**

Replace the file with:

```tsx
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listAgentTasks } from "../../lib/api";
import type { Agent, AgentStatus } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { AgentTaskRow } from "./AgentTaskRow";
import { OutcomeBadge, TaskStatusBadge, relativeTime } from "./AgentTaskBadges";

interface Props {
  agent: Agent;
  busy: boolean;
  error: unknown;
  onEdit: (agent: Agent) => void;
  onStatus: (agent: Agent, status: AgentStatus) => void;
  onDelete: (agent: Agent) => void;
  onRun: (agent: Agent) => void;
  onCancelTask: (agent: Agent) => void;
}

const BADGE: Record<AgentStatus, { color: string; bg: string; border: string; label: string }> = {
  draft:    { color: "var(--text-secondary)", bg: "rgba(148, 163, 184, 0.12)", border: "rgba(148, 163, 184, 0.25)", label: "Draft" },
  active:   { color: "var(--success)",        bg: "rgba(52, 211, 153, 0.10)",  border: "rgba(52, 211, 153, 0.20)",  label: "Active" },
  paused:   { color: "var(--warning)",        bg: "rgba(251, 191, 36, 0.12)",  border: "rgba(251, 191, 36, 0.25)",  label: "Paused" },
  archived: { color: "var(--text-muted)",     bg: "rgba(100, 116, 139, 0.10)", border: "rgba(100, 116, 139, 0.20)", label: "Archived" },
};

export function AgentCard({ agent, busy, error, onEdit, onStatus, onDelete, onRun, onCancelTask }: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showTasks, setShowTasks] = useState(false);
  const badge = BADGE[agent.status];
  const updated = new Date(agent.updated_at).toLocaleString();
  const running = agent.running_task_id !== null;

  const { data: recent = [], isLoading: loadingTasks } = useQuery({
    queryKey: ["agent-tasks", agent.id, "recent"],
    queryFn: () => listAgentTasks(agent.id, { limit: 5 }),
    enabled: showTasks,
  });

  const action = (label: string, onClick: () => void, cls = "btn-secondary") => (
    <button key={label} type="button" className={`${cls} btn-sm`} disabled={busy} onClick={onClick}>{label}</button>
  );

  const deleteButton = confirmDelete
    ? [action("Confirm delete", () => { setConfirmDelete(false); onDelete(agent); }, "btn-danger"), action("Keep", () => setConfirmDelete(false))]
    : [action("Delete", () => setConfirmDelete(true), "btn-danger")];

  const runButton = running
    ? action("Cancel run", () => onCancelTask(agent), "btn-danger")
    : action("Run", () => onRun(agent), "btn-primary");

  const actions: ReactNode[] = {
    draft:    [action("Activate", () => onStatus(agent, "active"), "btn-primary"), action("Edit", () => onEdit(agent)), ...deleteButton],
    active:   [runButton, action("Pause", () => onStatus(agent, "paused")), action("Edit", () => onEdit(agent)), action("Archive", () => onStatus(agent, "archived"))],
    paused:   [action("Resume", () => onStatus(agent, "active"), "btn-primary"), action("Edit", () => onEdit(agent)), action("Archive", () => onStatus(agent, "archived"))],
    archived: [action("Restore", () => onStatus(agent, "draft")), ...deleteButton],
  }[agent.status];

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className={`h-2 w-2 flex-shrink-0 rounded-full ${agent.status === "active" ? "pulse-dot" : ""}`} style={{ backgroundColor: badge.color }} />
            <span className="font-semibold truncate" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)", fontSize: "0.9375rem" }}>{agent.name}</span>
            <span className="badge flex-shrink-0" style={{ color: badge.color, backgroundColor: badge.bg, border: `1px solid ${badge.border}` }}>{badge.label}</span>
            {running && agent.running_task_id && (
              <Link to={`/agents/${agent.id}/tasks/${agent.running_task_id}`} className="flex-shrink-0" style={{ textDecoration: "none" }}>
                <TaskStatusBadge status="running" />
              </Link>
            )}
            {agent.cron_expr && <span className="font-mono text-xs flex-shrink-0" style={{ color: "var(--text-muted)" }} title="Cron schedule">{agent.cron_expr}</span>}
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

      <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
        {agent.last_task ? (
          <Link to={`/agents/${agent.id}/tasks/${agent.last_task.id}`} className="flex items-center gap-2" style={{ textDecoration: "none" }}>
            <span>Last run</span>
            <TaskStatusBadge status={agent.last_task.status} />
            <OutcomeBadge outcome={agent.last_task.outcome} />
            <span>{relativeTime(agent.last_task.finished_at)}</span>
          </Link>
        ) : (
          <span>No runs yet</span>
        )}
        {agent.last_task && (
          <button type="button" className="ml-auto underline-offset-2 hover:underline" style={{ color: "var(--text-secondary)" }} onClick={() => setShowTasks((v) => !v)}>
            {showTasks ? "Hide recent tasks" : "Recent tasks"}
          </button>
        )}
      </div>

      {showTasks && (
        <div className="space-y-1.5">
          {loadingTasks && <p className="text-xs" style={{ color: "var(--text-muted)" }}>Loading…</p>}
          {recent.map((t) => <AgentTaskRow key={t.id} agentId={agent.id} task={t} />)}
        </div>
      )}

      <MutationError error={error} />
    </div>
  );
}
```

- [ ] **Step 5: Wire the modal and cancel into `AgentList.tsx`**

In `AgentList.tsx`:
1. Imports: add `cancelAgentTask` to the `../../lib/api` import; `import { RunAgentModal } from "./RunAgentModal";`.
2. State: `const [runAgent, setRunAgent] = useState<Agent | null>(null);`
3. Mutation: `const cancelMut = useMutation({ mutationFn: (taskId: string) => cancelAgentTask(taskId) });`
4. In `run`'s `finally`, also `queryClient.invalidateQueries({ queryKey: ["agent-tasks"] });`
5. Pass to each card:
   ```tsx
   onRun={(a) => setRunAgent(a)}
   onCancelTask={(a) => a.running_task_id && run(a.id, () => cancelMut.mutateAsync(a.running_task_id!))}
   ```
6. Render after the list (inside the returned fragment, so wrap the `<div className="space-y-3">` and the modal in `<>...</>`):
   ```tsx
   <RunAgentModal open={runAgent !== null} agent={runAgent} onClose={() => setRunAgent(null)} />
   ```
   The empty-state branch returns early without the modal, which is fine: no agent, nothing to run.
7. Make the list refresh while something runs: add `refetchInterval: (q) => (q.state.data ?? []).some((a) => a.running_task_id) ? 5000 : false` to the agents `useQuery` options so the Running badge clears by itself.

- [ ] **Step 6: Lint and build**

Run: `npm run lint && npm run build` → clean. If `tsc` rejects the `refetchInterval` callback typing, use `refetchInterval: (query) => query.state.data?.some((a) => a.running_task_id) ? 5000 : false`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Agents/AgentTaskBadges.tsx frontend/src/components/Agents/RunAgentModal.tsx frontend/src/components/Agents/AgentTaskRow.tsx frontend/src/components/Agents/AgentCard.tsx frontend/src/components/Agents/AgentList.tsx
git commit -m "feat(agents): run an agent from its card and show its recent tasks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The live task hook and the four panels

**Files:**
- Create: `frontend/src/components/Agents/useAgentTaskStream.ts`
- Create: `frontend/src/components/Agents/TaskPlan.tsx`
- Create: `frontend/src/components/Agents/TaskTimeline.tsx`
- Create: `frontend/src/components/Agents/TaskCritique.tsx`
- Create: `frontend/src/components/Agents/TaskReport.tsx`

**Interfaces:**
- Produces:
  ```ts
  useAgentTaskStream(taskId: string): { task: AgentTaskDetail | null; steps: AgentTaskStep[]; gone: boolean; live: boolean; streamError: string | null; isLoading: boolean; error: unknown; refetch: () => void }
  TaskPlan({ plan })  TaskTimeline({ taskId, steps })  TaskCritique({ critique, plan })  TaskReport({ report })
  ```

- [ ] **Step 1: Create the hook**

`frontend/src/components/Agents/useAgentTaskStream.ts`:

```ts
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FINAL_TASK_STATUSES, getAgentTask, streamAgentTask } from "../../lib/api";
import type { AgentTaskDetail, AgentTaskStep } from "../../lib/api";

/**
 * Loads a task once, then follows it over SSE while it is not final.
 * Steps arriving on the stream are merged by `seq`; a `status` event updates
 * the task; `done` ends the stream and refetches the full detail (plan,
 * critique, report, totals) in one go.
 */
export function useAgentTaskStream(taskId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["agent-task", taskId], queryFn: () => getAgentTask(taskId) });
  const [liveSteps, setLiveSteps] = useState<AgentTaskStep[]>([]);
  const [liveStatus, setLiveStatus] = useState<AgentTaskDetail["status"] | "gone" | null>(null);
  const [liveMeta, setLiveMeta] = useState<{ outcome: AgentTaskDetail["outcome"]; error: string | null; finished_at: string | null } | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const started = useRef(false);

  const initialStatus = query.data?.status;
  const shouldStream = Boolean(initialStatus) && !FINAL_TASK_STATUSES.has(initialStatus as string);

  // The page stays mounted when the route switches to another task: reset the live state per task id.
  useEffect(() => {
    started.current = false;
    setLiveSteps([]);
    setLiveStatus(null);
    setLiveMeta(null);
    setStreamError(null);
  }, [taskId]);

  useEffect(() => {
    if (!shouldStream || started.current) return;
    started.current = true;
    const controller = new AbortController();
    setLive(true);
    streamAgentTask(taskId, (e) => {
      if (e.event === "step") {
        setLiveSteps((prev) => (prev.some((s) => s.seq === e.data.seq) ? prev : [...prev, e.data].sort((a, b) => a.seq - b.seq)));
      } else if (e.event === "status") {
        setLiveStatus(e.data.status);
        setLiveMeta({ outcome: e.data.outcome, error: e.data.error, finished_at: e.data.finished_at });
      } else if (e.event === "done") {
        setLive(false);
        queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        queryClient.invalidateQueries({ queryKey: ["agent-tasks"] });
      } else if (e.event === "error") {
        setStreamError(e.data.message);
      }
    }, controller.signal)
      .catch((err: unknown) => { if (!controller.signal.aborted) setStreamError(err instanceof Error ? err.message : String(err)); })
      .finally(() => setLive(false));
    return () => controller.abort();
  }, [shouldStream, taskId, queryClient]);

  // Merge: the fetched detail is the base; live steps and status overlay it.
  const base = query.data ?? null;
  const steps = base
    ? [...base.steps, ...liveSteps.filter((s) => !base.steps.some((b) => b.seq === s.seq))].sort((a, b) => a.seq - b.seq)
    : liveSteps;
  const task = base
    ? { ...base, ...(liveStatus && liveStatus !== "gone" ? { status: liveStatus } : {}), ...(liveMeta ?? {}) }
    : null;

  return {
    task,
    steps,
    gone: liveStatus === "gone",
    live,
    streamError,
    isLoading: query.isLoading,
    error: query.error,
    refetch: () => query.refetch(),
  };
}
```

- [ ] **Step 2: Create `TaskPlan.tsx`**

```tsx
import type { AgentPlan } from "../../lib/api";

export function TaskPlan({ plan }: { plan: AgentPlan | null }) {
  return (
    <section className="card p-4 space-y-3">
      <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Plan</h3>
      {!plan ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Not planned yet.</p>
      ) : (
        <>
          <ol className="space-y-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
            {plan.steps.map((s, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono" style={{ color: "var(--text-muted)" }}>{i + 1}.</span>
                <span>
                  {s.title}
                  {s.tools.length > 0 && <span className="ml-2 font-mono text-xs" style={{ color: "var(--accent)" }}>{s.tools.join(", ")}</span>}
                </span>
              </li>
            ))}
          </ol>
          <div>
            <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Success criteria</p>
            <ul className="space-y-1 text-sm" style={{ color: "var(--text-secondary)" }}>
              {plan.success_criteria.map((c) => (
                <li key={c.id} className="flex gap-2"><span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{c.id}</span><span>{c.description}</span></li>
              ))}
            </ul>
          </div>
          {plan.risks.length > 0 && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Risks</p>
              <ul className="list-disc pl-5 text-sm" style={{ color: "var(--text-secondary)" }}>{plan.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Create `TaskTimeline.tsx`**

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAgentTaskStep } from "../../lib/api";
import type { AgentTaskStep, StepKind } from "../../lib/api";

const KIND_LABEL: Record<StepKind, string> = {
  plan: "Plan", turn: "Model turn", tool_call: "Tool call", critique: "Self-critique", report: "Report", error: "Error",
};
const LLM_KINDS: ReadonlySet<StepKind> = new Set(["plan", "turn", "critique", "report"]);

function pretty(value: unknown): string {
  if (typeof value === "string") {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
  }
  return JSON.stringify(value, null, 2);
}

function ToolCallBody({ payload }: { payload: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const ok = payload.ok !== false;
  const result = pretty(payload.result);
  return (
    <div className="rounded-lg text-xs" style={{ border: `1px solid ${ok ? "rgba(96, 165, 250, 0.25)" : "rgba(248, 113, 113, 0.35)"}`, backgroundColor: ok ? "rgba(96, 165, 250, 0.05)" : "rgba(248, 113, 113, 0.06)" }}>
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen((v) => !v)}>
        <span style={{ color: ok ? "var(--running)" : "var(--error)" }}>{ok ? "Called" : "Failed"}</span>
        <code className="font-mono" style={{ color: "var(--accent)" }}>{String(payload.tool)}</code>
        {payload.server ? <span style={{ color: "var(--text-muted)" }}>on {String(payload.server)}</span> : null}
        <span className="ml-auto" style={{ color: "var(--text-muted)" }}>{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          <div><p className="uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Arguments</p><pre className="overflow-x-auto whitespace-pre-wrap font-mono" style={{ color: "var(--text-secondary)" }}>{pretty(payload.args ?? {})}</pre></div>
          <div><p className="uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Result</p><pre className="overflow-x-auto whitespace-pre-wrap font-mono max-h-64 overflow-y-auto" style={{ color: "var(--text-secondary)" }}>{result}</pre></div>
        </div>
      )}
    </div>
  );
}

function PromptDisclosure({ taskId, seq }: { taskId: string; seq: number }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["agent-task-step", taskId, seq], queryFn: () => getAgentTaskStep(taskId, seq), enabled: open });
  return (
    <div>
      <button type="button" className="text-xs underline-offset-2 hover:underline" style={{ color: "var(--text-secondary)" }} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide prompt" : "Show prompt"}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {isLoading && <p className="text-xs" style={{ color: "var(--text-muted)" }}>Loading prompt…</p>}
          {error ? <p className="text-xs" style={{ color: "var(--error)" }}>{(error as Error).message}</p> : null}
          {data?.prompt?.map((m, i) => (
            <div key={i} className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              <p className="uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>{String(m.role ?? "message")}</p>
              <pre className="whitespace-pre-wrap font-mono" style={{ color: "var(--text-secondary)" }}>{typeof m.content === "string" ? m.content : pretty(m.content ?? m)}</pre>
            </div>
          ))}
          {data && !data.prompt && <p className="text-xs" style={{ color: "var(--text-muted)" }}>No prompt stored for this step.</p>}
        </div>
      )}
    </div>
  );
}

function StepCard({ taskId, step }: { taskId: string; step: AgentTaskStep }) {
  const p = step.payload;
  const isError = step.kind === "error";
  return (
    <li id={`step-${step.seq}`} className="rounded-xl p-3 space-y-2" style={{ backgroundColor: "var(--bg-panel)", border: `1px solid ${isError ? "rgba(248, 113, 113, 0.4)" : "var(--border)"}` }}>
      <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
        <span className="font-mono">#{step.seq}</span>
        <span className="font-medium" style={{ color: isError ? "var(--error)" : "var(--text-primary)" }}>{KIND_LABEL[step.kind]}</span>
        {step.duration_ms !== null && <span>{step.duration_ms} ms</span>}
        {(step.tokens_in || step.tokens_out) ? <span>{step.tokens_in ?? 0} in / {step.tokens_out ?? 0} out</span> : null}
        <span className="ml-auto">{new Date(step.created_at).toLocaleTimeString()}</span>
      </div>
      {step.kind === "turn" && (
        <>
          {typeof p.text === "string" && p.text && <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>{p.text}</p>}
          {Array.isArray(p.tool_calls) && p.tool_calls.length > 0 && (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Requested: {(p.tool_calls as { name: string }[]).map((t) => t.name).join(", ")}</p>
          )}
        </>
      )}
      {step.kind === "tool_call" && <ToolCallBody payload={p} />}
      {step.kind === "error" && <p className="text-sm" style={{ color: "var(--error)" }}>{String(p.message)} <span style={{ color: "var(--text-muted)" }}>(phase: {String(p.phase)})</span></p>}
      {(step.kind === "plan" || step.kind === "critique" || step.kind === "report") && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>See the {KIND_LABEL[step.kind].toLowerCase()} panel.</p>
      )}
      {LLM_KINDS.has(step.kind) && <PromptDisclosure taskId={taskId} seq={step.seq} />}
    </li>
  );
}

export function TaskTimeline({ taskId, steps }: { taskId: string; steps: AgentTaskStep[] }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Steps</h3>
      {steps.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Waiting for the worker to pick this task up…</p>
      ) : (
        <ol className="space-y-2">{steps.map((s) => <StepCard key={s.seq} taskId={taskId} step={s} />)}</ol>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Create `TaskCritique.tsx`**

```tsx
import type { AgentCritique, AgentPlan } from "../../lib/api";

export function TaskCritique({ critique, plan }: { critique: AgentCritique | null; plan: AgentPlan | null }) {
  const describe = (id: string) => plan?.success_criteria.find((c) => c.id === id)?.description ?? "";
  return (
    <section className="card p-4 space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Self-critique</h3>
        {critique?.limit_hit && <span className="badge" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.12)", border: "1px solid rgba(251, 191, 36, 0.3)" }}>Stopped by {critique.limit_hit.replace("_", " ")}</span>}
      </div>
      {!critique ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Not evaluated yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wider text-left" style={{ color: "var(--text-muted)" }}>
              <th className="pb-2 pr-3 font-medium">Criterion</th>
              <th className="pb-2 pr-3 font-medium">Met</th>
              <th className="pb-2 pr-3 font-medium">Confidence</th>
              <th className="pb-2 font-medium">Justification</th>
            </tr>
          </thead>
          <tbody>
            {critique.criteria.map((c) => {
              const counts = c.met && c.confidence >= 0.5;
              return (
                <tr key={c.id} className="align-top" style={{ borderTop: "1px solid var(--border)" }}>
                  <td className="py-2 pr-3"><span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{c.id}</span> <span style={{ color: "var(--text-secondary)" }}>{describe(c.id)}</span></td>
                  <td className="py-2 pr-3" style={{ color: counts ? "var(--success)" : "var(--error)" }}>{c.met ? "yes" : "no"}</td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-24 rounded-full overflow-hidden" style={{ backgroundColor: "var(--bg-elevated)" }}>
                        <div className="h-full" style={{ width: `${Math.round(c.confidence * 100)}%`, backgroundColor: counts ? "var(--success)" : "var(--warning)" }} />
                      </div>
                      <span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{c.confidence.toFixed(2)}</span>
                    </div>
                  </td>
                  <td className="py-2" style={{ color: "var(--text-secondary)" }}>{c.justification}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {critique && <p className="text-xs" style={{ color: "var(--text-muted)" }}>A criterion counts as met when the model says so with confidence ≥ 0.50. All met → success, none → failed, otherwise partial.</p>}
    </section>
  );
}
```

- [ ] **Step 5: Create `TaskReport.tsx`**

```tsx
import type { AgentReport } from "../../lib/api";

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>{title}</p>
      <ul className="list-disc pl-5 text-sm space-y-0.5" style={{ color: "var(--text-secondary)" }}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}

export function TaskReport({ report }: { report: AgentReport | null }) {
  return (
    <section className="card p-4 space-y-3">
      <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Report</h3>
      {!report ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>No report yet.</p>
      ) : (
        <>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>{report.summary}</p>
          {report.actions.length > 0 && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Actions</p>
              <ul className="space-y-0.5 text-sm" style={{ color: "var(--text-secondary)" }}>
                {report.actions.map((a, i) => (
                  <li key={i}><a href={`#step-${a.step_seq}`} className="font-mono text-xs mr-2" style={{ color: "var(--accent)" }}>#{a.step_seq}</a>{a.description}</li>
                ))}
              </ul>
            </div>
          )}
          <List title="Evidence" items={report.evidence} />
          <List title="Uncertainties" items={report.uncertainties} />
          <List title="Next steps" items={report.next_steps} />
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 6: Lint and build**

Run: `npm run lint && npm run build` → clean (the new files are unused until Task 5, which is fine for `tsc`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Agents/useAgentTaskStream.ts frontend/src/components/Agents/TaskPlan.tsx frontend/src/components/Agents/TaskTimeline.tsx frontend/src/components/Agents/TaskCritique.tsx frontend/src/components/Agents/TaskReport.tsx
git commit -m "feat(agents): add the live task stream hook and the plan, timeline, critique and report panels

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The task page, its route, shell context, browser check, docs

**Files:**
- Create: `frontend/src/pages/AgentTaskPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/AppShell.tsx`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create `AgentTaskPage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { FINAL_TASK_STATUSES, cancelAgentTask, listAgents } from "../lib/api";
import { Spinner } from "../components/ui/Spinner";
import { MutationError } from "../components/ui/MutationError";
import { useAgentTaskStream } from "../components/Agents/useAgentTaskStream";
import { OutcomeBadge, TaskStatusBadge, formatDuration } from "../components/Agents/AgentTaskBadges";
import { TaskPlan } from "../components/Agents/TaskPlan";
import { TaskTimeline } from "../components/Agents/TaskTimeline";
import { TaskCritique } from "../components/Agents/TaskCritique";
import { TaskReport } from "../components/Agents/TaskReport";

export function AgentTaskPage() {
  const { agentId = "", taskId = "" } = useParams();
  const queryClient = useQueryClient();
  const { task, steps, gone, live, streamError, isLoading, error } = useAgentTaskStream(taskId);
  const { data: agents = [] } = useQuery({ queryKey: ["agents", "all"], queryFn: () => listAgents() });
  const agent = agents.find((a) => a.id === agentId) ?? null;

  const cancelMut = useMutation({
    mutationFn: () => cancelAgentTask(taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  if (isLoading) return <div className="flex justify-center py-12"><Spinner /></div>;
  if (error || !task) {
    return (
      <div className="space-y-3">
        <p className="text-sm" style={{ color: "var(--error)" }}>{error ? (error as Error).message : "Task not found"}</p>
        <Link to="/agents" className="btn-secondary btn-sm" style={{ textDecoration: "none" }}>Back to agents</Link>
      </div>
    );
  }

  const isFinal = FINAL_TASK_STATUSES.has(task.status) || gone;
  const duration = formatDuration(task.started_at, task.finished_at);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 space-y-1.5">
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            <Link to="/agents" style={{ color: "var(--text-secondary)" }}>Agents</Link> / {agent?.name ?? "Agent"} / task
          </p>
          <h2 className="text-xl font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>{task.objective}</h2>
          <div className="flex items-center gap-2 flex-wrap text-xs" style={{ color: "var(--text-muted)" }}>
            <TaskStatusBadge status={gone ? "gone" : task.status} />
            <OutcomeBadge outcome={task.outcome} />
            {live && <span style={{ color: "var(--running)" }}>live</span>}
            <span>{task.trigger}</span>
            {task.started_at && <span>started {new Date(task.started_at).toLocaleString()}</span>}
            {duration && <span>{duration}</span>}
            <span>{task.step_count} steps</span>
            <span>{task.tokens_in} in / {task.tokens_out} out tokens</span>
            <span>limits {task.max_steps} rounds · {task.timeout_seconds} s</span>
          </div>
          {task.error && <p className="text-sm" style={{ color: "var(--error)" }}>{task.error}</p>}
          {streamError && <p className="text-xs" style={{ color: "var(--warning)" }}>Live updates interrupted: {streamError}. Reload to resync.</p>}
        </div>
        {!isFinal && (
          <div className="flex flex-col items-end gap-2">
            <button type="button" className="btn-danger btn-sm" disabled={cancelMut.isPending || task.cancel_requested} onClick={() => cancelMut.mutate()}>
              {task.cancel_requested ? "Cancelling…" : "Cancel"}
            </button>
            <MutationError error={cancelMut.error} />
          </div>
        )}
      </div>

      <p className="text-xs rounded-lg px-3 py-2" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.08)", border: "1px solid rgba(251, 191, 36, 0.25)" }}>
        No approval step yet: every authorised tool runs immediately.
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <TaskPlan plan={task.plan} />
        <TaskCritique critique={task.critique} plan={task.plan} />
      </div>
      <TaskReport report={task.report} />
      <TaskTimeline taskId={taskId} steps={steps} />
    </div>
  );
}
```

- [ ] **Step 2: Route and shell context**

In `App.tsx`: `import { AgentTaskPage } from "./pages/AgentTaskPage";` and after the `agents` route add
`<Route path="agents/:agentId/tasks/:taskId" element={<AgentTaskPage />} />`.

In `AppShell.tsx` replace the lookup so a nested agents path keeps its context:

```tsx
  const PAGES: Record<string, [string, string]> = {
    "/": ["Automations", "Create, schedule and supervise MCP workflows."],
    "/agents": ["Agents", "Define autonomous agents, their MCP servers and limits."],
    "/reports": ["Reports", "Review the results of every execution."],
    "/activity": ["Activity", "Follow document changes across your workspace."],
    "/pairing": ["SIM Pairing", "Route and manage connected SIM numbers."],
    "/sms-auto-reply": ["SMS Reply", "Keep SMS conversations moving automatically."],
    "/stress-call": ["Stress Call", "Measure SIP capacity and call quality."],
    "/chat": ["Assistant", "Ask, test tools and turn ideas into workflows."],
    "/config": ["Settings", "Configure the control plane and its integrations."],
  };
  const key = pathname === "/" ? "/" : Object.keys(PAGES).find((k) => k !== "/" && (pathname === k || pathname.startsWith(k + "/")));
  const page = (key && PAGES[key]) ?? ["Tour de Control", "Operations workspace."];
```

- [ ] **Step 3: Lint and build**

Run: `npm run lint && npm run build` → clean.

- [ ] **Step 4: Browser check against the live stream**

Start the stack locally: from `backend/`, `PYTHONPATH=. venv/bin/uvicorn app.main:app --reload` and, in a second terminal, `PYTHONPATH=. venv/bin/python -m app.worker`; from `frontend/`, `npm run dev`. Open `http://localhost:3000/agents`.

1. Create an agent (any enabled MCP server; `sipp-stress` is auto-registered, reachable or not), Activate it, open Edit and tick "Run on a schedule": the `CronPicker` appears; untick, Save.
2. Click **Run**: the modal shows the objective pre-filled and the approval notice; **Start** navigates to `/agents/{id}/tasks/{taskId}`; the header shows `Queued` then `Running` with "live" without a reload; steps appear as the worker writes them. If no LLM key is configured locally the task fails at the first step with "LLM not configured": the error step and the `Failed` badge must still appear live. Record which of the two you observed.
3. Click **Show prompt** on the first LLM step: the stored messages render; the system message contains the objective.
4. If the run reaches the end: the Plan, Self-critique (with confidence bars) and Report panels fill in after `done`; the report's action links jump to steps.
5. Back on `/agents`: the card shows "Last run" with status/outcome, "Recent tasks" expands to the list, and a second **Run** while one is running shows "Cancel run" instead.
6. Reload the task page of a finished task: it renders from the fetch alone, no "live" label, no stream opened (check the Network tab: no `/events` request).
7. Narrow the window to ~375 px: the header wraps, the two-column grid stacks, no horizontal scroll.

Stop the servers; delete the test agent (archive then delete) so the dev DB is left clean.

- [ ] **Step 5: Document**

In `CLAUDE.md`, in the Agents paragraph, append: "The frontend streams a task on `/agents/:agentId/tasks/:taskId` through `streamAgentTask()` in `lib/api.ts`, built on the generic `parseSSE()` the chat also uses; the page merges the initial `GET /agent-tasks/{id}` with live `step`/`status` events until `done`, then refetches."

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AgentTaskPage.tsx frontend/src/App.tsx frontend/src/components/Layout/AppShell.tsx CLAUDE.md
git commit -m "feat(agents): add the live task page with plan, steps, critique and report

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
