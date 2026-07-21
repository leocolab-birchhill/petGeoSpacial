import { useEffect, useRef } from "react";
import maplibregl, { type MapLayerMouseEvent, type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useAppState } from "../../state/useAppState";
import {
  BASEMAP_STYLE_URL,
  INITIAL_VIEW,
  LAYERS,
  PROVEN_BLUE,
  PROVEN_FILL_OPACITY,
  SOURCES,
  WHITESPACE_FILL,
  WHITESPACE_FILL_OPACITY,
  WHITESPACE_GREEN,
  WHITESPACE_HALO,
  ZOOM,
  pmtilesUrl,
} from "../../config/layers";
import {
  COMPETITOR_TYPE_STYLE,
  NETWORK_MARKER_ICON,
  NETWORK_MARKER_ICON_SIZE,
  NETWORK_MARKER_URL,
} from "../../config/classification";
import { assetUrl } from "../../lib/baseUrl";
import { fetchHexDetail } from "../../lib/detailsClient";
import { setMap } from "../../lib/mapRef";
import { decodeUrlState, encodeUrlState } from "../../lib/urlState";
import { fmtKm, fmtMinutes } from "../../lib/format";
import {
  buildFillColor,
  buildHexFilter,
  buildOptInClassFilter,
  buildSpotlightOpacity,
} from "./expressions";
import type { Meta } from "../../types";

function makeHatchImage(): ImageData {
  const size = 16;
  const data = new Uint8ClampedArray(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const on = (x + y) % 4 === 0;
      data[i] = on ? 120 : 245;
      data[i + 1] = on ? 120 : 245;
      data[i + 2] = on ? 120 : 245;
      data[i + 3] = on ? 140 : 0;
    }
  }
  return new ImageData(data, size, size);
}

