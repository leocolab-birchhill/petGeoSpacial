import { create } from "zustand";
import type { Filters, LayerToggles, Meta, MetricId, Selection } from "../types";
import type { AppTab } from "../types/dashboard";
import { DEFAULT_METRIC } from "../config/metrics";

export const DEFAULT_FILTERS: Filters = {
  demandPctRange: [0, 1],
  nearestPvMinutesRange: [0, 240],
  competitorIntensityRange: [0, 999],
  opportunityScoreRange: [0, 100],
  provinces: [],
  urbanRural: "all",
  // Opt-in overlays on; empty "other" selection = all other classes shown
  marketClasses: ["true_whitespace", "proven_market_no_pv"],
  topTrueWhitespacePct: null,
  hideOtherClasses: false,
};

export const DEFAULT_TOGGLES: LayerToggles = {
  clusters: true,
  networkStores: true,
  competitorTypes: {
    mass_merchant: true,
    specialty_chain: true,
    independent_boutique: true,
    services_other: false,
  },
  postalPoints: false,
  whitespaceSpotlight: false,
};

interface AppState {
  meta: Meta | null;
  tab: AppTab;
  metric: MetricId;
  filters: Filters;
  toggles: LayerToggles;
  selection: Selection | null;

  setMeta: (m: Meta) => void;
  setTab: (t: AppTab) => void;
  setMetric: (m: MetricId) => void;
  setFilters: (patch: Partial<Filters>) => void;
  resetFilters: () => void;
  setToggles: (patch: Partial<LayerToggles>) => void;
  select: (s: Selection | null) => void;
}

/**
 * Single app store. MapView subscribes to metric/filters/toggles and converts
 * them to MapLibre paint/filter expressions (lib/expressions in MapView/);
 * lib/urlState.ts serializes metric+filters+viewport into location.hash.
 */
export const useAppState = create<AppState>((set) => ({
  meta: null,
  tab: "map",
  metric: DEFAULT_METRIC,
  filters: DEFAULT_FILTERS,
  toggles: DEFAULT_TOGGLES,
  selection: null,

  setMeta: (meta) => set({ meta }),
  setTab: (tab) => set({ tab }),
  setMetric: (metric) => set({ metric }),
  setFilters: (patch) => set((s) => ({ filters: { ...s.filters, ...patch } })),
  resetFilters: () => set({ filters: DEFAULT_FILTERS }),
  setToggles: (patch) => set((s) => ({ toggles: { ...s.toggles, ...patch } })),
  select: (selection) => set({ selection }),
}));
