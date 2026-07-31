import { useState } from "react";

interface Props {
  tool: string;
  server: string;
  args?: Record<string, unknown>;
  result?: unknown;
  loading?: boolean;
}

export function ToolCallBlock({ tool, server, args, result, loading }: Props) {
  const [expanded, setExpanded] = useState(false);
  const resultStr = typeof result === "string" ? result : JSON.stringify(result, null, 2);
  const isLong = resultStr && resultStr.length > 200;

  return (
    <div
      className="my-2 rounded-lg text-xs"
      style={{ border: "1px solid rgba(96, 165, 250, 0.2)", backgroundColor: "rgba(96, 165, 250, 0.05)" }}
    >
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer"
        onClick={() => result !== undefined && setExpanded(!expanded)}
      >
        {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" style={{ color: "var(--running)" }} />}
        <span style={{ color: "var(--running)" }}>Appel</span>
        <code className="font-mono" style={{ color: "var(--accent)" }}>{tool}</code>
        {server && <span style={{ color: "var(--text-muted)" }}>sur {server}</span>}
        {result !== undefined && !loading && (
          <span style={{ color: "var(--success)", marginLeft: "auto" }}>{expanded ? "▾" : "▸"}</span>
        )}
      </div>
      {expanded && result !== undefined && (
        <div className="px-3 pb-2">
          {args && Object.keys(args).length > 0 && (
            <div className="pb-1">
              <span style={{ color: "var(--text-muted)" }}>Args: </span>
              <code className="font-mono" style={{ color: "var(--text-muted)" }}>
                {JSON.stringify(args)}
              </code>
            </div>
          )}
          <pre
            className="text-xs overflow-x-auto font-mono whitespace-pre-wrap break-all"
            style={{
              color: "var(--text-secondary)",
              maxHeight: isLong ? "200px" : "auto",
              overflow: isLong ? "auto" : "visible",
            }}
          >
            {resultStr}
          </pre>
        </div>
      )}
    </div>
  );
}
