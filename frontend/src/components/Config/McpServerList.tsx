import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listMcpServers,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  testMcpServer,
} from "../../lib/api";
import type { McpServerCreate, McpTestResult } from "../../lib/api";
import { McpServerForm } from "./McpServerForm";
import { McpToolsPreview } from "./McpToolsPreview";
import { Spinner } from "../ui/Spinner";

export function McpServerList() {
  const queryClient = useQueryClient();
  const { data: servers = [], isLoading } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: listMcpServers,
  });
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, McpTestResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: createMcpServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<McpServerCreate> }) =>
      updateMcpServer(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      setEditingId(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteMcpServer,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcp-servers"] }),
  });

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const result = await testMcpServer(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="card p-6">
      <div className="mb-5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span style={{ color: "var(--running)", fontSize: "1.1rem" }}>⬡</span>
          <h3
            className="text-base font-semibold"
            style={{
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              color: "var(--text-primary)",
            }}
          >
            MCP Servers
          </h3>
        </div>
        <button onClick={() => setShowForm(true)} className="btn-primary text-xs px-3 py-1.5">
          + Add Server
        </button>
      </div>

      {showForm && (
        <div className="mb-5">
          <McpServerForm
            onSubmit={(data) => createMut.mutate(data)}
            onCancel={() => setShowForm(false)}
          />
        </div>
      )}

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-3">
          {servers.map((server) => (
            <div
              key={server.id}
              className="card-elevated p-4"
            >
              {editingId === server.id ? (
                <McpServerForm
                  initial={{
                    name: server.name,
                    transport: server.transport,
                    command: server.command ?? undefined,
                    args: server.args ?? undefined,
                    url: server.url ?? undefined,
                    api_key_set: server.api_key_set,
                    enabled: server.enabled,
                  }}
                  onSubmit={(data) => updateMut.mutate({ id: server.id, data })}
                  onCancel={() => setEditingId(null)}
                />
              ) : (
                <>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={`h-2 w-2 flex-shrink-0 rounded-full ${server.enabled ? "pulse-dot" : ""}`}
                        style={{
                          backgroundColor: server.enabled
                            ? "var(--success)"
                            : "var(--text-muted)",
                        }}
                      />
                      <span
                        className="font-medium"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {server.name}
                      </span>
                      <span
                        className="badge font-mono"
                        style={{
                          backgroundColor: "rgba(96, 165, 250, 0.1)",
                          color: "var(--running)",
                          border: "1px solid rgba(96, 165, 250, 0.2)",
                        }}
                      >
                        {server.transport}
                      </span>
                      {server.api_key_set && (
                        <span
                          className="badge font-mono"
                          style={{
                            backgroundColor: "rgba(226, 179, 64, 0.1)",
                            color: "var(--accent)",
                            border: "1px solid rgba(226, 179, 64, 0.2)",
                          }}
                        >
                          key
                        </span>
                      )}
                      <span
                        className="hidden text-xs font-mono sm:block truncate"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {server.transport === "stdio"
                          ? `${server.command} ${(server.args || []).join(" ")}`
                          : server.url}
                      </span>
                    </div>
                    <div className="flex gap-1.5 flex-shrink-0">
                      <button
                        onClick={() => handleTest(server.id)}
                        disabled={testingId === server.id}
                        className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                        style={{
                          backgroundColor: "rgba(96, 165, 250, 0.1)",
                          color: "var(--running)",
                          border: "1px solid rgba(96, 165, 250, 0.2)",
                        }}
                      >
                        {testingId === server.id ? "Testing..." : "Test"}
                      </button>
                      <button
                        onClick={() => setEditingId(server.id)}
                        className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150"
                        style={{
                          backgroundColor: "var(--bg-panel)",
                          color: "var(--text-secondary)",
                          border: "1px solid var(--border)",
                        }}
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Delete server "${server.name}"?`)) {
                            deleteMut.mutate(server.id);
                          }
                        }}
                        disabled={deleteMut.isPending}
                        className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                        style={{
                          backgroundColor: "rgba(248, 113, 113, 0.1)",
                          color: "var(--error)",
                          border: "1px solid rgba(248, 113, 113, 0.2)",
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>

                  {testResults[server.id] &&
                    (testResults[server.id].success ? (
                      <McpToolsPreview tools={testResults[server.id].tools} />
                    ) : (
                      <p
                        className="mt-2 rounded-lg px-3 py-2 text-xs"
                        style={{
                          color: "var(--error)",
                          backgroundColor: "rgba(248, 113, 113, 0.08)",
                          border: "1px solid rgba(248, 113, 113, 0.2)",
                        }}
                      >
                        {testResults[server.id].error}
                      </p>
                    ))}
                </>
              )}
            </div>
          ))}

          {servers.length === 0 && !showForm && (
            <div
              className="rounded-xl py-12 text-center"
              style={{
                border: "1px dashed var(--border)",
              }}
            >
              <div className="flex flex-col items-center gap-2">
                <span className="text-3xl">⬡</span>
                <p
                  className="text-sm font-medium"
                  style={{ color: "var(--text-secondary)" }}
                >
                  No MCP servers configured
                </p>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Add a server to give your prompts access to tools.
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
