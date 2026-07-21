"""Step 04 — Export tiling GeoJSON + app static data."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import h3
import numpy as np
import pandas as pd

import config


def _hex_polygon(h3_id: str) -> list[list[list[float]]]:
    # h3 v4: cell_to_boundary returns (lat, lng); GeoJSON needs [lng, lat]
    boundary = h3.cell_to_boundary(h3_id)
    ring = [[round(lng, 5), round(lat, 5)] for lat, lng in boundary]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return [ring]


def _json_safe(v):
    """Coerce numpy/pandas scalars to plain JSON types."""
    if v is None:
        return None
    try:
        if v is pd.NA:
            return None
    except Exception:
        pass
    if isinstance(v, (str,)):
        return v
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        if np.isnan(v) or np.isinf(v):
            return None
        return float(v)
    if isinstance(v, (list, dict)):
        return v
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    # Last resort for odd pandas scalar types
    if hasattr(v, "item"):
        try:
            return _json_safe(v.item())
        except Exception:
            pass
    return v


def _round_or_omit(props: dict) -> dict:
    out = {}
    for k, v in props.items():
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            continue
        if isinstance(v, (np.floating, float)):
            out[k] = float(v)
        elif isinstance(v, (np.integer, int)):
            out[k] = int(v)
        elif isinstance(v, (np.bool_, bool)):
            out[k] = int(bool(v))
        else:
            out[k] = v
    return out


def write_ndjson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for feat in features:
            f.write(json.dumps(feat, separators=(",", ":")) + "\n")


def export_hex_tiles(master: pd.DataFrame, r7: pd.DataFrame) -> None:
    r8_feats = []
    for row in master.itertuples(index=False):
        props = _round_or_omit(
            {
                "h3_id": row.h3_id,
                "opportunity_score": None if pd.isna(row.opportunity_score) else round(float(row.opportunity_score), 1),
                "market_class": row.market_class,
                "adjusted_addressable_demand": round(float(row.adjusted_addressable_demand), 0)
                if pd.notna(row.adjusted_addressable_demand)
                else None,
                "national_demand_percentile": round(float(row.national_demand_percentile), 3)
                if pd.notna(row.national_demand_percentile)
                else None,
                "nearest_pv_minutes": None
                if pd.isna(row.nearest_pv_minutes)
                else round(float(row.nearest_pv_minutes), 1),
                "avg3_pv_minutes": None if pd.isna(row.avg3_pv_minutes) else round(float(row.avg3_pv_minutes), 1),
                "competitor_intensity": None
                if pd.isna(row.competitor_intensity)
                else round(float(row.competitor_intensity), 2),
                "competitor_intensity_pct": None
                if pd.isna(row.competitor_intensity_pct)
                else round(float(row.competitor_intensity_pct), 3),
                "province": row.province,
                "is_rural_h3": int(bool(row.is_rural_h3)),
                "routing_status": row.routing_status,
                "households": None if pd.isna(row.households) else round(float(row.households), 0),
                "cluster_id": None if pd.isna(getattr(row, "cluster_id", np.nan)) else int(row.cluster_id),
                "data_confidence": int(
                    bool(getattr(row, "flag_income_imputed", False))
                    or getattr(row, "coordinate_precision_flag", "") == "rural_fsa_centroid_imprecise"
                ),
            }
        )
        r8_feats.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Polygon", "coordinates": _hex_polygon(row.h3_id)},
            }
        )
    write_ndjson(config.GEOJSON_DIR / "h3_r8.geojson.nd", r8_feats)

    r7_feats = []
    for row in r7.itertuples(index=False):
        props = _round_or_omit(
            {
                "h3_id": row.h3_r7_id,
                "opportunity_score": None if pd.isna(row.opportunity_score) else round(float(row.opportunity_score), 1),
                "market_class": row.market_class,
                "adjusted_addressable_demand": round(float(row.adjusted_addressable_demand), 0),
                "national_demand_percentile": None
                if pd.isna(row.national_demand_percentile)
                else round(float(row.national_demand_percentile), 3),
                "nearest_pv_minutes": None
                if pd.isna(row.nearest_pv_minutes)
                else round(float(row.nearest_pv_minutes), 1),
                "avg3_pv_minutes": None if pd.isna(row.avg3_pv_minutes) else round(float(row.avg3_pv_minutes), 1),
                "competitor_intensity": None
                if pd.isna(row.competitor_intensity)
                else round(float(row.competitor_intensity), 2),
                "competitor_intensity_pct": None
                if pd.isna(row.competitor_intensity_pct)
                else round(float(row.competitor_intensity_pct), 3),
                "province": row.province,
                "is_rural_h3": int(row.is_rural_h3),
                "routing_status": row.routing_status,
                "households": round(float(row.households), 0),
                "pending_share": round(float(row.pending_share), 3),
                "data_confidence": 0,
            }
        )
        r7_feats.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Polygon", "coordinates": _hex_polygon(row.h3_r7_id)},
            }
        )
    write_ndjson(config.GEOJSON_DIR / "h3_r7.geojson.nd", r7_feats)
    print(f"Hex NDJSON: r8={len(r8_feats)} r7={len(r7_feats)}")


def export_postal_points() -> None:
    """Export postal points; keep lean props. For tiling we sample lightly below dense urban cores
    by writing all points — the Python tiler drops densest at lower zooms."""
    cross = pd.read_parquet(config.POSTAL_CROSSWALK_PARQUET)
    # Attach is_rural from postal demographic demand if available; else 0
    rural_path = config.DATA / "processed" / "postal_demographic_demand.parquet"
    if rural_path.exists():
        rural = pd.read_parquet(rural_path, columns=["postal_code", "is_rural"])
        cross = cross.merge(rural, on="postal_code", how="left")
    else:
        cross["is_rural"] = 0
    feats = []
    for row in cross.itertuples(index=False):
        if pd.isna(row.latitude) or pd.isna(row.longitude):
            continue
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "postal_code": row.postal_code,
                    "households": int(round(float(row.households))) if pd.notna(row.households) else 0,
                    "is_rural": int(bool(getattr(row, "is_rural", False))),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(row.longitude), 5), round(float(row.latitude), 5)],
                },
            }
        )
    write_ndjson(config.GEOJSON_DIR / "postal_points.geojson.nd", feats)
    print(f"Postal NDJSON: {len(feats)}")


def export_stores() -> None:
    network = pd.read_parquet(config.NETWORK_STORES_PARQUET)
    comps = pd.read_parquet(config.COMPETITOR_STORES_PARQUET)
    features = []
    for row in network.itertuples(index=False):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "network",
                    "id": row.store_id,
                    "name": row.store_name,
                    "banner_or_chain": row.banner,
                    "competitor_type": None,
                    "city": row.city,
                    "province": row.province,
                    "address": row.address,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row.store_longitude), float(row.store_latitude)],
                },
            }
        )
    for row in comps.itertuples(index=False):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "competitor",
                    "id": row.competitor_id,
                    "name": row.store_name or row.chain_name,
                    "banner_or_chain": row.chain_name,
                    "competitor_type": row.competitor_type,
                    "city": row.city,
                    "province": row.province,
                    "address": row.address,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row.longitude), float(row.latitude)],
                },
            }
        )
    config.APP_DATA.mkdir(parents=True, exist_ok=True)
    (config.APP_DATA / "stores.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"stores.geojson: {len(features)} features")


def _cluster_outline(member_ids: list[str]) -> dict | None:
    """Build a MultiPolygon outline from union of hex boundaries (outer rings)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    polys = []
    for hid in member_ids:
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(hid)]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        polys.append(Polygon(ring))
    if not polys:
        return None
    merged = unary_union(polys)
    if merged.geom_type == "Polygon":
        coords = [[[[round(x, 5), round(y, 5)] for x, y in merged.exterior.coords]]]
        return {"type": "MultiPolygon", "coordinates": coords}
    if merged.geom_type == "MultiPolygon":
        coords = []
        for poly in merged.geoms:
            coords.append([[[round(x, 5), round(y, 5)] for x, y in poly.exterior.coords]])
        return {"type": "MultiPolygon", "coordinates": coords}
    return None


