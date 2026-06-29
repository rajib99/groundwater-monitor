"use client";

import { useState } from "react";
import type { Alert } from "@/types/api";
import StatusBadge from "./StatusBadge";

interface AlertsTableProps {
  alerts: Alert[];
}

export default function AlertsTable({ alerts }: AlertsTableProps) {
  const [filter, setFilter] = useState<"all" | "active" | "resolved">("all");

  const filtered = alerts.filter((a) => {
    if (filter === "active") return a.resolved_at === null;
    if (filter === "resolved") return a.resolved_at !== null;
    return true;
  });

  function fmtDate(ts: string) {
    return new Date(ts).toLocaleString("en-GB", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
          Alerts
        </h2>
        <div className="flex gap-1">
          {(["all", "active", "resolved"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 text-xs rounded transition-colors capitalize ${
                filter === f
                  ? "bg-[#1a2340] text-slate-200 border border-[#2a3f60]"
                  : "text-slate-500 hover:text-slate-300 border border-transparent"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-[#1e2d4a] overflow-hidden">
        {filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-slate-600 bg-[#141c35]">
            No {filter !== "all" ? filter : ""} alerts
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#1e2d4a] bg-[#0f1629]">
                <th className="text-left px-3 py-2.5 text-xs text-slate-500 font-medium">Severity</th>
                <th className="text-left px-3 py-2.5 text-xs text-slate-500 font-medium hidden sm:table-cell">Type</th>
                <th className="text-left px-3 py-2.5 text-xs text-slate-500 font-medium">Message</th>
                <th className="text-left px-3 py-2.5 text-xs text-slate-500 font-medium hidden md:table-cell">Triggered</th>
                <th className="text-left px-3 py-2.5 text-xs text-slate-500 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((alert, i) => (
                <tr
                  key={alert.id}
                  className={`border-b border-[#1e2d4a] last:border-0 ${
                    i % 2 === 0 ? "bg-[#141c35]" : "bg-[#0f1629]"
                  }`}
                >
                  <td className="px-3 py-2.5">
                    <StatusBadge status={alert.severity} size="sm" />
                  </td>
                  <td className="px-3 py-2.5 text-slate-500 font-mono text-xs hidden sm:table-cell">
                    {alert.alert_type}
                  </td>
                  <td className="px-3 py-2.5 text-slate-300 max-w-xs">
                    <span className="line-clamp-2">{alert.message}</span>
                  </td>
                  <td className="px-3 py-2.5 text-slate-500 text-xs whitespace-nowrap hidden md:table-cell">
                    {fmtDate(alert.triggered_at)}
                  </td>
                  <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                    {alert.resolved_at ? (
                      <span className="text-green-400">Resolved</span>
                    ) : (
                      <span className="text-amber-400 animate-pulse">Active</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
