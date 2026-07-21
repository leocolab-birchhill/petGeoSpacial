"""Step 03 — Join everything; opportunity score, market class, clusters, R7 rollup."""

from __future__ import annotations

from collections import Counter, defaultdict

import h3
import numpy as np
import pandas as pd

import config


def _pct_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average")


def classify_row(row: pd.Series) -> str:
    status = row["routing_status"]
    if status == "pending":
        return "pending_routing"
    # no_route / failed cache: cannot score access — fold into "other" (cache pull is complete)
    if status != "ok":
        return "other"
    high_demand = float(row["national_demand_percentile"]) >= config.CLASS_THRESHOLDS["high_demand_percentile"]
    access_cut = (
        config.CLASS_THRESHOLDS["poor_access_minutes_rural"]
        if bool(row["is_rural_h3"])
        else config.CLASS_THRESHOLDS["poor_access_minutes_urban"]
    )
    poor_access = float(row["nearest_pv_minutes"]) >= access_cut
    meaningful_comp = float(row["competitor_intensity_pct"]) >= config.CLASS_THRESHOLDS["meaningful_competition_pct"]

    if high_demand and poor_access and not meaningful_comp:
        return "true_whitespace"
    if high_demand and poor_access and meaningful_comp:
        return "proven_market_no_pv"
    if high_demand and (not poor_access) and meaningful_comp:
        return "competitive_infill"
    if (not high_demand) and poor_access and not meaningful_comp:
        return "weak_whitespace"
    return "other"


