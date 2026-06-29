export interface Site {
  id: number;
  name: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
}

export interface Reading {
  site_id: number;
  timestamp: string;
  water_level_m: number;
  flow_rate_lpm: number | null;
  pump_pressure_bar: number | null;
  turbidity_ntu: number | null;
  conductivity_us_cm: number | null;
  temperature_c: number | null;
}

export interface PaginatedReadings {
  data: Reading[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface Alert {
  id: number;
  site_id: number;
  alert_type: string;
  severity: "critical" | "high" | "medium" | "low";
  message: string;
  triggered_at: string;
  resolved_at: string | null;
}

export interface HealthScore {
  site_id: number;
  timestamp: string;
  score: number;
  contributing_factors: Record<string, unknown> | null;
}

export interface ForecastPoint {
  ds: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
}

export interface Forecast {
  site_id: number;
  site_name: string;
  generated_at: string;
  model_trained_at: string;
  training_rows: number;
  forecast_horizon_hours: number;
  threshold_m: number;
  breach_risk: boolean;
  estimated_breach_time: string | null;
  breach_confidence: number;
  forecast: ForecastPoint[];
}

export interface AISummary {
  site_id: number;
  site_name: string;
  summary: string;
  generated_at: string;
  cached: boolean;
  cache_ttl_s: number;
}

export interface SiteSummary {
  site_id: number;
  site_name: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  latest_reading: Reading | null;
  health_score: number | null;
  active_alert_count: number;
  status: "normal" | "warning" | "critical";
}

export interface DashboardSummary {
  sites: SiteSummary[];
  total_sites: number;
  sites_critical: number;
  sites_warning: number;
  sites_normal: number;
  generated_at: string;
}

export interface LiveReadingMessage {
  event: "connected" | "reading" | "pong";
  site_id: number | null;
  site_name: string | null;
  data: Reading | null;
  message: string | null;
  server_time: string | null;
}
