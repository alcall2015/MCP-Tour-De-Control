import type { ActivitySection } from "../../lib/api";
import { DocumentRow } from "./DocumentRow";

export function SectionList({ sections }: { sections: ActivitySection[] }) {
  if (sections.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        Nothing tracked yet. Share a Drive folder with the service account, set it in Config, then scan.
      </p>
    );
  }

  return (
    <div className="grid gap-5">
      {sections.map((section) => (
        <div key={section.name} className="card p-5">
          <div className="mb-2 flex items-baseline justify-between">
            <h3
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              {section.name}
            </h3>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {section.documents.length} file{section.documents.length !== 1 ? "s" : ""}
            </span>
          </div>
          {section.documents.map((doc) => (
            <DocumentRow key={doc.id} document={doc} />
          ))}
        </div>
      ))}
    </div>
  );
}
