import type { CompetitorType, MarketClass } from "../types";
import { assetUrl } from "../lib/baseUrl";

/** Opt-in overlays — hidden until their Market class checkbox is checked. */
export const OPT_IN_MARKET_CLASSES: MarketClass[] = ["true_whitespace", "proven_market_no_pv"];

export const OTHER_MARKET_CLASSES: MarketClass[] = [
  "competitive_infill",
  "weak_whitespace",
  "other",
];

export function isOptInMarketClass(cls: MarketClass): boolean {
  return OPT_IN_MARKET_CLASSES.includes(cls);
}

export const MARKET_CLASS_STYLE: Record<
  MarketClass,
  { label: string; color: string; description: string }
> = {
  true_whitespace: {
    label: "True whitespace",
    color: "#2e7d32",
    description: "High demand, poor Pet Valu access, low competition",
  },
  proven_market_no_pv: {
    label: "Proven market, no Pet Valu",
    color: "#1565c0",
    description: "High demand, poor Pet Valu access, meaningful competitor presence",
  },
  competitive_infill: {
    label: "Competitive infill",
    color: "#b8a84a",
    description: "High demand, better Pet Valu access, high competition",
  },
  weak_whitespace: {
    label: "Weak whitespace",
    color: "#d8d48a",
    description: "Low demand, poor access, low competition",
  },
  other: {
    label: "Other",
    color: "#e8e4b0",
    description: "Does not meet any classification thresholds",
  },
  pending_routing: {
    label: "Routing pending",
    color: "#f3f0d4", // + hatch pattern overlay in MapView
    description: "Drive-time data still being pulled from Databricks",
  },
};

export const COMPETITOR_TYPE_STYLE: Record<
  CompetitorType,
  { label: string; color: string; shape: "square" | "triangle" | "diamond" | "cross" }
> = {
  mass_merchant: { label: "Mass merchant", color: "#111111", shape: "square" },
  specialty_chain: { label: "Specialty chain", color: "#d32f2f", shape: "triangle" },
  independent_boutique: { label: "Independent / boutique", color: "#6a1b9a", shape: "diamond" },
  services_other: { label: "Services (vet/groom/daycare)", color: "#546e7a", shape: "cross" },
};

/** Bright blue ring baked into /assets/pet-valu-marker.png */
export const NETWORK_MARKER_ICON = "pet-valu-marker";
export const NETWORK_MARKER_URL = assetUrl("/assets/pet-valu-marker.png");
/** Icon size relative to 64px asset — larger than competitor dots (~9px). */
export const NETWORK_MARKER_ICON_SIZE = 0.42;
