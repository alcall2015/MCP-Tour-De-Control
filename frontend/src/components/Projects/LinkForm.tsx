import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addProjectLink, deleteProjectLink, type Project } from "../../lib/api";

export function LinkForm({ project, onDone }: { project: Project; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [isKpiSource, setIsKpiSource] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["projects"] });

  const addMutation = useMutation({
    mutationFn: () => addProjectLink(project.id, { label, url, is_kpi_source: isKpiSource }),
    onSuccess: () => {
      invalidate();
      setLabel("");
      setUrl("");
      setIsKpiSource(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (linkId: string) => deleteProjectLink(linkId),
    onSuccess: invalidate,
  });

  return (
    <div className="card p-5">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        Links — {project.name}
      </h3>

      <ul className="mb-4 grid gap-2">
        {project.links.map((link) => (
          <li key={link.id} className="flex items-center justify-between gap-3 text-sm">
            <span style={{ color: "var(--text-primary)" }}>
              {link.label}
              {link.is_kpi_source && (
                <span style={{ color: "var(--accent)" }}> · KPI source</span>
              )}
            </span>
            <button
              className="text-xs"
              style={{ color: "var(--error)" }}
              onClick={() => deleteMutation.mutate(link.id)}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="grid gap-3">
        <input
          className="input-field"
          placeholder="Label (e.g. Weekly tracking)"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <input
          className="input-field"
          placeholder="https://docs.google.com/spreadsheets/d/..."
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          <input
            type="checkbox"
            checked={isKpiSource}
            onChange={(event) => setIsKpiSource(event.target.checked)}
          />
          This Sheet carries the SUIVI tab (KPI source)
        </label>
        {addMutation.isError && (
          <p className="text-xs" style={{ color: "var(--error)" }}>
            {(addMutation.error as Error).message}
          </p>
        )}
        <div className="flex gap-2">
          <button
            className="btn-primary"
            disabled={!label || !url || addMutation.isPending}
            onClick={() => addMutation.mutate()}
          >
            Add link
          </button>
          <button className="btn-secondary" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
