import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RISK_LEVELS, listServerTools, setToolPolicy } from "../../lib/api";
import type { RiskLevel, ToolPolicy } from "../../lib/api";
import { RiskBadge } from "../Agents/RiskBadge";
import { MutationError } from "../ui/MutationError";
import { Spinner } from "../ui/Spinner";

const RULE = "A tool runs without approval when its level is at or below the agent's ceiling; everything above parks the task until an operator decides. R3 always requires approval.";

export function McpToolsPanel({ serverId, serverName }: { serverId: string; serverName: string }) {
  const queryClient = useQueryClient();
  const key = ["mcp-server-tools", serverId];
  // Discovery opens a real MCP connection: fetched on demand, never in the background.
  const { data: tools = [], isLoading, isFetching, error, refetch } = useQuery({ queryKey: key, queryFn: () => listServerTools(serverId), staleTime: Infinity, retry: false });
  const [filter, setFilter] = useState("");
  const [pendingName, setPendingName] = useState<string | null>(null);

  const setLevel = useMutation({
    mutationFn: ({ name, level }: { name: string; level: RiskLevel }) => setToolPolicy(serverId, name, level),
    onMutate: ({ name }) => setPendingName(name),
    onSuccess: (updated: ToolPolicy) => {
      queryClient.setQueryData<ToolPolicy[]>(key, (prev) => prev?.map((t) => (t.name === updated.name ? { ...t, risk_level: updated.risk_level } : t)));
    },
    onSettled: () => setPendingName(null),
  });

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? tools.filter((t) => t.name.toLowerCase().includes(q) || (t.description ?? "").toLowerCase().includes(q)) : tools;
  }, [tools, filter]);
  const counts = useMemo(() => RISK_LEVELS.map((r) => tools.filter((t) => t.risk_level === r.level).length), [tools]);

  return (
    <div className="mt-3 rounded-lg p-3 space-y-3" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
          Tools on {serverName}{tools.length ? ` · ${tools.length}` : ""}
        </p>
        {tools.length > 0 && (
          <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
            {RISK_LEVELS.map((r, i) => `${r.code} ${counts[i]}`).join(" · ")}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <input className="input-field" style={{ width: "12rem", padding: "0.3rem 0.6rem", fontSize: "0.75rem" }} placeholder="Filter tools" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <button type="button" className="btn-secondary btn-sm" disabled={isFetching} onClick={() => refetch()}>{isFetching ? "Discovering…" : "Refresh"}</button>
        </div>
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>{RULE}</p>

      {isLoading && <div className="flex justify-center py-4"><Spinner /></div>}
      {error ? <p className="text-xs" style={{ color: "var(--error)" }}>{(error as Error).message}</p> : null}
      {!isLoading && !error && tools.length === 0 && <p className="text-xs" style={{ color: "var(--text-muted)" }}>No tools discovered on this server.</p>}
      {visible.length > 0 && (
        <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
          {visible.map((t) => (
            <li key={t.name} className="flex flex-wrap items-center gap-3 py-2 text-xs">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <code className="font-mono truncate" style={{ color: "var(--text-primary)" }}>{t.name}</code>
                  <RiskBadge level={t.risk_level} compact />
                </div>
                {t.description && <p className="mt-0.5 line-clamp-2" style={{ color: "var(--text-muted)" }}>{t.description}</p>}
              </div>
              <select
                className="input-field flex-shrink-0 w-full sm:w-[15rem]"
                style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}
                value={t.risk_level}
                disabled={pendingName === t.name}
                aria-label={`Risk level of ${t.name}`}
                onChange={(e) => setLevel.mutate({ name: t.name, level: Number(e.target.value) as RiskLevel })}
              >
                {RISK_LEVELS.map((r) => <option key={r.level} value={r.level}>{r.code} · {r.label}</option>)}
              </select>
            </li>
          ))}
        </ul>
      )}
      {visible.length === 0 && tools.length > 0 && <p className="text-xs" style={{ color: "var(--text-muted)" }}>No tool matches "{filter}".</p>}
      <MutationError error={setLevel.error} />
    </div>
  );
}
