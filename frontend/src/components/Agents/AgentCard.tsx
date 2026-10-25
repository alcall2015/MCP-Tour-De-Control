import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listAgentTasks } from "../../lib/api";
import type { Agent, AgentStatus } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { AgentTaskRow } from "./AgentTaskRow";
import { OutcomeBadge, TaskStatusBadge } from "./AgentTaskBadges";
import { relativeTime } from "./time";

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
