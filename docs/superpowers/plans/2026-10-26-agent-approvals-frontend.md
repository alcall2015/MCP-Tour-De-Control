# Agent Approvals (3b, frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give operators the screens the 3a backend needs: classify tools by risk per MCP server, set an agent's automatic ceiling, configure WhatsApp notifications, see pending approvals, and approve or reject a parked task from its page.

**Architecture:** All HTTP calls and types go through `frontend/src/lib/api.ts`. Settings gains an editable tools panel per MCP server and an Approvals section; the agent form gains a ceiling select; the task page gains an approval card driven by `AgentTaskDetail.approval` (refetched on every SSE status change) plus risk badges on tool-call steps; the Agents page gains a pending-approvals strip and the sidebar a counter. No new routes.

**Tech Stack:** React 19, TanStack Query 5, react-router 7, Tailwind v4 utility classes plus the app's CSS classes (`card`, `card-elevated`, `badge`, `btn-primary`/`btn-secondary`/`btn-danger`, `btn-sm`, `input-field`), oxlint, `tsc -b`.

Spec: `docs/superpowers/specs/2026-10-26-agent-approvals-design.md` (Frontend section). Backend is merged on `main` (`edc2b2d`).

## Global Constraints

- Branch `feat/agent-approvals-ui` from `main`. Conventional Commits `feat(agents-ui): ...` / `fix(agents-ui): ...` / `docs(agents): ...`; every commit message ends with exactly these two trailer lines:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx
  ```
  Stage named paths only; never `git add -A`; never bare `git stash`.
- Frontend checks, from `frontend/`: `npm run lint` (baseline: exactly two pre-existing `no-useless-escape` warnings in `src/pages/PairingPage.tsx:168`, nothing else) and `npm run build` (`tsc -b && vite build`). There is no frontend test suite; every task ends with both commands green.
- No ad-hoc `fetch` in components; every call and shared type lives in `src/lib/api.ts`.
- UI copy in English. No emojis in navigation or badges. Reuse the existing colour tokens (`var(--success)`, `var(--warning)`, `var(--error)`, `var(--running)`, `var(--accent)`, `var(--text-*)`, `var(--bg-*)`, `var(--border)`) and the rgba borders already used in `AgentTaskBadges.tsx`.
- Risk levels are exactly four, labelled everywhere through one shared table: `R0 Read-only`, `R1 Limited writes`, `R2 Significant changes`, `R3 Destructive or irreversible`. The agent ceiling offers R0, R1 (default) and R2 only; R3 is never automatic. Rule text on the tools panel, verbatim: "A tool runs without approval when its level is at or below the agent's ceiling; everything above parks the task until an operator decides. R3 always requires approval."
- Backend contract (from 3a, do not change): `GET /api/v1/approvals?status=pending|approved|rejected|expired` (default pending, newest first) → `ApprovalRead[]`; `POST /api/v1/approvals/{id}/approve|reject` body `{reason?: string | null}` → `ApprovalRead`, 404 unknown, 409 not pending; `GET /api/v1/mcp-servers/{id}/tools` → `{name, description, risk_level}[]` (502 on discovery failure); `PUT /api/v1/mcp-servers/{id}/tools/{tool_name}` body `{risk_level: 0..3}`; `Config` fields `approval_expiry_hours` (1..168), `approval_whatsapp_enabled`, `approval_whatsapp_number` (`^\+?\d{8,15}$`), `approval_whatsapp_server_id` (uuid or null), `approval_whatsapp_session_id` (string or null), `approval_whatsapp_template` (must contain `{code}`); `Agent.max_auto_risk` 0..2; `AgentTaskDetail.approval: ApprovalRead | null` (the pending one; list rows do not carry it); `approval_requested` step payload `{approval_id, tool, server, args, risk_level, code, expires_at}`; `tool_call` payload gains `risk_level` and, on a resumed call, `approval_id` (`ok=false` with result `{"error": "rejected by operator: ..."}` when rejected).
- `ApprovalRead` fields: `id, task_id, agent_id, agent_name, task_objective, step_seq, call_index, tool_name, server_name, args, risk_level, code, status, requested_at, expires_at, seconds_left, decided_at, decided_by, decision_reason, notified_at, notify_error, consumed_at`. `notify_error === "notifications disabled"` means WhatsApp is off, not a failure.
- SSE protocol is unchanged: `waiting_approval` arrives as a non-final `status` event; the stream stays open; `queued` then `running` follow a decision.

## File Structure

| Path | Responsibility |
|---|---|
| `frontend/src/lib/api.ts` | types + calls: `Approval`, `ApprovalStatus`, `ToolPolicy`, `RISK_LEVELS`, `listApprovals`, `approveApproval`, `rejectApproval`, `listServerTools`, `setToolPolicy`, config fields, `Agent.max_auto_risk`, `AgentTaskDetail.approval` |
| `frontend/src/components/Agents/RiskBadge.tsx` | one badge for a risk level (used by tools panel, task steps, approval card, strip) |
| `frontend/src/components/Config/McpToolsPanel.tsx` | editable tools list per server (replaces `McpToolsPreview.tsx`, which is deleted) |
| `frontend/src/components/Config/McpServerList.tsx` | "Tools" toggle per server; Test success opens the panel |
| `frontend/src/components/Config/ApprovalsConfig.tsx` | Settings → Approvals section |
| `frontend/src/pages/ConfigPage.tsx` | mounts `ApprovalsConfig` |
| `frontend/src/components/Agents/AgentFormModal.tsx`, `AgentCard.tsx` | ceiling select; ceiling shown on the card |
| `frontend/src/components/Agents/useAgentTaskStream.ts` | refetch the detail on every `status` event |
| `frontend/src/components/Agents/ApprovalCard.tsx` | "Approval required" card with Approve / Reject |
| `frontend/src/components/Agents/TaskTimeline.tsx` | risk badge on tool calls, `approval_requested` rendering |
| `frontend/src/pages/AgentTaskPage.tsx` | card at the top, old notice removed |
| `frontend/src/components/Agents/PendingApprovalsStrip.tsx` | strip on the Agents page |
| `frontend/src/pages/AgentsPage.tsx` | mounts the strip |
| `frontend/src/components/Layout/TabNav.tsx` | "Pending approvals" status line |
| `frontend/src/components/Agents/time.ts` | `timeLeft(iso)` |
| `CLAUDE.md` | one sentence on the frontend surface |

---

### Task 1: API client

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/Agents/RiskBadge.tsx`
- Modify: `frontend/src/components/Agents/time.ts`

