import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getConfig, updateConfig } from "../../lib/api";
import { MutationError } from "../ui/MutationError";
import { Spinner } from "../ui/Spinner";

export function GoogleConfig() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [saKey, setSaKey] = useState("");
  const [cron, setCron] = useState<string | null>(null);
  const [folder, setFolder] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      updateConfig({
        google_sa_key: saKey || undefined,
        activity_cron: cron ?? undefined,
        drive_folder_id: folder ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaKey("");
      setCron(null);
      setFolder(null);
    },
  });

  return (
    <div className="card p-6">
      <h3
        className="mb-5 text-base font-semibold"
        style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}
      >
        Google Drive Access
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
              Grants read access to the tracked Drive folder below. Keep the shared files private
              otherwise.
            </p>
            {config?.google_sa_email && (
              <p className="mt-1 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
                {config.google_sa_email}
              </p>
            )}
          </div>

          <div>
            <label
              className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Tracked Drive folder
            </label>
            <input
              className="input-field"
              placeholder="Folder id, or paste the folder URL"
              value={folder ?? config?.drive_folder_id ?? ""}
              onChange={(event) => setFolder(event.target.value)}
            />
            <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
              Share this folder with the service account above. Every Doc and Sheet inside it is tracked.
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Refresh schedule (cron)
            </label>
            <input
              className="input-field"
              value={cron ?? config?.activity_cron ?? "0 6 * * *"}
              onChange={(event) => setCron(event.target.value)}
            />
          </div>

          <MutationError error={mutation.error} />

          <button
            className="btn-primary"
            disabled={mutation.isPending || (!saKey && cron === null && folder === null)}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
