"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useDashboard } from "@/lib/api";
import Navbar from "@/components/Navbar";
import StatusBadge from "@/components/StatusBadge";

const SiteMap = dynamic(() => import("@/components/SiteMap"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center text-slate-600 text-sm">
      Loading map…
    </div>
  ),
});

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded-lg border border-[#1e2d4a] bg-[#141c35] px-4 py-3 flex items-center justify-between">
      <span className="text-xs text-slate-500 uppercase tracking-wider">{label}</span>
      <span className={`text-2xl font-bold tabular-nums ${accent ?? "text-slate-200"}`}>
        {value}
      </span>
    </div>
  );
}

export default function HomePage() {
  const { data: dashboard, isLoading } = useDashboard();

  return (
    <>
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        {/* Stats row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <StatCard label="Total Sites" value={dashboard?.total_sites ?? 0} />
          <StatCard label="Normal" value={dashboard?.sites_normal ?? 0} accent="text-green-400" />
          <StatCard label="Warning" value={dashboard?.sites_warning ?? 0} accent="text-amber-400" />
          <StatCard label="Critical" value={dashboard?.sites_critical ?? 0} accent="text-red-400" />
        </div>

        {/* Map */}
        <div className="rounded-xl border border-[#1e2d4a] overflow-hidden mb-6" style={{ height: 420 }}>
          {dashboard ? (
            <SiteMap sites={dashboard.sites} />
          ) : (
            <div className="h-full flex items-center justify-center text-slate-600 text-sm">
              {isLoading ? "Loading…" : "No site data"}
            </div>
          )}
        </div>

        {/* Site cards */}
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Sites
        </h2>
        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-36 rounded-xl bg-[#141c35] border border-[#1e2d4a] animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(dashboard?.sites ?? []).map((site) => (
              <Link
                key={site.site_id}
                href={`/sites/${site.site_id}`}
                className="rounded-xl border border-[#1e2d4a] bg-[#141c35] p-4 hover:border-slate-600 hover:bg-[#1a2340] transition-colors group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="font-semibold text-slate-100 group-hover:text-cyan-400 transition-colors">
                      {site.site_name}
                    </h3>
                    {site.location && (
                      <p className="text-xs text-slate-500 mt-0.5">{site.location}</p>
                    )}
                  </div>
                  <StatusBadge status={site.status} size="sm" />
                </div>

                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                  <div>
                    <span className="text-slate-500 text-xs">Water level</span>
                    <p className="font-medium text-slate-200 tabular-nums">
                      {site.latest_reading
                        ? `${site.latest_reading.water_level_m.toFixed(2)} m`
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <span className="text-slate-500 text-xs">Health</span>
                    <p className="font-medium text-slate-200 tabular-nums">
                      {site.health_score !== null ? `${site.health_score.toFixed(0)} / 100` : "—"}
                    </p>
                  </div>
                </div>

                {site.active_alert_count > 0 && (
                  <div className="mt-3 text-xs text-amber-400">
                    {site.active_alert_count} active alert{site.active_alert_count > 1 ? "s" : ""}
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
