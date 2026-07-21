export function fmtMinutes(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v < 60) return `${v.toFixed(1)} min`;
  const h = Math.floor(v / 60);
  return `${h} h ${Math.round(v % 60)} min`;
}

export function fmtKm(v: number | null | undefined): string {
  return v == null ? "—" : `${v.toFixed(1)} km`;
}

export function fmtInt(v: number | null | undefined): string {
  return v == null ? "—" : Math.round(v).toLocaleString("en-CA");
}

export function fmtPct01(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}

export function fmtMoney(v: number | null | undefined): string {
  return v == null ? "—" : `$${Math.round(v).toLocaleString("en-CA")}`;
}
