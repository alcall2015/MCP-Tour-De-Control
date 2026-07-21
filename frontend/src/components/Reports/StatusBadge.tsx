const STATUS_STYLES: Record<string, { bg: string; text: string; dot: string; label: string }> = {
  success: {
    bg: "rgba(52, 211, 153, 0.12)",
    text: "#34d399",
    dot: "#34d399",
    label: "success",
  },
  failed: {
    bg: "rgba(248, 113, 113, 0.12)",
    text: "#f87171",
    dot: "#f87171",
    label: "failed",
  },
  running: {
    bg: "rgba(96, 165, 250, 0.12)",
    text: "#60a5fa",
    dot: "#60a5fa",
    label: "running",
  },
  timeout: {
    bg: "rgba(251, 191, 36, 0.12)",
    text: "#fbbf24",
    dot: "#fbbf24",
    label: "timeout",
  },
};

const DEFAULT_STYLE = {
  bg: "rgba(100, 116, 139, 0.15)",
  text: "#94a3b8",
  dot: "#64748b",
  label: "",
};

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || { ...DEFAULT_STYLE, label: status };

  return (
    <span
      className="badge"
      style={{
        backgroundColor: style.bg,
        color: style.text,
        border: `1px solid ${style.text}25`,
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full flex-shrink-0 inline-block"
        style={{ backgroundColor: style.dot }}
      />
      {style.label || status}
    </span>
  );
}
