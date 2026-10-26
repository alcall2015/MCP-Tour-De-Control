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
