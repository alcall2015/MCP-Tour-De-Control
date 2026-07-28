import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listStressTests, stopStressTest, deleteStressTest } from "../../lib/api";
import type { StressTest } from "../../lib/api";
import { Spinner } from "../ui/Spinner";

interface Props {
  onViewDetail: (test: StressTest) => void;
  onCompare?: (testIds: string[]) => void;
}

type StatusKey = "pending" | "running" | "completed" | "failed" | "stopped";

const STATUS_STYLES: Record<StatusKey, { bg: string; border: string; color: string }> = {
  pending: {
    bg: "rgba(100, 116, 139, 0.12)",
    border: "rgba(100, 116, 139, 0.25)",
    color: "#94a3b8",
  },
  running: {
    bg: "rgba(96, 165, 250, 0.12)",
    border: "rgba(96, 165, 250, 0.25)",
    color: "#60a5fa",
  },
  completed: {
    bg: "rgba(52, 211, 153, 0.1)",
    border: "rgba(52, 211, 153, 0.2)",
    color: "#34d399",
  },
  failed: {
    bg: "rgba(248, 113, 113, 0.1)",
    border: "rgba(248, 113, 113, 0.2)",
    color: "#f87171",
  },
  stopped: {
    bg: "rgba(226, 179, 64, 0.1)",
    border: "rgba(226, 179, 64, 0.2)",
    color: "#e2b340",
  },
};

function getStatusStyle(status: string) {
  return STATUS_STYLES[(status as StatusKey)] ?? STATUS_STYLES.pending;
}

