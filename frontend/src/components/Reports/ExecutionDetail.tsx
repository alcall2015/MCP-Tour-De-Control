import type { Execution } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";

interface Props {
  execution: Execution;
  onClose: () => void;
}

export function ExecutionDetail({ execution, onClose }: Props) {
  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{execution.prompt_name}</h3>
          <StatusBadge status={execution.status} />
          <span className="text-sm text-zinc-500">v{execution.script_version}</span>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-white">Close</button>
      </div>

      <div className="mb-4 grid grid-cols-4 gap-4 text-sm">
        <div>
          <span className="text-zinc-500">Started</span>
          <p>{new Date(execution.started_at).toLocaleString("fr-FR")}</p>
        </div>
        <div>
          <span className="text-zinc-500">Duration</span>
          <p>{execution.duration_ms ? `${(execution.duration_ms / 1000).toFixed(1)}s` : "—"}</p>
        </div>
        <div>
          <span className="text-zinc-500">Tokens used</span>
          <p>{execution.tokens_used}</p>
        </div>
        <div>
          <span className="text-zinc-500">Finished</span>
          <p>{execution.finished_at ? new Date(execution.finished_at).toLocaleString("fr-FR") : "—"}</p>
        </div>
      </div>

      {execution.output && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-zinc-400">Output</h4>
          <pre className="max-h-64 overflow-auto rounded bg-zinc-800 p-4 text-sm text-zinc-200">
            {execution.output}
          </pre>
        </div>
      )}

      {execution.llm_output && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-zinc-400">LLM Output</h4>
          <pre className="max-h-64 overflow-auto rounded bg-zinc-800 p-4 text-sm text-zinc-200">
            {execution.llm_output}
          </pre>
        </div>
      )}

      {execution.error && (
        <div>
          <h4 className="mb-1 text-sm font-medium text-red-400">Error</h4>
          <pre className="max-h-64 overflow-auto rounded bg-red-950 p-4 text-sm text-red-300">
            {execution.error}
          </pre>
        </div>
      )}
    </div>
  );
}
