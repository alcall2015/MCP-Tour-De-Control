import type { HeatmapDay } from "../../lib/api";

const CELL = 11;
const GAP = 3;
const STEP = CELL + GAP;
const ROWS = 7;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Four filled steps plus an empty one, so a quiet day is visibly different from a light one. */
function level(total: number, max: number): number {
  if (total <= 0 || max <= 0) return 0;
  return Math.min(4, Math.ceil((total / max) * 4));
}

export function ActivityGrid({ days }: { days: HeatmapDay[] }) {
  if (days.length === 0) return null;

  const max = Math.max(...days.map((d) => d.total));
  const columns = Math.ceil(days.length / ROWS);
  const width = columns * STEP;
  const height = ROWS * STEP;

  // A month label sits above the first column that starts a new month.
  const monthLabels: { x: number; label: string }[] = [];
  let previousMonth = -1;
  for (let column = 0; column < columns; column += 1) {
    const day = days[column * ROWS];
    if (!day) continue;
    const month = new Date(day.day).getMonth();
    if (month !== previousMonth) {
      monthLabels.push({ x: column * STEP, label: MONTHS[month] });
      previousMonth = month;
    }
  }

  return (
    <div className="overflow-x-auto">
      <svg
        width={width + 30}
        height={height + 20}
        role="img"
        aria-label={`Activity over the last 12 months, ${max} lines on the busiest day`}
      >
        {monthLabels.map((m) => (
          <text
            key={`${m.label}-${m.x}`}
            x={m.x + 30}
            y={10}
            fontSize="9"
            fill="var(--text-muted)"
          >
            {m.label}
          </text>
        ))}

        {["Mon", "Wed", "Fri"].map((label, index) => (
          <text
            key={label}
            x={0}
            y={20 + (index * 2 + 1) * STEP - GAP}
            fontSize="9"
            fill="var(--text-muted)"
          >
            {label}
          </text>
        ))}

        {days.map((day, index) => {
          const intensity = level(day.total, max);
          return (
            <rect
              key={day.day}
              x={Math.floor(index / ROWS) * STEP + 30}
              y={(index % ROWS) * STEP + 20}
              width={CELL}
              height={CELL}
              rx={2}
              fill={intensity === 0 ? "var(--bg-elevated)" : "var(--accent)"}
              fillOpacity={intensity === 0 ? 1 : 0.25 * intensity}
            >
              <title>
                {day.day} — +{day.added} −{day.removed}
              </title>
            </rect>
          );
        })}
      </svg>
    </div>
  );
}
