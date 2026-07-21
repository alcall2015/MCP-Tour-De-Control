import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listPrompts,
  togglePrompt,
  deletePrompt,
  regenerateScript,
  listScripts,
  runScript,
} from "../../lib/api";
import type { Prompt, Script } from "../../lib/api";
import { ScriptPreview } from "./ScriptPreview";
import { Spinner } from "../ui/Spinner";
import cronstrue from "cronstrue/i18n";

export function PromptList() {
  const queryClient = useQueryClient();
  const { data: prompts = [], isLoading } = useQuery({
    queryKey: ["prompts"],
    queryFn: listPrompts,
  });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [scripts, setScripts] = useState<Record<string, Script[]>>({});
  const [loadingScripts, setLoadingScripts] = useState<Record<string, boolean>>({});

  const toggleMut = useMutation({
    mutationFn: togglePrompt,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const deleteMut = useMutation({
    mutationFn: deletePrompt,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const regenMut = useMutation({
    mutationFn: regenerateScript,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const handleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!scripts[id]) {
      setLoadingScripts((prev) => ({ ...prev, [id]: true }));
      try {
        const s = await listScripts(id);
        setScripts((prev) => ({ ...prev, [id]: s }));
      } finally {
        setLoadingScripts((prev) => ({ ...prev, [id]: false }));
      }
    }
  };

  const handleRun = async (prompt: Prompt) => {
    let s = scripts[prompt.id];
    if (!s) {
      s = await listScripts(prompt.id);
      setScripts((prev) => ({ ...prev, [prompt.id]: s }));
    }
    if (s.length > 0) {
      await runScript(s[0].id);
      queryClient.invalidateQueries({ queryKey: ["executions"] });
    }
  };

  const cronLabel = (expr: string | null) => {
    if (!expr) return "No schedule";
    try {
      return cronstrue.toString(expr, { locale: "en" });
    } catch {
      return expr;
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }

  if (prompts.length === 0) {
    return (
      <div
        className="rounded-xl py-16 text-center"
        style={{
          backgroundColor: "var(--bg-panel)",
          border: "1px dashed var(--border)",
        }}
      >
        <div className="flex flex-col items-center gap-3">
          <span className="text-4xl">⚡</span>
          <p
            className="text-base font-medium"
            style={{
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              color: "var(--text-primary)",
            }}
          >
            No prompts yet
          </p>
          <p className="text-sm max-w-xs mx-auto" style={{ color: "var(--text-muted)" }}>
            Create your first prompt to start automating tasks with your MCP servers.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {prompts.map((prompt) => (
        <div
          key={prompt.id}
          className="card transition-all duration-200"
        >
          {/* Card header row */}
          <div
            className="flex cursor-pointer items-center justify-between p-4"
            onClick={() => handleExpand(prompt.id)}
          >
            <div className="flex items-center gap-3 min-w-0">
              {/* Status dot */}
              <span
                className={`h-2 w-2 flex-shrink-0 rounded-full ${prompt.enabled ? "pulse-dot" : ""}`}
                style={{
                  backgroundColor: prompt.enabled ? "var(--success)" : "var(--text-muted)",
                }}
              />

              {/* Name */}
              <span
                className="font-semibold truncate"
                style={{
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  color: "var(--text-primary)",
                  fontSize: "0.9375rem",
                }}
              >
                {prompt.name}
              </span>

              {/* Version */}
              {prompt.latest_script_version !== null && (
                <span
                  className="font-mono text-xs flex-shrink-0"
                  style={{ color: "var(--text-muted)" }}
                >
                  v{prompt.latest_script_version}
                </span>
              )}

              {/* LLM badge */}
              {prompt.needs_llm !== null && (
                <span
                  className="badge flex-shrink-0"
                  style={
                    prompt.needs_llm
                      ? {
                          backgroundColor: "rgba(251, 191, 36, 0.12)",
                          color: "var(--warning)",
                          border: "1px solid rgba(251, 191, 36, 0.25)",
                        }
                      : {
                          backgroundColor: "rgba(52, 211, 153, 0.1)",
                          color: "var(--success)",
                          border: "1px solid rgba(52, 211, 153, 0.2)",
                        }
                  }
                >
                  {prompt.needs_llm ? "LLM" : "No LLM"}
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 flex-shrink-0">
              {/* Cron label */}
              <span
                className="hidden text-xs sm:block"
                style={{ color: "var(--text-muted)" }}
              >
                {cronLabel(prompt.cron_expr)}
              </span>

              {/* Action buttons */}
              <div
                className="flex gap-1.5"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => handleRun(prompt)}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150"
                  style={{
                    backgroundColor: "rgba(226, 179, 64, 0.12)",
                    color: "var(--accent)",
                    border: "1px solid rgba(226, 179, 64, 0.2)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                      "rgba(226, 179, 64, 0.2)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                      "rgba(226, 179, 64, 0.12)";
                  }}
                >
                  ▶ Run
                </button>
                <button
                  onClick={() => regenMut.mutate(prompt.id)}
                  disabled={regenMut.isPending}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                  style={{
                    backgroundColor: "var(--bg-elevated)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                  onMouseEnter={(e) => {
                    if (!regenMut.isPending)
                      (e.currentTarget as HTMLButtonElement).style.color =
                        "var(--text-primary)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.color =
                      "var(--text-secondary)";
                  }}
                >
                  ↻ Regen
                </button>
                <button
                  onClick={() => toggleMut.mutate(prompt.id)}
                  disabled={toggleMut.isPending}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                  style={{
                    backgroundColor: "var(--bg-elevated)",
                    color: prompt.enabled ? "var(--success)" : "var(--text-muted)",
                    border: `1px solid ${prompt.enabled ? "rgba(52, 211, 153, 0.2)" : "var(--border)"}`,
                  }}
                >
                  {prompt.enabled ? "Disable" : "Enable"}
                </button>
                <button
                  onClick={() => {
                    if (confirm(`Delete prompt "${prompt.name}"?`)) {
                      deleteMut.mutate(prompt.id);
                    }
                  }}
                  disabled={deleteMut.isPending}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium transition-all duration-150 disabled:opacity-50"
                  style={{
                    backgroundColor: "rgba(248, 113, 113, 0.1)",
                    color: "var(--error)",
                    border: "1px solid rgba(248, 113, 113, 0.2)",
                  }}
                  onMouseEnter={(e) => {
                    if (!deleteMut.isPending)
                      (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                        "rgba(248, 113, 113, 0.2)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                      "rgba(248, 113, 113, 0.1)";
                  }}
                >
                  Delete
                </button>
              </div>

              {/* Expand chevron */}
              <span
                className="text-xs transition-transform duration-200"
                style={{
                  color: "var(--text-muted)",
                  transform: expandedId === prompt.id ? "rotate(180deg)" : "rotate(0deg)",
                  display: "inline-block",
                }}
              >
                ▾
              </span>
            </div>
          </div>

          {/* Expanded section */}
          {expandedId === prompt.id && (
            <div
              className="px-4 pb-4 pt-0"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              {/* Prompt text */}
              <div className="pt-4">
                {prompt.description && (
                  <p
                    className="mb-2 text-xs"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {prompt.description}
                  </p>
                )}
                <p
                  className="mb-3 text-sm leading-relaxed"
                  style={{
                    color: "var(--text-secondary)",
                    backgroundColor: "var(--bg-elevated)",
                    border: "1px solid var(--border)",
                    borderRadius: "0.5rem",
                    padding: "0.75rem 1rem",
                  }}
                >
                  {prompt.prompt_text}
                </p>
                <p
                  className="mb-4 text-xs"
                  style={{ color: "var(--text-muted)" }}
                >
                  Schedule: {cronLabel(prompt.cron_expr)}
                </p>
              </div>

              {/* Script preview */}
              {loadingScripts[prompt.id] ? (
                <div className="flex justify-center py-6">
                  <Spinner />
                </div>
              ) : scripts[prompt.id] ? (
                scripts[prompt.id].length > 0 ? (
                  <ScriptPreview
                    code={scripts[prompt.id][0].code}
                    version={scripts[prompt.id][0].version}
                    needsLlm={scripts[prompt.id][0].needs_llm}
                  />
                ) : (
                  <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                    No script generated yet. Click Regen to create one.
                  </p>
                )
              ) : null}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
