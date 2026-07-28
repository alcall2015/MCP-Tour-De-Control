interface DataPoint {
  second: number;
  cps: number;
}

interface Props {
  data: DataPoint[] | null;
  targetCps: number;
}

const CHART_WIDTH = 600;
const CHART_HEIGHT = 160;
const PADDING = { top: 12, right: 20, bottom: 32, left: 44 };

const INNER_W = CHART_WIDTH - PADDING.left - PADDING.right;
const INNER_H = CHART_HEIGHT - PADDING.top - PADDING.bottom;

const GRID_LINES = 4;

export function CpsChart({ data, targetCps }: Props) {
  if (!data || data.length === 0) {
    return (
      <div
        className="card p-5"
        style={{ minHeight: "180px" }}
      >
        <h3
          className="mb-4 text-sm font-semibold uppercase tracking-wider"
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            color: "var(--text-secondary)",
          }}
        >
          CPS Over Time
        </h3>
        <div
          className="flex items-center justify-center rounded-lg"
          style={{
            height: CHART_HEIGHT,
            backgroundColor: "var(--bg-elevated)",
            border: "1px solid var(--border)",
          }}
        >
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            No ramp-up data available
          </p>
        </div>
      </div>
    );
  }

  const maxSecond = Math.max(...data.map((d) => d.second), 1);
  const maxCps = Math.max(...data.map((d) => d.cps), targetCps, 1);
  const yMax = Math.ceil((maxCps * 1.15) / 5) * 5; // 15% headroom, round up to 5

  const toX = (second: number) => (second / maxSecond) * INNER_W;
  const toY = (cps: number) => INNER_H - (cps / yMax) * INNER_H;

  // Build polyline points
  const points = data
    .map((d) => `${toX(d.second)},${toY(d.cps)}`)
    .join(" ");

  // Grid y values
  const gridValues = Array.from({ length: GRID_LINES + 1 }, (_, i) =>
    Math.round((yMax / GRID_LINES) * i)
  );

  // X-axis tick count
  const xTickCount = Math.min(6, data.length);
  const xTicks = Array.from({ length: xTickCount }, (_, i) =>
    Math.round((maxSecond / (xTickCount - 1)) * i)
  );

  return (
    <div className="card p-5">
      <h3
        className="mb-4 text-sm font-semibold uppercase tracking-wider"
        style={{
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          color: "var(--text-secondary)",
        }}
      >
        CPS Over Time
      </h3>

      <div
        className="rounded-lg overflow-hidden"
        style={{
          backgroundColor: "var(--bg-elevated)",
          border: "1px solid var(--border)",
        }}
      >
        <svg
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
          width="100%"
          preserveAspectRatio="none"
          style={{ display: "block", height: CHART_HEIGHT }}
        >
          <g transform={`translate(${PADDING.left},${PADDING.top})`}>
            {/* Grid lines + Y labels */}
            {gridValues.map((val) => {
              const y = toY(val);
              return (
                <g key={val}>
                  <line
                    x1={0}
                    y1={y}
                    x2={INNER_W}
                    y2={y}
                    stroke="rgba(30,39,64,1)"
                    strokeWidth={1}
                  />
                  <text
                    x={-6}
                    y={y + 4}
                    textAnchor="end"
                    fontSize={10}
                    fill="#64748b"
                    fontFamily="JetBrains Mono, monospace"
                  >
                    {val}
                  </text>
                </g>
              );
            })}

            {/* Target CPS dashed line */}
            {targetCps > 0 && (
              <line
                x1={0}
                y1={toY(targetCps)}
                x2={INNER_W}
                y2={toY(targetCps)}
                stroke="rgba(226,179,64,0.3)"
                strokeWidth={1}
                strokeDasharray="4 3"
              />
            )}

            {/* Area fill */}
            <defs>
              <linearGradient id="cps-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="rgba(226,179,64,0.18)" />
                <stop offset="100%" stopColor="rgba(226,179,64,0.01)" />
              </linearGradient>
            </defs>
            <polygon
              points={`0,${INNER_H} ${points} ${toX(data[data.length - 1].second)},${INNER_H}`}
              fill="url(#cps-fill)"
            />

            {/* Amber polyline */}
            <polyline
              points={points}
              fill="none"
              stroke="var(--warning)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {/* X-axis ticks + labels */}
            {xTicks.map((sec) => (
              <g key={sec}>
                <line
                  x1={toX(sec)}
                  y1={INNER_H}
                  x2={toX(sec)}
                  y2={INNER_H + 4}
                  stroke="#1e2740"
                  strokeWidth={1}
                />
                <text
                  x={toX(sec)}
                  y={INNER_H + 16}
                  textAnchor="middle"
                  fontSize={10}
                  fill="#64748b"
                  fontFamily="JetBrains Mono, monospace"
                >
                  {sec}s
                </text>
              </g>
            ))}

            {/* Axes */}
            <line x1={0} y1={0} x2={0} y2={INNER_H} stroke="#1e2740" strokeWidth={1} />
            <line x1={0} y1={INNER_H} x2={INNER_W} y2={INNER_H} stroke="#1e2740" strokeWidth={1} />
          </g>
        </svg>
      </div>

      <p className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>
        Dashed line = target {targetCps} CPS
      </p>
    </div>
  );
}
