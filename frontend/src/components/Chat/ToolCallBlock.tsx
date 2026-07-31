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
  const isLong = resultStr && resultStr.split("\n").length > 5;

  return (
    <div
      className="my-2 rounded-lg text-xs"
      style={{ border: "1px solid rgba(96, 165, 250, 0.2)", backgroundColor: "rgba(96, 165, 250, 0.05)" }}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" style={{ color: "var(--running)" }} />}
        <span style={{ color: "var(--running)" }}>Appel</span>
        <code className="font-mono" style={{ color: "var(--accent)" }}>{tool}</code>
        {server && <span style={{ color: "var(--text-muted)" }}>sur {server}</span>}
      </div>
      {args && Object.keys(args).length > 0 && (
        <div className="px-3 pb-1">
          <pre className="text-xs overflow-x-auto font-mono" style={{ color: "var(--text-muted)" }}>
            {JSON.stringify(args, null, 2)}
          </pre>
        </div>
      )}
      {result !== undefined && (
        <div className="px-3 pb-2">
          {isLong && !expanded ? (
            <>
              <pre className="text-xs overflow-x-auto font-mono" style={{ color: "var(--text-secondary)", maxHeight: "80px", overflow: "hidden" }}>
                {resultStr?.slice(0, 300)}...
              </pre>
              <button onClick={() => setExpanded(true)} className="text-xs mt-1" style={{ color: "var(--running)" }}>
                Voir tout
              </button>
            </>
          ) : (
            <pre className="text-xs overflow-x-auto font-mono" style={{ color: "var(--text-secondary)", maxHeight: expanded ? "400px" : "200px", overflow: "auto" }}>
              {resultStr}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
