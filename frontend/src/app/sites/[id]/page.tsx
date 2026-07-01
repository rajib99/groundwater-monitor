"use client";

import { use, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  useSiteLatest,
  useSiteReadings,
  useSiteAlerts,
  useSiteHealth,
  useSiteForecast,
  useAISummary,
} from "@/lib/api";
import Navbar from "@/components/Navbar";
import LiveReadingsPanel from "@/components/LiveReadingsPanel";
import WaterLevelChart from "@/components/WaterLevelChart";
import AnomalyTimeline from "@/components/AnomalyTimeline";
import PumpHealthGauge from "@/components/PumpHealthGauge";
import AISummaryCard from "@/components/AISummaryCard";
import AlertsTable from "@/components/AlertsTable";
import StatusBadge from "@/components/StatusBadge";
import type { WsStatus } from "@/lib/useWebSocket";
import type { Reading } from "@/types/api";

export default function SiteDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const siteId = parseInt(id);

  const [wsStatus, setWsStatus] = useState<WsStatus>("disconnected");

  // Memoized so the value (and SWR cache key) stays stable across re-renders
  const sevenDaysAgo = useMemo(
    () => new Date(Date.now() - 7 * 86_400_000).toISOString(),
    []
  );

  const { data: latest } = useSiteLatest(siteId);
  const { data: readings } = useSiteReadings(siteId, {
    start: sevenDaysAgo,
    page_size: 1000,
  });
  const { data: alerts } = useSiteAlerts(siteId);
  const { data: health } = useSiteHealth(siteId);
  const { data: forecast } = useSiteForecast(siteId);
  const {
    data: aiSummary,
    isLoading: aiLoading,
    error: aiError,
  } = useAISummary(siteId);

  const handleWsStatus = useCallback((s: WsStatus) => setWsStatus(s), []);

  const activeAlerts = alerts?.filter((a) => !a.resolved_at) ?? [];
  const siteStatus =
    activeAlerts.some((a) => a.severity === "critical")
      ? "critical"
      : activeAlerts.some((a) => a.severity === "high" || a.severity === "medium")
      ? "warning"
      : "normal";

  return (
    <>
      <Navbar wsStatus={wsStatus} />
      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">

        {/* Header */}
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link href="/" className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
                ← All Sites
              </Link>
            </div>
            <h1 className="text-xl font-bold text-slate-100 flex items-center gap-3">
              Site #{siteId}
              <StatusBadge status={siteStatus} />
            </h1>
            {forecast && (
              <p className="text-xs text-slate-500 mt-1">{forecast.site_name}</p>
            )}
          </div>
          {forecast?.breach_risk && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400 flex items-center gap-2">
              <span className="size-2 rounded-full bg-red-500 animate-pulse shrink-0" />
              Breach risk detected
              {forecast.estimated_breach_time && (
                <span className="text-red-500/70">
                  — est. {new Date(forecast.estimated_breach_time).toLocaleTimeString("en-GB", { hour12: false })}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Top row: Live readings + Pump health */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-xl border border-[#1e2d4a] bg-[#0f1629] p-5">
            <LiveReadingsPanel
              siteId={siteId}
              initialReading={latest ?? null}
              onWsStatus={handleWsStatus}
            />
          </div>
          <div className="rounded-xl border border-[#1e2d4a] bg-[#0f1629] p-5">
            <PumpHealthGauge score={health?.score ?? null} />
          </div>
        </div>

        {/* AI Summary */}
        <div className="rounded-xl border border-[#1e2d4a] bg-[#0f1629] p-5">
          <AISummaryCard
            siteId={siteId}
            data={aiSummary}
            isLoading={aiLoading}
            error={aiError}
          />
        </div>

        {/* Chart */}
        <div className="rounded-xl border border-[#1e2d4a] bg-[#0f1629] p-5">
          <WaterLevelChart
            readings={readings?.data ?? []}
            forecast={forecast}
          />
        </div>

        {/* Bottom row: Anomaly timeline + Alerts table */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="rounded-xl border border-[#1e2d4a] bg-[#0f1629] p-5">
            <AnomalyTimeline alerts={alerts ?? []} />
          </div>
          <div className="rounded-xl border border-[#1e2d4a] bg-[#0f1629] p-5">
            <AlertsTable alerts={alerts ?? []} />
          </div>
        </div>

      </main>
    </>
  );
}
