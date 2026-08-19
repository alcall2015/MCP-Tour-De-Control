import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteProject,
  getBudgetSummary,
  listDecisions,
  listProjects,
  refreshProjects,
  type Project,
} from "../lib/api";
import { BudgetSummaryPanel } from "../components/Projects/BudgetSummary";
import { DecisionsPanel } from "../components/Projects/DecisionsPanel";
import { LinkForm } from "../components/Projects/LinkForm";
import { MutationError } from "../components/ui/MutationError";
import { ProjectCard } from "../components/Projects/ProjectCard";
import { ProjectForm } from "../components/Projects/ProjectForm";
import { Spinner } from "../components/ui/Spinner";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [managingLinksId, setManagingLinksId] = useState<string | null>(null);

  const { data: projects = [], isLoading } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  // Derived fresh from the query on every render, rather than a frozen
  // snapshot captured at click time — otherwise the links panel goes stale
  // the moment a link is added or removed underneath it. If the project
  // disappears (deleted elsewhere) this simply comes back undefined and the
  // panel closes instead of rendering a stale copy.
  const managingLinksProject = managingLinksId
    ? projects.find((project) => project.id === managingLinksId)
    : undefined;
  const { data: decisions = [] } = useQuery({ queryKey: ["project-decisions"], queryFn: listDecisions });
  const { data: summary } = useQuery({ queryKey: ["project-summary"], queryFn: getBudgetSummary });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["projects"] });
    queryClient.invalidateQueries({ queryKey: ["project-decisions"] });
    queryClient.invalidateQueries({ queryKey: ["project-summary"] });
  };

  const refreshMutation = useMutation({ mutationFn: refreshProjects, onSuccess: invalidateAll });
  const deleteMutation = useMutation({ mutationFn: deleteProject, onSuccess: invalidateAll });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <div className="flex items-center justify-between gap-3">
        <button className="btn-primary" onClick={() => setCreating(true)}>
          New project
        </button>
        <div className="flex items-center gap-3">
          <MutationError error={refreshMutation.error} />
          <button
            className="btn-secondary"
            disabled={refreshMutation.isPending}
            onClick={() => refreshMutation.mutate()}
          >
            {refreshMutation.isPending ? "Refreshing..." : "Refresh now"}
          </button>
        </div>
      </div>

      <MutationError error={deleteMutation.error} />

      {creating && <ProjectForm onDone={() => setCreating(false)} />}
      {editing && <ProjectForm project={editing} onDone={() => setEditing(null)} />}
      {managingLinksProject && (
        <LinkForm project={managingLinksProject} onDone={() => setManagingLinksId(null)} />
      )}

      <DecisionsPanel decisions={decisions} />
      {summary && <BudgetSummaryPanel summary={summary} />}

      {projects.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          No project yet.
        </p>
      ) : (
        <div className="grid gap-4">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onEdit={() => setEditing(project)}
              onManageLinks={() => setManagingLinksId(project.id)}
              onDelete={() => {
                if (
                  window.confirm(
                    `Delete project "${project.name}"? This also deletes its links and its entire snapshot history.`,
                  )
                ) {
                  deleteMutation.mutate(project.id);
                }
              }}
              isDeleting={deleteMutation.isPending && deleteMutation.variables === project.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
