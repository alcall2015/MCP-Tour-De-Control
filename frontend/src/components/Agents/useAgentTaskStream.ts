import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FINAL_TASK_STATUSES, getAgentTask, streamAgentTask } from "../../lib/api";
import type { AgentTaskDetail, AgentTaskStep } from "../../lib/api";

/**
 * Loads a task once, then follows it over SSE while it is not final.
 * Steps arriving on the stream are merged by `seq`; a `status` event updates
 * the task; `done` ends the stream and refetches the full detail (plan,
 * critique, report, totals) in one go.
 */
export function useAgentTaskStream(taskId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["agent-task", taskId], queryFn: () => getAgentTask(taskId) });
  // Bound once per observer by TanStack Query, so it is a stable effect dependency.
  const { refetch } = query;
  const [liveSteps, setLiveSteps] = useState<AgentTaskStep[]>([]);
  const [liveStatus, setLiveStatus] = useState<AgentTaskDetail["status"] | "gone" | null>(null);
  const [liveMeta, setLiveMeta] = useState<{ outcome: AgentTaskDetail["outcome"]; error: string | null; finished_at: string | null } | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [live, setLive] = useState(false);

  const initialStatus = query.data?.status;
  const shouldStream = Boolean(initialStatus) && !FINAL_TASK_STATUSES.has(initialStatus as string);

  // The page stays mounted when the route switches to another task: reset the live state per task id.
  useEffect(() => {
    setLiveSteps([]);
    setLiveStatus(null);
    setLiveMeta(null);
    setStreamError(null);
  }, [taskId]);

  // No "started" guard: StrictMode runs setup/cleanup/setup on mount and the cleanup aborts the first stream, so the second setup must be allowed to open the real one.
  useEffect(() => {
    if (!shouldStream) return;
    const controller = new AbortController();
    let sawDone = false;
    setLive(true);
    streamAgentTask(taskId, (e) => {
      if (e.event === "step") {
        setLiveSteps((prev) => (prev.some((s) => s.seq === e.data.seq) ? prev : [...prev, e.data].sort((a, b) => a.seq - b.seq)));
      } else if (e.event === "status") {
        setLiveStatus(e.data.status);
        setLiveMeta({ outcome: e.data.outcome, error: e.data.error, finished_at: e.data.finished_at });
      } else if (e.event === "done") {
        sawDone = true;
        setLive(false);
        queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        queryClient.invalidateQueries({ queryKey: ["agent-tasks"] });
      } else if (e.event === "error") {
        setStreamError(e.data.message);
      }
    }, controller.signal)
      .catch((err: unknown) => { if (!controller.signal.aborted) setStreamError(err instanceof Error ? err.message : String(err)); })
      .finally(() => {
        // A stream that ends without `done` (proxy timeout, worker gone) leaves the merged view stale: resync once.
        if (!controller.signal.aborted) {
          if (!sawDone) {
            refetch();
            setStreamError((prev) => prev ?? "the live connection closed before the task finished");
          }
          // Guarded: StrictMode's first cleanup aborts a controller whose promise settles after the second setup set `live`.
          setLive(false);
        }
      });
    return () => controller.abort();
  }, [shouldStream, taskId, queryClient, refetch]);

  // Merge: the fetched detail is the base; live steps and status overlay it.
  const base = query.data ?? null;
  const steps = base
    ? [...base.steps, ...liveSteps.filter((s) => !base.steps.some((b) => b.seq === s.seq))].sort((a, b) => a.seq - b.seq)
    : liveSteps;
  const task = base
    ? { ...base, ...(liveStatus && liveStatus !== "gone" ? { status: liveStatus } : {}), ...(liveMeta ?? {}) }
    : null;

  return {
    task,
    steps,
    gone: liveStatus === "gone",
    live,
    streamError,
    isLoading: query.isLoading,
    error: query.error,
    refetch,
  };
}
