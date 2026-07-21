export function Spinner({ className = "" }: { className?: string }) {
  return (
    <div
      className={`spinner ${className}`}
      role="status"
      aria-label="Loading"
    />
  );
}
