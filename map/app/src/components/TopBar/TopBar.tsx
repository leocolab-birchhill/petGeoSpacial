import { useEffect, useMemo, useState } from "react";
import { METRICS } from "../../config/metrics";
import { useAppState } from "../../state/useAppState";
import { assetUrl } from "../../lib/baseUrl";
import { getMap } from "../../lib/mapRef";
import type { MetricId, SearchEntry } from "../../types";

export default function TopBar({
  onOpenHelp,
  showDashboardHint = false,
}: {
  onOpenHelp: () => void;
  showDashboardHint?: boolean;
}) {
  const tab = useAppState((s) => s.tab);
  const setTab = useAppState((s) => s.setTab);
  const metric = useAppState((s) => s.metric);
  const setMetric = useAppState((s) => s.setMetric);
  const filters = useAppState((s) => s.filters);
  const setFilters = useAppState((s) => s.setFilters);
  const meta = useAppState((s) => s.meta);

  const [q, setQ] = useState("");
  const [index, setIndex] = useState<SearchEntry[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch(assetUrl("/data/fsa_index.json"))
      .then((r) => r.json())
      .then((d) => setIndex(d.search ?? []))
      .catch(() => undefined);
  }, []);

  const hits = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (needle.length < 2) return [];
    return index.filter((e) => e.label.toLowerCase().includes(needle)).slice(0, 12);
  }, [q, index]);

  const coverage = meta?.routing_coverage;
  const pct = coverage ? Math.round((100 * coverage.ok) / coverage.total) : null;

  return (
    <header className="topbar">
      <div className="brand">Pet Valu Whitespace</div>
      <div className="tab-nav-wrap">
        <nav className="tab-nav" aria-label="Primary">
          <button
            type="button"
            className={tab === "map" ? "tab active" : "tab"}
            onClick={() => setTab("map")}
          >
            Map
          </button>
          <button
            type="button"
            className={tab === "dashboard" ? "tab active" : "tab"}
            onClick={() => setTab("dashboard")}
          >
            Dashboard
          </button>
        </nav>
        {showDashboardHint && tab !== "dashboard" && (
          <div className="dash-hint" role="status">
            <span className="dash-hint-arrow" aria-hidden>
              ↑
            </span>
            Try the Dashboard
          </div>
        )}
      </div>
      <button type="button" className="help-btn" onClick={onOpenHelp} title="How to use this map">
        Help
      </button>

      <div className="search-wrap" style={{ display: tab === "map" ? undefined : "none" }}>
        <input
          className="search"
          placeholder="Search FSA or store…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
        {open && hits.length > 0 && (
          <ul className="search-results">
            {hits.map((h) => (
              <li
                key={h.label + h.lat}
                onMouseDown={() => {
                  getMap()?.flyTo({ center: [h.lon, h.lat], zoom: h.zoom, essential: true });
                  setQ(h.label);
                  setOpen(false);
                }}
              >
                <span className="muted">{h.kind}</span> {h.label}
              </li>
            ))}
          </ul>
        )}
      </div>

      {tab === "map" && (
        <>
          <label className="field">
            Province
            <select
              value={filters.provinces[0] ?? ""}
              onChange={(e) =>
                setFilters({ provinces: e.target.value ? [e.target.value] : [] })
              }
            >
              <option value="">All</option>
              {(meta?.provinces ?? []).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            Metric
            <select value={metric} onChange={(e) => setMetric(e.target.value as MetricId)}>
              {METRICS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {pct != null && (
        <div className="coverage-chip" title="Cached Mapbox Matrix coverage — no new API calls">
          Routing {pct}%
        </div>
      )}
    </header>
  );
}
