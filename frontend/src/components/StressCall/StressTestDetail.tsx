import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getStressMetricsLatest, getStressTest, stopStressTest } from "../../lib/api";
import { Spinner } from "../ui/Spinner";
import { MetricsGauges } from "./MetricsGauges";
import { SipMetricsCard } from "./SipMetricsCard";
import { RtpMetricsCard } from "./RtpMetricsCard";
import { CpsChart } from "./CpsChart";

interface Props {
  testId: string;
  onBack: () => void;
}

type StatusKey = "pending" | "running" | "completed" | "failed" | "stopped";

const STATUS_STYLES: Record<StatusKey, { bg: string; border: string; color: string }> = {
  pending: { bg: "rgba(100,116,139,0.12)", border: "rgba(100,116,139,0.25)", color: "#94a3b8" },
  running: { bg: "rgba(96,165,250,0.12)", border: "rgba(96,165,250,0.25)", color: "#60a5fa" },
  completed: { bg: "rgba(52,211,153,0.1)", border: "rgba(52,211,153,0.2)", color: "#34d399" },
  failed: { bg: "rgba(248,113,113,0.1)", border: "rgba(248,113,113,0.2)", color: "#f87171" },
  stopped: { bg: "rgba(226,179,64,0.1)", border: "rgba(226,179,64,0.2)", color: "#e2b340" },
};

function getStatusStyle(status: string) {
  return STATUS_STYLES[(status as StatusKey)] ?? STATUS_STYLES.pending;
}

function StatusBadge({ status }: { status: string }) {
  const s = getStatusStyle(status);
  return (
    <span
      className="badge"
      style={{ backgroundColor: s.bg, border: `1px solid ${s.border}`, color: s.color }}
    >
      {status === "running" && (
        <span
          className="h-1.5 w-1.5 rounded-full pulse-dot"
          style={{ backgroundColor: s.color }}
        />
      )}
      {status}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface RampPoint { second: number; cps: number }

function extractRampCurve(rampUpCurve: Record<string, unknown>[] | null): RampPoint[] | null {
  if (!rampUpCurve || rampUpCurve.length === 0) return null;
  const first = rampUpCurve[0];
  // Accept {second, cps} or {t, v} or any two numeric keys
  if (typeof first.second === "number" && typeof first.cps === "number") {
    return rampUpCurve as unknown as RampPoint[];
  }
  // Try to detect generic key names
  const keys = Object.keys(first).filter((k) => typeof first[k] === "number");
  if (keys.length >= 2) {
    return rampUpCurve.map((item) => ({
      second: item[keys[0]] as number,
      cps: item[keys[1]] as number,
    }));
  }
  return null;
}

export function StressTestDetail({ testId, onBack }: Props) {
  const queryClient = useQueryClient();

  const { data: test, isLoading: testLoading } = useQuery({
    queryKey: ["stress-test", testId],
    queryFn: () => getStressTest(testId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" ? 5000 : false;
    },
  });

  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: ["stress-metrics-latest", testId],
    queryFn: () => getStressMetricsLatest(testId),
    refetchInterval: (query) => {
      // Only poll when test is running; we derive from test data if available
      const testData = queryClient.getQueryData<typeof test>(["stress-test", testId]);
      const status = testData?.status ?? query.state.data;
      void status; // We re-check via test query
      return test?.status === "running" ? 3000 : false;
    },
    enabled: !!test,
  });

  const stopMut = useMutation({
    mutationFn: () => stopStressTest(testId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stress-test", testId] });
      queryClient.invalidateQueries({ queryKey: ["stress-metrics-latest", testId] });
      queryClient.invalidateQueries({ queryKey: ["stress-tests"] });
    },
  });

  if (testLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (!test) {
    return (
      <div className="card p-8 text-center" style={{ color: "var(--text-muted)" }}>
        Test not found.
      </div>
    );
  }

  const isRunning = test.status === "running";
  const rampCurve = extractRampCurve(metrics?.ramp_up_curve ?? null);

  return (
    <div className="space-y-5">
      {/* Running progress bar */}
      {isRunning && (
        <div
          style={{
            height: "2px",
            background: "linear-gradient(90deg, var(--running) 0%, rgba(96,165,250,0.3) 70%, transparent 100%)",
            borderRadius: "2px",
          }}
        />
      )}

      {/* Header card */}
      <div className="card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          {/* Left: test info */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={test.status} />
              <h3
                className="text-xl font-semibold"
                style={{
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  color: "var(--text-primary)",
                }}
              >
                {test.name}
              </h3>
            </div>
            <div
              className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs"
              style={{ color: "var(--text-muted)" }}
            >
              <span>{test.target_host}:{test.target_port}</span>
              <span className="uppercase">{test.transport}</span>
              <span>{test.scenario || "uac"}</span>
              <span>{test.cps} CPS target</span>
              <span>{test.max_calls} max calls</span>
              <span>{test.duration}s duration</span>
              {test.started_at && <span>Started {formatDate(test.started_at)}</span>}
              {test.finished_at && <span>Finished {formatDate(test.finished_at)}</span>}
            </div>
          </div>

          {/* Right: actions */}
          <div className="flex flex-shrink-0 items-center gap-2">
            {isRunning && (
              <button
                onClick={() => stopMut.mutate()}
                disabled={stopMut.isPending}
                className="btn-danger"
              >
                {stopMut.isPending ? "Stopping…" : "Stop Test"}
              </button>
            )}
            <button onClick={onBack} className="btn-secondary">
              ← Back
            </button>
          </div>
        </div>
      </div>

      {/* Metrics gauges */}
      {metricsLoading && !metrics ? (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      ) : (
        <MetricsGauges metrics={metrics ?? null} />
      )}

      {/* Two-column: SIP + RTP */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <SipMetricsCard metrics={metrics ?? null} />
        <RtpMetricsCard metrics={metrics ?? null} />
      </div>

      {/* CPS Chart */}
      <CpsChart data={rampCurve} targetCps={test.cps} />

      {/* Additional test metadata */}
      <div className="card p-5">
        <h3
          className="mb-3 text-sm font-semibold uppercase tracking-wider"
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            color: "var(--text-secondary)",
          }}
        >
          Test Configuration
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {[
            { label: "Call Duration", value: `${test.call_duration}s` },
            { label: "Ramp Up", value: `${test.ramp_up}s` },
            { label: "Ramp Step", value: String(test.ramp_step) },
            { label: "Caller ID", value: test.caller_id },
            { label: "Media", value: test.media_type },
            { label: "Transport", value: test.transport.toUpperCase() },
            { label: "Test ID", value: test.id.slice(0, 8) + "…" },
          ].map(({ label, value }) => (
            <div
              key={label}
              className="rounded-lg p-3"
              style={{
                backgroundColor: "var(--bg-elevated)",
                border: "1px solid var(--border)",
              }}
            >
              <p className="mb-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
                {label}
              </p>
              <p
                className="text-sm font-medium font-mono truncate"
                style={{ color: "var(--text-primary)" }}
              >
                {value}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
