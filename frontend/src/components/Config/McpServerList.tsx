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

export function McpServerList() {
  const queryClient = useQueryClient();
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers });
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, McpTestResult>>({});

  const createMut = useMutation({
    mutationFn: createMcpServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<McpServerCreate> }) => updateMcpServer(id, data),
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
    const result = await testMcpServer(id);
    setTestResults((prev) => ({ ...prev, [id]: result }));
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">MCP Servers</h3>
        <button
          onClick={() => setShowForm(true)}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          + Add
        </button>
      </div>

      {showForm && (
        <div className="mb-4">
          <McpServerForm onSubmit={(data) => createMut.mutate(data)} onCancel={() => setShowForm(false)} />
        </div>
      )}

      <div className="space-y-3">
        {servers.map((server) => (
          <div key={server.id} className="rounded border border-zinc-700 bg-zinc-800 p-4">
            {editingId === server.id ? (
              <McpServerForm
                initial={{
                  name: server.name,
                  transport: server.transport,
                  command: server.command ?? undefined,
                  args: server.args ?? undefined,
                  url: server.url ?? undefined,
                  enabled: server.enabled,
                }}
                onSubmit={(data) => updateMut.mutate({ id: server.id, data })}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`h-2 w-2 rounded-full ${server.enabled ? "bg-green-500" : "bg-zinc-500"}`} />
                    <span className="font-medium">{server.name}</span>
                    <span className="text-xs text-zinc-500">{server.transport}</span>
                    <span className="text-xs text-zinc-500">
                      {server.transport === "stdio" ? `${server.command} ${(server.args || []).join(" ")}` : server.url}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleTest(server.id)} className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600">
                      Test
                    </button>
                    <button onClick={() => setEditingId(server.id)} className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600">
                      Edit
                    </button>
                    <button onClick={() => deleteMut.mutate(server.id)} className="rounded bg-red-900 px-2 py-1 text-xs text-white hover:bg-red-800">
                      Delete
                    </button>
                  </div>
                </div>
                {testResults[server.id] && (
                  testResults[server.id].success ? (
                    <McpToolsPreview tools={testResults[server.id].tools} />
                  ) : (
                    <p className="mt-2 text-sm text-red-400">{testResults[server.id].error}</p>
                  )
                )}
              </>
            )}
          </div>
        ))}
        {servers.length === 0 && !showForm && (
          <p className="text-sm text-zinc-500">No MCP servers configured yet.</p>
        )}
      </div>
    </div>
  );
}
