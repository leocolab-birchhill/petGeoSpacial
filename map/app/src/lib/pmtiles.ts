import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";

/** Register the pmtiles:// protocol once, before any map is created. */
export function registerPmtilesProtocol(): void {
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
}
