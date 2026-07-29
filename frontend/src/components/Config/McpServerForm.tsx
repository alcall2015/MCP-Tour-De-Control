import { useState } from "react";
import type { McpServerCreate } from "../../lib/api";

interface Props {
  initial?: Partial<McpServerCreate> & { api_key_set?: boolean };
  onSubmit: (data: McpServerCreate) => void;
  onCancel: () => void;
}

export function McpServerForm({ initial, onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initial?.name || "");
  const [transport, setTransport] = useState(initial?.transport || "stdio");
  const [command, setCommand] = useState(initial?.command || "");
  const [args, setArgs] = useState(initial?.args?.join(" ") || "");
  const [url, setUrl] = useState(initial?.url || "");
  const [apiKey, setApiKey] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      transport,
      command: transport === "stdio" ? command : undefined,
      args: transport === "stdio" && args ? args.split(" ") : undefined,
      url: transport === "http" ? url : undefined,
      api_key: transport === "http" && apiKey ? apiKey : undefined,
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="card-elevated p-4 space-y-3"
    >
      <input
        required
        placeholder="Server name"
        className="input-field"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <select
        className="input-field"
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
            className="input-field font-mono"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
          />
          <input
            placeholder="Args (space-separated, e.g. server.py --port 8080)"
            className="input-field font-mono"
            value={args}
            onChange={(e) => setArgs(e.target.value)}
          />
        </>
      ) : (
        <>
          <input
            required
            placeholder="URL (e.g. http://localhost:8080/mcp)"
            className="input-field font-mono"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <div className="relative">
            <input
              type="password"
              placeholder={initial?.api_key_set ? "API Key (configured, leave empty to keep)" : "API Key (optional)"}
              className="input-field font-mono"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
        </>
      )}
      <div className="flex gap-2 pt-1">
        <button type="submit" className="btn-primary text-xs px-3 py-1.5">
          Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="btn-secondary text-xs px-3 py-1.5"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
