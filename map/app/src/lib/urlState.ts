import type { Filters, MetricId } from "../types";

export interface UrlState {
  center: [number, number];
  zoom: number;
  metric: MetricId;
  filters: Partial<Filters>;
}

export function encodeUrlState(s: UrlState): string {
  const p = new URLSearchParams();
  p.set("c", `${s.center[0].toFixed(4)},${s.center[1].toFixed(4)}`);
  p.set("z", s.zoom.toFixed(2));
  p.set("m", s.metric);
  const f = s.filters;
  if (f.provinces?.length) p.set("prov", f.provinces.join(","));
  if (f.urbanRural && f.urbanRural !== "all") p.set("ur", f.urbanRural);
  return "#" + p.toString();
}

export function decodeUrlState(hash: string): Partial<UrlState> {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!raw) return {};
  const p = new URLSearchParams(raw);
  const out: Partial<UrlState> = {};
  const c = p.get("c");
  if (c) {
    const [lon, lat] = c.split(",").map(Number);
    if (Number.isFinite(lon) && Number.isFinite(lat)) out.center = [lon, lat];
  }
  const z = p.get("z");
  if (z && Number.isFinite(Number(z))) out.zoom = Number(z);
  const m = p.get("m");
  if (m) out.metric = m as MetricId;
  const filters: Partial<Filters> = {};
  const prov = p.get("prov");
  if (prov) filters.provinces = prov.split(",").filter(Boolean);
  const ur = p.get("ur");
  if (ur === "urban" || ur === "rural") filters.urbanRural = ur;
  if (Object.keys(filters).length) out.filters = filters;
  return out;
}
