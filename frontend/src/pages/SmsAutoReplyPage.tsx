import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, getSmsAutoReplyStats, listSmsReplies, previewSmsAutoReply, runSmsAutoReply, updateConfig } from "../lib/api";
import { Spinner } from "../components/ui/Spinner";

export function SmsAutoReplyPage() {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [template, setTemplate] = useState<string | null>(null);
  const [maxPerRun, setMaxPerRun] = useState<number | null>(null);
  const [lookbackMinutes, setLookbackMinutes] = useState<number | null>(null);
  const [cooldownHours, setCooldownHours] = useState<number | null>(null);

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: stats } = useQuery({ queryKey: ["sms-autoreply-stats"], queryFn: getSmsAutoReplyStats, refetchInterval: 30000 });
  const { data: replies = [], isLoading } = useQuery({ queryKey: ["sms-autoreply-replies"], queryFn: listSmsReplies, refetchInterval: 30000 });

  const configMut = useMutation({
    mutationFn: updateConfig,
    onSuccess: () => {
      setEnabled(null);
      setTemplate(null);
      setMaxPerRun(null);
      setLookbackMinutes(null);
      setCooldownHours(null);
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
  const previewMut = useMutation({ mutationFn: previewSmsAutoReply });
  const runMut = useMutation({
    mutationFn: runSmsAutoReply,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sms-autoreply-replies"] });
      queryClient.invalidateQueries({ queryKey: ["sms-autoreply-stats"] });
    },
  });

  const activeEnabled = enabled ?? config?.sms_autoreply_enabled ?? false;
  const activeTemplate = template ?? config?.sms_autoreply_template ?? "";
  const activeMaxPerRun = maxPerRun ?? config?.sms_autoreply_max_per_run ?? 10;
  const activeLookback = lookbackMinutes ?? config?.sms_autoreply_lookback_minutes ?? 60;
  const activeCooldown = cooldownHours ?? config?.sms_autoreply_recipient_cooldown_hours ?? 24;

  const saveSettings = () =>
    configMut.mutate({
      sms_autoreply_enabled: activeEnabled,
      sms_autoreply_template: activeTemplate,
      sms_autoreply_max_per_run: activeMaxPerRun,
      sms_autoreply_lookback_minutes: activeLookback,
      sms_autoreply_recipient_cooldown_hours: activeCooldown,
    });

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span className="h-5 w-1 rounded-full flex-shrink-0" style={{ backgroundColor: "var(--accent)" }} />
        <div>
          <h2 className="text-2xl font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
            SMS Auto-Reply
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
            Answers inbound SMS from numbers outside the fleet, and follows up the most recent unanswered call.
          </p>
        </div>
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Settings</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          The reply text is fixed and rendered from the template below — the same message goes to every recipient. Quiet hours are shared with SIM Pairing and configured there, not on this page.
        </p>
        <div className="mt-5 grid max-w-xl gap-4">
          <label className="flex items-center gap-3 text-sm" style={{ color: "var(--text-primary)" }}>
            <input type="checkbox" checked={activeEnabled} onChange={(event) => setEnabled(event.target.checked)} /> Enable SMS auto-reply
          </label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Reply template
            <textarea
              value={activeTemplate}
              onChange={(event) => setTemplate(event.target.value)}
              rows={3}
              className="input mt-1 w-full"
              placeholder="e.g. Salut, j'essaye de te joindre. Ecris-moi sur WhatsApp au {whatsapp}."
            />
            <span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>Use {"{whatsapp}"} to insert the WhatsApp number. Identical text is sent to every recipient.</span>
          </label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Maximum replies per run
            <input type="number" min="1" max="100" value={activeMaxPerRun} onChange={(event) => setMaxPerRun(Number(event.target.value))} className="input mt-1 w-full" />
          </label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Lookback window (minutes)
            <input type="number" min="1" max="1440" value={activeLookback} onChange={(event) => setLookbackMinutes(Number(event.target.value))} className="input mt-1 w-full" />
            <span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>How far back to look for unanswered SMS and missed calls on each run.</span>
          </label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Per-recipient cooldown (hours)
            <input type="number" min="0" max="168" value={activeCooldown} onChange={(event) => setCooldownHours(Number(event.target.value))} className="input mt-1 w-full" />
            <span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>Minimum time before the same recipient can receive another auto-reply.</span>
          </label>
          <div>
            <button type="button" className="btn-primary" onClick={saveSettings} disabled={configMut.isPending}>
              {configMut.isPending ? "Saving..." : "Save settings"}
            </button>
          </div>
          {configMut.error && <p className="text-sm" style={{ color: "var(--error)" }}>{configMut.error.message}</p>}
        </div>
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Run</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Preview shows exactly what the real run would send, without sending anything. Read every proposed message and recipient before running for real.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="button" className="btn-secondary" onClick={() => previewMut.mutate()} disabled={previewMut.isPending}>
            {previewMut.isPending ? "Generating preview..." : "Preview (no send)"}
          </button>
          <button type="button" className="btn-primary" onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            {runMut.isPending ? "Running..." : "Run now"}
          </button>
        </div>
        {(previewMut.error || runMut.error) && (
          <p className="mt-3 text-sm" style={{ color: "var(--error)" }}>{(previewMut.error || runMut.error)?.message}</p>
        )}

        {previewMut.data && (
          <div className="mt-5 rounded-lg p-4" style={{ backgroundColor: "var(--bg-panel)" }}>
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>Preview result</p>
            {previewMut.data.reason ? (
              <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>{previewMut.data.reason}</p>
            ) : (
              <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                {previewMut.data.sent} sent / {previewMut.data.skipped} skipped / {previewMut.data.failed} failed
              </p>
            )}
            <div className="mt-3 space-y-2">
              {previewMut.data.previews?.map((preview, index) => (
                <div key={index} className="rounded-lg p-3 text-sm" style={{ backgroundColor: "var(--bg-card)" }}>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {preview.kind} → {preview.to_number}{preview.whatsapp ? ` (WhatsApp ${preview.whatsapp})` : ""}
                  </p>
                  {preview.content !== null ? (
                    <p className="mt-1" style={{ color: "var(--text-primary)" }}>{preview.content}</p>
                  ) : (
                    <p className="mt-1" style={{ color: "var(--warning)" }}>Would not send: {preview.skip_reason}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {runMut.data && (
          <div className="mt-5 rounded-lg p-4" style={{ backgroundColor: "var(--bg-panel)" }}>
            <p className="text-sm" style={{ color: "var(--success)" }}>
              {runMut.data.reason ?? `${runMut.data.sent} sent / ${runMut.data.skipped} skipped / ${runMut.data.failed} failed`}
            </p>
          </div>
        )}
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>History</h3>
        {stats && (
          <div className="mt-4 flex flex-wrap gap-6 text-sm">
            <span style={{ color: "var(--text-secondary)" }}>Sent <span className="font-medium" style={{ color: "var(--success)" }}>{stats.sent}</span></span>
            <span style={{ color: "var(--text-secondary)" }}>Failed <span className="font-medium" style={{ color: stats.failed ? "var(--error)" : "var(--text-primary)" }}>{stats.failed}</span></span>
            <span style={{ color: "var(--text-secondary)" }}>Skipped <span className="font-medium" style={{ color: "var(--text-primary)" }}>{stats.skipped}</span></span>
            <span style={{ color: "var(--text-secondary)" }}>Sending <span className="font-medium" style={{ color: stats.sending ? "var(--warning)" : "var(--text-primary)" }}>{stats.sending}</span></span>
            <span style={{ color: "var(--text-secondary)" }}>Last sent <span className="font-medium" style={{ color: "var(--text-primary)" }}>{stats.last_sent_at ? new Date(stats.last_sent_at).toLocaleString() : "never"}</span></span>
          </div>
        )}
        {stats && stats.sending > 0 && (
          <p className="mt-3 text-xs" style={{ color: "var(--warning)" }}>
            {stats.sending} repl{stats.sending === 1 ? "y is" : "ies are"} stuck in "sending" — the outcome was never recorded, most likely a crash mid-send.
          </p>
        )}

        <p className="mt-5 text-sm" style={{ color: "var(--text-secondary)" }}>Last 100 replies.</p>
        {isLoading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : replies.length === 0 ? (
          <p className="mt-4 rounded-lg px-4 py-5 text-sm" style={{ color: "var(--text-muted)", backgroundColor: "var(--bg-panel)" }}>
            No replies yet.
          </p>
        ) : (
          <div className="mt-4 space-y-2">
            {replies.map((reply) => (
              <div key={reply.id} className="card-elevated px-4 py-3">
                <div className="flex items-center justify-between">
                  <span className="font-medium" style={{ color: "var(--text-primary)" }}>{reply.to_number}</span>
                  <span
                    className="text-xs font-medium"
                    style={{
                      color:
                        reply.status === "sent"
                          ? "var(--success)"
                          : reply.status === "sending"
                          ? "var(--warning)"
                          : reply.status === "failed"
                          ? "var(--error)"
                          : "var(--text-muted)",
                    }}
                  >
                    {reply.status}
                  </span>
                </div>
                <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  {reply.trigger_kind} · WhatsApp {reply.whatsapp_number ?? "none"} · {new Date(reply.created_at).toLocaleString()}
                  {reply.sent_at ? ` · sent ${new Date(reply.sent_at).toLocaleString()}` : ""}
                </p>
                {reply.error && <p className="mt-1 text-xs" style={{ color: "var(--error)" }}>{reply.error}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
