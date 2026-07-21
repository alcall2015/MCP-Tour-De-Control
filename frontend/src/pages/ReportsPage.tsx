import { ExecutionList } from "../components/Reports/ExecutionList";

export function ReportsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span
          className="h-5 w-1 rounded-full flex-shrink-0"
          style={{ backgroundColor: "var(--accent)" }}
        />
        <h2
          className="text-2xl font-semibold"
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            color: "var(--text-primary)",
          }}
        >
          Reports
        </h2>
      </div>
      <ExecutionList />
    </div>
  );
}
