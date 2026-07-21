import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listExecutions, getExecution } from "../../lib/api";
import type { Execution } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";
import { ExecutionDetail } from "./ExecutionDetail";
import { Spinner } from "../ui/Spinner";

const STATUS_BORDER: Record<string, string> = {
  success: "#34d399",
  failed: "#f87171",
  running: "#60a5fa",
  timeout: "#fbbf24",
};

const STATUS_FILTERS = ["", "success", "failed", "timeout", "running"] as const;

export function ExecutionList() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selected, setSelected] = useState<Execution | null>(null);

  const { data: executions = [], isLoading } = useQuery({
    queryKey: ["executions", statusFilter],
    queryFn: () => listExecutions({ status: statusFilter || undefined }),
    refetchInterval: 10000,
  });

  const handleSelect = async (id: string) => {
    const exec = await getExecution(id);
    setSelected(exec);
  };

  if (selected) {
    return <ExecutionDetail execution={selected} onClose={() => setSelected(null)} />;
  }

  return (
    <div>
      {/* Filter bar */}
      <div className="mb-4 flex flex-wrap gap-2">
        {STATUS_FILTERS.map((s) => {
          const isActive = statusFilter === s;
          return (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-200"
              style={{
                backgroundColor: isActive ? "var(--accent)" : "var(--bg-elevated)",
                color: isActive ? "#080b12" : "var(--text-secondary)",
                border: `1px solid ${isActive ? "var(--accent)" : "var(--border)"}`,
              }}
            >
              {s || "All"}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      ) : (
        <div
          className="overflow-hidden rounded-xl"
          style={{ border: "1px solid var(--border)" }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr
                style={{
                  backgroundColor: "var(--bg-elevated)",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                {["Date", "Prompt", "Status", "Tokens", "Duration"].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider"
                    style={{
                      color: "var(--text-muted)",
                      fontFamily: "'Space Grotesk', system-ui, sans-serif",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody style={{ backgroundColor: "var(--bg-panel)" }}>
              {executions.map((exec, idx) => {
                const borderColor = STATUS_BORDER[exec.status] || "transparent";
                return (
                  <tr
                    key={exec.id}
                    onClick={() => handleSelect(exec.id)}
                    className="cursor-pointer transition-colors duration-150"
                    style={{
                      borderBottom:
                        idx < executions.length - 1
                          ? "1px solid var(--border)"
                          : "none",
                      borderLeft: `3px solid ${borderColor}`,
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                        "var(--bg-elevated)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                        "transparent";
                    }}
                  >
                    <td className="px-4 py-3" style={{ color: "var(--text-secondary)" }}>
                      {new Date(exec.started_at).toLocaleString("fr-FR")}
                    </td>
                    <td className="px-4 py-3 font-medium" style={{ color: "var(--text-primary)" }}>
                      {exec.prompt_name}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={exec.status} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                      {exec.tokens_used}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                      {exec.duration_ms ? `${(exec.duration_ms / 1000).toFixed(1)}s` : "—"}
                    </td>
                  </tr>
                );
              })}
              {executions.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center gap-2">
                      <span className="text-3xl">📊</span>
                      <p
                        className="text-sm font-medium"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        No executions yet
                      </p>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                        Run a prompt to see execution history here.
                      </p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
