import type { ActivityDocument } from "../../lib/api";

const DOC_MIME = "application/vnd.google-apps.document";
const SHEET_MIME = "application/vnd.google-apps.spreadsheet";

function typeLabel(mimeType: string): string {
  if (mimeType === DOC_MIME) return "DOC";
  if (mimeType === SHEET_MIME) return "SHEET";
  return "FILE";
}

function relativeDate(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function DocumentRow({ document }: { document: ActivityDocument }) {
  const hasActivity = document.last_activity_day !== null;

  return (
    <div
      className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2"
      style={{ borderBottom: "1px solid var(--border)" }}
    >
      <span
        className="font-mono text-xs"
        style={{ color: "var(--text-muted)", minWidth: "3.2rem" }}
      >
        {typeLabel(document.mime_type)}
      </span>

      <a
        href={document.web_url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex-1 text-sm"
        style={{ color: "var(--text-primary)", minWidth: "12rem" }}
      >
        {document.name}
        {!document.is_present && (
          <span style={{ color: "var(--text-muted)" }}> · removed from the folder</span>
        )}
      </a>

      {hasActivity ? (
        <span className="font-mono text-xs" style={{ whiteSpace: "nowrap" }}>
          <span style={{ color: "var(--success)" }}>+{document.last_added}</span>{" "}
          <span style={{ color: "var(--error)" }}>−{document.last_removed}</span>{" "}
          <span style={{ color: "var(--text-muted)" }}>
            {relativeDate(document.last_activity_day)}
          </span>
        </span>
      ) : (
        <span className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
          —
        </span>
      )}

      <span className="text-xs" style={{ color: "var(--text-muted)", minWidth: "9rem" }}>
        {document.last_author ?? "unknown"} · {relativeDate(document.last_modified_at)}
      </span>

      {document.last_error && (
        <span className="w-full text-xs" style={{ color: "var(--error)" }}>
          Read failed — {document.last_error}
        </span>
      )}
    </div>
  );
}
