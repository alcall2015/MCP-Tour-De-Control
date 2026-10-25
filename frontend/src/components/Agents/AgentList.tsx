import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FINAL_TASK_STATUSES, cancelAgentTask, deleteAgent, listAgents, setAgentStatus } from "../../lib/api";
import type { Agent, AgentStatus } from "../../lib/api";

import { AgentCard } from "./AgentCard";
import { RunAgentModal } from "./RunAgentModal";
import { Spinner } from "../ui/Spinner";

/** A run still in flight: queued counts too, since `running_task_id` is set only once the worker picks the task up. */
const hasOpenTask = (agent: Agent) => Boolean(agent.last_task && !FINAL_TASK_STATUSES.has(agent.last_task.status));

interface Props {
  view: "active" | "archived";
  onEdit: (agent: Agent) => void;
  onCreate: () => void;
}

export function AgentList({ view, onEdit, onCreate }: Props) {
  const queryClient = useQueryClient();
  const status: AgentStatus | undefined = view === "archived" ? "archived" : undefined;
  const { data: agents = [], isLoading } = useQuery({
    queryKey: ["agents", status ?? "all"],
    queryFn: () => listAgents(status),
    refetchInterval: (query) => query.state.data?.some(hasOpenTask) ? 5000 : false,
  });
  const [errors, setErrors] = useState<Record<string, unknown>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [runAgent, setRunAgent] = useState<Agent | null>(null);

  const statusMut = useMutation({ mutationFn: ({ id, status }: { id: string; status: AgentStatus }) => setAgentStatus(id, status) });
  const deleteMut = useMutation({ mutationFn: (id: string) => deleteAgent(id) });
  const cancelMut = useMutation({ mutationFn: (taskId: string) => cancelAgentTask(taskId) });

  // Tracks busy state and the per-card error around one mutation; `mutateAsync` rejects on failure.
  const run = async (id: string, call: () => Promise<unknown>) => {
    setBusyId(id);
    setErrors((prev) => ({ ...prev, [id]: null }));
    try {
      await call();
    } catch (err) {
      setErrors((prev) => ({ ...prev, [id]: err }));
    } finally {
      setBusyId(null);
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-tasks"] });
    }
  };

  if (isLoading) {
    return <div className="flex justify-center py-12"><Spinner /></div>;
  }

  if (agents.length === 0) {
    return (
      <div className="rounded-xl py-16 text-center" style={{ backgroundColor: "var(--bg-panel)", border: "1px dashed var(--border)" }}>
        <p className="text-base font-medium" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
          {view === "archived" ? "No archived agents" : "No agents yet"}
        </p>
        <p className="mt-1 text-sm max-w-xs mx-auto" style={{ color: "var(--text-muted)" }}>
          {view === "archived" ? "Archived agents will show up here." : "Define an objective, pick the MCP servers it may use, and set its limits."}
        </p>
        {view !== "archived" && <button type="button" className="btn-primary mt-4" onClick={onCreate}>+ New Agent</button>}
      </div>
    );
  }

  return (
    <>
      <div className="space-y-3">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            busy={busyId === agent.id}
            error={errors[agent.id]}
            onEdit={onEdit}
            onStatus={(a, s) => run(a.id, () => statusMut.mutateAsync({ id: a.id, status: s }))}
            onDelete={(a) => run(a.id, () => deleteMut.mutateAsync(a.id))}
            onRun={(a) => setRunAgent(a)}
            onCancelTask={(a, taskId) => run(a.id, () => cancelMut.mutateAsync(taskId))}
          />
        ))}
      </div>
      <RunAgentModal open={runAgent !== null} agent={runAgent} onClose={() => setRunAgent(null)} />
    </>
  );
}
