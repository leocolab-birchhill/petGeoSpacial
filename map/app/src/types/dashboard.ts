import type { MarketClass } from "../types";

export interface DashboardHex {
  h3_id: string;
  /** Human label: nearest city · dominant FSA */
  place: string;
  city?: string | null;
  fsa?: string | null;
  province: string;
  market_class: MarketClass;
  is_rural: boolean;
  opportunity_score: number | null;
  opportunity_pct: number | null;
  demand: number | null;
  demand_pct: number | null;
  nearest_pv_min: number | null;
  avg3_pv_min: number | null;
  comp_intensity: number | null;
  comp_pct: number | null;
  households: number | null;
  population: number | null;
  cluster_id: number | null;
  routing_status: string;
  lat: number | null;
  lon: number | null;
}

export interface DashboardPayload {
  hexes: DashboardHex[];
  class_counts: Record<string, number>;
  score_hist: { bins: number[]; counts: number[] };
  province_opportunity: Record<
    string,
    { true_whitespace: number; proven_market_no_pv: number; demand: number }
  >;
}

export type AppTab = "map" | "dashboard";
