import type { ExpressionSpecification, FilterSpecification } from "maplibre-gl";
import type { Filters, MetricId, Meta } from "../../types";
import { METRICS } from "../../config/metrics";
import {
  MARKET_CLASS_STYLE,
  OPT_IN_MARKET_CLASSES,
  OTHER_MARKET_CLASSES,
} from "../../config/classification";

const MISSING = "#eceff1";

export function buildFillColor(metric: MetricId, meta: Meta | null): ExpressionSpecification {
  if (metric === "market_class") {
    const pairs: unknown[] = [];
    for (const [cls, style] of Object.entries(MARKET_CLASS_STYLE)) {
      pairs.push(cls, style.color);
    }
    return ["match", ["get", "market_class"], ...pairs, MISSING] as unknown as ExpressionSpecification;
  }

  const def = METRICS.find((m) => m.id === metric)!;
  const field = def.field;
  const breaks = meta?.metric_domains?.[field]?.breaks ?? [];
  const ramp = def.ramp;

  if (!breaks.length || ramp.length < 2) {
    return [
      "case",
      ["has", field],
      ramp[Math.floor(ramp.length / 2)] ?? MISSING,
      MISSING,
    ] as ExpressionSpecification;
  }

  const stepArgs: unknown[] = ["step", ["to-number", ["get", field]], ramp[0]];
  const n = Math.min(breaks.length, ramp.length - 1);
  for (let i = 0; i < n; i++) {
    stepArgs.push(breaks[i], ramp[i + 1]);
  }

  return [
    "case",
    ["has", field],
    stepArgs,
    MISSING,
  ] as unknown as ExpressionSpecification;
}

/** Shared non-class filters (province, rural, ranges, pending). */
export function buildSharedFilters(filters: Filters): FilterSpecification[] {
  const all: FilterSpecification[] = [];

  if (filters.provinces.length) {
    all.push(["in", ["get", "province"], ["literal", filters.provinces]] as FilterSpecification);
  }

  if (filters.urbanRural === "urban") {
    all.push(["==", ["get", "is_rural_h3"], 0] as FilterSpecification);
  } else if (filters.urbanRural === "rural") {
    all.push(["==", ["get", "is_rural_h3"], 1] as FilterSpecification);
  }

  const addRange = (field: string, lo: number, hi: number, absLo: number, absHi: number) => {
    if (lo <= absLo && hi >= absHi) return;
    all.push([
      "any",
      ["!", ["has", field]],
      [
        "all",
        [">=", ["to-number", ["get", field]], lo],
        ["<=", ["to-number", ["get", field]], hi],
      ],
    ] as unknown as FilterSpecification);
  };

  addRange("national_demand_percentile", filters.demandPctRange[0], filters.demandPctRange[1], 0, 1);
  addRange("nearest_pv_minutes", filters.nearestPvMinutesRange[0], filters.nearestPvMinutesRange[1], 0, 240);
  addRange("competitor_intensity", filters.competitorIntensityRange[0], filters.competitorIntensityRange[1], 0, 999);
  addRange("opportunity_score", filters.opportunityScoreRange[0], filters.opportunityScoreRange[1], 0, 100);

  return all;
}

function neverMatch(): FilterSpecification {
  return ["==", ["get", "h3_id"], ""] as FilterSpecification;
}

/**
 * Choropleth hex filter: never includes true_whitespace / proven_market (those are
 * opt-in overlays). Other classes: empty selection = all other classes — unless
 * hideOtherClasses / top-true-whitespace mode forces them off.
 */
export function buildHexFilter(filters: Filters): FilterSpecification {
  const all = buildSharedFilters(filters);

  // Always exclude opt-in classes from the base choropleth
  all.push([
    "!",
    ["in", ["get", "market_class"], ["literal", OPT_IN_MARKET_CLASSES]],
  ] as FilterSpecification);

  const otherSelected = filters.marketClasses.filter((c) =>
    (OTHER_MARKET_CLASSES as string[]).includes(c),
  );
  const hideOthers =
    filters.topTrueWhitespacePct != null ||
    (filters.hideOtherClasses && otherSelected.length === 0);

  if (hideOthers) {
    all.push(neverMatch());
  } else if (otherSelected.length) {
    all.push(["in", ["get", "market_class"], ["literal", otherSelected]] as FilterSpecification);
  }

  if (!all.length) return true as unknown as FilterSpecification;
  return ["all", ...all] as FilterSpecification;
}

/** Overlay filter for a single opt-in class + shared filters. */
export function buildOptInClassFilter(
  filters: Filters,
  cls: "true_whitespace" | "proven_market_no_pv",
  meta?: Meta | null,
): FilterSpecification {
  const parts = buildSharedFilters(filters);
  parts.unshift(["==", ["get", "market_class"], cls] as FilterSpecification);

  if (cls === "true_whitespace" && filters.topTrueWhitespacePct != null) {
    const thr = meta?.true_whitespace_top_thresholds?.[String(filters.topTrueWhitespacePct)];
    if (thr != null && Number.isFinite(thr)) {
      parts.push([
        "all",
        ["has", "opportunity_score"],
        [">=", ["to-number", ["get", "opportunity_score"]], thr],
      ] as unknown as FilterSpecification);
    }
  }

  return ["all", ...parts] as FilterSpecification;
}

export function buildSpotlightOpacity(enabled: boolean): ExpressionSpecification | number {
  // Base choropleth (yellow-green scale) — dim harder in spotlight so WS/proven pop
  if (!enabled) return 0.5;
  return 0.12;
}
