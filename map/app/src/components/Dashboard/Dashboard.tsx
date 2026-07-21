import { Fragment, useEffect, useMemo, useState } from "react";
import { MARKET_CLASS_STYLE, OPT_IN_MARKET_CLASSES } from "../../config/classification";
import { DEFAULT_FILTERS, useAppState } from "../../state/useAppState";
import { assetUrl } from "../../lib/baseUrl";
import { getMap } from "../../lib/mapRef";
import { fmtInt, fmtMinutes, fmtPct01 } from "../../lib/format";
import type { ClusterListEntry, MarketClass } from "../../types";
import type { DashboardHex, DashboardPayload } from "../../types/dashboard";

type SortKey = "opportunity_score" | "demand" | "nearest_pv_min" | "comp_intensity" | "demand_pct";

function BarChart({
  items,
  max,
  colorFor,
}: {
  items: { label: string; value: number; color?: string }[];
  max: number;
  colorFor?: (label: string) => string;
}) {
  const m = max || 1;
  return (
    <div className="bar-chart">
      {items.map((it) => (
        <div key={it.label} className="bar-row">
          <div className="bar-label" title={it.label}>
            {it.label}
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${Math.max(2, (100 * it.value) / m)}%`,
                background: it.color ?? colorFor?.(it.label) ?? "#8f9432",
              }}
            />
          </div>
          <div className="bar-val">{fmtInt(it.value)}</div>
        </div>
      ))}
    </div>
  );
}

function StatTile({
  label,
  value,
  unit,
  sub,
  accent,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="stat-tile" style={accent ? { borderTopColor: accent } : undefined}>
      <div className="stat-label">{label}</div>
      <div className="stat-value-row">
        <span className="stat-value">{value}</span>
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
      {sub && <div className="stat-sub muted">{sub}</div>}
    </div>
  );
}

function ExpansionOverview({
  hexes,
  clusters,
  networkStores,
}: {
  hexes: DashboardHex[];
  clusters: ClusterListEntry[];
  networkStores: number;
}) {
  const tw = hexes.filter((h) => h.market_class === "true_whitespace");
  const proven = hexes.filter((h) => h.market_class === "proven_market_no_pv");
  const expandable = [...tw, ...proven];

  const sum = (rows: DashboardHex[], key: "demand" | "households" | "population") =>
    rows.reduce((a, h) => a + (h[key] ?? 0), 0);

  const expDemand = sum(expandable, "demand");
  const expHh = sum(expandable, "households");
  const expPop = sum(expandable, "population");
  const twHh = sum(tw, "households");
  const provenHh = sum(proven, "households");
  const clusterDemand = clusters.reduce((a, c) => a + (c.total_addressable_demand ?? 0), 0);
  const provinces = new Set(expandable.map((h) => h.province)).size;
  const avgDrive =
    expandable.filter((h) => h.nearest_pv_min != null).length > 0
      ? expandable
          .filter((h) => h.nearest_pv_min != null)
          .reduce((a, h) => a + (h.nearest_pv_min ?? 0), 0) /
        expandable.filter((h) => h.nearest_pv_min != null).length
      : null;

  return (
    <div className="dash-card dash-span-2 expansion-overview">
      <div className="expansion-head">
        <div>
          <h3>Expansion opportunity snapshot</h3>
          <p className="muted" style={{ margin: 0 }}>
            High-demand places with weak Pet Valu access — the pool Pet Valu could grow into. Counts
            follow the filters above. A <strong>neighbourhood area</strong> is one map hex (~local
            catchment). “Proven market” is a class name (competitor present, no Pet Valu nearby), not a
            separate unit of measure.
          </p>
        </div>
      </div>
      <div className="stat-tile-grid">
        <StatTile
          label="True whitespace"
          value={fmtInt(tw.length)}
          unit="neighbourhood areas"
          sub={`${fmtInt(twHh)} households in those areas`}
          accent={MARKET_CLASS_STYLE.true_whitespace.color}
        />
        <StatTile
          label="Proven market, no Pet Valu"
          value={fmtInt(proven.length)}
          unit="neighbourhood areas"
          sub={`${fmtInt(provenHh)} households · competitors already nearby`}
          accent={MARKET_CLASS_STYLE.proven_market_no_pv.color}
        />
        <StatTile
          label="Total expansion pool"
          value={fmtInt(expandable.length)}
          unit="neighbourhood areas"
          sub={`${fmtInt(expHh)} households · ${fmtInt(expPop)} people`}
          accent="#37474f"
        />
        <StatTile
          label="Households in expansion pool"
          value={fmtInt(expHh)}
          unit="households"
          sub="Clearest size measure for business planning"
        />
        <StatTile
          label="Population in expansion pool"
          value={fmtInt(expPop)}
          unit="people"
          sub="Residents in true whitespace + proven-market areas"
        />
        <StatTile
          label="Addressable demand index"
          value={fmtInt(expDemand)}
          unit="index"
          sub="Households weighted by local propensity (not dollars)"
        />
        <StatTile
          label="Expandable clusters"
          value={fmtInt(clusters.length)}
          unit="clusters"
          sub={`Adjacent neighbourhood groups · demand index ${fmtInt(clusterDemand)}`}
        />
        <StatTile
          label="Provinces with opportunity"
          value={fmtInt(provinces)}
          unit="provinces"
          sub={
            avgDrive != null
              ? `Avg drive to nearest Pet Valu ${fmtMinutes(avgDrive)} · network ${fmtInt(networkStores)} stores`
              : `Pet Valu network ${fmtInt(networkStores)} stores`
          }
        />
      </div>
    </div>
  );
}

export default function Dashboard() {
  const meta = useAppState((s) => s.meta);
  const setMeta = useAppState((s) => s.setMeta);
  const setTab = useAppState((s) => s.setTab);
  const select = useAppState((s) => s.select);
  const setFilters = useAppState((s) => s.setFilters);

  const [data, setData] = useState<DashboardPayload | null>(null);
  const [clusters, setClusters] = useState<ClusterListEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [province, setProvince] = useState("");
  const [classes, setClasses] = useState<MarketClass[]>([...OPT_IN_MARKET_CLASSES]);
  const [urbanRural, setUrbanRural] = useState<"all" | "urban" | "rural">("all");
  const [scoreMin, setScoreMin] = useState(0);
  const [demandMin, setDemandMin] = useState(0);
  const [maxDrive, setMaxDrive] = useState(240);
  const [sortKey, setSortKey] = useState<SortKey>("demand");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const needMeta = !useAppState.getState().meta;
    Promise.all([
      fetch(assetUrl("/data/dashboard.json")).then((r) => {
        if (!r.ok) throw new Error("dashboard.json missing — re-run pipeline export");
        return r.json();
      }),
      fetch(assetUrl("/data/clusters_list.json")).then((r) => r.json()),
      needMeta ? fetch(assetUrl("/data/meta.json")).then((r) => r.json()) : Promise.resolve(null),
    ])
      .then(([dash, cl, m]) => {
        if (!cancelled) {
          setData(dash);
          setClusters(cl);
          if (m) setMeta(m);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [setMeta]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.hexes.filter((h) => {
      if (province && h.province !== province) return false;
      if (classes.length && !classes.includes(h.market_class)) return false;
      if (urbanRural === "urban" && h.is_rural) return false;
      if (urbanRural === "rural" && !h.is_rural) return false;
      if ((h.opportunity_score ?? -1) < scoreMin) return false;
      if ((h.demand ?? -1) < demandMin) return false;
      if (h.nearest_pv_min != null && h.nearest_pv_min > maxDrive) return false;
      return true;
    });
  }, [data, province, classes, urbanRural, scoreMin, demandMin, maxDrive]);

  const sorted = useMemo(() => {
    const rows = [...filtered];
    rows.sort((a, b) => {
      const av = a[sortKey] ?? (sortDir === "desc" ? -Infinity : Infinity);
      const bv = b[sortKey] ?? (sortDir === "desc" ? -Infinity : Infinity);
      return sortDir === "desc" ? Number(bv) - Number(av) : Number(av) - Number(bv);
    });
    return rows;
  }, [filtered, sortKey, sortDir]);

  const expansionClusters = useMemo(() => {
    return [...clusters]
      .filter((c) =>
        c.dominant_class === "true_whitespace" || c.dominant_class === "proven_market_no_pv",
      )
      .filter((c) => !province || c.province === province)
      .sort((a, b) => b.total_addressable_demand - a.total_addressable_demand);
  }, [clusters, province]);

  const topClusters = useMemo(() => expansionClusters.slice(0, 15), [expansionClusters]);

  const classBars = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.class_counts)
      .map(([label, value]) => ({
        label: MARKET_CLASS_STYLE[label as MarketClass]?.label ?? label,
        value,
        color: MARKET_CLASS_STYLE[label as MarketClass]?.color,
      }))
      .sort((a, b) => b.value - a.value);
  }, [data]);

  const scoreBars = useMemo(() => {
    if (!data) return [];
    const { bins, counts } = data.score_hist;
    return counts.map((value, i) => ({
      label: `${bins[i]}–${bins[i + 1]}`,
      value,
      color: "#8f9432",
    }));
  }, [data]);

  const provBars = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.province_opportunity)
      .map(([label, v]) => ({
        label,
        value: Math.round(v.demand),
        color: "#2e7d32",
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 12);
  }, [data]);

  const flyToHex = (h: DashboardHex) => {
    if (h.lon == null || h.lat == null) return;
    setTab("map");
    // Keep all market classes visible (do not narrow filters to the clicked hex)
    setFilters({
      marketClasses: [...DEFAULT_FILTERS.marketClasses],
      topTrueWhitespacePct: null,
      hideOtherClasses: false,
    });
    // Open detail pane + drive map highlight/routes (MapView syncs on selection)
    select({ kind: "hex", id: h.h3_id });
    window.setTimeout(() => {
      const map = getMap();
      if (!map) return;
      map.resize();
      map.flyTo({ center: [h.lon!, h.lat!], zoom: 11.2, essential: true });
      // Re-assert selection after layout so the right pane mounts reliably
      select({ kind: "hex", id: h.h3_id });
    }, 160);
  };

  const flyToCluster = (c: ClusterListEntry) => {
    setTab("map");
    // Keep all market classes visible (do not narrow filters to the cluster class)
    setFilters({
      marketClasses: [...DEFAULT_FILTERS.marketClasses],
      topTrueWhitespacePct: null,
      hideOtherClasses: false,
    });
    select({ kind: "cluster", id: String(c.cluster_id) });
    window.setTimeout(() => {
      const map = getMap();
      if (!map) return;
      map.resize();
      const [minx, miny, maxx, maxy] = c.bbox;
      map.fitBounds(
        [
          [minx, miny],
          [maxx, maxy],
        ],
        { padding: 80, duration: 800 },
      );
      select({ kind: "cluster", id: String(c.cluster_id) });
    }, 160);
  };

  const toggleClass = (cls: MarketClass) => {
    setClasses((prev) => (prev.includes(cls) ? prev.filter((c) => c !== cls) : [...prev, cls]));
  };

  if (error) {
    return (
      <div className="dashboard">
        <p className="warn">{error}</p>
      </div>
    );
  }

  if (!data || !meta) {
    return (
      <div className="dashboard">
        <p className="muted">Loading dashboard…</p>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="dash-hero">
        <div>
          <h1>Opportunity dashboard</h1>
          <p className="muted">
            {fmtInt(filtered.length)} hexes match filters · {fmtInt(data.hexes.length)} national · routing{" "}
            {Math.round((100 * meta.routing_coverage.ok) / meta.routing_coverage.total)}%
          </p>
        </div>
      </div>

      <div className="dash-filters">
        <label>
          Province
          <select value={province} onChange={(e) => setProvince(e.target.value)}>
            <option value="">All</option>
            {meta.provinces.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label>
          Urban / rural
          <select
            value={urbanRural}
            onChange={(e) => setUrbanRural(e.target.value as "all" | "urban" | "rural")}
          >
            <option value="all">All</option>
            <option value="urban">Urban</option>
            <option value="rural">Rural</option>
          </select>
        </label>
        <label>
          Min opportunity
          <input
            type="number"
            min={0}
            max={100}
            value={scoreMin}
            onChange={(e) => setScoreMin(Number(e.target.value))}
          />
        </label>
        <label>
          Min demand
          <input
            type="number"
            min={0}
            value={demandMin}
            onChange={(e) => setDemandMin(Number(e.target.value))}
          />
        </label>
        <label>
          Max drive (min)
          <input
            type="number"
            min={0}
            max={240}
            value={maxDrive}
            onChange={(e) => setMaxDrive(Number(e.target.value))}
          />
        </label>
        <label>
          Sort by
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="demand">Addressable demand</option>
            <option value="opportunity_score">Opportunity score</option>
            <option value="demand_pct">Demand percentile</option>
            <option value="nearest_pv_min">Nearest PV minutes</option>
            <option value="comp_intensity">Competitor intensity</option>
          </select>
        </label>
        <label>
          Order
          <select value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")}>
            <option value="desc">High → low</option>
            <option value="asc">Low → high</option>
          </select>
        </label>
        <div className="dash-class-toggles">
          {(Object.keys(MARKET_CLASS_STYLE) as MarketClass[])
            .filter((cls) => cls !== "pending_routing")
            .map((cls) => (
            <label key={cls} className="check">
              <input
                type="checkbox"
                checked={classes.includes(cls)}
                onChange={() => toggleClass(cls)}
              />
              <span className="swatch" style={{ background: MARKET_CLASS_STYLE[cls].color }} />
              {MARKET_CLASS_STYLE[cls].label}
            </label>
          ))}
          <button type="button" className="linkish" onClick={() => setClasses([...OPT_IN_MARKET_CLASSES])}>
            Whitespace only
          </button>
          <button
            type="button"
            className="linkish"
            onClick={() =>
              setClasses(
                (Object.keys(MARKET_CLASS_STYLE) as MarketClass[]).filter((c) => c !== "pending_routing"),
              )
            }
          >
            All classes
          </button>
        </div>
      </div>

      <div className="dash-grid">
        <ExpansionOverview
          hexes={filtered}
          clusters={expansionClusters}
          networkStores={meta.counts.network_stores}
        />

        <div className="dash-card">
          <h3>Hexes by market class</h3>
          <BarChart items={classBars} max={Math.max(...classBars.map((b) => b.value), 1)} />
        </div>

        <div className="dash-card">
          <h3>Opportunity score distribution</h3>
          <BarChart items={scoreBars} max={Math.max(...scoreBars.map((b) => b.value), 1)} />
        </div>

        <div className="dash-card">
          <h3>Whitespace / proven demand by province</h3>
          <BarChart items={provBars} max={Math.max(...provBars.map((b) => b.value), 1)} />
        </div>

        <div className="dash-card dash-span-2">
          <h3>Top expandable clusters (by Σ demand)</h3>
          <table className="dash-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Area</th>
                <th>Class</th>
                <th>Hexes</th>
                <th>Σ Demand</th>
                <th>Mean score</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {topClusters.map((c, i) => (
                <tr key={c.cluster_id}>
                  <td>{i + 1}</td>
                  <td>
                    {c.anchor_city}, {c.province}
                  </td>
                  <td>
                    <span className="chip tiny-chip" style={{ background: MARKET_CLASS_STYLE[c.dominant_class].color }}>
                      {MARKET_CLASS_STYLE[c.dominant_class].label}
                    </span>
                  </td>
                  <td>{c.hex_count}</td>
                  <td>{fmtInt(c.total_addressable_demand)}</td>
                  <td>{c.mean_opportunity_score.toFixed(0)}</td>
                  <td>
                    <button type="button" className="linkish" onClick={() => flyToCluster(c)}>
                      View on map
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="dash-card dash-span-2">
          <h3>
            Ranked hexes{" "}
            <span className="muted">
              (showing {Math.min(sorted.length, 100)} of {fmtInt(sorted.length)})
            </span>
          </h3>
          <table className="dash-table">
            <thead>
              <tr>
                <th></th>
                <th>Area</th>
                <th>Province</th>
                <th>Class</th>
                <th>Score</th>
                <th>Demand</th>
                <th>Demand pct</th>
                <th>Nearest PV</th>
                <th>Competition</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, 100).map((h) => {
                const open = expanded === h.h3_id;
                const label = h.place || h.fsa || h.city || h.h3_id.slice(0, 10);
                return (
                  <Fragment key={h.h3_id}>
                    <tr className={open ? "row-open" : undefined}>
                      <td>
                        <button
                          type="button"
                          className="linkish"
                          onClick={() => setExpanded(open ? null : h.h3_id)}
                        >
                          {open ? "▾" : "▸"}
                        </button>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="linkish place-label"
                          title={h.h3_id}
                          onClick={() => flyToHex(h)}
                        >
                          {label}
                        </button>
                      </td>
                      <td>{h.province}</td>
                      <td>
                        <span
                          className="chip tiny-chip"
                          style={{ background: MARKET_CLASS_STYLE[h.market_class].color }}
                        >
                          {MARKET_CLASS_STYLE[h.market_class].label}
                        </span>
                      </td>
                      <td>{h.opportunity_score?.toFixed(0) ?? "—"}</td>
                      <td>{fmtInt(h.demand)}</td>
                      <td>{fmtPct01(h.demand_pct)}</td>
                      <td>{fmtMinutes(h.nearest_pv_min)}</td>
                      <td>{h.comp_intensity?.toFixed(2) ?? "—"}</td>
                      <td>
                        <button type="button" className="linkish" onClick={() => flyToHex(h)}>
                          View on map
                        </button>
                      </td>
                    </tr>
                    {open && (
                      <tr className="row-expand">
                        <td colSpan={10}>
                          <div className="expand-body">
                            <div>
                              {label}
                              {h.fsa ? ` · FSA ${h.fsa}` : ""} · Households {fmtInt(h.households)} ·
                              Population {fmtInt(h.population)} · {h.is_rural ? "Rural" : "Urban"} ·
                              routing {h.routing_status}
                              {h.cluster_id != null ? ` · cluster #${h.cluster_id}` : ""}
                            </div>
                            <div className="muted mono" title="H3 cell id">
                              {h.h3_id}
                            </div>
                            <div className="muted">
                              Avg-3 drive {fmtMinutes(h.avg3_pv_min)} · competition pct{" "}
                              {fmtPct01(h.comp_pct)} · opportunity pct {fmtPct01(h.opportunity_pct)}
                            </div>
                            <button type="button" className="btn" onClick={() => flyToHex(h)}>
                              View on map
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
