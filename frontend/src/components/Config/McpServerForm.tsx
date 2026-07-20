import { useState } from "react";
import type { McpServerCreate } from "../../lib/api";

interface Props {
  initial?: Partial<McpServerCreate>;
  onSubmit: (data: McpServerCreate) => void;
  onCancel: () => void;
}

export function McpServerForm({ initial, onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initial?.name || "");
  const [transport, setTransport] = useState(initial?.transport || "stdio");
  const [command, setCommand] = useState(initial?.command || "");
  const [args, setArgs] = useState(initial?.args?.join(" ") || "");
  const [url, setUrl] = useState(initial?.url || "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      transport,
      command: transport === "stdio" ? command : undefined,
      args: transport === "stdio" && args ? args.split(" ") : undefined,
      url: transport === "http" ? url : undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="grid gap-3 rounded border border-zinc-700 bg-zinc-800 p-4">
      <input
        required
        placeholder="Server name"
        className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <select
        className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
        value={transport}
        onChange={(e) => setTransport(e.target.value)}
      >
        <option value="stdio">stdio</option>
        <option value="http">http</option>
      </select>
      {transport === "stdio" ? (
        <>
          <input
            required
            placeholder="Command (e.g. python)"
            className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
          />
          <input
            placeholder="Args (space-separated, e.g. server.py --port 8080)"
            className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
            value={args}
            onChange={(e) => setArgs(e.target.value)}
          />
        </>
      ) : (
        <input
          required
          placeholder="URL (e.g. http://localhost:8080/mcp)"
          className="rounded border border-zinc-600 bg-zinc-900 px-3 py-2 text-white"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      )}
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
          Save
        </button>
        <button type="button" onClick={onCancel} className="rounded bg-zinc-700 px-4 py-2 text-sm text-white hover:bg-zinc-600">
          Cancel
        </button>
      </div>
    </form>
  );
}
