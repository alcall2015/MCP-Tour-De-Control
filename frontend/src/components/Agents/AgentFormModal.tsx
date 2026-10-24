import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAgent, listMcpServers, updateAgent } from "../../lib/api";
import type { Agent, AgentCreate } from "../../lib/api";
import { Modal } from "../ui/Modal";
import { MutationError } from "../ui/MutationError";

interface Props {
  open: boolean;
  agent?: Agent | null;
  onClose: () => void;
}

const LIMITS = { steps: { min: 1, max: 100, def: 20 }, timeout: { min: 10, max: 3600, def: 300 } };

const labelStyle = { color: "var(--text-muted)" } as const;
const labelClass = "mb-1.5 block text-xs font-medium uppercase tracking-wider";

export function AgentFormModal({ open, agent, onClose }: Props) {
  const queryClient = useQueryClient();
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });

  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [instructions, setInstructions] = useState("");
  const [description, setDescription] = useState("");
  const [serverIds, setServerIds] = useState<string[]>([]);
  const [maxSteps, setMaxSteps] = useState<number>(LIMITS.steps.def);
  const [timeoutSeconds, setTimeoutSeconds] = useState<number>(LIMITS.timeout.def);

  // Re-seed the fields each time the modal opens, for a new agent or an existing one.
  useEffect(() => {
    if (!open) return;
    setName(agent?.name ?? "");
    setObjective(agent?.objective ?? "");
    setInstructions(agent?.instructions ?? "");
    setDescription(agent?.description ?? "");
    setServerIds(agent?.mcp_servers.map((s) => s.id) ?? []);
    setMaxSteps(agent?.max_steps ?? LIMITS.steps.def);
    setTimeoutSeconds(agent?.timeout_seconds ?? LIMITS.timeout.def);
  }, [open, agent]);

  const mutation = useMutation({
    mutationFn: (data: AgentCreate) => (agent ? updateAgent(agent.id, data) : createAgent(data)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      onClose();
    },
  });

  const inRange = (v: number, r: { min: number; max: number }) => Number.isInteger(v) && v >= r.min && v <= r.max;
  const valid = name.trim() !== "" && objective.trim() !== "" && inRange(maxSteps, LIMITS.steps) && inRange(timeoutSeconds, LIMITS.timeout);

  const toggleServer = (id: string) =>
    setServerIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    mutation.mutate({
      name: name.trim(),
      objective: objective.trim(),
      instructions,
      description: description.trim(),
      max_steps: maxSteps,
      timeout_seconds: timeoutSeconds,
      mcp_server_ids: serverIds,
    });
  };

  return (
    <Modal open={open} title={agent ? "Edit agent" : "New agent"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label className={labelClass} style={labelStyle}>Name</label>
          <input className="input-field" placeholder="Log analyst" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Objective</label>
          <textarea rows={3} className="input-field" placeholder="What this agent is responsible for achieving" value={objective} onChange={(e) => setObjective(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Instructions</label>
          <textarea rows={5} className="input-field" placeholder="System prompt: how the agent should behave, what it must never do, how to report" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Description</label>
          <input className="input-field" placeholder="Optional note for humans" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div>
          <label className={labelClass} style={labelStyle}>Authorised MCP servers</label>
          {servers.length === 0 ? (
            <p className="text-sm rounded-lg px-3 py-2" style={{ color: "var(--text-muted)", backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              No MCP servers configured. Add one in Settings first.
            </p>
          ) : (
            <div className="space-y-1.5">
              {servers.map((s) => (
                <label key={s.id} className="flex items-center gap-2.5 text-sm cursor-pointer" style={{ color: "var(--text-primary)" }}>
                  <input type="checkbox" checked={serverIds.includes(s.id)} onChange={() => toggleServer(s.id)} />
                  <span>{s.name}</span>
                  {!s.enabled && <span className="text-xs" style={{ color: "var(--text-muted)" }}>disabled</span>}
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass} style={labelStyle}>Max steps</label>
            <input type="number" min={LIMITS.steps.min} max={LIMITS.steps.max} className="input-field" value={maxSteps} onChange={(e) => setMaxSteps(Number(e.target.value))} />
            <p className="mt-1 text-xs" style={labelStyle}>{LIMITS.steps.min} to {LIMITS.steps.max} tool rounds per task</p>
          </div>
          <div>
            <label className={labelClass} style={labelStyle}>Timeout (s)</label>
            <input type="number" min={LIMITS.timeout.min} max={LIMITS.timeout.max} className="input-field" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} />
            <p className="mt-1 text-xs" style={labelStyle}>{LIMITS.timeout.min} to {LIMITS.timeout.max} seconds per task</p>
          </div>
        </div>

        <MutationError error={mutation.error} />

        <div className="flex justify-end gap-3 pt-1">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!valid || mutation.isPending}>
            {mutation.isPending ? "Saving..." : agent ? "Save changes" : "Create agent"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
