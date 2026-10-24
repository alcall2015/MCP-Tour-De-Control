import { useState } from "react";
import type { Agent } from "../lib/api";
import { AgentList } from "../components/Agents/AgentList";
import { AgentFormModal } from "../components/Agents/AgentFormModal";

export function AgentsPage() {
  const [view, setView] = useState<"active" | "archived">("active");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);

  const openCreate = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (agent: Agent) => { setEditing(agent); setModalOpen(true); };
  const close = () => { setModalOpen(false); setEditing(null); };

  const tab = (value: "active" | "archived", label: string) => (
    <button type="button" className={value === view ? "btn-primary btn-sm" : "btn-secondary btn-sm"} onClick={() => setView(value)}>
      {label}
    </button>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-5 w-1 rounded-full flex-shrink-0" style={{ backgroundColor: "var(--accent)" }} />
          <h2 className="text-2xl font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
            Agents
          </h2>
        </div>
        <button type="button" onClick={openCreate} className="btn-primary">+ New Agent</button>
      </div>

      <div className="flex gap-2">
        {tab("active", "Active")}
        {tab("archived", "Archived")}
      </div>

      <AgentList view={view} onEdit={openEdit} onCreate={openCreate} />
      <AgentFormModal open={modalOpen} agent={editing} onClose={close} />
    </div>
  );
}
