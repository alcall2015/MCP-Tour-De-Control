import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "../../lib/api";

export function LlmConfig() {
  const queryClient = useQueryClient();
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const mutation = useMutation({
    mutationFn: updateConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setApiKey("");
    },
  });

  const handleSave = () => {
    mutation.mutate({
      llm_provider: provider || undefined,
      llm_model: model || undefined,
      api_key: apiKey || undefined,
    });
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6">
      <h3 className="mb-4 text-lg font-semibold">LLM Configuration</h3>
      <div className="grid gap-4">
        <div>
          <label className="mb-1 block text-sm text-zinc-400">Provider</label>
          <select
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            value={provider || config?.llm_provider || ""}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm text-zinc-400">Model</label>
          <input
            type="text"
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            placeholder={config?.llm_model || "gpt-4"}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-zinc-400">
            API Key {config?.api_key_set && <span className="text-green-500">(set)</span>}
          </label>
          <input
            type="password"
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            placeholder="sk-..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <button
          onClick={handleSave}
          disabled={mutation.isPending}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
