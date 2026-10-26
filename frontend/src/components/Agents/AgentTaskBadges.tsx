import type { AgentOutcome, AgentTaskStatus } from "../../lib/api";

// `color` is a CSS variable reference, so it cannot carry an alpha suffix: the border is a literal rgba() of the same hue.
const STATUS: Record<AgentTaskStatus | "gone", { color: string; bg: string; border: string; label: string; pulse?: boolean }> = {
  queued:    { color: "var(--text-secondary)", bg: "rgba(148, 163, 184, 0.12)", border: "rgba(148, 163, 184, 0.3)", label: "Queued" },
  running:   { color: "var(--running)",        bg: "rgba(96, 165, 250, 0.12)",  border: "rgba(96, 165, 250, 0.3)",  label: "Running", pulse: true },
  waiting_approval: { color: "var(--warning)", bg: "rgba(251, 191, 36, 0.12)",  border: "rgba(251, 191, 36, 0.35)", label: "Waiting approval", pulse: true },
  completed: { color: "var(--success)",        bg: "rgba(52, 211, 153, 0.10)",  border: "rgba(52, 211, 153, 0.3)",  label: "Completed" },
  failed:    { color: "var(--error)",          bg: "rgba(248, 113, 113, 0.12)", border: "rgba(248, 113, 113, 0.35)", label: "Failed" },
  cancelled: { color: "var(--text-muted)",     bg: "rgba(100, 116, 139, 0.10)", border: "rgba(100, 116, 139, 0.3)", label: "Cancelled" },
  gone:      { color: "var(--text-muted)",     bg: "rgba(100, 116, 139, 0.10)", border: "rgba(100, 116, 139, 0.3)", label: "Gone" },
};

const OUTCOME: Record<AgentOutcome, { color: string; bg: string; border: string; label: string }> = {
  success: { color: "var(--success)", bg: "rgba(52, 211, 153, 0.10)",  border: "rgba(52, 211, 153, 0.3)",   label: "Success" },
  partial: { color: "var(--warning)", bg: "rgba(251, 191, 36, 0.12)",  border: "rgba(251, 191, 36, 0.35)",  label: "Partial" },
  failed:  { color: "var(--error)",   bg: "rgba(248, 113, 113, 0.12)", border: "rgba(248, 113, 113, 0.35)", label: "Failed" },
};

export function TaskStatusBadge({ status }: { status: AgentTaskStatus | "gone" }) {
  const s = STATUS[status];
  return (
    <span className="badge" style={{ color: s.color, backgroundColor: s.bg, border: `1px solid ${s.border}` }}>
      <span className={`h-1.5 w-1.5 rounded-full inline-block ${s.pulse ? "pulse-dot" : ""}`} style={{ backgroundColor: s.color }} />
      {s.label}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: AgentOutcome | null }) {
  if (!outcome) return null;
  const o = OUTCOME[outcome];
  return <span className="badge" style={{ color: o.color, backgroundColor: o.bg, border: `1px solid ${o.border}` }}>{o.label}</span>;
}
