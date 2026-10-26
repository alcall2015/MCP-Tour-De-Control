import { RISK_LEVELS } from "../../lib/api";

const STYLE: Record<number, { color: string; bg: string; border: string }> = {
  0: { color: "var(--success)",        bg: "rgba(52, 211, 153, 0.10)",  border: "rgba(52, 211, 153, 0.3)" },
  1: { color: "var(--running)",        bg: "rgba(96, 165, 250, 0.12)",  border: "rgba(96, 165, 250, 0.3)" },
  2: { color: "var(--warning)",        bg: "rgba(251, 191, 36, 0.12)",  border: "rgba(251, 191, 36, 0.35)" },
  3: { color: "var(--error)",          bg: "rgba(248, 113, 113, 0.12)", border: "rgba(248, 113, 113, 0.35)" },
};

/** One badge per risk level. Unknown values (a payload from an older run) render as a neutral "R?" badge rather than throwing. */
export function RiskBadge({ level, compact = false }: { level: number; compact?: boolean }) {
  const def = RISK_LEVELS.find((r) => r.level === level);
  const s = STYLE[level] ?? { color: "var(--text-muted)", bg: "rgba(100, 116, 139, 0.10)", border: "rgba(100, 116, 139, 0.3)" };
  const code = def?.code ?? "R?";
  return (
    <span className="badge font-mono" title={def ? `${def.label}: ${def.hint}` : "Unknown risk level"} style={{ color: s.color, backgroundColor: s.bg, border: `1px solid ${s.border}` }}>
      {compact || !def ? code : `${code} ${def.label}`}
    </span>
  );
}
