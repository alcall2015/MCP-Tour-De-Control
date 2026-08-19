export function MutationError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="text-xs" style={{ color: "var(--error)" }}>
      {(error as Error).message}
    </p>
  );
}
