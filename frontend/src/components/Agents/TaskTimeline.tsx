import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAgentTaskStep } from "../../lib/api";
import type { AgentTaskStep, StepKind } from "../../lib/api";
import { RiskBadge } from "./RiskBadge";

const KIND_LABEL: Record<StepKind, string> = {
  plan: "Plan", turn: "Model turn", tool_call: "Tool call", critique: "Self-critique", report: "Report", error: "Error",
  approval_requested: "Approval requested",
};
const LLM_KINDS: ReadonlySet<StepKind> = new Set(["plan", "turn", "critique", "report"]);

function pretty(value: unknown): string {
  if (typeof value === "string") {
    try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
  }
  return JSON.stringify(value, null, 2);
}

function ToolCallBody({ payload }: { payload: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const ok = payload.ok !== false;
  const result = pretty(payload.result);
  const rejected = !ok && String(payload.result ?? "").includes("rejected by operator");
  return (
    <div className="rounded-lg text-xs" style={{ border: `1px solid ${ok ? "rgba(96, 165, 250, 0.25)" : "rgba(248, 113, 113, 0.35)"}`, backgroundColor: ok ? "rgba(96, 165, 250, 0.05)" : "rgba(248, 113, 113, 0.06)" }}>
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span style={{ color: ok ? "var(--running)" : "var(--error)" }}>{ok ? "Called" : "Failed"}</span>
        <code className="font-mono" style={{ color: "var(--accent)" }}>{String(payload.tool)}</code>
        {payload.server ? <span style={{ color: "var(--text-muted)" }}>on {String(payload.server)}</span> : null}
        {typeof payload.risk_level === "number" && <RiskBadge level={payload.risk_level} compact />}
        {typeof payload.approval_id === "string" && (
          <span style={{ color: "var(--text-muted)" }}>{rejected ? "rejected by operator" : "approved by operator"}</span>
        )}
        <span className="ml-auto" style={{ color: "var(--text-muted)" }}>{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          <div><p className="uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Arguments</p><pre className="overflow-x-auto whitespace-pre-wrap font-mono" style={{ color: "var(--text-secondary)" }}>{pretty(payload.args ?? {})}</pre></div>
          <div><p className="uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Result</p><pre className="overflow-x-auto whitespace-pre-wrap font-mono max-h-64 overflow-y-auto" style={{ color: "var(--text-secondary)" }}>{result}</pre></div>
        </div>
      )}
    </div>
  );
}

function ApprovalRequestedBody({ payload }: { payload: Record<string, unknown> }) {
  return (
    <div className="rounded-lg px-3 py-2 text-xs space-y-1" style={{ border: "1px solid rgba(251, 191, 36, 0.35)", backgroundColor: "rgba(251, 191, 36, 0.06)" }}>
      <div className="flex items-center gap-2 flex-wrap">
        <span style={{ color: "var(--warning)" }}>Parked</span>
        <code className="font-mono" style={{ color: "var(--accent)" }}>{String(payload.tool)}</code>
        {payload.server ? <span style={{ color: "var(--text-muted)" }}>on {String(payload.server)}</span> : null}
        {typeof payload.risk_level === "number" && <RiskBadge level={payload.risk_level} compact />}
        {typeof payload.code === "string" && <span className="ml-auto font-mono" style={{ color: "var(--text-secondary)" }}>code {payload.code}</span>}
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap font-mono max-h-64 overflow-y-auto" style={{ color: "var(--text-secondary)" }}>{pretty(payload.args ?? {})}</pre>
    </div>
  );
}

function PromptDisclosure({ taskId, seq }: { taskId: string; seq: number }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["agent-task-step", taskId, seq], queryFn: () => getAgentTaskStep(taskId, seq), enabled: open });
  return (
    <div>
      <button type="button" className="text-xs underline-offset-2 hover:underline" style={{ color: "var(--text-secondary)" }} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide prompt" : "Show prompt"}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {isLoading && <p className="text-xs" style={{ color: "var(--text-muted)" }}>Loading prompt…</p>}
          {error ? <p className="text-xs" style={{ color: "var(--error)" }}>{(error as Error).message}</p> : null}
          {data?.prompt?.map((m, i) => (
            <div key={i} className="rounded-md px-3 py-2 text-xs" style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              <p className="uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>{String(m.role ?? "message")}</p>
              <pre className="whitespace-pre-wrap font-mono" style={{ color: "var(--text-secondary)" }}>{typeof m.content === "string" ? m.content : pretty(m.content ?? m)}</pre>
            </div>
          ))}
          {data && !data.prompt && <p className="text-xs" style={{ color: "var(--text-muted)" }}>No prompt stored for this step.</p>}
        </div>
      )}
    </div>
  );
}

function StepCard({ taskId, step }: { taskId: string; step: AgentTaskStep }) {
  const p = step.payload;
  const isError = step.kind === "error";
  return (
    <li id={`step-${step.seq}`} className="rounded-xl p-3 space-y-2" style={{ backgroundColor: "var(--bg-panel)", border: `1px solid ${isError ? "rgba(248, 113, 113, 0.4)" : "var(--border)"}` }}>
      <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
        <span className="font-mono">#{step.seq}</span>
        <span className="font-medium" style={{ color: isError ? "var(--error)" : "var(--text-primary)" }}>{KIND_LABEL[step.kind]}</span>
        {step.duration_ms !== null && <span>{step.duration_ms} ms</span>}
        {(step.tokens_in || step.tokens_out) ? <span>{step.tokens_in ?? 0} in / {step.tokens_out ?? 0} out</span> : null}
        <span className="ml-auto">{new Date(step.created_at).toLocaleTimeString()}</span>
      </div>
      {step.kind === "turn" && (
        <>
          {typeof p.text === "string" && p.text && <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>{p.text}</p>}
          {Array.isArray(p.tool_calls) && p.tool_calls.length > 0 && (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Requested: {(p.tool_calls as { name: string }[]).map((t) => t.name).join(", ")}</p>
          )}
        </>
      )}
      {step.kind === "tool_call" && <ToolCallBody payload={p} />}
      {step.kind === "approval_requested" && <ApprovalRequestedBody payload={p} />}
      {step.kind === "error" && <p className="text-sm" style={{ color: "var(--error)" }}>{String(p.message)} <span style={{ color: "var(--text-muted)" }}>(phase: {String(p.phase)})</span></p>}
      {(step.kind === "plan" || step.kind === "critique" || step.kind === "report") && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>See the {KIND_LABEL[step.kind].toLowerCase()} panel.</p>
      )}
      {LLM_KINDS.has(step.kind) && <PromptDisclosure taskId={taskId} seq={step.seq} />}
    </li>
  );
}

export function TaskTimeline({ taskId, steps }: { taskId: string; steps: AgentTaskStep[] }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Steps</h3>
      {steps.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Waiting for the worker to pick this task up…</p>
      ) : (
        <ol className="space-y-2">{steps.map((s) => <StepCard key={s.seq} taskId={taskId} step={s} />)}</ol>
      )}
    </section>
  );
}
