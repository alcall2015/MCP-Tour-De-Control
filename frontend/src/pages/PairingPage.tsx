import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createSimPairingGroup, createSimPairingTopic, deleteSimPairingGroup, deleteSimPairingTopic, getConfig, getSimPairQueueStats, getSimPairsCount, listSimPairHistory, listSimPairingGroups, listSimPairingTopics, listSimPairMessageQueue, listSimPairMessages, listSimPairs, previewSimPairConversation, runSimPairCalls, runSimPairConversations, syncSimPairs, updateConfig } from "../lib/api";
import { Spinner } from "../components/ui/Spinner";

const PAIRS_PAGE_SIZE = 25;

const NEW_SIM_AUTOMATION_NOTICE = (
  <div className="rounded-lg border px-3 py-2 text-xs leading-5" style={{ borderColor: "rgba(251, 191, 36, 0.35)", backgroundColor: "rgba(251, 191, 36, 0.08)", color: "var(--warning)" }}>
    <strong>New-SIM risk notice.</strong> A call or SMS between two newly activated SIMs in the same 60-minute window is statistically implausible in legitimate use (estimated below 0.1%). Colleagues usually call family, resellers use test numbers, and call centers use established lines; a household may test several SIMs, but rarely in the same hour. Keep this disabled unless the activity is documented and authorised.
  </div>
);

