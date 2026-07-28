import { useQuery } from "@tanstack/react-query";
import { compareStressTests } from "../../lib/api";
import type { StressTest, StressTestMetrics } from "../../lib/api";
import { Spinner } from "../ui/Spinner";

interface Props {
  testIds: string[];
  onBack: () => void;
}

interface MetricDef {
  label: string;
  key: keyof StressTestMetrics;
  unit: string;
  higherIsBetter: boolean;
  format?: (v: number) => string;
}

const METRICS: MetricDef[] = [
  { label: "ASR", key: "asr_percent", unit: "%", higherIsBetter: true, format: (v) => v.toFixed(1) },
  { label: "MOS Score", key: "mos_score", unit: "", higherIsBetter: true, format: (v) => v.toFixed(2) },
  { label: "PDD Avg", key: "pdd_avg_ms", unit: "ms", higherIsBetter: false, format: (v) => v.toFixed(0) },
  { label: "Packet Loss", key: "packet_loss_pct", unit: "%", higherIsBetter: false, format: (v) => v.toFixed(2) },
  { label: "Jitter Avg", key: "jitter_avg_ms", unit: "ms", higherIsBetter: false, format: (v) => v.toFixed(1) },
  { label: "RTT Avg", key: "rtt_avg_ms", unit: "ms", higherIsBetter: false, format: (v) => v.toFixed(1) },
  { label: "Max Concurrent", key: "max_concurrent", unit: "", higherIsBetter: true, format: (v) => v.toFixed(0) },
  { label: "Retransmissions", key: "retransmissions", unit: "", higherIsBetter: false, format: (v) => v.toFixed(0) },
  { label: "CPS Achieved", key: "cps_achieved", unit: "", higherIsBetter: true, format: (v) => v.toFixed(1) },
  { label: "Throughput", key: "throughput_kbps", unit: "kbps", higherIsBetter: true, format: (v) => v.toFixed(0) },
];

function getDeltaIndicator(
  value: number,
  baseline: number,
  higherIsBetter: boolean
): { symbol: string; color: string } | null {
  if (value === baseline) return null;
  const better = higherIsBetter ? value > baseline : value < baseline;
  return {
    symbol: better ? "▲" : "▼",
    color: better ? "#34d399" : "#f87171",
  };
}

function formatValue(metric: MetricDef, value: number | undefined | null): string {
  if (value === undefined || value === null) return "—";
  const formatted = metric.format ? metric.format(value) : String(value);
  return metric.unit ? `${formatted} ${metric.unit}` : formatted;
}

