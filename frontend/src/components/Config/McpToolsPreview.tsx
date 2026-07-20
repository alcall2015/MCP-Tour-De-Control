import type { McpToolInfo } from "../../lib/api";

export function McpToolsPreview({ tools }: { tools: McpToolInfo[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="mt-2 rounded border border-zinc-700 bg-zinc-800 p-3">
      <p className="mb-2 text-xs font-medium text-zinc-400">
        {tools.length} tool{tools.length > 1 ? "s" : ""} discovered:
      </p>
      <div className="flex flex-wrap gap-2">
        {tools.map((t) => (
          <span
            key={t.name}
            className="rounded bg-zinc-700 px-2 py-1 text-xs text-zinc-300"
            title={t.description || ""}
          >
            {t.name}
          </span>
        ))}
      </div>
    </div>
  );
}
