"use client";

import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { useMemo } from "react";
import type { Reading, Forecast } from "@/types/api";

interface ChartPoint {
  ts: number;
  actual?: number;
  yhat?: number;
  yhat_lower?: number;
  yhat_upper?: number;
}

function fmtAxis(ts: number) {
  const d = new Date(ts);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function fmtTick(ts: number) {
  const d = new Date(ts);
  const now = Date.now();
  const diffDays = (now - ts) / 86_400_000;
  if (diffDays < 1) return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

interface WaterLevelChartProps {
  readings: Reading[];
  forecast?: Forecast | null;
}

export default function WaterLevelChart({ readings, forecast }: WaterLevelChartProps) {
  const data = useMemo<ChartPoint[]>(() => {
    const hist: ChartPoint[] = readings.map((r) => ({
      ts: new Date(r.timestamp).getTime(),
      actual: r.water_level_m,
    }));
    hist.sort((a, b) => a.ts - b.ts);

    if (!forecast?.forecast?.length) return hist;

    const forecastPoints: ChartPoint[] = forecast.forecast.map((p) => ({
      ts: new Date(p.ds).getTime(),
      yhat: p.yhat,
      yhat_lower: p.yhat_lower,
      yhat_upper: p.yhat_upper,
    }));

    // Merge — sort combined
    const merged = [...hist, ...forecastPoints].sort((a, b) => a.ts - b.ts);

    // Stitch the handoff: last historical point appears as yhat anchor
    const lastHist = hist[hist.length - 1];
    if (lastHist && forecast.forecast.length) {
      const stitch = merged.find((p) => p.ts === lastHist.ts);
      if (stitch) stitch.yhat = lastHist.actual;
    }

    return merged;
  }, [readings, forecast]);

  const now = Date.now();

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">
        Water Level — 7d History + 24h Forecast
      </h2>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="gradActual" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradForecast" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#818cf8" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#818cf8" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="#1e2d4a" />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={fmtTick}
            tick={{ fill: "#64748b", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "#1e2d4a" }}
          />
          <YAxis
            tickFormatter={(v) => `${v.toFixed(1)}m`}
            tick={{ fill: "#64748b", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            contentStyle={{ background: "#141c35", border: "1px solid #1e2d4a", borderRadius: 6 }}
            labelStyle={{ color: "#94a3b8", fontSize: 11 }}
            itemStyle={{ color: "#e2e8f0", fontSize: 12 }}
            labelFormatter={(v) => fmtAxis(v as number)}
            formatter={(v: number, name: string) => [`${v.toFixed(3)} m`, name]}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "#64748b", paddingTop: 8 }}
            iconType="circle"
            iconSize={8}
          />

          {/* "Now" reference line */}
          <ReferenceLine x={now} stroke="#334155" strokeDasharray="4 4" label={{ value: "Now", fill: "#475569", fontSize: 10, position: "top" }} />

          {/* Breach threshold */}
          {forecast?.threshold_m && (
            <ReferenceLine
              y={forecast.threshold_m}
              stroke="#ef444460"
              strokeDasharray="5 3"
              label={{ value: "Breach threshold", fill: "#ef4444", fontSize: 10, position: "insideTopRight" }}
            />
          )}

          {/* CI band */}
          <Area
            dataKey="yhat_upper"
            name="CI upper"
            fill="url(#gradForecast)"
            stroke="transparent"
            dot={false}
            legendType="none"
            connectNulls
          />
          <Area
            dataKey="yhat_lower"
            name="CI lower"
            fill="transparent"
            stroke="transparent"
            dot={false}
            legendType="none"
            connectNulls
          />

          {/* Historical */}
          <Area
            dataKey="actual"
            name="Actual"
            stroke="#06b6d4"
            fill="url(#gradActual)"
            strokeWidth={2}
            dot={false}
            connectNulls
          />

          {/* Forecast line */}
          <Line
            dataKey="yhat"
            name="Forecast"
            stroke="#818cf8"
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
