import type { Map as MapLibreMap } from "maplibre-gl";

/** Module-level map handle so TopBar search can flyTo without prop drilling. */
let map: MapLibreMap | null = null;

export function setMap(m: MapLibreMap | null) {
  map = m;
}

export function getMap(): MapLibreMap | null {
  return map;
}
