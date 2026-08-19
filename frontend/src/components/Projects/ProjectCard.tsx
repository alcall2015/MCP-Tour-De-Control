import type { Project } from "../../lib/api";
import { Sparkline } from "./Sparkline";
import { StatusDot } from "./StatusDot";

// Rendered by DecisionsPanel instead of the metric grid.
const HIDDEN_METRICS = new Set(["decision_attendue"]);
const BUDGET_KEYS = new Set(["budget_consomme", "budget_total"]);

function formatNumber(value: number): string {
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function Trend({ delta }: { delta: number | undefined }) {
  if (delta === undefined || delta === 0) return null;
  const up = delta > 0;
  return (
    <span className="ml-1.5 text-xs" style={{ color: up ? "var(--success)" : "var(--error)" }}>
      {up ? "▲" : "▼"} {formatNumber(Math.abs(delta))}
    </span>
  );
}

function relativeDate(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function ProjectCard({ project }: { project: Project }) {
  const metrics = project.metrics ?? {};
  const consumed = metrics.budget_consomme;
  const total = metrics.budget_total;
  const extraKeys = Object.keys(metrics).filter(
    (key) => !HIDDEN_METRICS.has(key) && !BUDGET_KEYS.has(key) && key !== "avancement",
  );

  return (
    <div className="card p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3
            className="text-base font-semibold"
            style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}
          >
            {project.name}
          </h3>
          {project.description && (
            <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
              {project.description}
            </p>
          )}
        </div>
        <StatusDot status={project.status} />
      </div>

      {project.error && (
        <p className="mb-3 text-xs" style={{ color: "var(--error)" }}>
          Read failed — showing last known values from {relativeDate(project.captured_at)}.
        </p>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        {typeof metrics.avancement === "number" && (
          <div>
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Progress
            </span>
            <div className="text-sm" style={{ color: "var(--text-primary)" }}>
              {formatNumber(metrics.avancement)}%
              <Trend delta={project.trends.avancement} />
            </div>
          </div>
        )}

        {typeof consumed === "number" && typeof total === "number" && (
          <div>
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Budget
            </span>
            <div className="text-sm" style={{ color: "var(--text-primary)" }}>
              {formatNumber(consumed)} / {formatNumber(total)}
              <Trend delta={project.trends.budget_consomme} />
            </div>
          </div>
        )}

        {project.sparkline.length > 1 && <Sparkline values={project.sparkline} />}
      </div>

      {extraKeys.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1">
          {extraKeys.map((key) => (
            <span key={key} className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {humanize(key)}:{" "}
              <span style={{ color: "var(--text-primary)" }}>
                {typeof metrics[key] === "number" ? formatNumber(metrics[key] as number) : String(metrics[key])}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {project.links.map((link) => (
          <a
            key={link.id}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded px-2 py-1 text-xs transition-colors"
            style={{ backgroundColor: "var(--bg-elevated)", color: "var(--text-secondary)" }}
            title={link.is_kpi_source ? "KPI source" : link.url}
          >
            {link.label}
            {link.is_kpi_source ? " *" : ""}
          </a>
        ))}
        {project.links.length === 0 && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            No links yet
          </span>
        )}
      </div>

      <p className="mt-3 text-xs" style={{ color: "var(--text-muted)" }}>
        Last read {relativeDate(project.captured_at)}
        {project.source_modified_at && ` · file modified ${relativeDate(project.source_modified_at)}`}
      </p>
    </div>
  );
}
