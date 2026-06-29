"use client";

import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { useRouter } from "next/navigation";
import "leaflet/dist/leaflet.css";
import type { SiteSummary } from "@/types/api";

const STATUS_COLORS: Record<string, string> = {
  normal:   "#22c55e",
  warning:  "#f59e0b",
  critical: "#ef4444",
};

interface SiteMapProps {
  sites: SiteSummary[];
}

export default function SiteMap({ sites }: SiteMapProps) {
  const router = useRouter();

  // Fix Leaflet default icon issue with Next.js
  useEffect(() => {
    // Intentional side-effect: Leaflet reads _getIconUrl at runtime
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).L?.Icon?.Default?.prototype?._getIconUrl;
  }, []);

  const mapped = sites.filter((s) => s.latitude !== null && s.longitude !== null);

  const center: [number, number] =
    mapped.length > 0
      ? [
          mapped.reduce((a, s) => a + s.latitude!, 0) / mapped.length,
          mapped.reduce((a, s) => a + s.longitude!, 0) / mapped.length,
        ]
      : [24.4, 54.4];

  return (
    <MapContainer
      center={center}
      zoom={9}
      style={{ height: "100%", width: "100%" }}
      attributionControl
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        maxZoom={19}
      />
      {mapped.map((site) => (
        <CircleMarker
          key={site.site_id}
          center={[site.latitude!, site.longitude!]}
          radius={10}
          pathOptions={{
            color: STATUS_COLORS[site.status] ?? "#64748b",
            fillColor: STATUS_COLORS[site.status] ?? "#64748b",
            fillOpacity: 0.85,
            weight: 2,
          }}
          eventHandlers={{
            click: () => router.push(`/sites/${site.site_id}`),
          }}
        >
          <Popup className="gwm-popup">
            <div className="text-slate-100 text-sm font-medium">{site.site_name}</div>
            {site.location && (
              <div className="text-slate-400 text-xs mt-0.5">{site.location}</div>
            )}
            <div className="mt-1.5 text-xs text-slate-300 space-y-0.5">
              {site.latest_reading && (
                <div>Water level: <strong>{site.latest_reading.water_level_m.toFixed(2)} m</strong></div>
              )}
              {site.health_score !== null && (
                <div>Health: <strong>{site.health_score.toFixed(0)} / 100</strong></div>
              )}
              {site.active_alert_count > 0 && (
                <div className="text-amber-400">{site.active_alert_count} active alert{site.active_alert_count > 1 ? "s" : ""}</div>
              )}
            </div>
            <button
              onClick={() => router.push(`/sites/${site.site_id}`)}
              className="mt-2 text-xs text-cyan-400 hover:underline"
            >
              View detail →
            </button>
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
