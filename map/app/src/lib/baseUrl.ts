/** Prefix a root-absolute path with Vite's base (e.g. `/petGeoSpacial/` on GitHub Pages). */
export function assetUrl(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  const normalized = path.startsWith("/") ? path.slice(1) : path;
  return `${base}${normalized}`;
}
