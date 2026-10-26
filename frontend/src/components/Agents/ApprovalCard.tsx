import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approveApproval, rejectApproval } from "../../lib/api";
import type { Approval } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { RiskBadge } from "./RiskBadge";
import { timeLeft } from "./time";

function notification(a: Approval): { text: string; color: string } {
  if (a.notified_at) return { text: `WhatsApp sent ${new Date(a.notified_at).toLocaleTimeString()}`, color: "var(--success)" };
  if (a.notify_error === "notifications disabled") return { text: "WhatsApp notifications are off", color: "var(--text-muted)" };
  if (a.notify_error) return { text: `WhatsApp failed: ${a.notify_error}`, color: "var(--error)" };
  return { text: "WhatsApp not sent yet", color: "var(--text-muted)" };
}

export function ApprovalCard({ approval, taskId }: { approval: Approval; taskId: string }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  // Re-render the countdown without refetching.
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick((n) => n + 1), 30000); return () => clearInterval(id); }, []);

  const done = () => {
    queryClient.invalidateQueries({ queryKey: ["agent-task", taskId] });
    queryClient.invalidateQueries({ queryKey: ["approvals"] });
    queryClient.invalidateQueries({ queryKey: ["agents"] });
  };
  const approve = useMutation({ mutationFn: () => approveApproval(approval.id, reason), onSuccess: done });
  const reject = useMutation({ mutationFn: () => rejectApproval(approval.id, reason), onSuccess: done });
  const busy = approve.isPending || reject.isPending;
  const note = notification(approval);

  return (
    <section className="rounded-xl p-4 space-y-3" style={{ backgroundColor: "rgba(251, 191, 36, 0.06)", border: "1px solid rgba(251, 191, 36, 0.35)" }} aria-labelledby="approval-title">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 id="approval-title" className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--warning)" }}>Approval required</h3>
        <RiskBadge level={approval.risk_level} />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{timeLeft(approval.expires_at)}</span>
        <span className="ml-auto font-mono text-sm" title="Reply OUI or NON followed by this code on WhatsApp" style={{ color: "var(--text-primary)" }}>code {approval.code}</span>
      </div>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        The agent wants to call <code className="font-mono" style={{ color: "var(--accent)" }}>{approval.tool_name}</code> on {approval.server_name}.
      </p>
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg px-3 py-2 font-mono text-xs max-h-64 overflow-y-auto" style={{ backgroundColor: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
        {JSON.stringify(approval.args, null, 2)}
      </pre>
      <p className="text-xs" style={{ color: note.color }}>{note.text}</p>
      <div className="flex items-center gap-2 flex-wrap">
        <input className="input-field" style={{ maxWidth: "24rem" }} placeholder="Reason (optional, sent back to the agent on reject)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="btn-primary btn-sm" disabled={busy} onClick={() => approve.mutate()}>{approve.isPending ? "Approving…" : "Approve"}</button>
        <button type="button" className="btn-danger btn-sm" disabled={busy} onClick={() => reject.mutate()}>{reject.isPending ? "Rejecting…" : "Reject"}</button>
      </div>
      <MutationError error={approve.error ?? reject.error} />
    </section>
  );
}
