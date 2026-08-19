import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "../../lib/api";
import { MutationError } from "../Projects/MutationError";
import { Spinner } from "../ui/Spinner";

export function GoogleConfig() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [saKey, setSaKey] = useState("");
  const [cron, setCron] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      updateConfig({
        google_sa_key: saKey || undefined,
        projects_cron: cron ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaKey("");
      setCron(null);
    },
  });

  return (
    <div className="card p-6">
      <h3
        className="mb-5 text-base font-semibold"
        style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}
      >
        Google Projects Access
      </h3>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <div className="grid gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Service account key (JSON)
            </label>
            <textarea
              className="input-field"
              rows={4}
              placeholder={config?.google_sa_key_set ? "Key set — paste a new one to replace it" : '{"type": "service_account", ...}'}
              value={saKey}
              onChange={(event) => setSaKey(event.target.value)}
            />
            <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
              Share every project Sheet with this service account email, then keep the files private.
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Refresh schedule (cron)
            </label>
            <input
              className="input-field"
              value={cron ?? config?.projects_cron ?? "0 6 * * *"}
              onChange={(event) => setCron(event.target.value)}
            />
          </div>

          <MutationError error={mutation.error} />

          <button
            className="btn-primary"
            disabled={mutation.isPending || (!saKey && cron === null)}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