def build_clusters(master: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    members = master[
        (master["market_class"].isin(["true_whitespace", "proven_market_no_pv"]))
        | (master["opportunity_score"].fillna(-1) >= config.CLUSTER_MEMBER_SCORE_MIN)
    ].copy()
    member_set = set(members["h3_id"].tolist())
    if not member_set:
        return pd.DataFrame(), pd.Series(dtype="Int64")

    parent: dict[str, str] = {h: h for h in member_set}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for h in member_set:
        for n in h3.grid_disk(h, 1):
            if n != h and n in member_set:
                union(h, n)

    components: dict[str, list[str]] = defaultdict(list)
    for h in member_set:
        components[find(h)].append(h)

    # Keep components >= min size; assign cluster_ids by demand desc
    kept = [hs for hs in components.values() if len(hs) >= config.CLUSTER_MIN_HEXES]
    cluster_rows = []
    cluster_id_by_hex: dict[str, int] = {}

    scored = []
    for hs in kept:
        sub = master[master["h3_id"].isin(hs)]
        total_demand = float(sub["adjusted_addressable_demand"].fillna(0).sum())
        scored.append((total_demand, hs, sub))
    scored.sort(key=lambda t: t[0], reverse=True)

    stores = pd.read_parquet(config.NETWORK_STORES_PARQUET)

    for cid, (total_demand, hs, sub) in enumerate(scored, start=1):
        for h in hs:
            cluster_id_by_hex[h] = cid
        lat = sub["centroid_lat"].to_numpy()
        lon = sub["centroid_lon"].to_numpy()
        w = sub["households"].fillna(0).to_numpy()
        wsum = w.sum() or 1.0
        c_lat = float(np.average(lat, weights=w))
        c_lon = float(np.average(lon, weights=w))
        # nearest network store city as anchor
        if len(stores):
            d2 = (stores["store_latitude"] - c_lat) ** 2 + (stores["store_longitude"] - c_lon) ** 2
            anchor = stores.loc[d2.idxmin(), "city"]
        else:
            anchor = ""
        class_counts = Counter(sub["market_class"])
        dominant = class_counts.most_common(1)[0][0]
        cluster_rows.append(
            {
                "cluster_id": cid,
                "hex_count": len(hs),
                "total_addressable_demand": total_demand,
                "mean_opportunity_score": float(sub["opportunity_score"].mean(skipna=True)),
                "dominant_class": dominant,
                "province": Counter(sub["province"]).most_common(1)[0][0],
                "anchor_city": str(anchor),
                "centroid_lat": c_lat,
                "centroid_lon": c_lon,
                "bbox_minx": float(lon.min()),
                "bbox_miny": float(lat.min()),
                "bbox_maxx": float(lon.max()),
                "bbox_maxy": float(lat.max()),
                "member_h3_ids": hs,
            }
        )

    clusters = pd.DataFrame(cluster_rows)
    mapping = pd.Series(cluster_id_by_hex, name="cluster_id")
    return clusters, mapping


def rollup_r7(master: pd.DataFrame) -> pd.DataFrame:
    tmp = master.copy()
    tmp["h3_r7_id"] = tmp["h3_id"].map(lambda x: h3.cell_to_parent(x, 7))
    rows = []
    for r7, g in tmp.groupby("h3_r7_id"):
        w = g["households"].fillna(0).to_numpy()
        wsum = float(w.sum()) or 1.0

        def wmean(col: str) -> float | None:
            s = g[col]
            mask = s.notna().to_numpy()
            if not mask.any():
                return None
            ww = w[mask]
            return float(np.average(s[mask].to_numpy(dtype=float), weights=ww))

        # household-weighted mode for class
        class_w: dict[str, float] = defaultdict(float)
        for cls, hh in zip(g["market_class"], w):
            class_w[cls] += float(hh)
        dominant = max(class_w.items(), key=lambda kv: kv[1])[0]
        pending_share = float((g["routing_status"] != "ok").astype(float).dot(w) / wsum)

        rows.append(
            {
                "h3_r7_id": r7,
                "households": float(wsum),
                "opportunity_score": wmean("opportunity_score"),
                "adjusted_addressable_demand": float(g["adjusted_addressable_demand"].fillna(0).sum()),
                "nearest_pv_minutes": wmean("nearest_pv_minutes"),
                "avg3_pv_minutes": wmean("avg3_pv_minutes"),
                "competitor_intensity": wmean("competitor_intensity"),
                "national_demand_percentile": wmean("national_demand_percentile"),
                "dominant_class": dominant,
                "market_class": dominant,
                "pending_share": pending_share,
                "province": Counter(g["province"]).most_common(1)[0][0],
                "is_rural_h3": int((g["is_rural_h3"].astype(bool) * w).sum() / wsum >= 0.5),
                "routing_status": "pending" if pending_share > 0.5 else "ok",
                "competitor_intensity_pct": wmean("competitor_intensity_pct"),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    config.BUILD.mkdir(parents=True, exist_ok=True)
    ranking = pd.read_parquet(config.RANKING_PARQUET)
    routing = pd.read_parquet(config.ROUTING_WIDE_PARQUET)
    competition = pd.read_parquet(config.H3_COMPETITION_PARQUET)

    master = ranking.merge(routing, on="h3_id", how="left", suffixes=("", "_r")).merge(
        competition, on="h3_id", how="left"
    )
    assert len(master) == config.EXPECTED_HEX_COUNT, len(master)

    ok_mask = master["routing_status"] == "ok"
    master["access_gap_pct"] = np.nan
    master.loc[ok_mask, "access_gap_pct"] = _pct_rank(master.loc[ok_mask, "nearest_pv_minutes"])

    w = config.SCORE_WEIGHTS
    master["opportunity_score"] = np.where(
        ok_mask,
        100.0
        * (
            w["demand"] * master["national_demand_percentile"].astype(float)
            + w["access"] * master["access_gap_pct"].astype(float)
            + w["competition"] * (1.0 - master["competitor_intensity_pct"].astype(float))
        ),
        np.nan,
    )
    master["opportunity_pct"] = np.nan
    master.loc[ok_mask, "opportunity_pct"] = _pct_rank(master.loc[ok_mask, "opportunity_score"])

    master["market_class"] = master.apply(classify_row, axis=1)

    cents = master["h3_id"].map(lambda x: h3.cell_to_latlng(x))
    master["centroid_lat"] = cents.map(lambda t: t[0])
    master["centroid_lon"] = cents.map(lambda t: t[1])

    clusters, mapping = build_clusters(master)
    master["cluster_id"] = master["h3_id"].map(mapping)

    r7 = rollup_r7(master)

    master.to_parquet(config.H3_MASTER_PARQUET, index=False)
    r7.to_parquet(config.H3_R7_ROLLUP_PARQUET, index=False)
    if len(clusters):
        clusters.to_parquet(config.CLUSTERS_PARQUET, index=False)
    else:
        pd.DataFrame(
            columns=[
                "cluster_id",
                "hex_count",
                "total_addressable_demand",
                "mean_opportunity_score",
                "dominant_class",
                "province",
                "anchor_city",
                "centroid_lat",
                "centroid_lon",
                "bbox_minx",
                "bbox_miny",
                "bbox_maxx",
                "bbox_maxy",
                "member_h3_ids",
            ]
        ).to_parquet(config.CLUSTERS_PARQUET, index=False)

    print(f"Master rows: {len(master)}")
    print("Market class distribution:")
    print(master["market_class"].value_counts().to_string())
    print(f"Clusters: {len(clusters)}")
    print(f"R7 rollup cells: {len(r7)}")
    print(f"Opportunity score (ok only): mean={master.loc[ok_mask, 'opportunity_score'].mean():.1f}")


if __name__ == "__main__":
    main()
