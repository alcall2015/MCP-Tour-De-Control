import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "../../lib/api";
import { Spinner } from "../ui/Spinner";

const DEFAULT_MODELS: Record<string, { model: string; placeholder: string }> = {
  openai: { model: "gpt-4", placeholder: "sk-..." },
  anthropic: { model: "claude-sonnet-4-20250514", placeholder: "sk-ant-..." },
  google: { model: "gemini-2.0-flash", placeholder: "AIza..." },
};

export function LlmConfig() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });
  const [provider, setProvider] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");

  const activeProvider = provider ?? config?.llm_provider ?? "openai";

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider);
    // Auto-fill default model when switching provider
    if (newProvider !== (config?.llm_provider ?? "openai")) {
      setModel(DEFAULT_MODELS[newProvider]?.model ?? "");
    } else {
      setModel(null); // Reset to config value
    }
  };

  const mutation = useMutation({
    mutationFn: updateConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setApiKey("");
    },
  });

  const handleSave = () => {
    mutation.mutate({
      llm_provider: provider ?? config?.llm_provider ?? undefined,
      llm_model: model ?? config?.llm_model ?? undefined,
      api_key: apiKey || undefined,
    });
  };

  return (
    <div className="card p-6">
      <div className="mb-5 flex items-center gap-2">
        <span style={{ color: "var(--warning)", fontSize: "1.1rem" }}>⚙</span>
        <h3
          className="text-base font-semibold"
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            color: "var(--text-primary)",
          }}
        >
          LLM Configuration
        </h3>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="grid gap-4">
          <div>
            <label
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Provider
            </label>
            <select
              className="input-field"
              value={activeProvider}
              onChange={(e) => handleProviderChange(e.target.value)}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="google">Google Gemini</option>
            </select>
          </div>

          <div>
            <label
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Model
            </label>
            <input
              type="text"
              className="input-field font-mono"
              placeholder={DEFAULT_MODELS[activeProvider]?.model ?? "model name"}
              value={model ?? config?.llm_model ?? ""}
              onChange={(e) => setModel(e.target.value)}
            />
          </div>

          <div>
            <label
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              API Key{" "}
              {config?.api_key_set && (
                <span style={{ color: "var(--success)", textTransform: "none" }}>
                  (configured)
                </span>
              )}
            </label>
            <input
              type="password"
              className="input-field font-mono"
              placeholder={DEFAULT_MODELS[activeProvider]?.placeholder ?? "api key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>

          {mutation.isError && (
            <p
              className="text-xs rounded-lg px-3 py-2"
              style={{
                color: "var(--error)",
                backgroundColor: "rgba(248, 113, 113, 0.08)",
                border: "1px solid rgba(248, 113, 113, 0.2)",
              }}
            >
              {mutation.error?.message}
            </p>
          )}

          {mutation.isSuccess && (
            <p
              className="text-xs rounded-lg px-3 py-2"
              style={{
                color: "var(--success)",
                backgroundColor: "rgba(52, 211, 153, 0.08)",
                border: "1px solid rgba(52, 211, 153, 0.2)",
              }}
            >
              Configuration saved.
            </p>
          )}

          <button
            onClick={handleSave}
            disabled={mutation.isPending}
            className="btn-primary w-fit"
          >
            {mutation.isPending ? "Saving..." : "Save Configuration"}
          </button>
        </div>
      )}
    </div>
  );
}
