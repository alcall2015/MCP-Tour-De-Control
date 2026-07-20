import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listExecutions, getExecution } from "../../lib/api";
import type { Execution } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";
import { ExecutionDetail } from "./ExecutionDetail";

export function ExecutionList() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selected, setSelected] = useState<Execution | null>(null);

  const { data: executions = [] } = useQuery({
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
      <div className="mb-4 flex gap-2">
        {["", "success", "failed", "timeout", "running"].map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded px-3 py-1 text-xs ${
              statusFilter === s ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
            }`}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900">
            <tr className="text-left text-zinc-400">
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Prompt</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Tokens</th>
              <th className="px-4 py-3">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {executions.map((exec) => (
              <tr
                key={exec.id}
                onClick={() => handleSelect(exec.id)}
                className="cursor-pointer hover:bg-zinc-900"
              >
                <td className="px-4 py-3 text-zinc-300">
                  {new Date(exec.started_at).toLocaleString("fr-FR")}
                </td>
                <td className="px-4 py-3">{exec.prompt_name}</td>
                <td className="px-4 py-3"><StatusBadge status={exec.status} /></td>
                <td className="px-4 py-3 text-zinc-400">{exec.tokens_used}</td>
                <td className="px-4 py-3 text-zinc-400">
                  {exec.duration_ms ? `${(exec.duration_ms / 1000).toFixed(1)}s` : "—"}
                </td>
              </tr>
            ))}
            {executions.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-zinc-500">
                  No executions yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