export function StressTestCompare({ testIds, onBack }: Props) {
  const { data: tests = [], isLoading, isError, error } = useQuery({
    queryKey: ["stress-tests-compare", testIds],
    queryFn: () => compareStressTests(testIds),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (isError) {
    return (
      <div
        className="rounded-xl px-4 py-3 text-sm"
        style={{
          backgroundColor: "rgba(248, 113, 113, 0.1)",
          border: "1px solid rgba(248, 113, 113, 0.25)",
          color: "var(--error)",
        }}
      >
        Error loading comparison: {(error as Error)?.message ?? "Unknown error"}
      </div>
    );
  }

  if (tests.length === 0) {
    return (
      <div
        className="rounded-xl py-12 text-center"
        style={{ backgroundColor: "var(--bg-panel)", border: "1px dashed var(--border)" }}
      >
        <p style={{ color: "var(--text-muted)" }}>No tests found for comparison.</p>
      </div>
    );
  }

  // Use the first test as baseline for delta calculations
  const baseline: StressTest = tests[0];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ border: "1px solid rgba(226, 179, 64, 0.3)" }}
      >
        {/* Amber header bar */}
        <div
          className="px-5 py-3 flex items-center justify-between"
          style={{
            background: "linear-gradient(135deg, rgba(226,179,64,0.18) 0%, rgba(226,179,64,0.06) 100%)",
            borderBottom: "1px solid rgba(226,179,64,0.2)",
          }}
        >
          <div className="flex items-center gap-3">
            <span
              className="h-4 w-1 rounded-full"
              style={{ backgroundColor: "var(--accent)" }}
            />
            <h3
              className="font-semibold text-base"
              style={{
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                color: "var(--accent)",
              }}
            >
              Test Comparison
            </h3>
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{
                backgroundColor: "rgba(226,179,64,0.12)",
                border: "1px solid rgba(226,179,64,0.2)",
                color: "var(--text-secondary)",
              }}
            >
              {tests.length} tests
            </span>
          </div>
          <button onClick={onBack} className="btn-secondary" style={{ fontSize: "0.8125rem", padding: "0.35rem 0.8rem" }}>
            ← Back
          </button>
        </div>

        {/* Test name headers */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `180px repeat(${tests.length}, 1fr)`,
            backgroundColor: "var(--bg-elevated)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div className="px-4 py-3 text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Metric
          </div>
          {tests.map((test, idx) => (
            <div
              key={test.id}
              className="px-4 py-3"
              style={{ borderLeft: "1px solid var(--border)" }}
            >
              <div
                className="font-semibold text-sm truncate"
                style={{
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  color: idx === 0 ? "var(--accent)" : "var(--text-primary)",
                }}
              >
                {test.name}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className="badge"
                  style={{
                    backgroundColor:
                      test.status === "completed"
                        ? "rgba(52, 211, 153, 0.1)"
                        : "rgba(100, 116, 139, 0.12)",
                    border: `1px solid ${
                      test.status === "completed"
                        ? "rgba(52, 211, 153, 0.2)"
                        : "rgba(100, 116, 139, 0.25)"
                    }`,
                    color:
                      test.status === "completed" ? "#34d399" : "#94a3b8",
                  }}
                >
                  {test.status}
                </span>
                {idx === 0 && (
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    baseline
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Metrics rows */}
        <div style={{ backgroundColor: "var(--bg-panel)" }}>
          {METRICS.map((metric, rowIdx) => {
            const baselineVal = baseline.latest_metrics?.[metric.key] as number | undefined;

            return (
              <div
                key={metric.key}
                style={{
                  display: "grid",
                  gridTemplateColumns: `180px repeat(${tests.length}, 1fr)`,
                  backgroundColor: rowIdx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)",
                  borderBottom: rowIdx < METRICS.length - 1 ? "1px solid rgba(30,39,64,0.7)" : "none",
                }}
              >
                {/* Metric label */}
                <div
                  className="px-4 py-2.5 text-sm"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {metric.label}
                </div>

                {/* Values per test */}
                {tests.map((test, testIdx) => {
                  const rawVal = test.latest_metrics?.[metric.key] as number | undefined;
                  const displayVal = formatValue(metric, rawVal);

                  let delta: { symbol: string; color: string } | null = null;
                  if (
                    testIdx > 0 &&
                    rawVal !== undefined &&
                    rawVal !== null &&
                    baselineVal !== undefined &&
                    baselineVal !== null
                  ) {
                    delta = getDeltaIndicator(rawVal, baselineVal, metric.higherIsBetter);
                  }

                  return (
                    <div
                      key={test.id}
                      className="px-4 py-2.5 flex items-center gap-2"
                      style={{ borderLeft: "1px solid var(--border)" }}
                    >
                      <span
                        className="font-mono text-sm"
                        style={{
                          color:
                            rawVal === undefined || rawVal === null
                              ? "var(--text-muted)"
                              : "var(--text-primary)",
                        }}
                      >
                        {displayVal}
                      </span>
                      {delta && (
                        <span
                          className="text-xs font-bold"
                          style={{ color: delta.color }}
                          title={delta.symbol === "▲" ? "Better than baseline" : "Worse than baseline"}
                        >
                          {delta.symbol}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* Footer legend */}
        <div
          className="px-5 py-3 flex items-center gap-5 text-xs"
          style={{
            borderTop: "1px solid var(--border)",
            backgroundColor: "var(--bg-elevated)",
            color: "var(--text-muted)",
          }}
        >
          <span>Deltas relative to baseline (first test)</span>
          <span style={{ color: "#34d399" }}>▲ Better</span>
          <span style={{ color: "#f87171" }}>▼ Worse</span>
        </div>
      </div>
    </div>
  );
}
