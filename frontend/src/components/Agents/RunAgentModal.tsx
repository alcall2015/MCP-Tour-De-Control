import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { createAgentTask } from "../../lib/api";
import type { Agent } from "../../lib/api";
import { Modal } from "../ui/Modal";
import { MutationError } from "../ui/MutationError";

interface Props {
  open: boolean;
  agent: Agent | null;
  onClose: () => void;
}

export function RunAgentModal({ open, agent, onClose }: Props) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [objective, setObjective] = useState("");

  useEffect(() => {
    if (open) setObjective(agent?.objective ?? "");
  }, [open, agent]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!agent) throw new Error("No agent selected");
      const override = objective.trim();
      return createAgentTask(agent.id, override && override !== agent.objective ? override : null);
    },
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-tasks", task.agent_id] });
      onClose();
      navigate(`/agents/${task.agent_id}/tasks/${task.id}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (objective.trim()) mutation.mutate();
  };

  return (
    <Modal open={open} title={agent ? `Run ${agent.name}` : "Run agent"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Objective for this run</label>
          <textarea rows={4} className="input-field" value={objective} onChange={(e) => setObjective(e.target.value)} />
          <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>Pre-filled with the agent's objective. Edit it to run a one-off variant; the agent itself is not changed.</p>
        </div>
        <p className="text-xs rounded-lg px-3 py-2" style={{ color: "var(--warning)", backgroundColor: "rgba(251, 191, 36, 0.08)", border: "1px solid rgba(251, 191, 36, 0.25)" }}>
          No approval step yet: every authorised tool runs immediately, including tools that write.
        </p>
        <MutationError error={mutation.error} />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!objective.trim() || mutation.isPending}>
            {mutation.isPending ? "Starting..." : "Start"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
