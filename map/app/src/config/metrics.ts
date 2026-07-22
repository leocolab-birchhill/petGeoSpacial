import type { MetricId } from "../types";

export interface MetricDef {
  id: MetricId;
  label: string;
  /** tile property to colour by */
  field: string;
  kind: "sequential" | "sequential-inverted" | "categorical";
  /** colorbrewer-ish ramp, low -> high (ignored for categorical) */
  ramp: string[];
  format: (v: number) => string;
  description: string;
}

const fmtScore = (v: number) => v.toFixed(0);
const fmtMin = (v: number) => `${v.toFixed(0)} min`;
const fmtDemand = (v: number) =>
  v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0);
const fmtPct = (v: number) => `${(v * 100).toFixed(0)}%`;
const fmtNum = (v: number) => v.toFixed(1);

/**
 * Break values come from meta.json metric_domains at runtime; ramps here.
 * Ramp length must be breaks.length + 1.
 */
export const METRICS: MetricDef[] = [
  {
    id: "opportunity_score",
    label: "Opportunity score",
    field: "opportunity_score",
    kind: "sequential",
    // Yellowish-green scale — keeps true-whitespace forest green as the visual hero
    ramp: ["#faf8e6", "#f0ecc0", "#e2db8c", "#c9c45e", "#aeb042", "#8f9432", "#747828", "#5c6020"],
    format: fmtScore,
    description: "Blend of demand percentile, Pet Valu access gap and competition (weights in meta.json).",
  },
  {
    id: "adjusted_addressable_demand",
    label: "Addressable demand",
    field: "adjusted_addressable_demand",
    kind: "sequential",
    ramp: ["#fcf6ec", "#f7e6c8", "#f0d09a", "#e6b268", "#d98e3d", "#c56a1e", "#a54c0d", "#7d3505"],
    format: fmtDemand,
    description: "Demographically adjusted addressable household demand (model output).",
  },
  {
    id: "nearest_pv_minutes",
    label: "Nearest Pet Valu drive time",
    field: "nearest_pv_minutes",
    kind: "sequential",
    ramp: ["#f2f7fb", "#d9e8f5", "#b7d4ec", "#8bbade", "#5d9bcb", "#3979b5", "#1f5898", "#103d73"],
    format: fmtMin,
    description: "Mapbox driving minutes to the closest network store.",
  },
  {
    id: "avg3_pv_minutes",
    label: "Avg drive time (3 stores)",
    field: "avg3_pv_minutes",
    kind: "sequential",
    ramp: ["#f2f7fb", "#d9e8f5", "#b7d4ec", "#8bbade", "#5d9bcb", "#3979b5", "#1f5898", "#103d73"],
    format: fmtMin,
    description: "Mean Mapbox driving minutes across the three nearest network stores.",
  },
  {
    id: "competitor_intensity",
    label: "Competitor intensity",
    field: "competitor_intensity",
    kind: "sequential",
    ramp: ["#fdf4f3", "#f9dcd9", "#f2bcb7", "#e8938d", "#da6763", "#c53f40", "#a02428", "#751318"],
    format: fmtNum,
    description: "Distance-weighted competitor presence within 15 km (services chains downweighted).",
  },
  {
    id: "national_demand_percentile",
    label: "Demand percentile",
    field: "national_demand_percentile",
    kind: "sequential",
    ramp: ["#f8f5fb", "#e9def1", "#d4bfe4", "#b898d2", "#9a70bd", "#7c4ba5", "#5e2c88", "#411764"],
    format: fmtPct,
    description: "National percentile of adjusted addressable demand.",
  },
  {
    id: "market_class",
    label: "Market classification",
    field: "market_class",
    kind: "categorical",
    ramp: [],
    format: fmtScore,
    description: "Explicit whitespace classification — see legend key.",
  },
];

export const DEFAULT_METRIC: MetricId = "opportunity_score";
