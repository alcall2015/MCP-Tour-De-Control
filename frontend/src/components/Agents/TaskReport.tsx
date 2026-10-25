import type { AgentReport } from "../../lib/api";

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>{title}</p>
      <ul className="list-disc pl-5 text-sm space-y-0.5" style={{ color: "var(--text-secondary)" }}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}

export function TaskReport({ report }: { report: AgentReport | null }) {
  return (
    <section className="card p-4 space-y-3">
      <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Report</h3>
      {!report ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>No report yet.</p>
      ) : (
        <>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>{report.summary}</p>
          {report.actions.length > 0 && (
            <div>
              <p className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Actions</p>
              <ul className="space-y-0.5 text-sm" style={{ color: "var(--text-secondary)" }}>
                {report.actions.map((a, i) => (
                  <li key={i}><a href={`#step-${a.step_seq}`} className="font-mono text-xs mr-2" style={{ color: "var(--accent)" }}>#{a.step_seq}</a>{a.description}</li>
                ))}
              </ul>
            </div>
          )}
          <List title="Evidence" items={report.evidence} />
          <List title="Uncertainties" items={report.uncertainties} />
          <List title="Next steps" items={report.next_steps} />
        </>
      )}
    </section>
  );
}
