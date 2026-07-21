import type { McpToolInfo } from "../../lib/api";

export function McpToolsPreview({ tools }: { tools: McpToolInfo[] }) {
  if (tools.length === 0) return null;

  return (
    <div
      className="mt-3 rounded-lg p-3"
      style={{
        backgroundColor: "rgba(52, 211, 153, 0.05)",
        border: "1px solid rgba(52, 211, 153, 0.15)",
      }}
    >
      <p
        className="mb-2 text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--success)" }}
      >
        {tools.length} tool{tools.length !== 1 ? "s" : ""} discovered
      </p>
      <div className="flex flex-wrap gap-1.5">
        {tools.map((t) => (
          <span
            key={t.name}
            className="rounded-md px-2 py-0.5 font-mono text-xs cursor-default"
            style={{
              backgroundColor: "var(--bg-panel)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
            title={t.description || ""}
          >
            {t.name}
          </span>
        ))}
      </div>
    </div>
  );
}
