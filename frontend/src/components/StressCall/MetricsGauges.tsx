import type { StressTestMetrics } from "../../lib/api";

interface Props {
  metrics: StressTestMetrics | null;
}

function getAsrColor(asr: number): string {
  if (asr > 95) return "var(--success)";
  if (asr > 90) return "var(--warning)";
  return "var(--error)";
}

function getMosColor(mos: number): string {
  if (mos > 4) return "var(--success)";
  if (mos > 3) return "var(--warning)";
  return "var(--error)";
}

function getLossColor(loss: number): string {
  if (loss < 1) return "var(--success)";
  if (loss < 5) return "var(--warning)";
  return "var(--error)";
}

function getPddColor(pdd: number): string {
  if (pdd < 50) return "var(--success)";
  if (pdd < 200) return "var(--warning)";
  return "var(--error)";
}

interface GaugeBoxProps {
  label: string;
  value: string;
  color: string;
}

function GaugeBox({ label, value, color }: GaugeBoxProps) {
  return (
    <div
      className="card flex flex-col items-center justify-center px-4 py-5 flex-1 min-w-0"
      style={{
        borderColor: `${color}33`,
        boxShadow: `0 0 12px ${color}18`,
      }}
    >
      <span
        className="font-display text-3xl font-bold tracking-tight"
        style={{
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          color,
          lineHeight: 1.1,
        }}
      >
        {value}
      </span>
      <span
        className="mt-1.5 text-xs font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-muted)" }}
      >
        {label}
      </span>
    </div>
  );
}

export function MetricsGauges({ metrics }: Props) {
  const asr = metrics?.asr_percent ?? null;
  const mos = metrics?.mos_score ?? null;
  const cps = metrics?.cps_achieved ?? null;
  const loss = metrics?.packet_loss_pct ?? null;
  const pdd = metrics?.pdd_avg_ms ?? null;

  return (
    <div className="flex gap-3 flex-wrap sm:flex-nowrap">
      <GaugeBox
        label="ASR"
        value={asr !== null ? `${asr.toFixed(1)}%` : "—"}
        color={asr !== null ? getAsrColor(asr) : "var(--text-muted)"}
      />
      <GaugeBox
        label="MOS"
        value={mos !== null && mos > 0 ? mos.toFixed(2) : "—"}
        color={mos !== null && mos > 0 ? getMosColor(mos) : "var(--text-muted)"}
      />
      <GaugeBox
        label="CPS"
        value={cps !== null ? cps.toFixed(1) : "—"}
        color="var(--warning)"
      />
      <GaugeBox
        label="Loss"
        value={loss !== null ? `${loss.toFixed(2)}%` : "—"}
        color={loss !== null ? getLossColor(loss) : "var(--text-muted)"}
      />
      <GaugeBox
        label="PDD"
        value={pdd !== null ? `${pdd.toFixed(0)}ms` : "—"}
        color={pdd !== null ? getPddColor(pdd) : "var(--text-muted)"}
      />
    </div>
  );
}