function StatusBadge({ status }: { status: string }) {
  const style = getStatusStyle(status);
  return (
    <span
      className="badge"
      style={{
        backgroundColor: style.bg,
        border: `1px solid ${style.border}`,
        color: style.color,
      }}
    >
      {status === "running" && (
        <span
          className="h-1.5 w-1.5 rounded-full pulse-dot"
          style={{ backgroundColor: style.color }}
        />
      )}
      {status}
    </span>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="rounded-lg px-3 py-1.5 text-center"
      style={{
        backgroundColor: "var(--bg-elevated)",
        border: "1px solid var(--border)",
        minWidth: "70px",
      }}
    >
      <div
        className="font-mono text-base font-semibold"
        style={{ color: "var(--text-primary)" }}
      >
        {value}
      </div>
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
        {label}
      </div>
    </div>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function StressTestList({ onViewDetail, onCompare }: Props) {
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const { data: tests = [], isLoading } = useQuery({
    queryKey: ["stress-tests"],
    queryFn: listStressTests,
    refetchInterval: (query) => {
      const hasRunning = (query.state.data ?? []).some((t: StressTest) => t.status === "running");
      return hasRunning ? 3000 : 15000;
    },
  });

  const stopMut = useMutation({
    mutationFn: stopStressTest,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["stress-tests"] }),
  });

  const deleteMut = useMutation({
    mutationFn: deleteStressTest,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["stress-tests"] }),
  });

  function toggleSelect(id: string, isCompleted: boolean) {
    if (!isCompleted) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < 3) {
        next.add(id);
      }
      return next;
    });
  }

  const completedTests = tests.filter((t) => t.status === "completed");
  const canCompare = selectedIds.size >= 2 && selectedIds.size <= 3;

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }

  if (tests.length === 0) {
    return (
      <div
        className="rounded-xl py-16 text-center"
        style={{
          backgroundColor: "var(--bg-panel)",
          border: "1px dashed var(--border)",
        }}
      >
        <div className="flex flex-col items-center gap-3">
          <div
            className="text-4xl font-bold"
            style={{
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              color: "var(--text-muted)",
            }}
          >
            ~
          </div>
          <p
            className="text-base font-medium"
            style={{
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              color: "var(--text-primary)",
            }}
          >
            No stress tests yet
          </p>
          <p className="text-sm max-w-xs mx-auto" style={{ color: "var(--text-muted)" }}>
            Create a new test to start load-testing your SIP infrastructure.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Compare toolbar — visible when completed tests exist */}
      {onCompare && completedTests.length >= 2 && (
        <div
          className="flex items-center justify-between rounded-xl px-4 py-2.5"
          style={{
            backgroundColor: "var(--bg-elevated)",
            border: "1px solid var(--border)",
          }}
        >
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            {selectedIds.size === 0
              ? "Select 2–3 completed tests to compare"
              : `${selectedIds.size} test${selectedIds.size > 1 ? "s" : ""} selected`}
          </span>
          <div className="flex gap-2">
            {selectedIds.size > 0 && (
              <button
                onClick={() => setSelectedIds(new Set())}
                className="btn-secondary"
                style={{ fontSize: "0.8125rem", padding: "0.35rem 0.8rem" }}
              >
                Clear
              </button>
            )}
            <button
              onClick={() => canCompare && onCompare(Array.from(selectedIds))}
              disabled={!canCompare}
              className="btn-primary"
              style={{ fontSize: "0.8125rem", padding: "0.35rem 0.8rem" }}
            >
              Compare
            </button>
          </div>
        </div>
      )}

      {tests.map((test) => {
        const m = test.latest_metrics;
        const asr = m ? `${m.asr_percent.toFixed(1)}%` : "—";
        const mos = m && m.mos_score > 0 ? m.mos_score.toFixed(2) : "—";
        const cpsAchieved = m ? m.cps_achieved.toFixed(1) : "—";
        const isRunning = test.status === "running";
        const isCompleted = test.status === "completed";
        const isSelected = selectedIds.has(test.id);

        return (
          <div
            key={test.id}
            className="card"
            style={
              isSelected
                ? {
                    borderColor: "rgba(226,179,64,0.5)",
                    boxShadow: "0 0 0 1px rgba(226,179,64,0.2)",
                  }
                : undefined
            }
          >
            {/* Running progress bar accent */}
            {isRunning && (
              <div
                style={{
                  height: "2px",
                  background:
                    "linear-gradient(90deg, var(--running) 0%, rgba(96,165,250,0.3) 70%, transparent 100%)",
                  borderRadius: "0.75rem 0.75rem 0 0",
                }}
              />
            )}

            <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              {/* Left: name + meta */}
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  {/* Checkbox for completed tests */}
                  {onCompare && isCompleted && (
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(test.id, isCompleted)}
                      title={
                        !isSelected && selectedIds.size >= 3
                          ? "Max 3 tests can be compared"
                          : "Select for comparison"
                      }
                      disabled={!isSelected && selectedIds.size >= 3}
                      style={{
                        accentColor: "var(--accent)",
                        width: "0.875rem",
                        height: "0.875rem",
                        cursor: "pointer",
                        flexShrink: 0,
                      }}
                    />
                  )}
                  <StatusBadge status={test.status} />
                  <span
                    className="font-semibold"
                    style={{
                      fontFamily: "'Space Grotesk', system-ui, sans-serif",
                      color: "var(--text-primary)",
                      fontSize: "0.9375rem",
                    }}
                  >
                    {test.name}
                  </span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
                  <span>
                    {test.target_host}:{test.target_port}
                  </span>
                  <span className="uppercase">{test.transport}</span>
                  <span>{test.scenario || "uac"}</span>
                  <span>{test.cps} CPS</span>
                  <span>{test.max_calls} calls</span>
                  <span>Created {formatDate(test.created_at)}</span>
                  {test.started_at && (
                    <span>Started {formatDate(test.started_at)}</span>
                  )}
                </div>
              </div>

              {/* Center: metrics pills */}
              <div className="flex gap-2 flex-shrink-0">
                <MetricPill label="ASR" value={asr} />
                <MetricPill label="MOS" value={mos} />
                <MetricPill label="CPS" value={cpsAchieved} />
              </div>

              {/* Right: actions */}
              <div
                className="flex flex-shrink-0 gap-1.5"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => onViewDetail(test)}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150"
                  style={{
                    backgroundColor: "rgba(226, 179, 64, 0.1)",
                    color: "var(--accent)",
                    border: "1px solid rgba(226, 179, 64, 0.2)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                      "rgba(226, 179, 64, 0.2)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                      "rgba(226, 179, 64, 0.1)";
                  }}
                >
                  View
                </button>

                {isRunning && (
                  <button
                    onClick={() => stopMut.mutate(test.id)}
                    disabled={stopMut.isPending}
                    className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                    style={{
                      backgroundColor: "rgba(251, 191, 36, 0.1)",
                      color: "var(--warning)",
                      border: "1px solid rgba(251, 191, 36, 0.2)",
                    }}
                    onMouseEnter={(e) => {
                      if (!stopMut.isPending)
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                          "rgba(251, 191, 36, 0.2)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                        "rgba(251, 191, 36, 0.1)";
                    }}
                  >
                    Stop
                  </button>
                )}

                {!isRunning && (
                  <button
                    onClick={() => {
                      if (confirm(`Delete test "${test.name}"?`)) {
                        deleteMut.mutate(test.id);
                      }
                    }}
                    disabled={deleteMut.isPending}
                    className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                    style={{
                      backgroundColor: "rgba(248, 113, 113, 0.1)",
                      color: "var(--error)",
                      border: "1px solid rgba(248, 113, 113, 0.2)",
                    }}
                    onMouseEnter={(e) => {
                      if (!deleteMut.isPending)
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                          "rgba(248, 113, 113, 0.2)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                        "rgba(248, 113, 113, 0.1)";
                    }}
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
