"use client";

import { useState } from "react";
import { mutate } from "swr";
import { refreshAISummary } from "@/lib/api";
import type { AISummary } from "@/types/api";

interface AISummaryCardProps {
  siteId: number;
  data: AISummary | undefined;
  isLoading: boolean;
  error?: Error & { status?: number };
}

export default function AISummaryCard({ siteId, data, isLoading, error }: AISummaryCardProps) {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  async function handleRefresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      const fresh = await refreshAISummary(siteId);
      mutate(`/api/sites/${siteId}/ai-summary`, fresh, false);
    } catch (e) {
      setRefreshError("Failed to refresh summary — check API key configuration.");
    } finally {
      setRefreshing(false);
    }
  }

  const generatedAt = data?.generated_at
    ? new Date(data.generated_at).toLocaleTimeString("en-GB", { hour12: false })
    : null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center gap-2">
          <svg className="size-4 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
          </svg>
          AI Site Summary
        </h2>
        <div className="flex items-center gap-2">
          {data?.cached && (
            <span className="text-xs text-slate-600 border border-slate-700 rounded px-1.5 py-0.5">
              cached
            </span>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing || isLoading}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-violet-400 disabled:opacity-40 transition-colors border border-[#1e2d4a] rounded px-2 py-1"
          >
            <svg
              className={`size-3 ${refreshing ? "animate-spin" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-[#1e2d4a] bg-[#141c35] p-4">
        {isLoading || refreshing ? (
          <div className="space-y-2">
            {[100, 85, 70].map((w) => (
              <div key={w} className="h-3 rounded animate-pulse bg-[#1a2340]" style={{ width: `${w}%` }} />
            ))}
          </div>
        ) : error ? (
          <p className="text-sm text-slate-500">
            {(error as Error & { status?: number }).status === 503
              ? "AI summary unavailable — ANTHROPIC_API_KEY not configured."
              : "Failed to load summary."}
          </p>
        ) : data ? (
          <>
            <div className="flex items-start gap-2">
              <div className="mt-0.5 size-2 rounded-full bg-violet-400 shrink-0" />
              <p className="text-sm text-slate-300 leading-relaxed">{data.summary}</p>
            </div>
            {generatedAt && (
              <p className="mt-2 text-xs text-slate-600">Generated at {generatedAt} UTC</p>
            )}
          </>
        ) : (
          <p className="text-sm text-slate-600">No summary available.</p>
        )}
        {refreshError && (
          <p className="mt-2 text-xs text-red-400">{refreshError}</p>
        )}
      </div>
    </div>
  );
}
