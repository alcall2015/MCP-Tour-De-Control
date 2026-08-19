import type { BudgetSummary } from "../../lib/api";

function format(value: number): string {
  return Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(0);
}

export function BudgetSummaryPanel({ summary }: { summary: BudgetSummary }) {
  if (summary.projects_counted === 0) return null;

  const ratio = summary.total > 0 ? Math.min(summary.consumed / summary.total, 1) : 0;
  const over = summary.consumed > summary.total;

  return (
    <div className="card p-5">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          Consolidated budget
        </h3>
        <span className="text-sm" style={{ color: "var(--text-primary)" }}>
          {format(summary.consumed)} / {format(summary.total)}
          <span style={{ color: "var(--text-muted)" }}> · {format(summary.remaining)} left</span>
        </span>
      </div>
      <div className="h-1.5 w-full rounded" style={{ backgroundColor: "var(--bg-elevated)" }}>
        <div
          className="h-1.5 rounded"
          style={{
            width: `${ratio * 100}%`,
            backgroundColor: over ? "var(--error)" : "var(--accent)",
          }}
        />
      </div>
      <p className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>
        Across {summary.projects_counted} project{summary.projects_counted !== 1 ? "s" : ""} reporting a budget
      </p>
    </div>
  );
}
