import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMcpServers } from "../../lib/api";
import type { PromptCreate } from "../../lib/api";
import { CronPicker } from "./CronPicker";

interface Props {
  onSubmit: (data: PromptCreate) => void;
  onCancel: () => void;
}

export function PromptForm({ onSubmit, onCancel }: Props) {
  const { data: servers = [] } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: listMcpServers,
  });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [promptText, setPromptText] = useState("");
  const [cronExpr, setCronExpr] = useState("0 8 * * *");
  const [selectedServers, setSelectedServers] = useState<string[]>([]);

  const toggleServer = (id: string) => {
    setSelectedServers((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      description: description || undefined,
      prompt_text: promptText,
      cron_expr: cronExpr,
      mcp_server_ids: selectedServers,
    });
  };

  const enabledServers = servers.filter((s) => s.enabled);

  return (
    <form
      onSubmit={handleSubmit}
      className="card p-6 space-y-5"
    >
      <h3
        className="text-base font-semibold mb-1"
        style={{
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          color: "var(--text-primary)",
        }}
      >
        New Prompt
      </h3>

      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Name
        </label>
        <input
          required
          className="input-field"
          placeholder="My automation prompt"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Description
        </label>
        <input
          className="input-field"
          placeholder="Optional description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Prompt
        </label>
        <textarea
          required
          rows={4}
          className="input-field"
          placeholder="Describe what the script should do..."
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
        />
      </div>

      <CronPicker value={cronExpr} onChange={setCronExpr} />

      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          MCP Servers to use
        </label>
        {enabledServers.length === 0 ? (
          <p
            className="text-sm rounded-lg px-3 py-2"
            style={{
              color: "var(--text-muted)",
              backgroundColor: "var(--bg-elevated)",
              border: "1px solid var(--border)",
            }}
          >
            No servers configured. Go to the Config tab first.
          </p>
        ) : (
          <div className="space-y-2">
            {enabledServers.map((server) => {
              const checked = selectedServers.includes(server.id);
              return (
                <label
                  key={server.id}
                  className="flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors duration-150"
                  style={{
                    backgroundColor: checked ? "rgba(226, 179, 64, 0.08)" : "var(--bg-elevated)",
                    border: `1px solid ${checked ? "rgba(226, 179, 64, 0.3)" : "var(--border)"}`,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleServer(server.id)}
                    className="rounded"
                    style={{ accentColor: "var(--accent)" }}
                  />
                  <span style={{ color: "var(--text-primary)" }}>{server.name}</span>
                  <span
                    className="font-mono text-xs"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {server.transport}
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={selectedServers.length === 0}
          className="btn-primary"
        >
          Create & Generate Script
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="btn-secondary"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