**Interfaces (produced, used by every later task):**

```ts
export type RiskLevel = 0 | 1 | 2 | 3;
export const RISK_LEVELS: readonly { level: RiskLevel; code: string; label: string; hint: string }[];
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export interface Approval { ... }           // see Global Constraints field list
export interface ToolPolicy { name: string; description: string | null; risk_level: RiskLevel }
export const listApprovals: (status?: ApprovalStatus) => Promise<Approval[]>;
export const approveApproval: (id: string, reason?: string | null) => Promise<Approval>;
export const rejectApproval: (id: string, reason?: string | null) => Promise<Approval>;
export const listServerTools: (serverId: string) => Promise<ToolPolicy[]>;
export const setToolPolicy: (serverId: string, toolName: string, level: RiskLevel) => Promise<ToolPolicy>;
// Agent.max_auto_risk: RiskLevel; AgentCreate.max_auto_risk?: RiskLevel; AgentTaskDetail.approval: Approval | null
// Config / ConfigUpdate: the six approval fields
export function RiskBadge({ level, compact? }: { level: number; compact?: boolean }): JSX.Element;
export function timeLeft(iso: string | null): string;   // "expires in 3 h 12 min" / "expired"
```

- [ ] **Step 1: Types and calls in `api.ts`**

After the `// MCP Servers` block add:

```ts
// Tool policies (risk levels)
export const listServerTools = (serverId: string) => request<ToolPolicy[]>(`/mcp-servers/${serverId}/tools`);
export const setToolPolicy = (serverId: string, toolName: string, level: RiskLevel) =>
  request<ToolPolicy>(`/mcp-servers/${serverId}/tools/${encodeURIComponent(toolName)}`, { method: "PUT", body: JSON.stringify({ risk_level: level }) });

// Approvals
export const listApprovals = (status: ApprovalStatus = "pending") => request<Approval[]>(`/approvals?status=${status}`);
export const approveApproval = (id: string, reason?: string | null) =>
  request<Approval>(`/approvals/${id}/approve`, { method: "POST", body: JSON.stringify({ reason: reason || null }) });
export const rejectApproval = (id: string, reason?: string | null) =>
  request<Approval>(`/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({ reason: reason || null }) });
```

In `Config` add (before the closing brace):

```ts
  approval_expiry_hours: number;
  approval_whatsapp_enabled: boolean;
  approval_whatsapp_number: string;
  approval_whatsapp_server_id: string | null;
  approval_whatsapp_session_id: string | null;
  approval_whatsapp_template: string;
```

In `ConfigUpdate` add:

```ts
  approval_expiry_hours?: number;
  approval_whatsapp_enabled?: boolean;
  approval_whatsapp_number?: string;
  approval_whatsapp_server_id?: string | null;
  approval_whatsapp_session_id?: string | null;
  approval_whatsapp_template?: string;
