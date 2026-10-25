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
