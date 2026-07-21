import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createPrompt } from "../lib/api";
import { PromptList } from "../components/Prompts/PromptList";
import { PromptForm } from "../components/Prompts/PromptForm";

export function PromptsPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);

  const createMut = useMutation({
    mutationFn: createPrompt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setShowForm(false);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className="h-5 w-1 rounded-full flex-shrink-0"
            style={{ backgroundColor: "var(--accent)" }}
          />
          <h2
            className="text-2xl font-semibold"
            style={{
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              color: "var(--text-primary)",
            }}
          >
            Prompts
          </h2>
        </div>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="btn-primary"
          >
            + New Prompt
          </button>
        )}
      </div>

      {createMut.isError && (
        <div
          className="rounded-xl px-4 py-3 text-sm"
          style={{
            backgroundColor: "rgba(248, 113, 113, 0.1)",
            border: "1px solid rgba(248, 113, 113, 0.25)",
            color: "var(--error)",
          }}
        >
          Error: {createMut.error?.message}
        </div>
      )}

      {showForm && (
        <PromptForm
          onSubmit={(data) => createMut.mutate(data)}
          onCancel={() => setShowForm(false)}
        />
      )}
      <PromptList />
    </div>
  );
}
