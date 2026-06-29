"use client";

import { useState, useCallback } from "react";
import { useWebSocket } from "@/lib/useWebSocket";
import type { Reading } from "@/types/api";

interface MetricCardProps {
  label: string;
  value: string | null;
  unit: string;
  flash?: boolean;
}

function MetricCard({ label, value, unit, flash }: MetricCardProps) {
  return (
    <div
      className={`rounded-lg border bg-[#141c35] p-4 transition-colors duration-700 ${
        flash ? "border-cyan-500/60" : "border-[#1e2d4a]"
      }`}
    >
      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-xl font-semibold tabular-nums text-slate-100">
        {value ?? <span className="text-slate-600">—</span>}
        {value && <span className="ml-1 text-sm font-normal text-slate-400">{unit}</span>}
      </p>
    </div>
  );
}

function fmt(v: number | null | undefined, decimals = 2): string | null {
  if (v === null || v === undefined) return null;
  return v.toFixed(decimals);
}

interface LiveReadingsPanelProps {
  siteId: number;
  initialReading: Reading | null;
  onWsStatus?: (status: import("@/lib/useWebSocket").WsStatus) => void;
}

export default function LiveReadingsPanel({
  siteId,
  initialReading,
  onWsStatus,
}: LiveReadingsPanelProps) {
  const [reading, setReading] = useState<Reading | null>(initialReading);
  const [flash, setFlash] = useState(false);

  const onReading = useCallback(
    (r: Reading, rid: number) => {
      if (rid !== siteId) return;
      setReading(r);
      setFlash(true);
      setTimeout(() => setFlash(false), 800);
    },
    [siteId]
  );

  const { status } = useWebSocket({ siteId, onReading });

  // Propagate WS status to parent (for Navbar indicator)
  if (onWsStatus) onWsStatus(status);

  const ts = reading?.timestamp
    ? new Date(reading.timestamp).toLocaleTimeString("en-GB", { hour12: false })
    : null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
          Live Readings
        </h2>
        {ts && <span className="text-xs text-slate-500">Last update: {ts}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <MetricCard label="Water Level" value={fmt(reading?.water_level_m)} unit="m" flash={flash} />
        <MetricCard label="Flow Rate" value={fmt(reading?.flow_rate_lpm, 1)} unit="L/min" flash={flash} />
        <MetricCard label="Pump Pressure" value={fmt(reading?.pump_pressure_bar)} unit="bar" flash={flash} />
        <MetricCard label="Turbidity" value={fmt(reading?.turbidity_ntu, 1)} unit="NTU" flash={flash} />
        <MetricCard label="Conductivity" value={fmt(reading?.conductivity_us_cm, 0)} unit="µS/cm" flash={flash} />
        <MetricCard label="Temperature" value={fmt(reading?.temperature_c, 1)} unit="°C" flash={flash} />
      </div>
    </div>
  );
}
