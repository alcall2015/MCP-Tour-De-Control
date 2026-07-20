const styles: Record<string, string> = {
  success: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
  running: "bg-blue-900 text-blue-300",
  timeout: "bg-amber-900 text-amber-300",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles[status] || "bg-zinc-700 text-zinc-300"}`}>
      {status}
    </span>
  );
}