export function PairingPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [topicName, setTopicName] = useState("");
  const [historyPairId, setHistoryPairId] = useState<string | null>(null);
  const [messagesPairId, setMessagesPairId] = useState<string | null>(null);
  const [pairsStatus, setPairsStatus] = useState<"active" | "archived">("active");
  const [pairsPage, setPairsPage] = useState(0);
  const [openRouterKey, setOpenRouterKey] = useState("");
  const [openRouterModel, setOpenRouterModel] = useState<string | null>(null);
  const [conversationInterval, setConversationInterval] = useState<number | null>(null);
  const [conversationEnabled, setConversationEnabled] = useState<boolean | null>(null);
  const [targetMessages, setTargetMessages] = useState<number | null>(null);
  const [maxPerRun, setMaxPerRun] = useState<number | null>(null);
  const [simCooldown, setSimCooldown] = useState<number | null>(null);
  const [quietEnabled, setQuietEnabled] = useState<boolean | null>(null);
  const [quietStart, setQuietStart] = useState<number | null>(null);
  const [quietEnd, setQuietEnd] = useState<number | null>(null);
  const [callEnabled, setCallEnabled] = useState<boolean | null>(null);
  const { data: groups = [], isLoading } = useQuery({
    queryKey: ["sim-pairing-groups"],
    queryFn: listSimPairingGroups,
  });
  const { data: topics = [] } = useQuery({ queryKey: ["sim-pairing-topics"], queryFn: listSimPairingTopics });
  const { data: pairsCount } = useQuery({ queryKey: ["sim-pairs-count"], queryFn: getSimPairsCount, refetchInterval: 30000 });
  const { data: pairs = [] } = useQuery({
    queryKey: ["sim-pairs", pairsStatus, pairsPage],
    queryFn: () => listSimPairs({ status: pairsStatus, limit: PAIRS_PAGE_SIZE, offset: pairsPage * PAIRS_PAGE_SIZE }),
    refetchInterval: 30000,
  });
  const { data: history = [] } = useQuery({ queryKey: ["sim-pair-history", historyPairId], queryFn: () => listSimPairHistory(historyPairId!), enabled: Boolean(historyPairId) });
  const { data: messages = [] } = useQuery({ queryKey: ["sim-pair-messages", messagesPairId], queryFn: () => listSimPairMessages(messagesPairId!), enabled: Boolean(messagesPairId), refetchInterval: 30000 });
  const { data: queue = [] } = useQuery({ queryKey: ["sim-pair-message-queue"], queryFn: listSimPairMessageQueue, refetchInterval: 30000 });
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: queueStats } = useQuery({ queryKey: ["sim-pair-queue-stats"], queryFn: getSimPairQueueStats, refetchInterval: 30000 });
  const createMut = useMutation({
    mutationFn: createSimPairingGroup,
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["sim-pairing-groups"] });
    },
  });
  const topicMut = useMutation({ mutationFn: createSimPairingTopic, onSuccess: () => { setTopicName(""); queryClient.invalidateQueries({ queryKey: ["sim-pairing-topics"] }); } });
  const deleteTopicMut = useMutation({ mutationFn: deleteSimPairingTopic, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sim-pairing-topics"] }) });
  const deleteMut = useMutation({
    mutationFn: deleteSimPairingGroup,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sim-pairing-groups"] }),
  });
  const syncMut = useMutation({
    mutationFn: syncSimPairs,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sim-pairs"] });
      queryClient.invalidateQueries({ queryKey: ["sim-pairs-count"] });
    },
  });
  const conversationMut = useMutation({
    mutationFn: runSimPairConversations,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sim-pair-messages"] });
      queryClient.invalidateQueries({ queryKey: ["sim-pair-history"] });
      queryClient.invalidateQueries({ queryKey: ["sim-pairs"] });
      queryClient.invalidateQueries({ queryKey: ["sim-pairs-count"] });
      queryClient.invalidateQueries({ queryKey: ["sim-pair-message-queue"] });
      queryClient.invalidateQueries({ queryKey: ["sim-pair-queue-stats"] });
    },
  });
  const previewMut = useMutation({ mutationFn: previewSimPairConversation });
  const callMut = useMutation({ mutationFn: runSimPairCalls });
  const conversationConfigMut = useMutation({
    mutationFn: updateConfig,
    onSuccess: () => { setOpenRouterKey(""); setOpenRouterModel(null); setConversationInterval(null); setConversationEnabled(null); setTargetMessages(null); setMaxPerRun(null); setSimCooldown(null); setQuietEnabled(null); setQuietStart(null); setQuietEnd(null); queryClient.invalidateQueries({ queryKey: ["config"] }); },
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (name.trim()) createMut.mutate({ name: name.trim() });
  };
  const activeConversationEnabled = conversationEnabled ?? config?.pairing_conversation_enabled ?? false;
  const activeQuietEnabled = quietEnabled ?? config?.pairing_quiet_hours_enabled ?? true;
  const activeQuietStart = quietStart ?? config?.pairing_quiet_start_hour ?? 22;
  const activeQuietEnd = quietEnd ?? config?.pairing_quiet_end_hour ?? 7;
  const activeMaxPerRun = maxPerRun ?? config?.pairing_max_messages_per_run ?? 10;
  const activeInterval = conversationInterval ?? config?.pairing_conversation_interval_minutes ?? 180;
  // The scheduler polls every 15 minutes, and only outside the quiet window.
  const sendingHours = activeQuietEnabled ? 24 - ((activeQuietEnd - activeQuietStart + 24) % 24) : 24;
  const dailyCapacity = activeMaxPerRun * 4 * sendingHours;
  const pairsSupported = Math.floor(dailyCapacity / (1440 / activeInterval));
  const togglePairsStatus = () => {
    setPairsStatus((current) => (current === "active" ? "archived" : "active"));
    setPairsPage(0);
  };
  const pairsTotal = pairsCount ? pairsCount[pairsStatus] : 0;
  const pairsRangeStart = pairsTotal === 0 ? 0 : pairsPage * PAIRS_PAGE_SIZE + 1;
  const pairsRangeEnd = Math.min(pairsTotal, (pairsPage + 1) * PAIRS_PAGE_SIZE);
  const canGoPrevPairs = pairsPage > 0;
  const canGoNextPairs = pairsRangeEnd < pairsTotal;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span className="h-5 w-1 rounded-full flex-shrink-0" style={{ backgroundColor: "var(--accent)" }} />
        <div>
          <h2 className="text-2xl font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
            SIM Pairing
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
            Configure SIM sources separately from the conversation subjects assigned to pairs.
          </p>
        </div>
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Pair Calls</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>Internal A → B / B → A calls hold for a random 45–75 seconds. Both SIMs must be IDLE, not in a call, not resting, and past their cooldown.</p>
        <div className="mt-4 flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}><input type="checkbox" checked={callEnabled ?? config?.pairing_call_enabled ?? false} onChange={(event) => setCallEnabled(event.target.checked)} /> Enable pair calls</label><button type="button" className="btn-secondary" onClick={() => conversationConfigMut.mutate({ pairing_call_enabled: callEnabled ?? config?.pairing_call_enabled ?? false })}>Save</button><button type="button" className="btn-primary" disabled={!(callEnabled ?? config?.pairing_call_enabled) || callMut.isPending} onClick={() => callMut.mutate()}>{callMut.isPending ? "Calling..." : "Run due calls now"}</button></div>
        <div className="mt-3 max-w-3xl">{NEW_SIM_AUTOMATION_NOTICE}</div>
        {callMut.data && <p className="mt-3 text-sm" style={{ color: "var(--success)" }}>{callMut.data.reason ?? `${callMut.data.started} calls started; ${callMut.data.skipped} skipped; ${callMut.data.failed} failed.`}</p>}
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>SIM groups to track</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Add the real TmLite SIM group names. Groups select eligible SIMs; they are not conversation subjects. Pairs may span groups but must stay in one country.
        </p>

        <form onSubmit={submit} className="mt-5 flex max-w-xl gap-3">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. love, affaire, famille"
            className="input flex-1"
            maxLength={200}
          />
          <button type="submit" className="btn-primary" disabled={!name.trim() || createMut.isPending}>
            {createMut.isPending ? "Adding..." : "Add group"}
          </button>
        </form>
        {createMut.error && <p className="mt-3 text-sm" style={{ color: "var(--error)" }}>{createMut.error.message}</p>}

        {isLoading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : groups.length === 0 ? (
          <p className="mt-6 rounded-lg px-4 py-5 text-sm" style={{ color: "var(--text-muted)", backgroundColor: "var(--bg-panel)" }}>
            No SIM groups are tracked yet. Add the groups that should be used to build pairs.
          </p>
        ) : (
          <div className="mt-5 space-y-2">
            {groups.map((group) => (
              <div key={group.id} className="card-elevated flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-3">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: "var(--success)" }} />
                  <span className="font-medium" style={{ color: "var(--text-primary)" }}>{group.name}</span>
                </div>
                <button
                  onClick={() => { if (confirm(`Stop tracking SIM group \"${group.name}\"?`)) deleteMut.mutate(group.id); }}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium"
                  style={{ color: "var(--error)", backgroundColor: "rgba(248, 113, 113, 0.1)" }}
                  disabled={deleteMut.isPending}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Pairs and history</h3>
        <div className="mt-1 flex items-center justify-between gap-4">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Each eligible SIM receives a permanent local West African first name. The scheduler checks pairs every 15 minutes; syncing only creates or updates records and never sends SMS.</p>
          <div className="flex gap-3">
            <button type="button" className="btn-secondary whitespace-nowrap" onClick={togglePairsStatus}>
              {pairsStatus === "active" ? `Show archived (${pairsCount?.archived ?? 0})` : `Show active (${pairsCount?.active ?? 0})`}
            </button>
            <button type="button" className="btn-secondary whitespace-nowrap" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
              {syncMut.isPending ? "Syncing..." : "Sync now"}
            </button>
          </div>
        </div>
        {syncMut.error && <p className="mt-3 text-sm" style={{ color: "var(--error)" }}>{syncMut.error.message}</p>}
        <div className="mt-5 space-y-2">
          {pairs.length === 0 ? <p className="text-sm" style={{ color: "var(--text-muted)" }}>No {pairsStatus} pairs.</p> : pairs.map((pair) => <div key={pair.id} className="card-elevated px-4 py-3"><div className="flex items-center justify-between"><div><span className="font-medium" style={{ color: "var(--text-primary)" }}>{pair.sim_a_name || `SIM ${pair.sim_a_id}`} ↔ {pair.sim_b_name || `SIM ${pair.sim_b_id}`}</span><span className="ml-2 text-xs" style={{ color: "var(--text-secondary)" }}>{pair.country} · {pair.topic}</span><span className="ml-2 text-xs font-medium" style={{ color: pair.sent_count >= pair.target_messages ? "var(--success)" : "var(--text-muted)" }}>{pair.sent_count}/{pair.target_messages}</span></div><div className="flex gap-3"><button onClick={() => setMessagesPairId(pair.id)} className="text-xs" style={{ color: "var(--accent)" }}>Messages</button><button onClick={() => setHistoryPairId(pair.id)} className="text-xs" style={{ color: "var(--running)" }}>History</button></div></div><p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>SIM {pair.sim_a_id} ↔ SIM {pair.sim_b_id}</p><p className="mt-1 text-xs" style={{ color: pair.status === "active" ? "var(--success)" : "var(--text-muted)" }}>{pair.status}{pair.archived_reason ? ` — ${pair.archived_reason}` : ""}</p></div>)}
        </div>
        {pairsTotal > 0 && (
          <div className="mt-4 flex items-center justify-between gap-4">
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{pairsRangeStart}–{pairsRangeEnd} of {pairsTotal}</span>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setPairsPage((page) => Math.max(0, page - 1))}
                disabled={!canGoPrevPairs}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setPairsPage((page) => page + 1)}
                disabled={!canGoNextPairs}
              >
                Next
              </button>
            </div>
          </div>
        )}
        {historyPairId && <div className="mt-5 rounded-lg p-4" style={{ backgroundColor: "var(--bg-panel)" }}><div className="flex justify-between"><span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>Pair history</span><button onClick={() => setHistoryPairId(null)} className="text-xs" style={{ color: "var(--text-secondary)" }}>Close</button></div>{history.map((event) => <p key={event.id} className="mt-2 text-xs" style={{ color: event.event === "archived" ? "var(--warning)" : "var(--text-secondary)" }}>{new Date(event.created_at).toLocaleString()} — {event.event}{typeof event.details?.reason === "string" ? `: ${event.details.reason}` : ""}</p>)}</div>}
        {messagesPairId && <div className="mt-5 rounded-lg p-4" style={{ backgroundColor: "var(--bg-panel)" }}><div className="flex justify-between"><span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>SMS conversation</span><button onClick={() => setMessagesPairId(null)} className="text-xs" style={{ color: "var(--text-secondary)" }}>Close</button></div>{messages.length === 0 ? <p className="mt-3 text-xs" style={{ color: "var(--text-muted)" }}>No messages yet.</p> : messages.map((message) => <div key={message.id} className="mt-3 rounded-lg p-3 text-sm" style={{ backgroundColor: "var(--bg-card)" }}><p style={{ color: "var(--text-primary)" }}>{message.content || "Message generation failed"}</p><p className="mt-1 text-xs" style={{ color: message.status === "sent" ? "var(--success)" : "var(--error)" }}>SIM {message.from_sim_id} → SIM {message.to_sim_id} · {message.status} · {new Date(message.created_at).toLocaleString()}</p>{message.error && <p className="mt-1 text-xs" style={{ color: "var(--error)" }}>{message.error}</p>}</div>)}</div>}
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Conversation automation</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>OpenRouter uses each pair’s subject, names and sent-message history to produce one short French SMS at a time. Direction alternates strictly, so a target of 10 means 5 messages from each SIM. Pairs below their target are always served before pairs that have reached it.</p>
        <div className="mt-5 grid max-w-xl gap-4">
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>OpenRouter API key {config?.pairing_openrouter_api_key_set && <span style={{ color: "var(--success)" }}>(configured)</span>}<input type="password" value={openRouterKey} onChange={(event) => setOpenRouterKey(event.target.value)} placeholder="sk-or-v1-..." className="input mt-1 w-full" /></label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>Model<input value={openRouterModel ?? config?.pairing_openrouter_model ?? "google/gemini-2.5-flash"} onChange={(event) => setOpenRouterModel(event.target.value)} className="input mt-1 w-full" /></label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>Minimum minutes between messages for one pair<input type="number" min="30" max="1440" value={activeInterval} onChange={(event) => setConversationInterval(Number(event.target.value))} className="input mt-1 w-full" /></label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>Messages per conversation (target)<input type="number" min="2" max="100" value={targetMessages ?? config?.pairing_target_messages ?? 10} onChange={(event) => setTargetMessages(Number(event.target.value))} className="input mt-1 w-full" /><span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>Applied to pairs created from now on. Reaching it takes at least (target − 1) × the interval above.</span></label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>Maximum messages per run<input type="number" min="1" max="50" value={activeMaxPerRun} onChange={(event) => setMaxPerRun(Number(event.target.value))} className="input mt-1 w-full" /><span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>A safety ceiling on run duration, not a rhythm setting — the interval per pair is what paces sending. With {sendingHours}h of sending per day that is <strong>{dailyCapacity} messages/day</strong> for the whole fleet, enough for <strong>{pairsSupported} pairs</strong> at the interval above. Beyond that the queue falls behind and the real cadence stretches.</span></label>
          <label className="text-sm" style={{ color: "var(--text-secondary)" }}>Minimum minutes between two messages for one SIM<input type="number" min="0" max="240" value={simCooldown ?? config?.pairing_sim_cooldown_minutes ?? 20} onChange={(event) => setSimCooldown(Number(event.target.value))} className="input mt-1 w-full" /><span className="mt-1 block text-xs" style={{ color: "var(--text-muted)" }}>A SIM belongs to up to three pairs. This keeps it from emitting on all of them at once. 0 disables the rule.</span></label>
          <div className="rounded-lg p-3" style={{ backgroundColor: "var(--bg-panel)" }}>
            <label className="flex items-center gap-3 text-sm" style={{ color: "var(--text-primary)" }}><input type="checkbox" checked={activeQuietEnabled} onChange={(event) => setQuietEnabled(event.target.checked)} /> Pause sending overnight</label>
            <div className="mt-3 flex items-center gap-3">
              <label className="text-xs" style={{ color: "var(--text-secondary)" }}>From (UTC)<input type="number" min="0" max="23" value={activeQuietStart} onChange={(event) => setQuietStart(Number(event.target.value))} className="input mt-1 w-24" disabled={!activeQuietEnabled} /></label>
              <label className="text-xs" style={{ color: "var(--text-secondary)" }}>To (UTC)<input type="number" min="0" max="23" value={activeQuietEnd} onChange={(event) => setQuietEnd(Number(event.target.value))} className="input mt-1 w-24" disabled={!activeQuietEnabled} /></label>
            </div>
            <p className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>One window for the whole fleet, in UTC — the SIMs span several countries and no local time is applied. Messages due inside the window are moved to just after it and spread over 90 minutes. Two equal hours mean no quiet time.</p>
          </div>
          <div>
            <label className="flex items-center gap-3 text-sm" style={{ color: "var(--text-primary)" }}><input type="checkbox" checked={activeConversationEnabled} onChange={(event) => setConversationEnabled(event.target.checked)} /> Enable automatic SMS continuation</label>
            <div className="mt-3">{NEW_SIM_AUTOMATION_NOTICE}</div>
          </div>
          <div className="flex flex-wrap gap-3"><button type="button" className="btn-secondary" onClick={() => conversationConfigMut.mutate({ pairing_openrouter_api_key: openRouterKey || undefined, pairing_openrouter_model: openRouterModel ?? config?.pairing_openrouter_model, pairing_conversation_interval_minutes: activeInterval, pairing_target_messages: targetMessages ?? config?.pairing_target_messages, pairing_max_messages_per_run: activeMaxPerRun, pairing_sim_cooldown_minutes: simCooldown ?? config?.pairing_sim_cooldown_minutes, pairing_quiet_hours_enabled: activeQuietEnabled, pairing_quiet_start_hour: activeQuietStart, pairing_quiet_end_hour: activeQuietEnd, pairing_conversation_enabled: activeConversationEnabled })} disabled={conversationConfigMut.isPending}>{conversationConfigMut.isPending ? "Saving..." : "Save conversation settings"}</button><button type="button" className="btn-secondary" onClick={() => previewMut.mutate()} disabled={!activeConversationEnabled || previewMut.isPending}>{previewMut.isPending ? "Generating preview..." : "Preview one SMS (no send)"}</button><button type="button" className="btn-primary" onClick={() => conversationMut.mutate()} disabled={!activeConversationEnabled || conversationMut.isPending}>{conversationMut.isPending ? "Continuing..." : "Continue due pairs now"}</button></div>
          {previewMut.data?.previews?.map((preview) => <div key={preview.pair_id} className="rounded-lg p-3 text-sm" style={{ color: "var(--text-primary)", backgroundColor: "var(--bg-panel)" }}><p className="text-xs" style={{ color: "var(--text-secondary)" }}>Preview — SIM {preview.from_sim_id} → SIM {preview.to_sim_id}; not sent</p><p className="mt-1">{preview.content}</p></div>)}
          {conversationMut.data && <p className="text-sm" style={{ color: "var(--success)" }}>{conversationMut.data.reason ?? `${conversationMut.data.sent} SMS sent; ${conversationMut.data.held ?? 0} held for pacing; ${conversationMut.data.skipped} deferred (SIM unavailable); ${conversationMut.data.failed} failed.`}</p>}
          {(conversationMut.error || conversationConfigMut.error) && <p className="text-sm" style={{ color: "var(--error)" }}>{(conversationMut.error || conversationConfigMut.error)?.message}</p>}
        </div>
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Message queue</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>Due items are processed in batches, pairs below their target first. Pending items survive restarts and keep their planned time.</p>
        {queueStats && <div className="mt-4 flex flex-wrap gap-6 text-sm"><span style={{ color: "var(--text-secondary)" }}>Pending <span className="font-medium" style={{ color: "var(--text-primary)" }}>{queueStats.pending}</span></span><span style={{ color: "var(--text-secondary)" }}>Overdue <span className="font-medium" style={{ color: queueStats.overdue > queueStats.pending / 2 ? "var(--warning)" : "var(--text-primary)" }}>{queueStats.overdue}</span></span><span style={{ color: "var(--text-secondary)" }}>Failed <span className="font-medium" style={{ color: queueStats.failed ? "var(--error)" : "var(--text-primary)" }}>{queueStats.failed}</span></span><span style={{ color: "var(--text-secondary)" }}>Pairs below target <span className="font-medium" style={{ color: "var(--text-primary)" }}>{queueStats.pairs_under_target}</span></span></div>}
        {queueStats && queueStats.overdue > (config?.pairing_max_messages_per_run ?? 10) && <p className="mt-3 text-xs" style={{ color: "var(--warning)" }}>More items are due than one run can send. Raise the maximum per run, or lengthen the interval per pair — otherwise the real cadence is slower than the interval you configured.</p>}
        <div className="mt-4 space-y-2">{queue.length === 0 ? <p className="text-sm" style={{ color: "var(--text-muted)" }}>No queued messages yet.</p> : queue.slice(0, 10).map((item) => <div key={item.id} className="card-elevated flex items-center justify-between px-4 py-3 text-sm"><span style={{ color: "var(--text-primary)" }}>Pair {item.pair_id.slice(0, 8)}</span><span style={{ color: item.status === "pending" ? "var(--warning)" : item.status === "sent" ? "var(--success)" : "var(--error)" }}>{item.status} · {new Date(item.due_at).toLocaleString()}</span></div>)}</div>
      </div>

      <div className="card p-6">
        <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Conversation subjects</h3>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>Add themes such as love, business, or family. A subject is assigned to each new pair and retained in its history.</p>
        <form onSubmit={(event) => { event.preventDefault(); if (topicName.trim()) topicMut.mutate({ name: topicName.trim() }); }} className="mt-5 flex max-w-xl gap-3">
          <input value={topicName} onChange={(event) => setTopicName(event.target.value)} placeholder="e.g. love" className="input flex-1" maxLength={200} />
          <button type="submit" className="btn-primary" disabled={!topicName.trim() || topicMut.isPending}>{topicMut.isPending ? "Adding..." : "Add subject"}</button>
        </form>
        {topicMut.error && <p className="mt-3 text-sm" style={{ color: "var(--error)" }}>{topicMut.error.message}</p>}
        <div className="mt-5 space-y-2">{topics.map((topic) => <div key={topic.id} className="card-elevated flex items-center justify-between px-4 py-3"><span className="font-medium" style={{ color: "var(--text-primary)" }}>{topic.name}</span><button onClick={() => deleteTopicMut.mutate(topic.id)} className="rounded-lg px-2.5 py-1 text-xs font-medium" style={{ color: "var(--error)", backgroundColor: "rgba(248, 113, 113, 0.1)" }}>Remove</button></div>)}</div>
      </div>
    </div>
  );
}
