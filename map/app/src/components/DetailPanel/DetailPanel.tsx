import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../state/useAppState";
import { assetUrl } from "../../lib/baseUrl";
import { fetchHexDetail } from "../../lib/detailsClient";
import { MARKET_CLASS_STYLE } from "../../config/classification";
import { fmtInt, fmtKm, fmtMinutes, fmtMoney, fmtPct01 } from "../../lib/format";
import { getMap } from "../../lib/mapRef";
import type { ClusterListEntry, HexDetail } from "../../types";

function mean(vals: (number | null | undefined)[]): number | null {
  const xs = vals.filter((v): v is number => v != null && Number.isFinite(v));
  if (!xs.length) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function sum(vals: (number | null | undefined)[]): number {
  return vals.reduce<number>((a, v) => a + (v != null && Number.isFinite(v) ? v : 0), 0);
}

function FactorBars({
  income,
  housing,
  family,
  age,
}: {
  income?: number | null;
  housing?: number | null;
  family?: number | null;
  age?: number | null;
}) {
  const factors = [
    ["Income", income],
    ["Housing", housing],
    ["Family", family],
    ["Age", age],
  ] as const;
  return (
    <div className="factors">
      <p className="muted tiny" style={{ margin: "0 0 8px" }}>
        Demand multipliers vs national baseline (1.00). Mid tick = average. Combined into
        addressable household demand.
      </p>
      {factors.map(([label, v]) => {
        const val = v ?? 1;
        const pct = Math.max(0, Math.min(100, val * 50));
        return (
          <div key={label} className="factor-row">
            <span>{label}</span>
            <div className="factor-track">
              <div className="factor-fill" style={{ width: `${pct}%` }} />
              <div className="factor-mid" />
            </div>
            <span className="muted">{v != null ? v.toFixed(2) : "—"}</span>
          </div>
        );
      })}
    </div>
  );
}

function HexBody({ detail }: { detail: HexDetail }) {
  const cls = MARKET_CLASS_STYLE[detail.market_class];
  return (
    <>
      <div className="detail-header">
        <span className="chip" style={{ background: cls.color }}>
          {cls.label}
        </span>
        <div className="score">
          {detail.opportunity_score != null ? detail.opportunity_score.toFixed(0) : "—"}
          <small>opportunity</small>
        </div>
        <div className="muted">
          {detail.province} · {detail.is_rural_h3 ? "Rural" : "Urban"}
          {detail.cluster_id != null ? ` · Cluster ${detail.cluster_id}` : ""}
        </div>
        <div className="mono">{detail.h3_id}</div>
      </div>

      <section>
        <h3>Routes to Pet Valu network</h3>
        {detail.routing_status !== "ok" ? (
          <p className="warn">
            {detail.routing_status === "pending"
              ? "Routing unavailable for this hex."
              : "No drivable route in cache (failed request or unreachable destinations)."}
          </p>
        ) : (
          <ul className="routes">
            {detail.routes.map((r) => (
              <li key={r.rank}>
                <strong>#{r.rank}</strong> {r.store_name}{" "}
                <span className="muted">({r.banner})</span>
                <div>
                  {fmtMinutes(r.driving_minutes)} · {fmtKm(r.driving_km)}
                  {r.straight_line_rank !== r.rank && (
                    <span className="muted"> · straight rank {r.straight_line_rank}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="muted tiny">Straight-line path; labels use Mapbox drive times.</p>
      </section>

      <section>
        <h3>Demand</h3>
        <div className="kv">
          <div>Addressable demand</div>
          <div>{fmtInt(detail.adjusted_addressable_demand)}</div>
          <div>National percentile</div>
          <div>{fmtPct01(detail.national_demand_percentile)}</div>
          <div>Province percentile</div>
          <div>{fmtPct01(detail.province_demand_percentile)}</div>
        </div>
        <FactorBars
          income={detail.income_factor}
          housing={detail.housing_factor}
          family={detail.family_factor}
          age={detail.age_factor}
        />
      </section>

      <section>
        <h3>Access</h3>
        <div className="kv">
          <div>Nearest Pet Valu</div>
          <div>{fmtMinutes(detail.nearest_pv_minutes)}</div>
          <div>Avg 3-store time</div>
          <div>{fmtMinutes(detail.avg3_pv_minutes)}</div>
          <div>Access gap percentile</div>
          <div>{fmtPct01(detail.access_gap_pct)}</div>
        </div>
      </section>

      <section>
        <h3>Competition</h3>
        <div className="kv">
          <div>Intensity</div>
          <div>
            {detail.competitor_intensity?.toFixed(2) ?? "—"} ({fmtPct01(detail.competitor_intensity_pct)})
          </div>
          <div>Nearest competitor</div>
          <div>
            {detail.nearest_competitor_chain ?? "—"} · {fmtKm(detail.nearest_competitor_km)}
          </div>
          <div>Within 5 / 10 km</div>
          <div>
            {detail.competitors_within_5km ?? 0} / {detail.competitors_within_10km ?? 0}
          </div>
        </div>
      </section>

      <section>
        <h3>Demographics</h3>
        <div className="kv">
          <div>Households</div>
          <div>{fmtInt(detail.households)}</div>
          <div>Population</div>
          <div>{fmtInt(detail.population)}</div>
          <div>Stabilized income</div>
          <div>{fmtMoney(detail.stabilized_income)}</div>
        </div>
      </section>

      <section>
        <h3>Data quality</h3>
        <div className="kv">
          <div>Postal codes</div>
          <div>{detail.contributing_postal_code_count ?? "—"}</div>
          <div>Precision</div>
          <div>{detail.coordinate_precision_flag ?? "—"}</div>
          <div>Income imputed</div>
          <div>{detail.flag_income_imputed ? "Yes" : "No"}</div>
        </div>
      </section>
    </>
  );
}

function ClusterBody({
  cluster,
  members,
  loading,
  onSelectHex,
}: {
  cluster: ClusterListEntry;
  members: HexDetail[];
  loading: boolean;
  onSelectHex: (id: string) => void;
}) {
  const cls = MARKET_CLASS_STYLE[cluster.dominant_class];
  const agg = useMemo(() => {
    if (!members.length) return null;
    const ruralShare =
      members.filter((m) => m.is_rural_h3).length / Math.max(members.length, 1);
    // Best (lowest) drive-time hex for representative routes
    const withRoutes = [...members]
      .filter((m) => m.routing_status === "ok" && m.routes?.length)
      .sort(
        (a, b) =>
          (a.nearest_pv_minutes ?? 1e9) - (b.nearest_pv_minutes ?? 1e9),
      );
    return {
      demand: sum(members.map((m) => m.adjusted_addressable_demand)),
      demandPct: mean(members.map((m) => m.national_demand_percentile)),
      nearestPv: mean(members.map((m) => m.nearest_pv_minutes)),
      avg3: mean(members.map((m) => m.avg3_pv_minutes)),
      accessGap: mean(members.map((m) => m.access_gap_pct)),
      comp: mean(members.map((m) => m.competitor_intensity)),
      compPct: mean(members.map((m) => m.competitor_intensity_pct)),
      comp5: mean(members.map((m) => m.competitors_within_5km)),
      comp10: mean(members.map((m) => m.competitors_within_10km)),
      nearestCompKm: mean(members.map((m) => m.nearest_competitor_km)),
      nearestCompChain: (() => {
        const chains = members
          .map((m) => m.nearest_competitor_chain)
          .filter((c): c is string => !!c);
        if (!chains.length) return null;
        const tallies = new Map<string, number>();
        for (const c of chains) tallies.set(c, (tallies.get(c) ?? 0) + 1);
        return [...tallies.entries()].sort((a, b) => b[1] - a[1])[0][0];
      })(),
      households: sum(members.map((m) => m.households)),
      population: sum(members.map((m) => m.population)),
      income: mean(members.map((m) => m.stabilized_income)),
      incomeF: mean(members.map((m) => m.income_factor)),
      housingF: mean(members.map((m) => m.housing_factor)),
      familyF: mean(members.map((m) => m.family_factor)),
      ageF: mean(members.map((m) => m.age_factor)),
      ruralShare,
      okRouting: members.filter((m) => m.routing_status === "ok").length,
      noRoute: members.filter((m) => m.routing_status === "no_route").length,
      routesHex: withRoutes[0] ?? null,
      rankedMembers: [...members].sort(
        (a, b) => (b.opportunity_score ?? -1) - (a.opportunity_score ?? -1),
      ),
    };
  }, [members]);

  return (
    <>
      <div className="detail-header">
        <span className="chip" style={{ background: cls.color }}>
          {cls.label}
        </span>
        <div className="score">
          {cluster.mean_opportunity_score?.toFixed(0) ?? "—"}
          <small>mean opportunity</small>
        </div>
        <div>
          {cluster.anchor_city}, {cluster.province} · {cluster.hex_count} hexes
        </div>
        <div className="muted">
          {agg ? `${Math.round(agg.ruralShare * 100)}% rural hexes` : "—"} · Cluster #
          {cluster.cluster_id}
        </div>
      </div>

      <button
        type="button"
        className="btn"
        onClick={() => {
          const [minx, miny, maxx, maxy] = cluster.bbox;
          getMap()?.fitBounds(
            [
              [minx, miny],
              [maxx, maxy],
            ],
            { padding: 60, duration: 800 },
          );
        }}
      >
        Zoom to cluster
      </button>

      {loading && <p className="muted">Loading member metrics…</p>}

      {agg && (
        <>
          <section>
            <h3>Demand</h3>
            <div className="kv">
              <div>Addressable demand Σ</div>
              <div>{fmtInt(agg.demand)}</div>
              <div>Mean national percentile</div>
              <div>{fmtPct01(agg.demandPct)}</div>
            </div>
            <FactorBars
              income={agg.incomeF}
              housing={agg.housingF}
              family={agg.familyF}
              age={agg.ageF}
            />
          </section>

          <section>
            <h3>Access (mean across hexes)</h3>
            <div className="kv">
              <div>Nearest Pet Valu</div>
              <div>{fmtMinutes(agg.nearestPv)}</div>
              <div>Avg 3-store time</div>
              <div>{fmtMinutes(agg.avg3)}</div>
              <div>Access gap percentile</div>
              <div>{fmtPct01(agg.accessGap)}</div>
              <div>Routing coverage</div>
              <div>
                {agg.okRouting}/{members.length} ok
                {agg.noRoute ? ` · ${agg.noRoute} no route` : ""}
              </div>
            </div>
          </section>

          <section>
            <h3>Competition (mean)</h3>
            <div className="kv">
              <div>Intensity</div>
              <div>
                {agg.comp?.toFixed(2) ?? "—"} ({fmtPct01(agg.compPct)})
              </div>
              <div>Nearest competitor</div>
              <div>
                {agg.nearestCompChain ?? "—"} · {fmtKm(agg.nearestCompKm)}
              </div>
              <div>Within 5 / 10 km</div>
              <div>
                {agg.comp5?.toFixed(1) ?? "—"} / {agg.comp10?.toFixed(1) ?? "—"}
              </div>
            </div>
          </section>

          <section>
            <h3>Demographics</h3>
            <div className="kv">
              <div>Households Σ</div>
              <div>{fmtInt(agg.households)}</div>
              <div>Population Σ</div>
              <div>{fmtInt(agg.population)}</div>
              <div>Mean stabilized income</div>
              <div>{fmtMoney(agg.income)}</div>
            </div>
          </section>

          {agg.routesHex && (
            <section>
              <h3>Example routes (best-access hex)</h3>
              <p className="muted tiny mono">{agg.routesHex.h3_id}</p>
              <ul className="routes">
                {agg.routesHex.routes.map((r) => (
                  <li key={r.rank}>
                    <strong>#{r.rank}</strong> {r.store_name}{" "}
                    <span className="muted">({r.banner})</span>
                    <div>
                      {fmtMinutes(r.driving_minutes)} · {fmtKm(r.driving_km)}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h3>Member hexes (by opportunity)</h3>
            <ul className="member-list">
              {agg.rankedMembers.map((m) => (
                <li key={m.h3_id}>
                  <button type="button" className="linkish" onClick={() => onSelectHex(m.h3_id)}>
                    {m.h3_id}
                  </button>
                  <span className="muted">
                    {" "}
                    · score {m.opportunity_score?.toFixed(0) ?? "—"} · demand{" "}
                    {fmtInt(m.adjusted_addressable_demand)} · {fmtMinutes(m.nearest_pv_minutes)}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      {!loading && !agg && (
        <ul className="member-list">
          {cluster.member_h3_ids.map((id) => (
            <li key={id}>
              <button type="button" className="linkish" onClick={() => onSelectHex(id)}>
                {id}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export default function DetailPanel() {
  const selection = useAppState((s) => s.selection);
  const select = useAppState((s) => s.select);
  const [detail, setDetail] = useState<HexDetail | null>(null);
  const [clusters, setClusters] = useState<ClusterListEntry[]>([]);
  const [clusterMembers, setClusterMembers] = useState<HexDetail[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(assetUrl("/data/clusters_list.json"))
      .then((r) => r.json())
      .then(setClusters)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!selection || selection.kind !== "hex") {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchHexDetail(selection.id).then((d) => {
      if (!cancelled) {
        setDetail(d);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selection]);

  useEffect(() => {
    if (!selection || selection.kind !== "cluster") {
      setClusterMembers([]);
      return;
    }
    const cluster = clusters.find((c) => String(c.cluster_id) === selection.id);
    if (!cluster) return;
    let cancelled = false;
    setLoading(true);
    Promise.all(cluster.member_h3_ids.map((id) => fetchHexDetail(id))).then((rows) => {
      if (!cancelled) {
        setClusterMembers(rows.filter((r): r is HexDetail => r != null));
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selection, clusters]);

  if (!selection) return null;

  const cluster =
    selection.kind === "cluster"
      ? clusters.find((c) => String(c.cluster_id) === selection.id)
      : null;

  return (
    <aside className="detail-panel">
      <div className="sidebar-head">
        <h2>{selection.kind === "hex" ? "Hex detail" : "Cluster"}</h2>
        <button type="button" className="linkish" onClick={() => select(null)}>
          Close
        </button>
      </div>

      {selection.kind === "hex" && (
        <>
          {loading && <p className="muted">Loading…</p>}
          {!loading && detail && <HexBody detail={detail} />}
          {!loading && !detail && <p className="warn">Detail shard not found for {selection.id}</p>}
        </>
      )}

      {selection.kind === "cluster" && cluster && (
        <ClusterBody
          cluster={cluster}
          members={clusterMembers}
          loading={loading}
          onSelectHex={(id) => select({ kind: "hex", id })}
        />
      )}

      {selection.kind === "cluster" && !cluster && (
        <p className="muted">Cluster {selection.id}</p>
      )}
    </aside>
  );
}