```

After `McpTestResult` add:

```ts
// Risk levels: the single source of labels for every screen.
export type RiskLevel = 0 | 1 | 2 | 3;
export const RISK_LEVELS: readonly { level: RiskLevel; code: string; label: string; hint: string }[] = [
  { level: 0, code: "R0", label: "Read-only", hint: "Lists, reads, searches" },
  { level: 1, code: "R1", label: "Limited writes", hint: "Reversible, low-impact changes" },
  { level: 2, code: "R2", label: "Significant changes", hint: "Sends, updates, money, external effects" },
  { level: 3, code: "R3", label: "Destructive or irreversible", hint: "Deletes, purges, resets. Never automatic" },
];
export interface ToolPolicy {
  name: string;
  description: string | null;
  risk_level: RiskLevel;
}
```

In `Agent` add `max_auto_risk: RiskLevel;` after `cron_expr`; in `AgentCreate` add `max_auto_risk?: RiskLevel;`.

After `AgentTaskDetail` (and change it) add:

```ts
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export interface Approval {
  id: string;
  task_id: string;
  agent_id: string;
  agent_name: string | null;
  task_objective: string | null;
  step_seq: number;
  call_index: number;
  tool_name: string;
  server_name: string;
  args: Record<string, unknown>;
  risk_level: RiskLevel;
  code: string;
  status: ApprovalStatus;
  requested_at: string;
  expires_at: string;
  seconds_left: number;
  decided_at: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  notified_at: string | null;
  notify_error: string | null;
  consumed_at: string | null;
}
export interface AgentTaskDetail extends AgentTask {
  steps: AgentTaskStep[];
  approval: Approval | null;
}
```

(Remove the previous two-line `AgentTaskDetail` declaration so there is exactly one.)

- [ ] **Step 2: `RiskBadge`**

Create `frontend/src/components/Agents/RiskBadge.tsx`:

```tsx
import { RISK_LEVELS } from "../../lib/api";

const STYLE: Record<number, { color: string; bg: string; border: string }> = {
  0: { color: "var(--success)",        bg: "rgba(52, 211, 153, 0.10)",  border: "rgba(52, 211, 153, 0.3)" },
  1: { color: "var(--running)",        bg: "rgba(96, 165, 250, 0.12)",  border: "rgba(96, 165, 250, 0.3)" },
  2: { color: "var(--warning)",        bg: "rgba(251, 191, 36, 0.12)",  border: "rgba(251, 191, 36, 0.35)" },
  3: { color: "var(--error)",          bg: "rgba(248, 113, 113, 0.12)", border: "rgba(248, 113, 113, 0.35)" },
};

