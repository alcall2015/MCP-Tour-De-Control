import { ExecutionList } from "../components/Reports/ExecutionList";

export function ReportsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Reports</h2>
      <ExecutionList />
    </div>
  );
}
