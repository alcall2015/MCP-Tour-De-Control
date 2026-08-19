import { useQuery } from "@tanstack/react-query";
import { getBudgetSummary, listDecisions, listProjects } from "../lib/api";
import { BudgetSummaryPanel } from "../components/Projects/BudgetSummary";
import { DecisionsPanel } from "../components/Projects/DecisionsPanel";
import { ProjectCard } from "../components/Projects/ProjectCard";
import { Spinner } from "../components/ui/Spinner";

export function ProjectsPage() {
  const { data: projects = [], isLoading } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: decisions = [] } = useQuery({ queryKey: ["project-decisions"], queryFn: listDecisions });
  const { data: summary } = useQuery({ queryKey: ["project-summary"], queryFn: getBudgetSummary });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <DecisionsPanel decisions={decisions} />
      {summary && <BudgetSummaryPanel summary={summary} />}

      {projects.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          No project yet.
        </p>
      ) : (
        <div className="grid gap-4">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
