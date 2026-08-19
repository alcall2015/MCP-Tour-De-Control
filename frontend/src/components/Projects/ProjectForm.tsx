import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createProject, updateProject, type Project } from "../../lib/api";

export function ProjectForm({ project, onDone }: { project?: Project; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [staleDays, setStaleDays] = useState(project?.stale_days ?? 14);
  const [budgetWarnPct, setBudgetWarnPct] = useState(project?.budget_warn_pct ?? 90);

  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        name,
        description: description || null,
        stale_days: staleDays,
        budget_warn_pct: budgetWarnPct,
      };
      return project ? updateProject(project.id, payload) : createProject(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onDone();
    },
  });

  return (
    <div className="card p-5">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {project ? "Edit project" : "New project"}
      </h3>
      <div className="grid gap-3">
        <input
          className="input-field"
          placeholder="Project name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <input
          className="input-field"
          placeholder="Description (optional)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <div className="flex gap-3">
          <label className="flex-1 text-xs" style={{ color: "var(--text-muted)" }}>
            Stale after (days)
            <input
              className="input-field mt-1"
              type="number"
              min={1}
              value={staleDays}
              onChange={(event) => setStaleDays(Number(event.target.value))}
            />
          </label>
          <label className="flex-1 text-xs" style={{ color: "var(--text-muted)" }}>
            Budget warning (%)
            <input
              className="input-field mt-1"
              type="number"
              min={1}
              max={100}
              value={budgetWarnPct}
              onChange={(event) => setBudgetWarnPct(Number(event.target.value))}
            />
          </label>
        </div>
        {mutation.isError && (
          <p className="text-xs" style={{ color: "var(--error)" }}>
            {(mutation.error as Error).message}
          </p>
        )}
        <div className="flex gap-2">
          <button className="btn-primary" disabled={!name || mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Saving..." : "Save"}
          </button>
          <button className="btn-secondary" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
