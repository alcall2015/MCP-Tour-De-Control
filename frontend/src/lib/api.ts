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

// Types
export interface Config {
  id: string;
  llm_provider: string;
  llm_model: string;
  api_key_set: boolean;
  updated_at: string;
}
export interface ConfigUpdate {
  llm_provider?: string;
  llm_model?: string;
  api_key?: string;
}
export interface McpServer {
  id: string;
  name: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  env: Record<string, string> | null;
  url: string | null;
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
