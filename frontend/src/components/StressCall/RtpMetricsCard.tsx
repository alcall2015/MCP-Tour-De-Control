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

function getMosColor(mos: number): string {
  if (mos > 4) return "var(--success)";
  if (mos > 3) return "var(--warning)";
  return "var(--error)";
}

export function RtpMetricsCard({ metrics }: Props) {
  const mos = metrics?.mos_score ?? null;
  const mosColor = mos !== null && mos > 0 ? getMosColor(mos) : "var(--text-muted)";

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start justify-between">
        <h3
          className="text-sm font-semibold uppercase tracking-wider"
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            color: "var(--text-secondary)",
          }}
        >
          RTP / Media Metrics
        </h3>

        {/* MOS score large display */}
        {mos !== null && mos > 0 && (
          <div className="flex flex-col items-center">
            <span
              className="font-display text-3xl font-bold leading-none"
              style={{
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                color: mosColor,
              }}
            >
              {mos.toFixed(2)}
            </span>
            <span className="text-xs font-semibold uppercase tracking-widest mt-0.5" style={{ color: "var(--text-muted)" }}>
              MOS
            </span>
          </div>
        )}
      </div>

      <div className="space-y-0">
        <Row
          label="Packets Sent"
          value={metrics ? metrics.packets_sent.toLocaleString() : "—"}
        />
        <Row
          label="Packets Received"
          value={metrics ? metrics.packets_received.toLocaleString() : "—"}
        />
        <Row
          label="Packet Loss"
          value={metrics ? `${metrics.packet_loss_pct.toFixed(2)}%` : "—"}
        />
        <Row
          label="Jitter Avg"
          value={metrics ? `${metrics.jitter_avg_ms.toFixed(1)} ms` : "—"}
        />
        <Row
          label="Jitter Max"
          value={metrics ? `${metrics.jitter_max_ms.toFixed(1)} ms` : "—"}
        />
        <Row
          label="RTT Avg"
          value={metrics ? `${metrics.rtt_avg_ms.toFixed(1)} ms` : "—"}
        />
        <Row
          label="RTT Max"
          value={metrics ? `${metrics.rtt_max_ms.toFixed(1)} ms` : "—"}
        />
        <Row
          label="Out of Order"
          value={metrics ? String(metrics.out_of_order) : "—"}
        />
        <Row
          label="Throughput"
          value={metrics ? `${metrics.throughput_kbps.toFixed(1)} kbps` : "—"}
        />
      </div>

      {!metrics && (
        <p className="text-sm text-center py-4" style={{ color: "var(--text-muted)" }}>
          No metrics yet
        </p>
      )}
    </div>
  );
}
