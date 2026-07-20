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
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });
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
    <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-zinc-700 bg-zinc-900 p-6">
      <div>
        <label className="mb-1 block text-sm text-zinc-400">Name</label>
        <input
          required
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="My prompt"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm text-zinc-400">Description</label>
        <input
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="Optional description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm text-zinc-400">Prompt</label>
        <textarea
          required
          rows={4}
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="Describe what the script should do..."
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
        />
      </div>
      <CronPicker value={cronExpr} onChange={setCronExpr} />
      <div>
        <label className="mb-1 block text-sm text-zinc-400">MCP Servers to use</label>
        {enabledServers.length === 0 ? (
          <p className="text-sm text-zinc-500">No servers configured. Go to Config tab first.</p>
        ) : (
          <div className="space-y-2">
            {enabledServers.map((server) => (
              <label key={server.id} className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedServers.includes(server.id)}
                  onChange={() => toggleServer(server.id)}
                  className="rounded"
                />
                <span className="text-white">{server.name}</span>
                <span className="text-xs text-zinc-500">({server.transport})</span>
              </label>
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={selectedServers.length === 0}
          className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Create & Generate Script
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded bg-zinc-700 px-4 py-2 text-sm text-white hover:bg-zinc-600"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
