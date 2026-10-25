import type { AgentCritique, AgentPlan } from "../../lib/api";
import { text } from "./text";

export function TaskCritique({ critique, plan }: { critique: AgentCritique | null; plan: AgentPlan | null }) {
  const criteria = critique && Array.isArray(critique.criteria) ? critique.criteria : [];
  const describe = (id: string) => {
    const list = plan && Array.isArray(plan.success_criteria) ? plan.success_criteria : [];
    const match = list.find((c) => c?.id === id);
    return match ? text(match.description) : "";
  };
  return (
    <section className="card p-4 space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Self-critique</h3>
        {critique?.limit_hit && <span className="badge" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.12)", border: "1px solid rgba(251, 191, 36, 0.3)" }}>Stopped by {critique.limit_hit.replace("_", " ")}</span>}
      </div>
      {!critique ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Not evaluated yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wider text-left" style={{ color: "var(--text-muted)" }}>
              <th className="pb-2 pr-3 font-medium">Criterion</th>
              <th className="pb-2 pr-3 font-medium">Met</th>
              <th className="pb-2 pr-3 font-medium">Confidence</th>
              <th className="pb-2 font-medium">Justification</th>
            </tr>
          </thead>
          <tbody>
            {criteria.map((c, i) => {
              // The model can return anything here: coerce the confidence rather than trusting it is a number.
              const confidence = Number(c?.confidence) || 0;
              const counts = Boolean(c?.met) && confidence >= 0.5;
              return (
                <tr key={c?.id ?? i} className="align-top" style={{ borderTop: "1px solid var(--border)" }}>
                  <td className="py-2 pr-3"><span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{c?.id}</span> <span style={{ color: "var(--text-secondary)" }}>{describe(c?.id)}</span></td>
                  <td className="py-2 pr-3" style={{ color: counts ? "var(--success)" : "var(--error)" }}>{c?.met ? "yes" : "no"}</td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-24 rounded-full overflow-hidden" style={{ backgroundColor: "var(--bg-elevated)" }}>
                        <div className="h-full" style={{ width: `${Math.round(confidence * 100)}%`, backgroundColor: counts ? "var(--success)" : "var(--warning)" }} />
                      </div>
                      <span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{confidence.toFixed(2)}</span>
                    </div>
                  </td>
                  <td className="py-2" style={{ color: "var(--text-secondary)" }}>{text(c?.justification)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {critique && <p className="text-xs" style={{ color: "var(--text-muted)" }}>A criterion counts as met when the model says so with confidence ≥ 0.50. All met → success, none → failed, otherwise partial.</p>}
    </section>
  );
}
