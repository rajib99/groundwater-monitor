"use client";

import type { Alert } from "@/types/api";
import StatusBadge from "./StatusBadge";

const ICON: Record<string, string> = {
  critical: "⬤",
  high:     "◆",
  medium:   "▲",
  low:      "●",
};

function relTime(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface AnomalyTimelineProps {
  alerts: Alert[];
}

export default function AnomalyTimeline({ alerts }: AnomalyTimelineProps) {
  const sorted = [...alerts].sort(
    (a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime()
  );

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">
        Anomaly Timeline
      </h2>
      {sorted.length === 0 ? (
        <div className="rounded-lg border border-[#1e2d4a] bg-[#141c35] px-4 py-8 text-center text-sm text-slate-600">
          No anomalies detected
        </div>
      ) : (
        <div className="relative">
          {/* Vertical line */}
          <div className="absolute left-3.5 top-0 bottom-0 w-px bg-[#1e2d4a]" />
          <ul className="space-y-3 pl-9">
            {sorted.map((alert) => (
              <li key={alert.id} className="relative">
                {/* Dot */}
                <span
                  className="absolute -left-[22px] top-1.5 size-2.5 rounded-full border-2 border-[#0f1629]"
                  style={{
                    background:
                      alert.severity === "critical" ? "#ef4444"
                      : alert.severity === "high"     ? "#f97316"
                      : alert.severity === "medium"   ? "#f59e0b"
                      : "#3b82f6",
                  }}
                />
                <div className="rounded-lg border border-[#1e2d4a] bg-[#141c35] px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2 flex-wrap">
                      <StatusBadge status={alert.severity} size="sm" />
                      <span className="text-xs text-slate-500 font-mono">{alert.alert_type}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {alert.resolved_at ? (
                        <span className="text-xs text-green-400">Resolved</span>
                      ) : (
                        <span className="text-xs text-amber-400 animate-pulse">Active</span>
                      )}
                      <span className="text-xs text-slate-600">{relTime(alert.triggered_at)}</span>
                    </div>
                  </div>
                  <p className="mt-1.5 text-sm text-slate-300 leading-snug">{alert.message}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
