const BASE = "/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Config
export const getConfig = () => request<Config>("/config");
export const updateConfig = (data: ConfigUpdate) =>
  request<Config>("/config", { method: "PUT", body: JSON.stringify(data) });

// MCP Servers
export const listMcpServers = () => request<McpServer[]>("/mcp-servers");
export const createMcpServer = (data: McpServerCreate) =>
  request<McpServer>("/mcp-servers", { method: "POST", body: JSON.stringify(data) });
export const updateMcpServer = (id: string, data: Partial<McpServerCreate>) =>
  request<McpServer>(`/mcp-servers/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteMcpServer = (id: string) =>
  request<void>(`/mcp-servers/${id}`, { method: "DELETE" });
export const testMcpServer = (id: string) =>
  request<McpTestResult>(`/mcp-servers/${id}/test`, { method: "POST" });

// SIM pairing
export const listSimPairingGroups = () => request<SimPairingGroup[]>("/sim-pairing/groups");
export const createSimPairingGroup = (data: SimPairingGroupCreate) =>
  request<SimPairingGroup>("/sim-pairing/groups", { method: "POST", body: JSON.stringify(data) });
export const deleteSimPairingGroup = (id: string) =>
  request<void>(`/sim-pairing/groups/${id}`, { method: "DELETE" });
export const listSimPairingTopics = () => request<SimPairingTopic[]>("/sim-pairing/topics");
export const createSimPairingTopic = (data: SimPairingTopicCreate) =>
  request<SimPairingTopic>("/sim-pairing/topics", { method: "POST", body: JSON.stringify(data) });
export const deleteSimPairingTopic = (id: string) => request<void>(`/sim-pairing/topics/${id}`, { method: "DELETE" });
export const listSimPairs = (params?: { status?: "active" | "archived"; limit?: number; offset?: number }) => {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));
  const qs = query.toString();
  return request<SimPair[]>(`/sim-pairing/pairs${qs ? `?${qs}` : ""}`);
};
export const getSimPairsCount = () => request<SimPairCount>("/sim-pairing/pairs/count");
export const listSimPairHistory = (id: string) => request<SimPairHistory[]>(`/sim-pairing/pairs/${id}/history`);
export const listSimPairMessages = (id: string) => request<SimPairMessage[]>(`/sim-pairing/pairs/${id}/messages`);
export const listSimPairMessageQueue = () => request<SimPairMessageQueue[]>("/sim-pairing/queue");
export const getSimPairQueueStats = () => request<SimPairQueueStats>("/sim-pairing/queue/stats");
export const syncSimPairs = () => request<SimPairingRun>("/sim-pairing/sync", { method: "POST" });
export const runSimPairConversations = () => request<SimPairConversationRun>("/sim-pairing/conversations/run", { method: "POST" });
export const previewSimPairConversation = () => request<SimPairConversationRun>("/sim-pairing/conversations/preview", { method: "POST" });
export const runSimPairCalls = () => request<SimPairCallRun>("/sim-pairing/calls/run", { method: "POST" });

// SMS auto-reply
export const listSmsReplies = () => request<SmsReply[]>("/sms-autoreply/replies");
export const getSmsAutoReplyStats = () => request<SmsAutoReplyStats>("/sms-autoreply/stats");
export const runSmsAutoReply = () => request<SmsAutoReplyRun>("/sms-autoreply/run", { method: "POST" });
export const previewSmsAutoReply = () => request<SmsAutoReplyRun>("/sms-autoreply/preview", { method: "POST" });

// Prompts
export const listPrompts = () => request<Prompt[]>("/prompts");
export const createPrompt = (data: PromptCreate) =>
  request<Prompt>("/prompts", { method: "POST", body: JSON.stringify(data) });
export const getPrompt = (id: string) => request<Prompt>(`/prompts/${id}`);
export const updatePrompt = (id: string, data: Partial<PromptCreate>) =>
  request<Prompt>(`/prompts/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deletePrompt = (id: string) =>
  request<void>(`/prompts/${id}`, { method: "DELETE" });
export const togglePrompt = (id: string) =>
  request<Prompt>(`/prompts/${id}/toggle`, { method: "PUT" });
export const regenerateScript = (id: string) =>
  request<Script>(`/prompts/${id}/regenerate`, { method: "POST" });

// Agents
export const listAgents = (status?: AgentStatus) =>
  request<Agent[]>(`/agents${status ? `?status=${status}` : ""}`);
export const createAgent = (data: AgentCreate) =>
  request<Agent>("/agents", { method: "POST", body: JSON.stringify(data) });
export const updateAgent = (id: string, data: AgentUpdate) =>
  request<Agent>(`/agents/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteAgent = (id: string) =>
  request<void>(`/agents/${id}`, { method: "DELETE" });
export const setAgentStatus = (id: string, status: AgentStatus) =>
  request<Agent>(`/agents/${id}/status`, { method: "PUT", body: JSON.stringify({ status }) });

// Scripts
export const listScripts = (promptId: string) =>
  request<Script[]>(`/prompts/${promptId}/scripts`);
export const getScript = (id: string) => request<Script>(`/scripts/${id}`);
export const runScript = (id: string) =>
  request<Execution>(`/scripts/${id}/run`, { method: "POST" });

// Executions
export const listExecutions = (params?: { status?: string; limit?: number; offset?: number }) => {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));
  return request<Execution[]>(`/executions?${query}`);
};
export const getExecution = (id: string) => request<Execution>(`/executions/${id}`);
export const listPromptExecutions = (promptId: string) =>
  request<Execution[]>(`/prompts/${promptId}/executions`);

// Stress Tests
export const listStressTests = () => request<StressTest[]>("/stress-tests");
export const createStressTest = (data: StressTestCreate) =>
  request<StressTest>("/stress-tests", { method: "POST", body: JSON.stringify(data) });
export const getStressTest = (id: string) => request<StressTest>(`/stress-tests/${id}`);
export const deleteStressTest = (id: string) =>
  request<void>(`/stress-tests/${id}`, { method: "DELETE" });
export const stopStressTest = (id: string) =>
  request<StressTest>(`/stress-tests/${id}/stop`, { method: "POST" });
export const getStressMetrics = (id: string) =>
  request<StressTestMetrics[]>(`/stress-tests/${id}/metrics`);
export const getStressMetricsLatest = (id: string) =>
  request<StressTestMetrics | null>(`/stress-tests/${id}/metrics/latest`);
export const compareStressTests = (testIds: string[]) =>
  request<StressTest[]>("/stress-tests/compare", { method: "POST", body: JSON.stringify({ test_ids: testIds }) });
export const listScenarios = () => request<ScenarioInfo[]>("/stress-tests/scenarios");

// Types
export interface Config {
  id: string;
  llm_provider: string;
  llm_model: string;
  api_key_set: boolean;
  updated_at: string;
  google_sa_key_set: boolean;
  google_sa_email: string | null;
  drive_folder_id: string;
  activity_cron: string;
  pairing_openrouter_api_key_set: boolean;
  pairing_openrouter_model: string;
  pairing_conversation_enabled: boolean;
  pairing_conversation_interval_minutes: number;
  pairing_target_messages: number;
  pairing_max_messages_per_run: number;
  pairing_sim_cooldown_minutes: number;
  pairing_quiet_hours_enabled: boolean;
  pairing_quiet_start_hour: number;
  pairing_quiet_end_hour: number;
  sms_autoreply_enabled: boolean;
  sms_autoreply_template: string;
  sms_autoreply_max_per_run: number;
  sms_autoreply_lookback_minutes: number;
  sms_autoreply_recipient_cooldown_hours: number;
  pairing_call_enabled: boolean;
  pairing_call_interval_minutes: number;
  pairing_call_min_seconds: number;
  pairing_call_max_seconds: number;
  pairing_call_max_per_run: number;
}
export interface ConfigUpdate {
  llm_provider?: string;
  llm_model?: string;
  api_key?: string;
  google_sa_key?: string;
  drive_folder_id?: string;
  activity_cron?: string;
  pairing_openrouter_api_key?: string;
  pairing_openrouter_model?: string;
  pairing_conversation_enabled?: boolean;
  pairing_conversation_interval_minutes?: number;
  pairing_target_messages?: number;
  pairing_max_messages_per_run?: number;
  pairing_sim_cooldown_minutes?: number;
  pairing_quiet_hours_enabled?: boolean;
  pairing_quiet_start_hour?: number;
  pairing_quiet_end_hour?: number;
  sms_autoreply_enabled?: boolean;
  sms_autoreply_template?: string;
  sms_autoreply_max_per_run?: number;
  sms_autoreply_lookback_minutes?: number;
  sms_autoreply_recipient_cooldown_hours?: number;
  pairing_call_enabled?: boolean;
  pairing_call_interval_minutes?: number;
  pairing_call_min_seconds?: number;
  pairing_call_max_seconds?: number;
  pairing_call_max_per_run?: number;
}
export interface McpServer {
  id: string;
  name: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  env: Record<string, string> | null;
  url: string | null;
  api_key_set: boolean;
  enabled: boolean;
  created_at: string;
}
export interface McpServerCreate {
  name: string;
  transport: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  api_key?: string;
  enabled?: boolean;
}
export interface McpToolInfo {
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
}
export interface McpTestResult {
  success: boolean;
  tools: McpToolInfo[];
  error: string | null;
}
export interface SimPairingGroup {
  id: string;
  name: string;
  enabled: boolean;
  created_at: string;
}
export interface SimPairingGroupCreate {
  name: string;
}
export interface SimPairingTopic { id: string; name: string; created_at: string; }
export interface SimPairingTopicCreate { name: string; }
export interface SimPair { id: string; sim_a_id: number; sim_b_id: number; sim_a_name: string; sim_b_name: string; country: string; group_a: string; group_b: string; topic: string; target_messages: number; sent_count: number; status: string; archived_reason: string | null; created_at: string; archived_at: string | null; }
export interface SimPairHistory { id: string; pair_id: string; event: string; details: Record<string, unknown> | null; created_at: string; }
export interface SimPairingRun { id: string; status: string; summary: Record<string, number> | null; error: string | null; started_at: string; completed_at: string | null; }
export interface SimPairMessage { id: string; pair_id: string; from_sim_id: number; to_sim_id: number; content: string; provider: string; model: string; status: string; error: string | null; sent_at: string | null; created_at: string; }
export interface SimPairMessageQueue { id: string; pair_id: string; status: string; due_at: string; attempts: number; last_error: string | null; sent_at: string | null; created_at: string; }
export interface SimPairQueueStats { pending: number; overdue: number; failed: number; pairs_under_target: number; }
export interface SimPairCount { active: number; archived: number; }
export interface SimPairConversationRun { sent: number; skipped: number; failed: number; held?: number; active_pairs?: number; queued?: number; overdue?: number; pairs_under_target?: number; reason?: string; previews?: { pair_id: string; from_sim_id: number; to_sim_id: number; content: string }[]; }
export interface SmsReply { id: string; trigger_kind: string; trigger_ref: string; sim_id: number; to_number: string; whatsapp_number: string | null; content: string; status: string; error: string | null; sent_at: string | null; created_at: string; }
export interface SmsAutoReplyStats { sent: number; failed: number; skipped: number; sending: number; last_sent_at: string | null; }
export interface SmsAutoReplyPreview { kind: string; to_number: string; whatsapp: string | null; content: string | null; skip_reason: string | null; }
export interface SmsAutoReplyRun { sent: number; skipped: number; failed: number; reason?: string; previews?: SmsAutoReplyPreview[]; }
export interface Prompt {
export interface SimPairCallRun { started: number; skipped: number; failed: number; reason?: string; }
  id: string;
  name: string;
  description: string | null;
  prompt_text: string;
  cron_expr: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  latest_script_version: number | null;
  needs_llm: boolean | null;
}
export interface PromptCreate {
  name: string;
  description?: string;
  prompt_text: string;
  cron_expr?: string;
  enabled?: boolean;
  mcp_server_ids: string[];
}
export type AgentStatus = "draft" | "active" | "paused" | "archived";
export interface AgentServerRef {
  id: string;
  name: string;
  enabled: boolean;
}
export interface Agent {
  id: string;
  name: string;
  objective: string;
  instructions: string;
  description: string | null;
  status: AgentStatus;
  max_steps: number;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
  mcp_servers: AgentServerRef[];
}
export interface AgentCreate {
  name: string;
  objective: string;
  instructions?: string;
  description?: string;
  max_steps?: number;
  timeout_seconds?: number;
  mcp_server_ids: string[];
}
export type AgentUpdate = Partial<AgentCreate>;
export interface Script {
  id: string;
  prompt_id: string;
  version: number;
  code: string;
  needs_llm: boolean;
  llm_steps: Record<string, unknown> | null;
  created_at: string;
}
export interface Execution {
  id: string;
  script_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  output: string | null;
  llm_output: string | null;
  tokens_used: number;
  error: string | null;
  duration_ms: number | null;
  prompt_name: string | null;
  script_version: number | null;
}

// Stress Tests
export interface StressTestMetrics {
  id: string;
  stress_test_id: string;
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  asr_percent: number;
  pdd_avg_ms: number;
  pdd_p95_ms: number;
  setup_time_avg_ms: number;
  cps_achieved: number;
  retransmissions: number;
  failed_by_code: Record<string, number> | null;
  packets_sent: number;
  packets_received: number;
  packet_loss_pct: number;
  jitter_avg_ms: number;
  jitter_max_ms: number;
  rtt_avg_ms: number;
  rtt_max_ms: number;
  mos_score: number;
  out_of_order: number;
  throughput_kbps: number;
  duration_seconds: number;
  max_concurrent: number;
  ramp_up_curve: Record<string, unknown>[] | null;
  collected_at: string;
}

export interface StressTest {
  id: string;
  name: string;
  scenario: string;
  target_host: string;
  target_port: number;
  transport: string;
  cps: number;
  max_calls: number;
  duration: number;
  call_duration: number;
  ramp_up: number;
  ramp_step: number;
  caller_id: string;
  media_type: string;
  status: string;
  remote_test_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  latest_metrics: StressTestMetrics | null;
}

export interface StressTestCreate {
  name: string;
  scenario?: string;
  target_host: string;
  target_port?: number;
  transport?: string;
  cps?: number;
  max_calls?: number;
  duration?: number;
  call_duration?: number;
  ramp_up?: number;
  ramp_step?: number;
  caller_id?: string;
  media_type?: string;
}

export interface ScenarioInfo {
  name: string;
  description: string;
  type: string;
}

// Chat
export const listConversations = () => request<Conversation[]>("/chat/conversations");
export const createConversation = () =>
  request<Conversation>("/chat/conversations", { method: "POST" });
export const deleteConversation = (id: string) =>
  request<void>(`/chat/conversations/${id}`, { method: "DELETE" });
export const listMessages = (conversationId: string) =>
  request<ChatMessageData[]>(`/chat/conversations/${conversationId}/messages`);
export const sendMessageSSE = async (conversationId: string, content: string): Promise<Response> => {
  const res = await fetch(`${BASE}/chat/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
  return res;
};
export const runScriptInChat = (conversationId: string, code: string) =>
  request<{ status: string; output: string | null; error: string | null; duration_ms: number | null }>(
    `/chat/conversations/${conversationId}/run-script`,
    { method: "POST", body: JSON.stringify({ code }) }
  );

// Chat types
export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
export interface ChatMessageData {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls: Array<{ name: string; args: Record<string, unknown>; result: string }> | null;
  created_at: string;
}
export interface SSEEvent {
  event: "text" | "tool_call" | "tool_result" | "script" | "done" | "error";
  data: Record<string, unknown>;
}

export function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";

  return reader.read().then(function process({ done, value }): Promise<void> {
    if (done) return Promise.resolve();
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ event: currentEvent as SSEEvent["event"], data });
        } catch { /* skip malformed */ }
        currentEvent = "";
      }
    }

    return reader.read().then(process);
  });
}

// Activity
export interface ActivityDocument {
  id: string;
  name: string;
  mime_type: string;
  web_url: string;
  section: string | null;
  last_modified_at: string | null;
  last_author: string | null;
  line_count: number | null;
  is_present: boolean;
  last_error: string | null;
  last_activity_day: string | null;
  last_added: number;
  last_removed: number;
}

export interface ActivitySection {
  name: string;
  documents: ActivityDocument[];
}

export interface HeatmapDay {
  day: string;
  added: number;
  removed: number;
  total: number;
}

export interface Heatmap {
  days: HeatmapDay[];
  total_changes: number;
  last_scan_at: string | null;
}

export const listActivityDocuments = () => request<ActivitySection[]>("/activity/documents");
export const getHeatmap = () => request<Heatmap>("/activity/heatmap");
export const scanActivity = () =>
  request<{ walked: number }>("/activity/scan", { method: "POST" });
