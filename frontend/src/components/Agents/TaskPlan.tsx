import type { AgentPlan } from "../../lib/api";
import { text } from "./text";

export function TaskPlan({ plan }: { plan: AgentPlan | null }) {
  return (
    <section className="card p-4 space-y-3">
      <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Plan</h3>
      {!plan ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Not planned yet.</p>
      ) : (
        <>
          <ol className="space-y-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
            {(plan.steps ?? []).map((s, i) => {
              const tools = s.tools ?? [];
              return (
                <li key={i} className="flex gap-2">
                  <span className="font-mono" style={{ color: "var(--text-muted)" }}>{i + 1}.</span>
                  <span>
                    {s.title}
                    {tools.length > 0 && <span className="ml-2 font-mono text-xs" style={{ color: "var(--accent)" }}>{tools.map(text).join(", ")}</span>}
                  </span>
                </li>
              );
            })}
          </ol>
          <div>
            <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Success criteria</p>
            <ul className="space-y-1 text-sm" style={{ color: "var(--text-secondary)" }}>
              {(plan.success_criteria ?? []).map((c, i) => (
                <li key={c?.id ?? i} className="flex gap-2"><span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>{c?.id}</span><span>{text(c?.description)}</span></li>
              ))}
            </ul>
          </div>
          {Array.isArray(plan.risks) && plan.risks.length > 0 && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Risks</p>
              <ul className="list-disc pl-5 text-sm" style={{ color: "var(--text-secondary)" }}>{plan.risks.map((r, i) => <li key={i}>{text(r)}</li>)}</ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