/** One badge per risk level. Unknown values (a payload from an older run) render as a neutral "R?" badge rather than throwing. */
export function RiskBadge({ level, compact = false }: { level: number; compact?: boolean }) {
  const def = RISK_LEVELS.find((r) => r.level === level);
  const s = STYLE[level] ?? { color: "var(--text-muted)", bg: "rgba(100, 116, 139, 0.10)", border: "rgba(100, 116, 139, 0.3)" };
  const code = def?.code ?? "R?";
  return (
    <span className="badge font-mono" title={def ? `${def.label}: ${def.hint}` : "Unknown risk level"} style={{ color: s.color, backgroundColor: s.bg, border: `1px solid ${s.border}` }}>
      {compact || !def ? code : `${code} ${def.label}`}
    </span>
  );
}
```

- [ ] **Step 3: `timeLeft` in `time.ts`**

Append:

```ts
/** "expires in 3 h 12 min" / "expires in 40 s" / "expired" for a future deadline. */
export function timeLeft(iso: string | null): string {
  if (!iso) return "";
  const sec = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (sec <= 0) return "expired";
  if (sec < 60) return `expires in ${sec} s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `expires in ${min} min`;
  return `expires in ${Math.floor(min / 60)} h ${min % 60} min`;
}
```

- [ ] **Step 4: Verify and commit**

Run from `frontend/`: `npm run lint` (baseline only) and `npm run build` (green: nothing consumes the new fields yet, and `AgentTaskDetail.approval` is only read by `getAgentTask`'s callers which do not touch it).

```bash
git add frontend/src/lib/api.ts frontend/src/components/Agents/RiskBadge.tsx frontend/src/components/Agents/time.ts
git commit -m "feat(agents-ui): add the approvals and tool policy API client, risk badge and time-left helper

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

---

### Task 2: Settings → MCP servers tools panel

**Files:**
- Create: `frontend/src/components/Config/McpToolsPanel.tsx`
- Delete: `frontend/src/components/Config/McpToolsPreview.tsx`
- Modify: `frontend/src/components/Config/McpServerList.tsx`

**Interfaces:** Consumes `listServerTools`, `setToolPolicy`, `RISK_LEVELS`, `ToolPolicy`, `RiskBadge`. Produces `McpToolsPanel({ serverId, serverName })`.

- [ ] **Step 1: Create `McpToolsPanel.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RISK_LEVELS, listServerTools, setToolPolicy } from "../../lib/api";
import type { RiskLevel, ToolPolicy } from "../../lib/api";
import { RiskBadge } from "../Agents/RiskBadge";
import { MutationError } from "../ui/MutationError";
import { Spinner } from "../ui/Spinner";

const RULE = "A tool runs without approval when its level is at or below the agent's ceiling; everything above parks the task until an operator decides. R3 always requires approval.";

export function McpToolsPanel({ serverId, serverName }: { serverId: string; serverName: string }) {
  const queryClient = useQueryClient();
  const key = ["mcp-server-tools", serverId];
  // Discovery opens a real MCP connection: fetched on demand, never in the background.
  const { data: tools = [], isLoading, isFetching, error, refetch } = useQuery({ queryKey: key, queryFn: () => listServerTools(serverId), staleTime: Infinity, retry: false });
  const [filter, setFilter] = useState("");
  const [pendingName, setPendingName] = useState<string | null>(null);

  const setLevel = useMutation({
    mutationFn: ({ name, level }: { name: string; level: RiskLevel }) => setToolPolicy(serverId, name, level),
    onMutate: ({ name }) => setPendingName(name),
    onSuccess: (updated: ToolPolicy) => {
      queryClient.setQueryData<ToolPolicy[]>(key, (prev) => prev?.map((t) => (t.name === updated.name ? { ...t, risk_level: updated.risk_level } : t)));
    },
    onSettled: () => setPendingName(null),
  });

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? tools.filter((t) => t.name.toLowerCase().includes(q) || (t.description ?? "").toLowerCase().includes(q)) : tools;
  }, [tools, filter]);
  const counts = useMemo(() => RISK_LEVELS.map((r) => tools.filter((t) => t.risk_level === r.level).length), [tools]);

  return (
    <div className="mt-3 rounded-lg p-3 space-y-3" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
          Tools on {serverName}{tools.length ? ` · ${tools.length}` : ""}
        </p>
        {tools.length > 0 && (
          <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
            {RISK_LEVELS.map((r, i) => `${r.code} ${counts[i]}`).join(" · ")}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <input className="input-field" style={{ width: "12rem", padding: "0.3rem 0.6rem", fontSize: "0.75rem" }} placeholder="Filter tools" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <button type="button" className="btn-secondary btn-sm" disabled={isFetching} onClick={() => refetch()}>{isFetching ? "Discovering…" : "Refresh"}</button>
        </div>
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>{RULE}</p>

      {isLoading && <div className="flex justify-center py-4"><Spinner /></div>}
      {error ? <p className="text-xs" style={{ color: "var(--error)" }}>{(error as Error).message}</p> : null}
      {!isLoading && !error && tools.length === 0 && <p className="text-xs" style={{ color: "var(--text-muted)" }}>No tools discovered on this server.</p>}
      {visible.length > 0 && (
        <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
          {visible.map((t) => (
            <li key={t.name} className="flex items-center gap-3 py-2 text-xs">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <code className="font-mono truncate" style={{ color: "var(--text-primary)" }}>{t.name}</code>
                  <RiskBadge level={t.risk_level} compact />
                </div>
                {t.description && <p className="mt-0.5 line-clamp-2" style={{ color: "var(--text-muted)" }}>{t.description}</p>}
              </div>
              <select
                className="input-field flex-shrink-0"
                style={{ width: "15rem", padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}
                value={t.risk_level}
                disabled={pendingName === t.name}
                aria-label={`Risk level of ${t.name}`}
                onChange={(e) => setLevel.mutate({ name: t.name, level: Number(e.target.value) as RiskLevel })}
              >
                {RISK_LEVELS.map((r) => <option key={r.level} value={r.level}>{r.code} · {r.label}</option>)}
              </select>
            </li>
          ))}
        </ul>
      )}
      {visible.length === 0 && tools.length > 0 && <p className="text-xs" style={{ color: "var(--text-muted)" }}>No tool matches "{filter}".</p>}
      <MutationError error={setLevel.error} />
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `McpServerList.tsx`**

- Replace `import { McpToolsPreview } from "./McpToolsPreview";` with `import { McpToolsPanel } from "./McpToolsPanel";`.
- Add state `const [toolsOpenId, setToolsOpenId] = useState<string | null>(null);`.
- In `handleTest`, after a successful result (`result.success`), call `queryClient.invalidateQueries({ queryKey: ["mcp-server-tools", id] })` and `setToolsOpenId(id)` so the freshly synced policies appear.
- In the button group, before the "Test" button, add a "Tools" toggle with the same styling as "Edit":
  ```tsx
  <button onClick={() => setToolsOpenId((cur) => (cur === server.id ? null : server.id))} className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150" aria-expanded={toolsOpenId === server.id} style={{ backgroundColor: "var(--bg-panel)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}>
    {toolsOpenId === server.id ? "Hide tools" : "Tools"}
  </button>
  ```
- Replace the `testResults[server.id] && (success ? <McpToolsPreview .../> : <p error/>)` block with: on success a one-line confirmation `<p className="mt-2 text-xs" style={{ color: "var(--success)" }}>Connected · {n} tool{s} discovered</p>`, on failure the existing error paragraph; then, independently, `{toolsOpenId === server.id && <McpToolsPanel serverId={server.id} serverName={server.name} />}`.
- Delete `frontend/src/components/Config/McpToolsPreview.tsx` (`git rm`). Grep for other importers first (`grep -rn McpToolsPreview frontend/src`); there must be none left.

- [ ] **Step 3: Verify and commit**

`npm run lint`, `npm run build` green. Manual check in `npm run dev` with the backend running: open Settings, click "Tools" on a server, change a level, reload the page and confirm it persisted.

```bash
git add frontend/src/components/Config/McpToolsPanel.tsx frontend/src/components/Config/McpServerList.tsx
git rm -q frontend/src/components/Config/McpToolsPreview.tsx
git commit -m "feat(agents-ui): classify MCP tools by risk level from the server list

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

---

### Task 3: Settings → Approvals section

**Files:**
- Create: `frontend/src/components/Config/ApprovalsConfig.tsx`
- Modify: `frontend/src/pages/ConfigPage.tsx`

**Interfaces:** Consumes `getConfig`, `updateConfig`, `listMcpServers`. Follows `GoogleConfig.tsx`'s draft-state pattern (local state `null` = untouched, Save sends only touched fields).

- [ ] **Step 1: Create `ApprovalsConfig.tsx`**

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, listMcpServers, updateConfig } from "../../lib/api";
import type { ConfigUpdate } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { Spinner } from "../ui/Spinner";

const labelClass = "mb-1.5 block text-xs font-medium uppercase tracking-wider";
const muted = { color: "var(--text-muted)" } as const;
const VARIABLES = "{agent} {tool} {server} {args} {code} {expires} {link}";

export function ApprovalsConfig() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });
  const [draft, setDraft] = useState<ConfigUpdate>({});
  const set = <K extends keyof ConfigUpdate>(key: K, value: ConfigUpdate[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = Object.keys(draft).length > 0;

  const mutation = useMutation({
    mutationFn: () => updateConfig(draft),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["config"] }); setDraft({}); },
  });

  if (isLoading || !config) return <div className="card p-6"><div className="flex justify-center py-8"><Spinner /></div></div>;

  const enabled = draft.approval_whatsapp_enabled ?? config.approval_whatsapp_enabled;
  const template = draft.approval_whatsapp_template ?? config.approval_whatsapp_template;
  const hours = draft.approval_expiry_hours ?? config.approval_expiry_hours;
  const whatsappServers = servers.filter((s) => s.enabled);
  const templateValid = template.includes("{code}");
  const hoursValid = Number.isInteger(hours) && hours >= 1 && hours <= 168;

  return (
    <div className="card p-6">
      <h3 className="mb-1 text-base font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Approvals</h3>
      <p className="mb-5 text-xs" style={muted}>Tool calls above an agent's ceiling park the task until an operator approves them here or by WhatsApp.</p>

      <div className="grid gap-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass} style={muted}>Expiry (hours)</label>
            <input type="number" min={1} max={168} className="input-field" value={hours} onChange={(e) => set("approval_expiry_hours", Number(e.target.value))} />
            <p className="mt-1 text-xs" style={muted}>1 to 168. An undecided approval expires and the task fails.</p>
          </div>
          <div>
            <label className={labelClass} style={muted}>Admin WhatsApp number</label>
            <input className="input-field" placeholder="+2250700003331" value={draft.approval_whatsapp_number ?? config.approval_whatsapp_number} onChange={(e) => set("approval_whatsapp_number", e.target.value)} />
            <p className="mt-1 text-xs" style={muted}>Digits with an optional leading +. Replies come from this chat.</p>
          </div>
        </div>

        <label className="flex items-start gap-2.5 text-sm cursor-pointer" style={{ color: "var(--text-primary)" }}>
          <input type="checkbox" className="mt-0.5" checked={enabled} onChange={(e) => set("approval_whatsapp_enabled", e.target.checked)} />
          <span>
            <span>Notify on WhatsApp and accept replies</span>
            <span className="block text-xs" style={muted}>
              Sends "OUI/NON code" instructions to the number above and polls the chat every minute. Anyone who can write in that chat can decide: keep it to yourself.
            </span>
          </span>
        </label>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass} style={muted}>WhatsApp MCP server</label>
            <select className="input-field" value={draft.approval_whatsapp_server_id === undefined ? (config.approval_whatsapp_server_id ?? "") : (draft.approval_whatsapp_server_id ?? "")} onChange={(e) => set("approval_whatsapp_server_id", e.target.value || null)}>
              <option value="">Auto (first enabled server named "whatsapp")</option>
              {whatsappServers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass} style={muted}>WhatsApp session id</label>
            <input className="input-field" placeholder="Auto (first ready session)" value={draft.approval_whatsapp_session_id === undefined ? (config.approval_whatsapp_session_id ?? "") : (draft.approval_whatsapp_session_id ?? "")} onChange={(e) => set("approval_whatsapp_session_id", e.target.value || null)} />
          </div>
        </div>

        <div>
          <label className={labelClass} style={muted}>Message template</label>
          <textarea rows={5} className="input-field font-mono" value={template} onChange={(e) => set("approval_whatsapp_template", e.target.value)} />
          <p className="mt-1 text-xs" style={{ color: templateValid ? "var(--text-muted)" : "var(--error)" }}>
            Variables: <code className="font-mono">{VARIABLES}</code>. {templateValid ? "" : "The template must contain {code}."}
          </p>
        </div>

        <MutationError error={mutation.error} />
        <button className="btn-primary" disabled={!dirty || !templateValid || !hoursValid || mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Mount it**

In `ConfigPage.tsx` import `ApprovalsConfig` and render it between `<GoogleConfig />` and `<McpServerList />`.

- [ ] **Step 3: Verify and commit**

`npm run lint`, `npm run build` green. Manual: change the expiry to 48, save, reload: 48 persists; clear the session id to empty, save: it reads "Auto" after reload (explicit null was sent).

```bash
git add frontend/src/components/Config/ApprovalsConfig.tsx frontend/src/pages/ConfigPage.tsx
git commit -m "feat(agents-ui): add the approvals settings section

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

---

### Task 4: Agent ceiling in the form and on the card

**Files:**
- Modify: `frontend/src/components/Agents/AgentFormModal.tsx`, `frontend/src/components/Agents/AgentCard.tsx`

- [ ] **Step 1: Form**

In `AgentFormModal.tsx`:
- Import `RISK_LEVELS` and `type RiskLevel` from `../../lib/api`.
- State: `const [maxAutoRisk, setMaxAutoRisk] = useState<RiskLevel>(1);` and in the re-seed effect `setMaxAutoRisk(agent?.max_auto_risk ?? 1);`.
- In `submit`, add `max_auto_risk: maxAutoRisk,` to the payload.
- After the "Authorised MCP servers" block and before the schedule block, add:
  ```tsx
  <div>
    <label className={labelClass} style={labelStyle}>Automatic up to</label>
    <select className="input-field" value={maxAutoRisk} onChange={(e) => setMaxAutoRisk(Number(e.target.value) as RiskLevel)}>
      {RISK_LEVELS.filter((r) => r.level <= 2).map((r) => <option key={r.level} value={r.level}>{r.code} · {r.label}</option>)}
    </select>
    <p className="mt-1 text-xs" style={labelStyle}>Tools at or below this level run on their own; anything above waits for your approval. R3 tools always wait. Levels are set per server in Settings.</p>
  </div>
  ```

- [ ] **Step 2: Card**

In `AgentCard.tsx`, import `RiskBadge` and in the meta line (`{agent.max_steps} steps · {agent.timeout_seconds} s`) prepend a ceiling badge: `<span className="flex items-center gap-1">auto ≤ <RiskBadge level={agent.max_auto_risk} compact /></span>`.

- [ ] **Step 3: Verify and commit**

`npm run lint`, `npm run build` green. Manual: edit an agent, set R0, save; the card shows `auto ≤ R0`; reopen the modal: R0 is selected.

```bash
git add frontend/src/components/Agents/AgentFormModal.tsx frontend/src/components/Agents/AgentCard.tsx
git commit -m "feat(agents-ui): set and show the agent's automatic risk ceiling

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

---

### Task 5: Task page — approval card, step badges, live refresh

**Files:**
- Create: `frontend/src/components/Agents/ApprovalCard.tsx`
- Modify: `frontend/src/components/Agents/useAgentTaskStream.ts`, `frontend/src/components/Agents/TaskTimeline.tsx`, `frontend/src/pages/AgentTaskPage.tsx`

**Interfaces:** `ApprovalCard({ approval, taskId })`; consumes `approveApproval`, `rejectApproval`, `RiskBadge`, `timeLeft`.

- [ ] **Step 1: Refetch the detail on status changes**

In `useAgentTaskStream.ts`, inside the `status` branch of the event handler, after the two `set*` calls add:

```ts
        // `approval` lives on the detail, not on the stream: a park or a decision changes it, so refresh the base once per status change.
        queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
```

The merge already prefers `liveStatus` over the stale base status, so the card is driven by `task.approval` (from the refetched detail) gated by `task.status === "waiting_approval"` (from the stream). Note the existing `useEffect` dependency list already contains `queryClient` and `taskId`.

- [ ] **Step 2: Create `ApprovalCard.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approveApproval, rejectApproval } from "../../lib/api";
import type { Approval } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { RiskBadge } from "./RiskBadge";
import { timeLeft } from "./time";

function notification(a: Approval): { text: string; color: string } {
  if (a.notified_at) return { text: `WhatsApp sent ${new Date(a.notified_at).toLocaleTimeString()}`, color: "var(--success)" };
  if (a.notify_error === "notifications disabled") return { text: "WhatsApp notifications are off", color: "var(--text-muted)" };
  if (a.notify_error) return { text: `WhatsApp failed: ${a.notify_error}`, color: "var(--error)" };
  return { text: "WhatsApp not sent yet", color: "var(--text-muted)" };
}

export function ApprovalCard({ approval, taskId }: { approval: Approval; taskId: string }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  // Re-render the countdown without refetching.
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick((n) => n + 1), 30000); return () => clearInterval(id); }, []);

  const done = () => {
    queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
    queryClient.invalidateQueries({ queryKey: ["approvals"] });
    queryClient.invalidateQueries({ queryKey: ["agents"] });
  };
  const approve = useMutation({ mutationFn: () => approveApproval(approval.id, reason), onSuccess: done });
  const reject = useMutation({ mutationFn: () => rejectApproval(approval.id, reason), onSuccess: done });
  const busy = approve.isPending || reject.isPending;
  const note = notification(approval);

  return (
    <section className="rounded-xl p-4 space-y-3" style={{ backgroundColor: "rgba(251, 191, 36, 0.06)", border: "1px solid rgba(251, 191, 36, 0.35)" }} aria-labelledby="approval-title">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 id="approval-title" className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--warning)" }}>Approval required</h3>
        <RiskBadge level={approval.risk_level} />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{timeLeft(approval.expires_at)}</span>
        <span className="ml-auto font-mono text-sm" title="Reply OUI or NON followed by this code on WhatsApp" style={{ color: "var(--text-primary)" }}>code {approval.code}</span>
      </div>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        The agent wants to call <code className="font-mono" style={{ color: "var(--accent)" }}>{approval.tool_name}</code> on {approval.server_name}.
      </p>
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg px-3 py-2 font-mono text-xs max-h-64 overflow-y-auto" style={{ backgroundColor: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
        {JSON.stringify(approval.args, null, 2)}
      </pre>
      <p className="text-xs" style={{ color: note.color }}>{note.text}</p>
      <div className="flex items-center gap-2 flex-wrap">
        <input className="input-field" style={{ maxWidth: "24rem" }} placeholder="Reason (optional, sent back to the agent on reject)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="btn-primary btn-sm" disabled={busy} onClick={() => approve.mutate()}>{approve.isPending ? "Approving…" : "Approve"}</button>
        <button type="button" className="btn-danger btn-sm" disabled={busy} onClick={() => reject.mutate()}>{reject.isPending ? "Rejecting…" : "Reject"}</button>
      </div>
      <MutationError error={approve.error ?? reject.error} />
    </section>
  );
}
```

- [ ] **Step 3: Timeline**

In `TaskTimeline.tsx`:
- Import `RiskBadge` from `./RiskBadge`.
- In `ToolCallBody`, compute `const rejected = !ok && String(payload.result ?? "").includes("rejected by operator");` and in the header button, after the tool name, add `{typeof payload.risk_level === "number" && <RiskBadge level={payload.risk_level} compact />}` and, when `typeof payload.approval_id === "string"`, `<span style={{ color: "var(--text-muted)" }}>{rejected ? "rejected by operator" : "approved by operator"}</span>`.
- Add a component for the new kind:
  ```tsx
  function ApprovalRequestedBody({ payload }: { payload: Record<string, unknown> }) {
    return (
      <div className="rounded-lg px-3 py-2 text-xs space-y-1" style={{ border: "1px solid rgba(251, 191, 36, 0.35)", backgroundColor: "rgba(251, 191, 36, 0.06)" }}>
        <div className="flex items-center gap-2 flex-wrap">
          <span style={{ color: "var(--warning)" }}>Parked</span>
          <code className="font-mono" style={{ color: "var(--accent)" }}>{String(payload.tool)}</code>
          {payload.server ? <span style={{ color: "var(--text-muted)" }}>on {String(payload.server)}</span> : null}
          {typeof payload.risk_level === "number" && <RiskBadge level={payload.risk_level} compact />}
          {typeof payload.code === "string" && <span className="ml-auto font-mono" style={{ color: "var(--text-secondary)" }}>code {payload.code}</span>}
        </div>
        <pre className="overflow-x-auto whitespace-pre-wrap font-mono" style={{ color: "var(--text-secondary)" }}>{pretty(payload.args ?? {})}</pre>
      </div>
    );
  }
  ```
  and in `StepCard` add `{step.kind === "approval_requested" && <ApprovalRequestedBody payload={p} />}`. The decision itself appears as the following `tool_call` step (approved: executed; rejected: `Failed` with the refusal), so no extra lookup is needed here.

- [ ] **Step 4: Page**

In `AgentTaskPage.tsx`:
- Import `ApprovalCard` from `../components/Agents/ApprovalCard`.
- Delete the "No approval step yet" paragraph.
- Right after the header `div` (before the plan/critique grid) add:
  ```tsx
  {task.status === "waiting_approval" && task.approval && (
    <ErrorBoundary><ApprovalCard approval={task.approval} taskId={taskId} /></ErrorBoundary>
  )}
  {task.status === "waiting_approval" && !task.approval && (
    <p className="text-xs rounded-lg px-3 py-2" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.08)", border: "1px solid rgba(251, 191, 36, 0.25)" }}>
      Waiting for an approval that is no longer pending. It may have been decided elsewhere or expired; the task will move on or fail within a minute.
    </p>
  )}
  ```
- The header's live counters already derive from steps; nothing else changes. The Cancel button remains available while waiting (status is not final).

- [ ] **Step 5: Verify and commit**

`npm run lint`, `npm run build` green. Manual end-to-end against the local backend (`backend` on :8000 and `python -m app.worker` running): set a tool to R2 on a server, an agent to R0, run it; the task page shows the Waiting approval badge and the card with the code; click Approve; the card disappears, the status goes queued → running, a new tool-call step shows the risk badge and "approved by operator". If the local LLM key cannot be decrypted (known dev-DB issue), do this part in production during the final browser pass and say so in the report.

```bash
git add frontend/src/components/Agents/ApprovalCard.tsx frontend/src/components/Agents/useAgentTaskStream.ts frontend/src/components/Agents/TaskTimeline.tsx frontend/src/pages/AgentTaskPage.tsx
git commit -m "feat(agents-ui): decide approvals from the task page and show risk on tool calls

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

