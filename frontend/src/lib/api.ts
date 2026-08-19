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
  projects_cron: string;
}
export interface ConfigUpdate {
  llm_provider?: string;
  llm_model?: string;
  api_key?: string;
  google_sa_key?: string;
  projects_cron?: string;
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
export interface Prompt {
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

// Projects
export type ProjectStatusLevel = "critical" | "attention" | "nominal" | "unknown";

export interface ProjectStatus {
  level: ProjectStatusLevel;
  reason: string;
}

export interface ProjectLink {
  id: string;
  label: string;
  url: string;
  kind: "doc" | "sheet" | "slide" | "drive" | "other";
  is_kpi_source: boolean;
  position: number;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  position: number;
  stale_days: number;
  budget_warn_pct: number;
  links: ProjectLink[];
  status: ProjectStatus;
  metrics: Record<string, number | string> | null;
  trends: Record<string, number>;
  sparkline: number[];
  captured_at: string | null;
  source_modified_at: string | null;
  error: string | null;
}

export interface ProjectSnapshot {
  captured_at: string;
  metrics: Record<string, number | string> | null;
  error: string | null;
}

export interface ProjectDetail extends Project {
  history: ProjectSnapshot[];
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  position?: number;
  stale_days?: number;
  budget_warn_pct?: number;
}

export interface ProjectLinkCreate {
  label: string;
  url: string;
  is_kpi_source?: boolean;
  position?: number;
}

export interface PendingDecision {
  project_id: string;
  project_name: string;
  decision: string;
}

export interface BudgetSummary {
  consumed: number;
  total: number;
  remaining: number;
  projects_counted: number;
}

export const listProjects = () => request<Project[]>("/projects");
export const getProject = (id: string) => request<ProjectDetail>(`/projects/${id}`);
export const createProject = (data: ProjectCreate) =>
  request<Project>("/projects", { method: "POST", body: JSON.stringify(data) });
export const updateProject = (id: string, data: Partial<ProjectCreate>) =>
  request<Project>(`/projects/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteProject = (id: string) =>
  request<void>(`/projects/${id}`, { method: "DELETE" });
export const addProjectLink = (projectId: string, data: ProjectLinkCreate) =>
  request<ProjectLink>(`/projects/${projectId}/links`, { method: "POST", body: JSON.stringify(data) });
export const updateProjectLink = (linkId: string, data: Partial<ProjectLinkCreate>) =>
  request<ProjectLink>(`/projects/links/${linkId}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteProjectLink = (linkId: string) =>
  request<void>(`/projects/links/${linkId}`, { method: "DELETE" });
export const refreshProjects = () =>
  request<{ refreshed: number }>("/projects/refresh", { method: "POST" });
export const refreshProject = (id: string) =>
  request<{ refreshed: number }>(`/projects/${id}/refresh`, { method: "POST" });
export const listDecisions = () => request<PendingDecision[]>("/projects/decisions");
export const getBudgetSummary = () => request<BudgetSummary>("/projects/summary");

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