def export_clusters(clusters: pd.DataFrame) -> None:
    features = []
    list_rows = []
    for row in clusters.itertuples(index=False):
        members = list(row.member_h3_ids) if isinstance(row.member_h3_ids, (list, np.ndarray)) else list(row.member_h3_ids)
        geom = _cluster_outline(members)
        if geom is None:
            continue
        props = {
            "cluster_id": int(row.cluster_id),
            "hex_count": int(row.hex_count),
            "total_addressable_demand": float(row.total_addressable_demand),
            "mean_opportunity_score": float(row.mean_opportunity_score) if pd.notna(row.mean_opportunity_score) else None,
            "dominant_class": row.dominant_class,
            "province": row.province,
            "anchor_city": row.anchor_city,
        }
        features.append({"type": "Feature", "properties": props, "geometry": geom})
        list_rows.append(
            {
                **props,
                "centroid_lat": float(row.centroid_lat),
                "centroid_lon": float(row.centroid_lon),
                "bbox": [
                    float(row.bbox_minx),
                    float(row.bbox_miny),
                    float(row.bbox_maxx),
                    float(row.bbox_maxy),
                ],
                "member_h3_ids": members,
            }
        )
    (config.APP_DATA / "clusters.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
        encoding="utf-8",
    )
    (config.APP_DATA / "clusters_list.json").write_text(
        json.dumps(list_rows, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"clusters: {len(features)}")


def export_details(master: pd.DataFrame) -> None:
    if config.DETAILS_DIR.exists():
        shutil.rmtree(config.DETAILS_DIR)
    config.DETAILS_DIR.mkdir(parents=True, exist_ok=True)

    # Convert master to records; build routes array
    shards: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in master.to_dict(orient="records"):
        h3_id = row["h3_id"]
        routes = []
        for i in range(1, 4):
            sid = row.get(f"store_id_drive_{i}")
            if sid is None or (isinstance(sid, float) and np.isnan(sid)):
                continue
            routes.append(
                {
                    "rank": i,
                    "store_id": sid,
                    "store_name": row.get(f"store_name_drive_{i}"),
                    "banner": row.get(f"banner_drive_{i}"),
                    "driving_minutes": None
                    if pd.isna(row.get(f"driving_minutes_{i}"))
                    else float(row[f"driving_minutes_{i}"]),
                    "driving_km": None
                    if pd.isna(row.get(f"driving_km_{i}"))
                    else float(row[f"driving_km_{i}"]),
                    "straight_line_km": None
                    if pd.isna(row.get(f"straight_line_km_drive_{i}"))
                    else float(row[f"straight_line_km_drive_{i}"]),
                    "straight_line_rank": None
                    if pd.isna(row.get(f"straight_line_rank_of_drive_{i}"))
                    else int(row[f"straight_line_rank_of_drive_{i}"]),
                    "store_lat": None
                    if pd.isna(row.get(f"store_lat_drive_{i}"))
                    else float(row[f"store_lat_drive_{i}"]),
                    "store_lon": None
                    if pd.isna(row.get(f"store_lon_drive_{i}"))
                    else float(row[f"store_lon_drive_{i}"]),
                    "null_route": row.get(f"driving_minutes_{i}") is None
                    or (isinstance(row.get(f"driving_minutes_{i}"), float) and np.isnan(row.get(f"driving_minutes_{i}"))),
                }
            )
        clean = {k: _json_safe(v) for k, v in row.items()}
        clean["routes"] = routes
        clean["origin"] = {
            "lat": float(row["origin_latitude"]) if pd.notna(row.get("origin_latitude")) else float(row["centroid_lat"]),
            "lon": float(row["origin_longitude"]) if pd.notna(row.get("origin_longitude")) else float(row["centroid_lon"]),
        }
        prefix = h3_id[: config.DETAIL_SHARD_PREFIX_LEN]
        shards[prefix][h3_id] = clean

    for prefix, body in shards.items():
        (config.DETAILS_DIR / f"{prefix}.json").write_text(
            json.dumps({prefix: body}, separators=(",", ":"), default=_json_safe),
            encoding="utf-8",
        )
    print(f"Detail shards: {len(shards)}")


def export_meta(master: pd.DataFrame, coverage: dict, n_clusters: int) -> None:
    domains = {}
    for metric in config.TILE_METRICS:
        s = master[metric].dropna()
        if len(s) == 0:
            domains[metric] = {"breaks": [], "min": None, "max": None}
            continue
        breaks = [float(s.quantile(q)) for q in config.METRIC_BREAK_QUANTILES]
        domains[metric] = {"breaks": breaks, "min": float(s.min()), "max": float(s.max())}

    # Min opportunity_score for top X% of true_whitespace (by score within that class)
    tw_scores = master.loc[
        master["market_class"] == "true_whitespace", "opportunity_score"
    ].dropna()
    tw_top_thresholds = {}
    for pct in (5, 10, 15, 20, 25, 50):
        if len(tw_scores):
            tw_top_thresholds[str(pct)] = float(tw_scores.quantile(1 - pct / 100.0))
        else:
            tw_top_thresholds[str(pct)] = 0.0

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "routing_coverage": coverage,
        "score_weights": config.SCORE_WEIGHTS,
        "class_thresholds": config.CLASS_THRESHOLDS,
        "true_whitespace_top_thresholds": tw_top_thresholds,
        "metric_domains": domains,
        "provinces": sorted(master["province"].dropna().unique().tolist()),
        "counts": {
            "hexes": int(len(master)),
            "network_stores": config.EXPECTED_NETWORK_STORES,
            "competitors": config.EXPECTED_COMPETITORS,
            "clusters": n_clusters,
        },
    }
    (config.APP_DATA / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def export_whitespace_points(master: pd.DataFrame) -> None:
    """Centroids of true_whitespace + proven_market_no_pv for zoomed-out MapLibre clustering."""
    ws = master[master["market_class"].isin(["true_whitespace", "proven_market_no_pv"])]
    feats = []
    for row in ws.itertuples(index=False):
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "h3_id": row.h3_id,
                    "market_class": row.market_class,
                    "opportunity_score": None
                    if pd.isna(row.opportunity_score)
                    else round(float(row.opportunity_score), 1),
                    "province": row.province,
                    "households": None if pd.isna(row.households) else int(row.households),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row.centroid_lon), float(row.centroid_lat)],
                },
            }
        )
    (config.APP_DATA / "whitespace_points.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"whitespace_points.geojson: {len(feats)}")


def _dashboard_place_labels(master: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Nearest city (network + competitor gazetteer) + household-weighted modal FSA."""
    from sklearn.neighbors import BallTree

    # Modal FSA per hex (highest household postal)
    cross = pd.read_parquet(
        config.POSTAL_CROSSWALK_PARQUET,
        columns=["postal_code", "households", "h3_r8"],
    )
    cross = cross.dropna(subset=["h3_r8"])
    cross["fsa"] = cross["postal_code"].astype(str).str[:3].str.upper()
    cross["households"] = cross["households"].fillna(0)
    fsa_by_hex = (
        cross.sort_values("households", ascending=False)
        .drop_duplicates("h3_r8")
        .set_index("h3_r8")["fsa"]
    )

    places = []
    stores = pd.read_parquet(
        config.NETWORK_STORES_PARQUET,
        columns=["city", "store_latitude", "store_longitude"],
    ).rename(columns={"store_latitude": "lat", "store_longitude": "lon"})
    places.append(stores[["city", "lat", "lon"]])
    if config.COMPETITOR_STORES_PARQUET.exists():
        comps = pd.read_parquet(
            config.COMPETITOR_STORES_PARQUET,
            columns=["city", "latitude", "longitude"],
        ).rename(columns={"latitude": "lat", "longitude": "lon"})
        places.append(comps[["city", "lat", "lon"]])
    gaz = pd.concat(places, ignore_index=True)
    gaz["city"] = gaz["city"].fillna("").astype(str).str.strip()
    gaz = gaz[(gaz["city"] != "") & gaz["lat"].notna() & gaz["lon"].notna()].drop_duplicates()

    n = len(master)
    city_arr = np.array([""] * n, dtype=object)
    if len(gaz):
        tree = BallTree(np.radians(gaz[["lat", "lon"]].to_numpy()), metric="haversine")
        q = np.radians(master[["centroid_lat", "centroid_lon"]].to_numpy())
        _, idx = tree.query(q, k=1)
        city_arr = gaz["city"].to_numpy()[idx.ravel()]

    fsa_arr = master["h3_id"].map(fsa_by_hex).fillna("").astype(str).to_numpy()
    return city_arr, fsa_arr


def export_dashboard(master: pd.DataFrame) -> None:
    """Lean national hex table + chart summaries for the Dashboard tab."""

    def _f(v, nd=1):
        if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
            return None
        return round(float(v), nd)

    def _i(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
            return None
        return int(v)

    cities, fsas = _dashboard_place_labels(master)

    hexes = []
    for i, row in enumerate(master.itertuples(index=False)):
        city_s = str(cities[i]).strip() if cities[i] else ""
        fsa_s = str(fsas[i]).strip() if fsas[i] else ""
        if city_s and fsa_s:
            place = f"{city_s} · {fsa_s}"
        elif city_s:
            place = city_s
        elif fsa_s:
            place = fsa_s
        else:
            place = f"{row.province} area"

        hexes.append(
            {
                "h3_id": row.h3_id,
                "place": place,
                "city": city_s or None,
                "fsa": fsa_s or None,
                "province": row.province,
                "market_class": row.market_class,
                "is_rural": bool(getattr(row, "is_rural_h3", False)),
                "opportunity_score": _f(row.opportunity_score, 1),
                "opportunity_pct": _f(getattr(row, "opportunity_pct", None), 3),
                "demand": _f(row.adjusted_addressable_demand, 0),
                "demand_pct": _f(row.national_demand_percentile, 3),
                "nearest_pv_min": _f(row.nearest_pv_minutes, 1),
                "avg3_pv_min": _f(getattr(row, "avg3_pv_minutes", None), 1),
                "comp_intensity": _f(row.competitor_intensity, 2),
                "comp_pct": _f(row.competitor_intensity_pct, 3),
                "households": _i(row.households),
                "population": _i(row.population),
                "cluster_id": _i(getattr(row, "cluster_id", None)),
                "routing_status": getattr(row, "routing_status", None) or "unknown",
                "lat": _f(row.centroid_lat, 5),
                "lon": _f(row.centroid_lon, 5),
            }
        )

    class_counts = master["market_class"].value_counts().to_dict()
    class_counts = {str(k): int(v) for k, v in class_counts.items()}

    scores = master["opportunity_score"].dropna()
    bins = list(range(0, 101, 10))
    hist_counts = [0] * (len(bins) - 1)
    if len(scores):
        counts, _ = np.histogram(scores.to_numpy(), bins=bins)
        hist_counts = [int(c) for c in counts]

    province_opportunity: dict[str, dict] = {}
    ws = master[master["market_class"].isin(["true_whitespace", "proven_market_no_pv"])]
    for prov, g in ws.groupby("province"):
        province_opportunity[str(prov)] = {
            "true_whitespace": int((g["market_class"] == "true_whitespace").sum()),
            "proven_market_no_pv": int((g["market_class"] == "proven_market_no_pv").sum()),
            "demand": float(g["adjusted_addressable_demand"].fillna(0).sum()),
        }

    payload = {
        "hexes": hexes,
        "class_counts": class_counts,
        "score_hist": {"bins": bins, "counts": hist_counts},
        "province_opportunity": province_opportunity,
    }
    out = config.APP_DATA / "dashboard.json"
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"dashboard.json: {len(hexes)} hexes ({out.stat().st_size / 1e6:.1f} MB)")


def export_fsa_index() -> None:
    cross = pd.read_parquet(config.POSTAL_CROSSWALK_PARQUET)
    cross["fsa"] = cross["postal_code"].astype(str).str[:3].str.upper()
    cross = cross.dropna(subset=["latitude", "longitude"])
    entries = []
    for fsa, g in cross.groupby("fsa"):
        w = g["households"].fillna(1).to_numpy()
        lat = float(np.average(g["latitude"].to_numpy(), weights=w))
        lon = float(np.average(g["longitude"].to_numpy(), weights=w))
        entries.append({"label": f"{fsa}", "kind": "fsa", "lat": lat, "lon": lon, "zoom": 11})

    stores = json.loads((config.APP_DATA / "stores.geojson").read_text(encoding="utf-8"))
    for feat in stores["features"]:
        p = feat["properties"]
        coords = feat["geometry"]["coordinates"]
        label = f"{p['banner_or_chain']} — {p['name'] or p['city']}, {p['province']}"
        entries.append(
            {
                "label": label,
                "kind": "store",
                "lat": coords[1],
                "lon": coords[0],
                "zoom": 13,
            }
        )
    (config.APP_DATA / "fsa_index.json").write_text(
        json.dumps({"search": entries}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Search index entries: {len(entries)}")


def main() -> None:
    config.BUILD.mkdir(parents=True, exist_ok=True)
    config.APP_DATA.mkdir(parents=True, exist_ok=True)
    config.GEOJSON_DIR.mkdir(parents=True, exist_ok=True)

    master = pd.read_parquet(config.H3_MASTER_PARQUET)
    r7 = pd.read_parquet(config.H3_R7_ROLLUP_PARQUET)
    clusters = pd.read_parquet(config.CLUSTERS_PARQUET)
    coverage = json.loads(config.ROUTING_COVERAGE_JSON.read_text(encoding="utf-8"))

    export_hex_tiles(master, r7)
    export_postal_points()
    export_stores()
    export_clusters(clusters)
    export_details(master)
    export_whitespace_points(master)
    export_dashboard(master)
    export_meta(master, coverage, n_clusters=len(clusters))
    export_fsa_index()
    print("Export complete.")


if __name__ == "__main__":
    main()
