interface PumpHealthGaugeProps {
  score: number | null;
  siteId?: number;
}

function scoreColor(s: number) {
  if (s >= 75) return { stroke: "#22c55e", text: "#4ade80", label: "Good" };
  if (s >= 50) return { stroke: "#f59e0b", text: "#fbbf24", label: "Fair" };
  if (s >= 25) return { stroke: "#f97316", text: "#fb923c", label: "Poor" };
  return { stroke: "#ef4444", text: "#f87171", label: "Critical" };
}

export default function PumpHealthGauge({ score }: PumpHealthGaugeProps) {
  const size = 120;
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = Math.PI * radius; // half-circle arc length

  const pct = score !== null && score !== undefined ? Math.max(0, Math.min(100, score)) : null;
  const progress = pct !== null ? (pct / 100) * circumference : 0;
  const colors = pct !== null ? scoreColor(pct) : { stroke: "#334155", text: "#475569", label: "—" };

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">
        Pump Health
      </h2>
      <div className="rounded-lg border border-[#1e2d4a] bg-[#141c35] p-4 flex items-center gap-6">
        {/* SVG gauge */}
        <div className="shrink-0">
          <svg width={size} height={size / 2 + strokeWidth} viewBox={`0 0 ${size} ${size / 2 + strokeWidth}`}>
            {/* Background track */}
            <path
              d={`M ${strokeWidth / 2} ${size / 2} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${size / 2}`}
              fill="none"
              stroke="#1e2d4a"
              strokeWidth={strokeWidth}
              strokeLinecap="round"
            />
            {/* Foreground arc */}
            <path
              d={`M ${strokeWidth / 2} ${size / 2} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${size / 2}`}
              fill="none"
              stroke={colors.stroke}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              strokeDasharray={`${progress} ${circumference}`}
              style={{ transition: "stroke-dasharray 0.8s ease" }}
            />
            {/* Score text */}
            <text
              x={size / 2}
              y={size / 2 - 4}
              textAnchor="middle"
              fontSize={22}
              fontWeight={600}
              fill={colors.text}
              fontFamily="ui-monospace, monospace"
            >
              {pct !== null ? Math.round(pct) : "—"}
            </text>
            <text
              x={size / 2}
              y={size / 2 + 12}
              textAnchor="middle"
              fontSize={10}
              fill="#475569"
            >
              / 100
            </text>
          </svg>
        </div>

        {/* Details */}
        <div>
          <p className="text-lg font-semibold" style={{ color: colors.text }}>
            {colors.label}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">Pump health score</p>
          <p className="text-xs text-slate-600 mt-1 leading-relaxed">
            {pct === null
              ? "No health data available"
              : pct >= 75
              ? "All systems operating normally"
              : pct >= 50
              ? "Minor stress detected — monitor closely"
              : pct >= 25
              ? "Pump degradation detected"
              : "Immediate inspection required"}
          </p>
        </div>
      </div>
    </div>
  );
}