---

### Task 6: Pending approvals strip and sidebar counter

**Files:**
- Create: `frontend/src/components/Agents/PendingApprovalsStrip.tsx`
- Modify: `frontend/src/pages/AgentsPage.tsx`, `frontend/src/components/Layout/TabNav.tsx`, `frontend/src/components/Agents/AgentList.tsx`

- [ ] **Step 1: Strip**

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listApprovals } from "../../lib/api";
import { RiskBadge } from "./RiskBadge";
import { timeLeft } from "./time";

export function PendingApprovalsStrip() {
  const { data: pending = [] } = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => listApprovals("pending"), refetchInterval: 15000 });
  if (pending.length === 0) return null;
  return (
    <section className="rounded-xl p-3 space-y-2" style={{ backgroundColor: "rgba(251, 191, 36, 0.06)", border: "1px solid rgba(251, 191, 36, 0.35)" }} aria-label="Pending approvals">
      <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--warning)" }}>
        {pending.length} approval{pending.length > 1 ? "s" : ""} pending
      </p>
      <ul className="space-y-1">
        {pending.map((a) => (
          <li key={a.id}>
            <Link to={`/agents/${a.agent_id}/tasks/${a.task_id}`} className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)", textDecoration: "none" }}>
              <span className="font-medium truncate" style={{ color: "var(--text-primary)" }}>{a.agent_name ?? "Agent"}</span>
              <code className="font-mono truncate" style={{ color: "var(--accent)" }}>{a.tool_name}</code>
              <RiskBadge level={a.risk_level} compact />
              <span className="ml-auto flex-shrink-0" style={{ color: "var(--text-muted)" }}>{timeLeft(a.expires_at)}</span>
              <span className="flex-shrink-0 font-mono" style={{ color: "var(--text-muted)" }}>{a.code}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 2: Mount on the Agents page**

In `AgentsPage.tsx` import `PendingApprovalsStrip` and render `<PendingApprovalsStrip />` between the header row and the Active/Archived tabs.

- [ ] **Step 3: Keep the list polling while a task waits**

In `AgentList.tsx`, `hasOpenTask` already treats any non-final status as open, so a `waiting_approval` task keeps the 5 s refetch; update the comment above it to: `/** A run still in flight: queued and waiting_approval count too, since running_task_id is set only while the worker holds the task. */`. In `AgentCard.tsx` the comment on `openTask` says the same thing; align its wording.

- [ ] **Step 4: Sidebar counter**

In `TabNav.tsx`, import `listApprovals` and inside `SystemStatus` add
`const { data: pendingApprovals = [] } = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => listApprovals("pending"), refetchInterval: 30000 });`
and a fourth line after "Active agents":
`<div className="system-status-line"><i className={pendingApprovals.length ? "is-warm" : ""}/><span>Pending approvals</span><b>{pendingApprovals.length}</b></div>`.

- [ ] **Step 5: Verify and commit**

`npm run lint`, `npm run build` green. Manual: with one approval pending the strip appears on Agents with the right agent, tool, badge and code, the sidebar shows 1; deciding it on the task page clears both within 15 s.

```bash
git add frontend/src/components/Agents/PendingApprovalsStrip.tsx frontend/src/pages/AgentsPage.tsx frontend/src/components/Layout/TabNav.tsx frontend/src/components/Agents/AgentList.tsx frontend/src/components/Agents/AgentCard.tsx
git commit -m "feat(agents-ui): surface pending approvals on the Agents page and in the sidebar

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

---

### Task 7: Docs and final checks

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1:** In `CLAUDE.md`'s Agents section, after the sentence ending "this is why prompts are kept.", append:

```markdown
On the frontend, tool levels are edited from Settings → MCP servers ("Tools" per server, `McpToolsPanel.tsx`), the ceiling from the agent form, WhatsApp settings from Settings → Approvals (`ApprovalsConfig.tsx`), and a parked task is decided from its page (`ApprovalCard.tsx`, driven by `AgentTaskDetail.approval`, which `useAgentTaskStream` refetches on every SSE status change); `PendingApprovalsStrip.tsx` and the sidebar counter poll `GET /approvals?status=pending`.
```

- [ ] **Step 2:** From `frontend/`: `npm run lint` (baseline), `npm run build` (green). From `backend/`: `venv/bin/python -m pytest tests/ -q -p no:cacheprovider` (unchanged, must still be green: 485 passed, one known `AuthlibDeprecationWarning`). `git status` clean apart from the doc change.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agents): describe the approvals screens

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NqXje8tsfP1rErD6hER7qx"
```

The browser pass in production (read-only agent capped at R0 requesting an R2 tool, decided once by WhatsApp and once in the UI) happens after the deploy of 3a + 3b together; it is the acceptance test of the whole sub-project, not part of this plan's commits.
