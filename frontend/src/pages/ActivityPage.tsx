import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getHeatmap, listActivityDocuments, scanActivity } from "../lib/api";
import { ActivityGrid } from "../components/Activity/ActivityGrid";
import { SectionList } from "../components/Activity/SectionList";
import { Spinner } from "../components/ui/Spinner";
import { MutationError } from "../components/ui/MutationError";

function relativeDate(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function ActivityPage() {
  const { data: sections = [], isLoading } = useQuery({
    queryKey: ["activity-documents"],
    queryFn: listActivityDocuments,
  });
  const { data: heatmap } = useQuery({ queryKey: ["activity-heatmap"], queryFn: getHeatmap });

  const queryClient = useQueryClient();
  const scanMutation = useMutation({
    mutationFn: scanActivity,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["activity-documents"] });
      queryClient.invalidateQueries({ queryKey: ["activity-heatmap"] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <div className="card p-5">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Activity — last 12 months
          </h3>
          <div className="flex items-center gap-3">
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {heatmap?.total_changes ?? 0} lines changed · last scan{" "}
              {relativeDate(heatmap?.last_scan_at ?? null)}
            </span>
            <button
              className="btn-secondary"
              disabled={scanMutation.isPending}
              onClick={() => scanMutation.mutate()}
            >
              {scanMutation.isPending ? "Scanning..." : "Scan now"}
            </button>
          </div>
        </div>
        <MutationError error={scanMutation.error} />
        {heatmap && <ActivityGrid days={heatmap.days} />}
      </div>

      <SectionList sections={sections} />
    </div>
  );
}
