import type { StressTestMetrics } from "../../lib/api";

interface Props {
  metrics: StressTestMetrics | null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b" style={{ borderColor: "var(--border)" }}>
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="text-sm font-medium font-mono" style={{ color: "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

const SIP_CODE_COLORS: Record<string, string> = {
  "4": "var(--warning)",
  "5": "var(--error)",
  "6": "#c084fc",
};

function getCodeColor(code: string): string {
  const first = code[0];
  return SIP_CODE_COLORS[first] ?? "var(--text-muted)";
}

export function SipMetricsCard({ metrics }: Props) {
  const failedByCodes = metrics?.failed_by_code ?? null;
  const hasFailures = failedByCodes && Object.keys(failedByCodes).length > 0;

  return (
    <div className="card p-5 space-y-4">
      <h3
        className="text-sm font-semibold uppercase tracking-wider"
        style={{
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          color: "var(--text-secondary)",
        }}
      >
        SIP Metrics
      </h3>

      <div className="space-y-0">
        <Row
          label="Total Calls"
          value={metrics ? String(metrics.total_calls) : "—"}
        />
        <Row
          label="Successful"
          value={metrics ? String(metrics.successful_calls) : "—"}
        />
        <Row
          label="Failed"
          value={metrics ? String(metrics.failed_calls) : "—"}
        />
        <Row
          label="ASR"
          value={metrics ? `${metrics.asr_percent.toFixed(2)}%` : "—"}
        />
        <Row
          label="Setup Time Avg"
          value={metrics ? `${metrics.setup_time_avg_ms.toFixed(0)} ms` : "—"}
        />
        <Row
          label="Retransmissions"
          value={metrics ? String(metrics.retransmissions) : "—"}
        />
        <Row
          label="PDD Avg"
          value={metrics ? `${metrics.pdd_avg_ms.toFixed(0)} ms` : "—"}
        />
        <Row
          label="PDD p95"
          value={metrics ? `${metrics.pdd_p95_ms.toFixed(0)} ms` : "—"}
        />
      </div>

      {hasFailures && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Failed by Code
          </p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(failedByCodes!).map(([code, count]) => (
              <span
                key={code}
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-mono font-semibold"
                style={{
                  backgroundColor: `${getCodeColor(code)}1a`,
                  border: `1px solid ${getCodeColor(code)}33`,
                  color: getCodeColor(code),
                }}
              >
                {code} <span style={{ color: "var(--text-secondary)" }}>×{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {!metrics && (
        <p className="text-sm text-center py-4" style={{ color: "var(--text-muted)" }}>
          No metrics yet
        </p>
      )}
    </div>
  );
}
