import type { PendingDecision } from "../../lib/api";

export function DecisionsPanel({ decisions }: { decisions: PendingDecision[] }) {
  if (decisions.length === 0) return null;

  return (
    <div className="card p-5" style={{ borderColor: "var(--warning)" }}>
      <h3
        className="mb-3 text-sm font-semibold uppercase tracking-wider"
        style={{ color: "var(--warning)" }}
      >
        Pending decisions ({decisions.length})
      </h3>
      <ul className="grid gap-2">
        {decisions.map((decision) => (
          <li key={decision.project_id} className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span style={{ color: "var(--text-muted)" }}>{decision.project_name} — </span>
            {decision.decision}
          </li>
        ))}
      </ul>
    </div>
  );
}
