import type { ProjectStatus, ProjectStatusLevel } from "../../lib/api";

const COLORS: Record<ProjectStatusLevel, string> = {
  critical: "var(--error)",
  attention: "var(--warning)",
  nominal: "var(--success)",
  unknown: "var(--text-muted)",
};

const LABELS: Record<ProjectStatusLevel, string> = {
  critical: "Critical",
  attention: "Attention",
  nominal: "On track",
  unknown: "No source",
};

export function StatusDot({ status }: { status: ProjectStatus }) {
  const color = COLORS[status.level];
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium" title={status.reason}>
      <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <span style={{ color }}>{LABELS[status.level]}</span>
    </span>
  );
}
