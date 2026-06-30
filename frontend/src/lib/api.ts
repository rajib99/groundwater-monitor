import useSWR from "swr";
import type {
  Alert,
  AISummary,
  DashboardSummary,
  Forecast,
  HealthScore,
  PaginatedReadings,
  Reading,
  Site,
} from "@/types/api";

async function fetcher<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const err = new Error(`API error ${res.status}`);
    (err as Error & { status: number }).status = res.status;
    throw err;
  }
  return res.json();
}

export function useSites() {
  return useSWR<Site[]>("/api/sites/", fetcher, { refreshInterval: 60_000 });
}

export function useDashboard() {
  return useSWR<DashboardSummary>("/api/dashboard/summary", fetcher, {
    refreshInterval: 30_000,
  });
}

export function useSiteLatest(siteId: number | null) {
  return useSWR<Reading>(
    siteId ? `/api/sites/${siteId}/latest` : null,
    fetcher,
    { refreshInterval: 35_000 }
  );
}

export function useSiteReadings(
  siteId: number | null,
  params?: { start?: string; end?: string; page?: number; page_size?: number }
) {
  const query = new URLSearchParams();
  if (params?.start) query.set("start", params.start);
  if (params?.end) query.set("end", params.end);
  if (params?.page) query.set("page", String(params.page));
  if (params?.page_size) query.set("page_size", String(params.page_size));
  const qs = query.toString();

  return useSWR<PaginatedReadings>(
    siteId ? `/api/sites/${siteId}/readings${qs ? `?${qs}` : ""}` : null,
    fetcher,
    { refreshInterval: 60_000 }
  );
}

export function useSiteAlerts(siteId: number | null, resolved?: boolean) {
  const query = new URLSearchParams();
  if (resolved !== undefined) query.set("resolved", String(resolved));

  return useSWR<Alert[]>(
    siteId
      ? `/api/sites/${siteId}/alerts?limit=100${resolved !== undefined ? `&resolved=${resolved}` : ""}`
      : null,
    fetcher,
    { refreshInterval: 30_000 }
  );
}

export function useSiteHealth(siteId: number | null) {
  return useSWR<HealthScore>(
    siteId ? `/api/sites/${siteId}/health` : null,
    fetcher,
    { refreshInterval: 60_000 }
  );
}

export function useSiteForecast(siteId: number | null) {
  return useSWR<Forecast>(
    siteId ? `/api/sites/${siteId}/forecast` : null,
    fetcher,
    { refreshInterval: 300_000 }
  );
}

export function useAISummary(siteId: number | null) {
  return useSWR<AISummary>(
    siteId ? `/api/sites/${siteId}/ai-summary` : null,
    fetcher,
    { revalidateOnFocus: false }
  );
}

export async function refreshAISummary(siteId: number): Promise<AISummary> {
  return fetcher<AISummary>(`/api/sites/${siteId}/ai-summary?refresh=true`);
}
