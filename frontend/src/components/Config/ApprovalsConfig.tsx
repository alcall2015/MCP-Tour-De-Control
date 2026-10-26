import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, listMcpServers, updateConfig } from "../../lib/api";
import type { ConfigUpdate } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { Spinner } from "../ui/Spinner";

const labelClass = "mb-1.5 block text-xs font-medium uppercase tracking-wider";
const muted = { color: "var(--text-muted)" } as const;
const VARIABLES = "{agent} {tool} {server} {args} {code} {expires} {link}";
const KNOWN_PLACEHOLDERS = ["agent", "tool", "server", "args", "code", "expires", "link"];

export function ApprovalsConfig() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });
  const [draft, setDraft] = useState<ConfigUpdate>({});
  const set = <K extends keyof ConfigUpdate>(key: K, value: ConfigUpdate[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = Object.keys(draft).length > 0;

  const mutation = useMutation({
    mutationFn: () => updateConfig(draft),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["config"] }); setDraft({}); },
  });

  if (isLoading || !config) return <div className="card p-6"><div className="flex justify-center py-8"><Spinner /></div></div>;

  const enabled = draft.approval_whatsapp_enabled ?? config.approval_whatsapp_enabled;
  const template = draft.approval_whatsapp_template ?? config.approval_whatsapp_template;
  const hours = draft.approval_expiry_hours ?? config.approval_expiry_hours;
  const number = draft.approval_whatsapp_number ?? config.approval_whatsapp_number;
  const whatsappServers = servers.filter((s) => s.enabled);
  const numberValid = /^\+?\d{8,15}$/.test(number);
  const hoursValid = Number.isInteger(hours) && hours >= 1 && hours <= 168;
  const unknownPlaceholders = [...template.matchAll(/\{([a-zA-Z_]+)\}/g)]
    .map((m) => m[1])
    .filter((name) => !KNOWN_PLACEHOLDERS.includes(name));
  const hasCode = template.includes("{code}");
  const templateValid = hasCode && unknownPlaceholders.length === 0;

  const configuredServerId = config.approval_whatsapp_server_id;
  const configuredServerMissing = Boolean(configuredServerId) && !whatsappServers.some((s) => s.id === configuredServerId);
  const configuredServerName = configuredServerMissing
    ? (servers.find((s) => s.id === configuredServerId)?.name ?? configuredServerId)
    : null;

  return (
    <div className="card p-6">
      <h3 className="mb-1 text-base font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>Approvals</h3>
      <p className="mb-1 text-xs" style={muted}>Tool calls above an agent's ceiling park the task until an operator approves them here or by WhatsApp.</p>
      <p className="mb-5 text-xs" style={muted}>Every discovered tool starts at R2 and an agent's ceiling defaults to R1, so an unclassified server asks before every call. Classify tools under Settings → MCP servers → Tools.</p>

      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass} style={muted}>Expiry (hours)</label>
            <input type="number" min={1} max={168} className="input-field" value={hours} onChange={(e) => set("approval_expiry_hours", Number(e.target.value))} />
            <p className="mt-1 text-xs" style={muted}>1 to 168. An undecided approval expires and the task fails.</p>
          </div>
          <div>
            <label className={labelClass} style={muted}>Admin WhatsApp number</label>
            <input className="input-field" placeholder="+2250700003331" value={number} onChange={(e) => set("approval_whatsapp_number", e.target.value.replace(/[\s.-]/g, ""))} />
            <p className="mt-1 text-xs" style={{ color: numberValid ? "var(--text-muted)" : "var(--error)" }}>
              {numberValid ? "Digits with an optional leading +. Replies come from this chat." : "Digits only, 8 to 15, optional leading +."}
            </p>
          </div>
        </div>

        <label className="flex items-start gap-2.5 text-sm cursor-pointer" style={{ color: "var(--text-primary)" }}>
          <input type="checkbox" className="mt-0.5" checked={enabled} onChange={(e) => set("approval_whatsapp_enabled", e.target.checked)} />
          <span>
            <span>Notify on WhatsApp and accept replies</span>
            <span className="block text-xs" style={muted}>
              Sends "OUI/NON code" instructions to the number above and polls the chat every minute. Anyone who can write in that chat can decide: keep it to yourself.
            </span>
          </span>
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass} style={muted}>WhatsApp MCP server</label>
            <select className="input-field" value={draft.approval_whatsapp_server_id === undefined ? (config.approval_whatsapp_server_id ?? "") : (draft.approval_whatsapp_server_id ?? "")} onChange={(e) => set("approval_whatsapp_server_id", e.target.value || null)}>
              <option value="">Auto (first enabled server named "whatsapp")</option>
              {whatsappServers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              {configuredServerMissing && <option value={configuredServerId ?? ""}>{configuredServerName} (disabled)</option>}
            </select>
          </div>
          <div>
            <label className={labelClass} style={muted}>WhatsApp session id</label>
            <input className="input-field" placeholder="Auto (first ready session)" value={draft.approval_whatsapp_session_id === undefined ? (config.approval_whatsapp_session_id ?? "") : (draft.approval_whatsapp_session_id ?? "")} onChange={(e) => set("approval_whatsapp_session_id", e.target.value || null)} />
          </div>
        </div>

        <div>
          <label className={labelClass} style={muted}>Message template</label>
          <textarea rows={5} className="input-field font-mono" value={template} onChange={(e) => set("approval_whatsapp_template", e.target.value)} />
          <p className="mt-1 text-xs" style={{ color: templateValid ? "var(--text-muted)" : "var(--error)" }}>
            Variables: <code className="font-mono">{VARIABLES}</code>. {!hasCode
              ? "The template must contain {code}."
              : unknownPlaceholders.length > 0
                ? `Unknown placeholder: ${unknownPlaceholders.map((n) => `{${n}}`).join(", ")}`
                : ""}
          </p>
        </div>

        <MutationError error={mutation.error} />
        <button className="btn-primary" disabled={!dirty || !templateValid || !hoursValid || !numberValid || mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
