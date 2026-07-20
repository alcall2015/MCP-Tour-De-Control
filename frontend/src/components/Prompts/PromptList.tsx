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
import cronstrue from "cronstrue/i18n";

export function PromptList() {
  const queryClient = useQueryClient();
  const { data: prompts = [], isLoading } = useQuery({ queryKey: ["prompts"], queryFn: listPrompts });
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
    return <p className="text-center text-zinc-500">Loading prompts...</p>;
  }

  return (
    <div className="space-y-3">
      {prompts.map((prompt) => (
        <div key={prompt.id} className="rounded-lg border border-zinc-800 bg-zinc-900">
          <div
            className="flex cursor-pointer items-center justify-between p-4"
            onClick={() => handleExpand(prompt.id)}
          >
            <div className="flex items-center gap-3">
              <span
                className={`h-2 w-2 flex-shrink-0 rounded-full ${
                  prompt.enabled ? "bg-green-500" : "bg-zinc-500"
                }`}
              />
              <span className="font-medium">{prompt.name}</span>
              {prompt.latest_script_version !== null && (
                <span className="text-xs text-zinc-500">v{prompt.latest_script_version}</span>
              )}
              {prompt.needs_llm !== null && (
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    prompt.needs_llm
                      ? "bg-amber-900/50 text-amber-400"
                      : "bg-green-900/50 text-green-400"
                  }`}
                >
                  {prompt.needs_llm ? "LLM" : "No LLM"}
                </span>
              )}
            </div>
            <div className="flex items-center gap-4">
              <span className="hidden text-xs text-zinc-500 sm:block">{cronLabel(prompt.cron_expr)}</span>
              <div
                className="flex gap-2"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => handleRun(prompt)}
                  className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600"
                >
                  Run
                </button>
                <button
                  onClick={() => regenMut.mutate(prompt.id)}
                  disabled={regenMut.isPending}
                  className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600 disabled:opacity-50"
                >
                  Regen
                </button>
                <button
                  onClick={() => toggleMut.mutate(prompt.id)}
                  disabled={toggleMut.isPending}
                  className="rounded bg-zinc-700 px-2 py-1 text-xs text-white hover:bg-zinc-600 disabled:opacity-50"
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
                  className="rounded bg-red-900 px-2 py-1 text-xs text-white hover:bg-red-800 disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>

          {expandedId === prompt.id && (
            <div className="border-t border-zinc-800 p-4">
              <p className="mb-3 text-sm text-zinc-400">{prompt.prompt_text}</p>
              {prompt.description && (
                <p className="mb-3 text-xs text-zinc-500">{prompt.description}</p>
              )}
              <p className="mb-3 text-xs text-zinc-500">
                Schedule: {cronLabel(prompt.cron_expr)}
              </p>
              {loadingScripts[prompt.id] ? (
                <p className="text-sm text-zinc-500">Loading script...</p>
              ) : scripts[prompt.id] ? (
                scripts[prompt.id].length > 0 ? (
                  <ScriptPreview
                    code={scripts[prompt.id][0].code}
                    version={scripts[prompt.id][0].version}
                    needsLlm={scripts[prompt.id][0].needs_llm}
                  />
                ) : (
                  <p className="text-sm text-zinc-500">No script generated yet.</p>
                )
              ) : null}
            </div>
          )}
        </div>
      ))}
      {prompts.length === 0 && (
        <p className="text-center text-zinc-500">No prompts yet. Create your first one!</p>
      )}
    </div>
  );
}
