import type { Execution } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";

interface Props {
  execution: Execution;
  onClose: () => void;
}

function MetaCell({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="rounded-lg p-3"
      style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}
    >
      <p className="mb-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p
        className="font-mono text-sm"
        style={{ color: "var(--text-primary)" }}
      >
        {value}
      </p>
    </div>
  );
}

export function ExecutionDetail({ execution, onClose }: Props) {
  return (
    <div className="card p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3
            className="text-lg font-semibold"
            style={{
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              color: "var(--text-primary)",
            }}
          >
            {execution.prompt_name}
          </h3>
          <StatusBadge status={execution.status} />
          {execution.script_version !== null && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              v{execution.script_version}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="btn-secondary text-xs px-3 py-1.5"
        >
          ← Back
        </button>
      </div>

      {/* Meta grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetaCell
          label="Started"
          value={new Date(execution.started_at).toLocaleString("fr-FR")}
        />
        <MetaCell
          label="Duration"
          value={execution.duration_ms ? `${(execution.duration_ms / 1000).toFixed(1)}s` : "—"}
        />
        <MetaCell label="Tokens used" value={String(execution.tokens_used)} />
        <MetaCell
          label="Finished"
          value={
            execution.finished_at
              ? new Date(execution.finished_at).toLocaleString("fr-FR")
              : "—"
          }
        />
      </div>

      {/* Output */}
      {execution.output && (
        <div>
          <h4
            className="mb-2 text-xs font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Output
          </h4>
          <pre
            className="max-h-64 overflow-auto rounded-lg p-4 text-sm font-mono"
            style={{
              backgroundColor: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          >
            {execution.output}
          </pre>
        </div>
      )}

      {/* LLM Output */}
      {execution.llm_output && (
        <div>
          <h4
            className="mb-2 text-xs font-semibold uppercase tracking-wider"
            style={{ color: "var(--warning)" }}
          >
            LLM Output
          </h4>
          <pre
            className="max-h-64 overflow-auto rounded-lg p-4 text-sm font-mono"
            style={{
              backgroundColor: "var(--bg-elevated)",
              border: "1px solid rgba(251, 191, 36, 0.2)",
              color: "var(--text-primary)",
            }}
          >
            {execution.llm_output}
          </pre>
        </div>
      )}

      {/* Error */}
      {execution.error && (
        <div>
          <h4
            className="mb-2 text-xs font-semibold uppercase tracking-wider"
            style={{ color: "var(--error)" }}
          >
            Error
          </h4>
          <pre
            className="max-h-64 overflow-auto rounded-lg p-4 text-sm font-mono"
            style={{
              backgroundColor: "rgba(248, 113, 113, 0.08)",
              border: "1px solid rgba(248, 113, 113, 0.25)",
              color: "var(--error)",
            }}
          >
            {execution.error}
          </pre>
        </div>
      )}
    </div>
  );
}
