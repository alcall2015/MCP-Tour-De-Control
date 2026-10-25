import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { FINAL_TASK_STATUSES, cancelAgentTask, listAgents } from "../lib/api";
import { Spinner } from "../components/ui/Spinner";
import { MutationError } from "../components/ui/MutationError";
import { ErrorBoundary } from "../components/ui/ErrorBoundary";
import { useAgentTaskStream } from "../components/Agents/useAgentTaskStream";
import { OutcomeBadge, TaskStatusBadge } from "../components/Agents/AgentTaskBadges";
import { formatDuration } from "../components/Agents/time";
import { TaskPlan } from "../components/Agents/TaskPlan";
import { TaskTimeline } from "../components/Agents/TaskTimeline";
import { TaskCritique } from "../components/Agents/TaskCritique";
import { TaskReport } from "../components/Agents/TaskReport";

export function AgentTaskPage() {
  const { agentId = "", taskId = "" } = useParams();
  const queryClient = useQueryClient();
  const { task, steps, gone, live, streamError, isLoading, error } = useAgentTaskStream(taskId);
  const { data: agents = [] } = useQuery({ queryKey: ["agents", "all"], queryFn: () => listAgents() });
  const agent = agents.find((a) => a.id === agentId) ?? null;

  const cancelMut = useMutation({
    mutationFn: () => cancelAgentTask(taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  if (isLoading) return <div className="flex justify-center py-12"><Spinner /></div>;
  if (error || !task) {
    return (
      <div className="space-y-3">
        <p className="text-sm" style={{ color: "var(--error)" }}>{error ? (error as Error).message : "Task not found"}</p>
        <Link to="/agents" className="btn-secondary btn-sm" style={{ textDecoration: "none" }}>Back to agents</Link>
      </div>
    );
  }

  const isFinal = FINAL_TASK_STATUSES.has(task.status) || gone;
  const duration = formatDuration(task.started_at, task.finished_at);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0 space-y-1.5">
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            <Link to="/agents" style={{ color: "var(--text-secondary)" }}>Agents</Link> / {agent?.name ?? "Agent"} / task
          </p>
          <h2 className="text-xl font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>{task.objective}</h2>
          <div className="flex items-center gap-2 flex-wrap text-xs" style={{ color: "var(--text-muted)" }}>
            <TaskStatusBadge status={gone ? "gone" : task.status} />
            <OutcomeBadge outcome={task.outcome} />
            {live && <span style={{ color: "var(--running)" }}>live</span>}
            <span>{task.trigger}</span>
            {task.started_at && <span>started {new Date(task.started_at).toLocaleString()}</span>}
            {duration && <span>{duration}</span>}
            <span>{task.step_count} steps</span>
            <span>{task.tokens_in} in / {task.tokens_out} out tokens</span>
            <span>limits {task.max_steps} rounds · {task.timeout_seconds} s</span>
          </div>
          {task.error && <p className="text-sm" style={{ color: "var(--error)" }}>{task.error}</p>}
          {streamError && <p className="text-xs" style={{ color: "var(--warning)" }}>Live updates interrupted: {streamError}. Reload to resync.</p>}
        </div>
        {!isFinal && (
          <div className="flex flex-col items-end gap-2">
            <button type="button" className="btn-danger btn-sm" disabled={cancelMut.isPending || task.cancel_requested} onClick={() => cancelMut.mutate()}>
              {task.cancel_requested ? "Cancelling…" : "Cancel"}
            </button>
            <MutationError error={cancelMut.error} />
          </div>
        )}
      </div>

      <p className="text-xs rounded-lg px-3 py-2" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.08)", border: "1px solid rgba(251, 191, 36, 0.25)" }}>
        No approval step yet: every authorised tool runs immediately.
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <ErrorBoundary><TaskPlan plan={task.plan} /></ErrorBoundary>
        <ErrorBoundary><TaskCritique critique={task.critique} plan={task.plan} /></ErrorBoundary>
      </div>
      <ErrorBoundary><TaskReport report={task.report} /></ErrorBoundary>
      <ErrorBoundary><TaskTimeline taskId={taskId} steps={steps} /></ErrorBoundary>
    </div>
  );
}