async function addLayers(map: maplibregl.Map) {
  map.addSource(SOURCES.hexes.id, {
    type: "vector",
    url: pmtilesUrl(SOURCES.hexes.path),
    promoteId: "h3_id",
  });
  map.addSource(SOURCES.postal.id, {
    type: "vector",
    url: pmtilesUrl(SOURCES.postal.path),
  });
  map.addSource(SOURCES.stores.id, {
    type: "geojson",
    data: SOURCES.stores.url,
    cluster: true,
    clusterMaxZoom: ZOOM.storeUncluster - 1,
    clusterRadius: 42,
  });
  map.addSource(SOURCES.clusters.id, {
    type: "geojson",
    data: SOURCES.clusters.url,
  });
  map.addSource(SOURCES.whitespace.id, {
    type: "geojson",
    data: SOURCES.whitespace.url,
    cluster: true,
    clusterMaxZoom: ZOOM.whitespaceUncluster - 1,
    clusterRadius: 56,
    clusterMinPoints: 2,
  });
  map.addSource(SOURCES.routeLines.id, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });

  if (!map.hasImage("hatch")) {
    map.addImage("hatch", makeHatchImage(), { pixelRatio: 1 });
  }
  if (!map.hasImage(NETWORK_MARKER_ICON)) {
    try {
      const img = await map.loadImage(NETWORK_MARKER_URL);
      if (!map.hasImage(NETWORK_MARKER_ICON)) {
        map.addImage(NETWORK_MARKER_ICON, img.data, { pixelRatio: 1 });
      }
    } catch (err) {
      console.warn("Failed to load Pet Valu marker icon", err);
    }
  }

  map.addLayer({
    id: LAYERS.hexFillR7,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r7",
    maxzoom: ZOOM.hexHandoff,
    paint: {
      "fill-color": "#cfd8dc",
      "fill-opacity": 0.72,
      "fill-outline-color": "rgba(255,255,255,0.25)",
    },
  });

  map.addLayer({
    id: LAYERS.hexFillR8,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    paint: {
      "fill-color": "#cfd8dc",
      "fill-opacity": 0.72,
    },
  });

  map.addLayer({
    id: LAYERS.hexLineR8,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    paint: {
      "line-color": "rgba(255,255,255,0.35)",
      "line-width": 0.4,
    },
  });

  // True whitespace: translucent fill + dual-ring (soft halo + bold inner stroke)
  // Proven: lighter fill + thinner stroke so it doesn't out-compete whitespace
  map.addLayer({
    id: LAYERS.hexWhitespaceFillR7,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r7",
    maxzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "true_whitespace"],
    paint: { "fill-color": WHITESPACE_FILL, "fill-opacity": WHITESPACE_FILL_OPACITY },
  });
  map.addLayer({
    id: LAYERS.hexWhitespaceFillR8,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "true_whitespace"],
    paint: { "fill-color": WHITESPACE_FILL, "fill-opacity": WHITESPACE_FILL_OPACITY },
  });
  map.addLayer({
    id: LAYERS.hexWhitespaceHaloR7,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r7",
    maxzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "true_whitespace"],
    paint: { "line-color": WHITESPACE_HALO, "line-width": 4.5, "line-opacity": 0.65, "line-blur": 0.4 },
  });
  map.addLayer({
    id: LAYERS.hexWhitespaceHaloR8,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "true_whitespace"],
    paint: { "line-color": WHITESPACE_HALO, "line-width": 5, "line-opacity": 0.7, "line-blur": 0.5 },
  });
  map.addLayer({
    id: LAYERS.hexWhitespaceLineR7,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r7",
    maxzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "true_whitespace"],
    paint: { "line-color": WHITESPACE_GREEN, "line-width": 2.2, "line-opacity": 1 },
  });
  map.addLayer({
    id: LAYERS.hexWhitespaceLineR8,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "true_whitespace"],
    paint: { "line-color": WHITESPACE_GREEN, "line-width": 2.4, "line-opacity": 1 },
  });
  map.addLayer({
    id: LAYERS.hexProvenFillR7,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r7",
    maxzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "proven_market_no_pv"],
    paint: { "fill-color": PROVEN_BLUE, "fill-opacity": PROVEN_FILL_OPACITY },
  });
  map.addLayer({
    id: LAYERS.hexProvenFillR8,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "proven_market_no_pv"],
    paint: { "fill-color": PROVEN_BLUE, "fill-opacity": PROVEN_FILL_OPACITY },
  });
  map.addLayer({
    id: LAYERS.hexProvenLineR7,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r7",
    maxzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "proven_market_no_pv"],
    paint: { "line-color": PROVEN_BLUE, "line-width": 0.9, "line-opacity": 0.7 },
  });
  map.addLayer({
    id: LAYERS.hexProvenLineR8,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    layout: { visibility: "none" },
    filter: ["==", ["get", "market_class"], "proven_market_no_pv"],
    paint: { "line-color": PROVEN_BLUE, "line-width": 1.0, "line-opacity": 0.75 },
  });

  map.addLayer({
    id: LAYERS.hexPendingHatch,
    type: "fill",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    filter: ["!=", ["get", "routing_status"], "ok"],
    paint: {
      "fill-pattern": "hatch",
      "fill-opacity": 0.55,
    },
  });

  map.addLayer({
    id: LAYERS.hexSelected,
    type: "line",
    source: SOURCES.hexes.id,
    "source-layer": "h3_r8",
    minzoom: ZOOM.hexHandoff,
    filter: ["==", ["get", "h3_id"], ""],
    paint: {
      "line-color": "#111",
      "line-width": 2.5,
    },
  });

  // Contiguous opportunity clusters — only when matching Market class is checked
  map.addLayer({
    id: LAYERS.clusterFill,
    type: "fill",
    source: SOURCES.clusters.id,
    minzoom: ZOOM.whitespacePolygons,
    layout: { visibility: "none" },
    paint: {
      "fill-color": [
        "match",
        ["get", "dominant_class"],
        "true_whitespace",
        WHITESPACE_GREEN,
        "proven_market_no_pv",
        PROVEN_BLUE,
        WHITESPACE_GREEN,
      ],
      "fill-opacity": 0.22,
    },
  });
  map.addLayer({
    id: LAYERS.clusterOutline,
    type: "line",
    source: SOURCES.clusters.id,
    minzoom: ZOOM.whitespacePolygons,
    layout: { visibility: "none" },
    paint: {
      "line-color": [
        "match",
        ["get", "dominant_class"],
        "true_whitespace",
        WHITESPACE_GREEN,
        "proven_market_no_pv",
        PROVEN_BLUE,
        WHITESPACE_GREEN,
      ],
      "line-width": 2.2,
      "line-opacity": 0.95,
    },
  });

  // Zoomed-out markers (cluster → disperse) — only for checked Market classes
  map.addLayer({
    id: LAYERS.wsClusters,
    type: "circle",
    source: SOURCES.whitespace.id,
    filter: ["has", "point_count"],
    maxzoom: ZOOM.whitespacePolygons + 1.5,
    layout: { visibility: "none" },
    paint: {
      "circle-color": WHITESPACE_GREEN,
      "circle-radius": ["step", ["get", "point_count"], 16, 10, 20, 40, 26, 100, 32],
      "circle-opacity": 0.85,
      "circle-stroke-width": 2.5,
      "circle-stroke-color": "#fff",
    },
  });
  map.addLayer({
    id: LAYERS.wsClusterCount,
    type: "symbol",
    source: SOURCES.whitespace.id,
    filter: ["has", "point_count"],
    maxzoom: ZOOM.whitespacePolygons + 1.5,
    layout: {
      visibility: "none",
      "text-field": ["to-string", ["get", "point_count"]],
      "text-size": 12,
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#fff",
      "text-halo-color": "rgba(0,0,0,0.25)",
      "text-halo-width": 0.5,
    },
  });
  map.addLayer({
    id: LAYERS.wsPoints,
    type: "circle",
    source: SOURCES.whitespace.id,
    filter: ["!", ["has", "point_count"]],
    maxzoom: ZOOM.whitespacePolygons + 0.8,
    layout: { visibility: "none" },
    paint: {
      "circle-color": [
        "match",
        ["get", "market_class"],
        "proven_market_no_pv",
        PROVEN_BLUE,
        WHITESPACE_GREEN,
      ],
      "circle-radius": 6,
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#fff",
      "circle-opacity": 0.85,
    },
  });

  map.addLayer({
    id: LAYERS.routeLines,
    type: "line",
    source: SOURCES.routeLines.id,
    paint: {
      "line-color": ["match", ["get", "rank"], 1, "#c62828", 2, "#ef6c00", "#1565c0"],
      "line-width": ["match", ["get", "rank"], 1, 3, 2, 2.2, 1.6],
      "line-dasharray": [2, 1.5],
    },
  });

  map.addLayer({
    id: LAYERS.routeLabels,
    type: "symbol",
    source: SOURCES.routeLines.id,
    layout: {
      "symbol-placement": "line-center",
      "text-field": ["get", "label"],
      "text-size": 11,
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#212121",
      "text-halo-color": "#fff",
      "text-halo-width": 1.5,
    },
  });

  map.addLayer({
    id: LAYERS.storeClusters,
    type: "circle",
    source: SOURCES.stores.id,
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#455a64",
      "circle-radius": ["step", ["get", "point_count"], 14, 25, 18, 80, 24],
      "circle-opacity": 0.85,
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#fff",
    },
  });

  map.addLayer({
    id: LAYERS.storeClusterCount,
    type: "symbol",
    source: SOURCES.stores.id,
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-size": 11,
    },
    paint: { "text-color": "#fff" },
  });

  // Pet Valu network — circular logo + bright blue outline (baked into PNG)
  map.addLayer({
    id: LAYERS.storeNetwork,
    type: "symbol",
    source: SOURCES.stores.id,
    filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "kind"], "network"]],
    layout: {
      "icon-image": NETWORK_MARKER_ICON,
      "icon-size": NETWORK_MARKER_ICON_SIZE,
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "icon-padding": 0,
    },
  });

  // Competitors: specialty = red, mass merchant = black (see COMPETITOR_TYPE_STYLE)
  const typeColors: unknown[] = ["match", ["get", "competitor_type"]];
  for (const [t, style] of Object.entries(COMPETITOR_TYPE_STYLE)) {
    typeColors.push(t, style.color);
  }
  typeColors.push("#546e7a");

  map.addLayer({
    id: LAYERS.storeCompetitor,
    type: "circle",
    source: SOURCES.stores.id,
    filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "kind"], "competitor"]],
    paint: {
      "circle-color": typeColors as maplibregl.ExpressionSpecification,
      "circle-radius": 4.5,
      "circle-stroke-width": 1,
      "circle-stroke-color": "#fff",
    },
  });

  map.addLayer({
    id: LAYERS.postalPoints,
    type: "circle",
    source: SOURCES.postal.id,
    "source-layer": "postal",
    minzoom: ZOOM.postalMin,
    layout: { visibility: "none" },
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["to-number", ["get", "households"]],
        0,
        1.2,
        200,
        2.5,
        800,
        4,
      ],
      "circle-color": "#5c6bc0",
      "circle-opacity": 0.55,
    },
  });
}

