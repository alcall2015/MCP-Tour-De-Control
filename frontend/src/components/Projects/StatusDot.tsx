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

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function StatusDot({ status }: { status: ProjectStatus }) {
  const color = COLORS[status.level];
  // The "unknown" level covers three distinct situations (no source, not
  // refreshed yet, empty SUIVI tab) — show the specific reason instead of a
  // single fixed label. The other levels keep their fixed labels.
  const label = status.level === "unknown" ? capitalize(status.reason) : LABELS[status.level];
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium" title={status.reason}>
      <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <span style={{ color }}>{label}</span>
    </span>
  );
}
