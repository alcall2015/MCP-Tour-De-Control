import { Link } from "react-router-dom";
import type { AgentTask } from "../../lib/api";
import { OutcomeBadge, TaskStatusBadge } from "./AgentTaskBadges";
import { relativeTime } from "./time";

export function AgentTaskRow({ agentId, task }: { agentId: string; task: AgentTask }) {
  return (
    <Link to={`/agents/${agentId}/tasks/${task.id}`} className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)", textDecoration: "none" }}>
      <TaskStatusBadge status={task.status} />
      <OutcomeBadge outcome={task.outcome} />
      <span className="truncate" style={{ color: "var(--text-primary)" }}>{task.objective}</span>
      <span className="ml-auto flex-shrink-0" style={{ color: "var(--text-muted)" }}>{task.trigger} · {relativeTime(task.finished_at ?? task.created_at)}</span>
    </Link>
  );
}