function applyStyle(
  map: maplibregl.Map,
  metric: ReturnType<typeof useAppState.getState>["metric"],
  filters: ReturnType<typeof useAppState.getState>["filters"],
  toggles: ReturnType<typeof useAppState.getState>["toggles"],
  meta: Meta | null,
) {
  const color = buildFillColor(metric, meta);
  const filter = buildHexFilter(filters);
  const opacity = buildSpotlightOpacity(toggles.whitespaceSpotlight);

  for (const id of [LAYERS.hexFillR7, LAYERS.hexFillR8]) {
    if (map.getLayer(id)) {
      map.setPaintProperty(id, "fill-color", color);
      map.setPaintProperty(id, "fill-opacity", opacity);
      map.setFilter(id, filter);
    }
  }
  if (map.getLayer(LAYERS.hexLineR8)) map.setFilter(LAYERS.hexLineR8, filter);

  const showTrueWs = filters.marketClasses.includes("true_whitespace");
  const showProven = filters.marketClasses.includes("proven_market_no_pv");
  const wsFilter = buildOptInClassFilter(filters, "true_whitespace", meta);
  const provenFilter = buildOptInClassFilter(filters, "proven_market_no_pv", meta);
  const twTopThr =
    filters.topTrueWhitespacePct != null
      ? meta?.true_whitespace_top_thresholds?.[String(filters.topTrueWhitespacePct)]
      : null;
  const wsFillOp = toggles.whitespaceSpotlight ? 0.55 : WHITESPACE_FILL_OPACITY;
  const provenFillOp = toggles.whitespaceSpotlight ? 0.35 : PROVEN_FILL_OPACITY;

  for (const id of [LAYERS.hexWhitespaceFillR7, LAYERS.hexWhitespaceFillR8]) {
    if (!map.getLayer(id)) continue;
    map.setFilter(id, wsFilter);
    map.setPaintProperty(id, "fill-opacity", wsFillOp);
    map.setLayoutProperty(id, "visibility", showTrueWs ? "visible" : "none");
  }
  for (const id of [
    LAYERS.hexWhitespaceHaloR7,
    LAYERS.hexWhitespaceHaloR8,
    LAYERS.hexWhitespaceLineR7,
    LAYERS.hexWhitespaceLineR8,
  ]) {
    if (!map.getLayer(id)) continue;
    map.setFilter(id, wsFilter);
    map.setLayoutProperty(id, "visibility", showTrueWs ? "visible" : "none");
  }
  for (const id of [LAYERS.hexProvenFillR7, LAYERS.hexProvenFillR8]) {
    if (!map.getLayer(id)) continue;
    map.setFilter(id, provenFilter);
    map.setPaintProperty(id, "fill-opacity", provenFillOp);
    map.setLayoutProperty(id, "visibility", showProven ? "visible" : "none");
  }
  for (const id of [LAYERS.hexProvenLineR7, LAYERS.hexProvenLineR8]) {
    if (!map.getLayer(id)) continue;
    map.setFilter(id, provenFilter);
    map.setLayoutProperty(id, "visibility", showProven ? "visible" : "none");
  }

  // Hatch layer retired — cache pull complete; no pending_routing class remains
  if (map.getLayer(LAYERS.hexPendingHatch)) {
    map.setLayoutProperty(LAYERS.hexPendingHatch, "visibility", "none");
  }

  // Cluster markers / outlines only when layer toggle on AND at least one opt-in class checked
  const anyOptIn = showTrueWs || showProven;
  const clusterVis = toggles.clusters && anyOptIn ? "visible" : "none";
  for (const id of [LAYERS.clusterFill, LAYERS.clusterOutline, LAYERS.wsPoints]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", clusterVis);
  }
  // Aggregate cluster bubbles can't apply a score cut cleanly — hide them in top-TW mode
  const bubbleVis = clusterVis !== "none" && twTopThr == null ? "visible" : "none";
  for (const id of [LAYERS.wsClusters, LAYERS.wsClusterCount]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", bubbleVis);
  }
  if (anyOptIn && map.getLayer(LAYERS.clusterFill)) {
    const allowed = [
      ...(showTrueWs ? ["true_whitespace"] : []),
      ...(showProven ? ["proven_market_no_pv"] : []),
    ];
    const parts: maplibregl.FilterSpecification[] = [
      ["in", ["get", "dominant_class"], ["literal", allowed]] as maplibregl.FilterSpecification,
    ];
    // Top-TW mode: keep true-whitespace-dominant clusters near the score cut
    if (twTopThr != null && Number.isFinite(twTopThr)) {
      parts.push([
        "all",
        ["==", ["get", "dominant_class"], "true_whitespace"],
        [">=", ["to-number", ["get", "mean_opportunity_score"]], twTopThr],
      ] as unknown as maplibregl.FilterSpecification);
    }
    const classFilter = ["all", ...parts] as maplibregl.FilterSpecification;
    map.setFilter(LAYERS.clusterFill, classFilter);
    map.setFilter(LAYERS.clusterOutline, classFilter);
  }
  if (anyOptIn && map.getLayer(LAYERS.wsPoints)) {
    const allowed = [
      ...(showTrueWs ? ["true_whitespace"] : []),
      ...(showProven ? ["proven_market_no_pv"] : []),
    ];
    const pointParts: unknown[] = [
      ["!", ["has", "point_count"]],
      ["in", ["get", "market_class"], ["literal", allowed]],
    ];
    if (twTopThr != null && Number.isFinite(twTopThr)) {
      pointParts.push([
        "all",
        ["==", ["get", "market_class"], "true_whitespace"],
        ["has", "opportunity_score"],
        [">=", ["to-number", ["get", "opportunity_score"]], twTopThr],
      ]);
    }
    map.setFilter(LAYERS.wsPoints, ["all", ...pointParts] as unknown as maplibregl.FilterSpecification);
  }

  map.setLayoutProperty(LAYERS.storeNetwork, "visibility", toggles.networkStores ? "visible" : "none");
  map.setLayoutProperty(LAYERS.storeClusters, "visibility", toggles.networkStores || Object.values(toggles.competitorTypes).some(Boolean) ? "visible" : "none");
  map.setLayoutProperty(LAYERS.storeClusterCount, "visibility", map.getLayoutProperty(LAYERS.storeClusters, "visibility") as string);

  const enabledTypes = Object.entries(toggles.competitorTypes)
    .filter(([, v]) => v)
    .map(([k]) => k);
  if (map.getLayer(LAYERS.storeCompetitor)) {
    map.setFilter(
      LAYERS.storeCompetitor,
      [
        "all",
        ["!", ["has", "point_count"]],
        ["==", ["get", "kind"], "competitor"],
        enabledTypes.length
          ? ["in", ["get", "competitor_type"], ["literal", enabledTypes]]
          : ["==", ["get", "competitor_type"], "__none__"],
      ] as unknown as maplibregl.FilterSpecification,
    );
  }

  map.setLayoutProperty(LAYERS.postalPoints, "visibility", toggles.postalPoints ? "visible" : "none");
}

