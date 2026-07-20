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
        <h2 className="text-2xl font-bold">Prompts</h2>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            + New Prompt
          </button>
        )}
      </div>
      {createMut.isError && (
        <div className="rounded border border-red-700 bg-red-900/20 px-4 py-3 text-sm text-red-400">
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
