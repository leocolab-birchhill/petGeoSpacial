/**
 * Type mirrors of DATA_CONTRACT.md. Keep in sync with pipeline outputs.
 */

export type RoutingStatus = "ok" | "no_route" | "pending";

export type MarketClass =
  | "true_whitespace"
  | "proven_market_no_pv"
  | "competitive_infill"
  | "weak_whitespace"
  | "other"
  | "pending_routing";

export type CompetitorType =
  | "mass_merchant"
  | "specialty_chain"
  | "independent_boutique"
  | "services_other";

export type MetricId =
  | "opportunity_score"
  | "adjusted_addressable_demand"
  | "nearest_pv_minutes"
  | "avg3_pv_minutes"
  | "competitor_intensity"
  | "national_demand_percentile"
  | "market_class"; // categorical

/** Properties present on h3_r7 / h3_r8 vector-tile features (DATA_CONTRACT §5.1). */
export interface HexTileProps {
  h3_id: string;
  opportunity_score?: number;
  market_class: MarketClass;
  adjusted_addressable_demand?: number;
  national_demand_percentile?: number;
  nearest_pv_minutes?: number;
  avg3_pv_minutes?: number;
  competitor_intensity?: number;
  competitor_intensity_pct?: number;
  province: string;
  is_rural_h3: 0 | 1;
  routing_status: RoutingStatus;
  households?: number;
  cluster_id?: number;
  data_confidence: 0 | 1;
  /** r7 layer only */
  pending_share?: number;
}

/** One of up to three routes shown when a hex is selected (DATA_CONTRACT §5.4). */
export interface HexRoute {
  rank: 1 | 2 | 3; // final rank by driving time
  store_id: string;
  store_name: string;
  banner: string;
  driving_minutes: number | null;
  driving_km: number | null;
  straight_line_km: number;
  straight_line_rank: number;
  store_lat: number;
  store_lon: number;
  null_route: boolean;
}

/** Full per-hex record fetched from details/{h3_id[:5]}.json on click. */
export interface HexDetail extends HexTileProps {
  population?: number;
  base_addressable_demand?: number;
  addressable_household_demand?: number;
  demand_index_per_household?: number;
  income_factor?: number;
  housing_factor?: number;
  family_factor?: number;
  age_factor?: number;
  stabilized_income?: number;
  ground_oriented_share?: number;
  high_rise_share?: number;
  family_share?: number;
  age_25_64_share?: number;
  national_demand_rank?: number;
  province_demand_rank?: number;
  province_demand_percentile?: number;
  access_gap_pct?: number;
  opportunity_pct?: number;
  competitors_within_5km?: number;
  competitors_within_10km?: number;
  nearest_competitor_km?: number;
  nearest_competitor_chain?: string;
  nearest_competitor_type?: CompetitorType;
  contributing_postal_code_count?: number;
  coordinate_precision_flag?: "urban_local" | "rural_fsa_centroid_imprecise";
  flag_income_imputed?: boolean;
  flag_extreme_demand_index?: boolean;
  routes: HexRoute[];
  origin: { lat: number; lon: number };
}

/** shard file shape: { [prefix]: { [h3_id]: HexDetail } } */
export type DetailShard = Record<string, Record<string, HexDetail>>;

export interface StoreProps {
  kind: "network" | "competitor";
  id: string;
  name: string;
  banner_or_chain: string;
  competitor_type: CompetitorType | null;
  city: string;
  province: string;
  address: string;
}

export interface ClusterProps {
  cluster_id: number;
  hex_count: number;
  total_addressable_demand: number;
  mean_opportunity_score: number;
  dominant_class: MarketClass;
  province: string;
  anchor_city: string;
}

export interface ClusterListEntry extends ClusterProps {
  centroid_lat: number;
  centroid_lon: number;
  bbox: [number, number, number, number];
  member_h3_ids: string[];
}

export interface Meta {
  generated_at: string;
  routing_coverage: { total: number; ok: number; no_route: number; pending: number };
  score_weights: { demand: number; access: number; competition: number };
  class_thresholds: Record<string, number>;
  /**
   * Min opportunity_score to be in the top X% of true_whitespace hexes.
   * Keys are percentile cut sizes as strings: "5", "10", "15", …
   */
  true_whitespace_top_thresholds?: Record<string, number>;
  metric_domains: Record<string, { breaks: number[]; min?: number; max?: number }>;
  provinces: string[];
  counts: { hexes: number; network_stores: number; competitors: number; clusters: number };
}

export interface SearchEntry {
  label: string;
  kind: "fsa" | "store";
  lat: number;
  lon: number;
  zoom: number;
}

/** Top-X% cut of true whitespace by opportunity score (null = filter off). */
export type TopTrueWhitespacePct = 5 | 10 | 15 | 20 | 25 | 50;

export interface Filters {
  demandPctRange: [number, number]; // 0..1
  nearestPvMinutesRange: [number, number];
  competitorIntensityRange: [number, number];
  opportunityScoreRange: [number, number]; // 0..100
  provinces: string[]; // empty = all
  urbanRural: "all" | "urban" | "rural";
  /** Opt-in for true_whitespace / proven_market; other classes: empty = all others */
  marketClasses: MarketClass[];
  /**
   * When set, only true_whitespace hexes in the top X% by opportunity score are shown.
   * While active, other market classes are forced off. Checking any other class clears this.
   */
  topTrueWhitespacePct: TopTrueWhitespacePct | null;
  /**
   * When true, an empty other-class selection means show none (not all).
   * Set by the top-true-whitespace filter so choropleth classes stay hidden after it turns off
   * via checking proven market.
   */
  hideOtherClasses: boolean;
}

export interface LayerToggles {
  clusters: boolean;
  networkStores: boolean;
  competitorTypes: Record<CompetitorType, boolean>;
  postalPoints: boolean;
  whitespaceSpotlight: boolean;
}

export interface Selection {
  kind: "hex" | "cluster";
  id: string; // h3_id or cluster_id as string
}