async function showRoutes(map: maplibregl.Map, h3Id: string) {
  const detail = await fetchHexDetail(h3Id);
  const src = map.getSource(SOURCES.routeLines.id) as GeoJSONSource;
  if (!detail || !detail.routes?.length) {
    src.setData({ type: "FeatureCollection", features: [] });
    return detail;
  }
  const origin = detail.origin;
  const features = detail.routes
    .filter((r) => r.store_lat != null && r.store_lon != null)
    .map((r) => ({
      type: "Feature" as const,
      properties: {
        rank: r.rank,
        label: `${r.rank} · ${fmtMinutes(r.driving_minutes)} · ${fmtKm(r.driving_km)}`,
      },
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [origin.lon, origin.lat],
          [r.store_lon, r.store_lat],
        ],
      },
    }));
  src.setData({ type: "FeatureCollection", features });
  return detail;
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const selectedId = useRef<string | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const metric = useAppState((s) => s.metric);
  const filters = useAppState((s) => s.filters);
  const toggles = useAppState((s) => s.toggles);
  const meta = useAppState((s) => s.meta);
  const selection = useAppState((s) => s.selection);
  const select = useAppState((s) => s.select);
  const setMeta = useAppState((s) => s.setMeta);
  const setMetric = useAppState((s) => s.setMetric);
  const setFilters = useAppState((s) => s.setFilters);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const restored = decodeUrlState(window.location.hash);
    // Always open on the curated first view (ignore saved camera in the hash)
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE_URL,
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
      minZoom: INITIAL_VIEW.minZoom,
      maxZoom: INITIAL_VIEW.maxZoom,
      attributionControl: { compact: true },
      fadeDuration: 0, // snappier layer swaps — reduces sticky feel
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;
    setMap(map);
    popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });

    if (restored.metric) setMetric(restored.metric);
    // Do not restore market-class / top-TW filters from the hash — every reload
    // starts with the curated defaults (all classes visible, Ottawa framing).
    if (restored.filters) {
      const { marketClasses: _c, topTrueWhitespacePct: _t, hideOtherClasses: _h, ...rest } =
        restored.filters;
      if (Object.keys(rest).length) setFilters(rest);
    }

    let cancelled = false;
    fetch(assetUrl("/data/meta.json"))
      .then((r) => r.json())
      .then((m: Meta) => {
        if (!cancelled) setMeta(m);
      })
      .catch(() => undefined);

    map.on("load", () => {
      void addLayers(map).then(() => {
        const state = useAppState.getState();
        applyStyle(map, state.metric, state.filters, state.toggles, state.meta);
      });
    });

    map.on("error", (e) => {
      // Basemap failure → fall back silently is hard; log for debug
      console.warn("MapLibre error", e.error);
    });

    const onClick = async (e: MapLayerMouseEvent) => {
      // Click clustered whitespace marker → zoom to expand
      if (map.getLayer(LAYERS.wsClusters)) {
        const clustered = map.queryRenderedFeatures(e.point, { layers: [LAYERS.wsClusters] });
        if (clustered.length) {
          const f = clustered[0];
          const clusterId = f.properties?.cluster_id as number | undefined;
          const src = map.getSource(SOURCES.whitespace.id) as GeoJSONSource;
          if (clusterId != null && src?.getClusterExpansionZoom) {
            src.getClusterExpansionZoom(clusterId).then((zoom) => {
              const coords = (f.geometry as { type: string; coordinates: [number, number] }).coordinates;
              map.easeTo({ center: coords, zoom });
            });
            return;
          }
        }
      }

      const layerIds = [
        LAYERS.hexWhitespaceFillR8,
        LAYERS.hexProvenFillR8,
        LAYERS.hexFillR8,
        LAYERS.hexWhitespaceFillR7,
        LAYERS.hexProvenFillR7,
        LAYERS.hexFillR7,
        LAYERS.clusterFill,
        LAYERS.clusterOutline,
        LAYERS.wsPoints,
      ].filter((id) => map.getLayer(id));
      const feats = map.queryRenderedFeatures(e.point, { layers: layerIds });
      if (!feats.length) {
        selectedId.current = null;
        select(null);
        if (map.getLayer(LAYERS.hexSelected)) {
          map.setFilter(LAYERS.hexSelected, ["==", ["get", "h3_id"], ""]);
        }
        (map.getSource(SOURCES.routeLines.id) as GeoJSONSource)?.setData({
          type: "FeatureCollection",
          features: [],
        });
        return;
      }
      const f = feats[0];
      if (f.layer.id === LAYERS.clusterOutline || f.layer.id === LAYERS.clusterFill) {
        select({ kind: "cluster", id: String(f.properties?.cluster_id) });
        return;
      }
      const h3Id = String(f.properties?.h3_id ?? "");
      if (!h3Id) return;
      selectedId.current = h3Id;
      select({ kind: "hex", id: h3Id });
      if (map.getLayer(LAYERS.hexSelected)) {
        map.setFilter(LAYERS.hexSelected, ["==", ["get", "h3_id"], h3Id]);
      }
      await showRoutes(map, h3Id);
    };

    map.on("click", onClick);

    map.on("mousemove", LAYERS.hexFillR8, (e) => {
      map.getCanvas().style.cursor = "pointer";
      const f = e.features?.[0];
      if (!f || !popupRef.current) return;
      const props = f.properties ?? {};
      const state = useAppState.getState();
      const field = state.metric === "market_class" ? "market_class" : state.metric;
      const val = props[field];
      popupRef.current
        .setLngLat(e.lngLat)
        .setHTML(`<strong>${props.h3_id ?? ""}</strong><br/>${field}: ${val ?? "—"}`)
        .addTo(map);
    });
    map.on("mouseleave", LAYERS.hexFillR8, () => {
      map.getCanvas().style.cursor = "";
      popupRef.current?.remove();
    });

    let urlTimer: number | undefined;
    map.on("moveend", () => {
      window.clearTimeout(urlTimer);
      urlTimer = window.setTimeout(() => {
        const c = map.getCenter();
        const state = useAppState.getState();
        const hash = encodeUrlState({
          center: [c.lng, c.lat],
          zoom: map.getZoom(),
          metric: state.metric,
          filters: state.filters,
        });
        if (window.location.hash !== hash) {
          history.replaceState(null, "", hash);
        }
      }, 250);
    });

    return () => {
      cancelled = true;
      window.clearTimeout(urlTimer);
      setMap(null);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Expression-only updates — never reload sources (keeps map non-sticky)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    applyStyle(map, metric, filters, toggles, meta);
  }, [metric, filters, toggles, meta]);

  // Keep highlight + routes in sync when selection comes from Dashboard / panel
  // (map clicks also set these; skip duplicate work when already applied)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!map.getLayer(LAYERS.hexSelected)) return;
      if (!selection || selection.kind !== "hex") {
        if (selectedId.current != null) {
          selectedId.current = null;
          map.setFilter(LAYERS.hexSelected, ["==", ["get", "h3_id"], ""]);
          (map.getSource(SOURCES.routeLines.id) as GeoJSONSource)?.setData({
            type: "FeatureCollection",
            features: [],
          });
        }
        return;
      }
      if (selectedId.current === selection.id) return;
      selectedId.current = selection.id;
      map.setFilter(LAYERS.hexSelected, ["==", ["get", "h3_id"], selection.id]);
      void showRoutes(map, selection.id);
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [selection]);

  return <div id="map" ref={containerRef} />;
}
