/** Source/layer ids, urls and zoom policy — single place to tune. */

import { assetUrl } from "../lib/baseUrl";

export const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
// Fallback if OpenFreeMap is unreachable (corporate proxy etc.): CARTO raster.
export const BASEMAP_FALLBACK_RASTER =
  "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png";

export function pmtilesUrl(path: string): string {
  // Absolute origin required so the pmtiles protocol can HTTP-range-fetch cleanly.
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `pmtiles://${origin}${assetUrl(path)}`;
}

export const SOURCES = {
  hexes: { id: "hexes", path: "/tiles/hexes.pmtiles" },
  postal: { id: "postal", path: "/tiles/postal.pmtiles" },
  stores: { id: "stores", url: assetUrl("/data/stores.geojson") },
  clusters: { id: "clusters", url: assetUrl("/data/clusters.geojson") },
  /** true_whitespace + proven_market_no_pv hex centroids — MapLibre-clustered when zoomed out */
  whitespace: { id: "whitespace", url: assetUrl("/data/whitespace_points.geojson") },
  /** in-memory GeoJSON source for the 3 selection route lines */
  routeLines: { id: "route-lines" },
} as const;

export const LAYERS = {
  hexFillR7: "hex-fill-r7",
  hexFillR8: "hex-fill-r8",
  hexLineR8: "hex-line-r8",
  /** Opt-in translucent fills + dual-ring outlines (only when Market class checkbox on) */
  hexWhitespaceFillR7: "hex-whitespace-fill-r7",
  hexWhitespaceFillR8: "hex-whitespace-fill-r8",
  hexWhitespaceHaloR7: "hex-whitespace-halo-r7",
  hexWhitespaceHaloR8: "hex-whitespace-halo-r8",
  hexWhitespaceLineR7: "hex-whitespace-line-r7",
  hexWhitespaceLineR8: "hex-whitespace-line-r8",
  hexProvenFillR7: "hex-proven-fill-r7",
  hexProvenFillR8: "hex-proven-fill-r8",
  hexProvenLineR7: "hex-proven-line-r7",
  hexProvenLineR8: "hex-proven-line-r8",
  hexPendingHatch: "hex-pending-hatch",
  hexSelected: "hex-selected",
  clusterFill: "cluster-fill",
  clusterOutline: "cluster-outline",
  /** Zoomed-out whitespace point clusters */
  wsClusters: "ws-clusters",
  wsClusterCount: "ws-cluster-count",
  wsPoints: "ws-points",
  storeClusters: "store-clusters",
  storeClusterCount: "store-cluster-count",
  storeNetwork: "store-network",
  storeCompetitor: "store-competitor",
  postalPoints: "postal-points",
  routeLines: "route-lines",
  routeLabels: "route-labels",
} as const;

export const ZOOM = {
  /** r7 visible below, r8 at/above */
  hexHandoff: 6.5,
  /** store markers: clustered below, individual at/above */
  storeUncluster: 9,
  /** whitespace point clusters break apart by this zoom */
  whitespaceUncluster: 8,
  /** show filled cluster polygons / hex greens strongly from here */
  whitespacePolygons: 7.0,
  /** postal points appear */
  postalMin: 11,
} as const;

export const WHITESPACE_GREEN = "#1b5e20"; // bold inner stroke / fill accent
export const WHITESPACE_HALO = "#81c784"; // soft outer ring
export const WHITESPACE_FILL = "#2e7d32";
export const PROVEN_BLUE = "#1565c0";
export const PROVEN_FILL_OPACITY = 0.24;
export const WHITESPACE_FILL_OPACITY = 0.42;

/** First-load framing: Ottawa–Gatineau — dense hex mix (infill, weak, proven, true WS). */
export const INITIAL_VIEW = {
  center: [-75.7, 45.4] as [number, number],
  /** Just past storeUncluster so Pet Valu logo markers appear (not clusters). */
  zoom: 9.15,
  minZoom: 3,
  maxZoom: 15,
};
