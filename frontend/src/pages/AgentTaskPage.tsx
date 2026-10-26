import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { FINAL_TASK_STATUSES, cancelAgentTask, getAgent } from "../lib/api";
import { Spinner } from "../components/ui/Spinner";
import { MutationError } from "../components/ui/MutationError";
import { ErrorBoundary } from "../components/ui/ErrorBoundary";
import { useAgentTaskStream } from "../components/Agents/useAgentTaskStream";
import { ApprovalCard } from "../components/Agents/ApprovalCard";
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
  // Fetched by id, not filtered out of the list: an archived agent's task page must still name its agent.
  const { data: agent } = useQuery({ queryKey: ["agent", agentId], queryFn: () => getAgent(agentId), enabled: Boolean(agentId) });

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
  // While streaming, the stored task row lags behind the steps already on screen: count and sum from the steps instead.
  const startedAt = task.started_at ?? (live ? steps[0]?.created_at ?? null : null);
  const duration = startedAt ? formatDuration(startedAt, task.finished_at) : "";
  const tokensIn = live ? steps.reduce((n, s) => n + (s.tokens_in ?? 0), 0) : task.tokens_in;
  const tokensOut = live ? steps.reduce((n, s) => n + (s.tokens_out ?? 0), 0) : task.tokens_out;

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
            {startedAt && <span>started {new Date(startedAt).toLocaleString()}</span>}
            {duration && <span>{duration}</span>}
            <span>{steps.length} steps</span>
            <span>{tokensIn} in / {tokensOut} out tokens</span>
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

      {task.status === "waiting_approval" && task.approval && (
        <ErrorBoundary><ApprovalCard approval={task.approval} taskId={taskId} /></ErrorBoundary>
      )}
      {task.status === "waiting_approval" && !task.approval && (
        <p className="text-xs rounded-lg px-3 py-2" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.08)", border: "1px solid rgba(251, 191, 36, 0.25)" }}>
          Waiting for an approval that is no longer pending. It may have been decided elsewhere or expired; the task will move on or fail within a minute.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <ErrorBoundary><TaskPlan plan={task.plan} /></ErrorBoundary>
        <ErrorBoundary><TaskCritique critique={task.critique} plan={task.plan} /></ErrorBoundary>
      </div>
      <ErrorBoundary><TaskReport report={task.report} /></ErrorBoundary>
      <ErrorBoundary><TaskTimeline taskId={taskId} steps={steps} /></ErrorBoundary>
    </div>
  );
}
