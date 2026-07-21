"""Step 02 — Competitor layer + per-hex competition intensity. No API calls."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config

EARTH_RADIUS_KM = 6371.0088


def load_competitors() -> pd.DataFrame:
    raw = pd.read_excel(
        config.STORES_XLSX,
        sheet_name=config.COMPETITOR_SHEET,
        header=config.COMPETITOR_HEADER_ROW,
    )
    raw = raw.dropna(axis=1, how="all")
    raw.columns = [str(c).strip() for c in raw.columns]
    df = raw[raw["Chain Name"].notna()].copy()
    df = df[df["Latitude"].notna() & df["Longitude"].notna()].copy()
    df = df.reset_index(drop=True)

    unmapped = sorted(set(df["Chain Name"]) - set(config.COMPETITOR_TYPE_BY_CHAIN))
    if unmapped:
        raise ValueError(f"Unmapped competitor chains: {unmapped}")

    df = df.sort_values(["Chain Name", "Province", "City", "Address"], kind="mergesort").reset_index(drop=True)
    df["competitor_id"] = [f"comp_{i:04d}" for i in range(1, len(df) + 1)]
    df["competitor_type"] = df["Chain Name"].map(config.COMPETITOR_TYPE_BY_CHAIN)
    df["intensity_weight"] = df["competitor_type"].map(config.INTENSITY_WEIGHT_BY_TYPE)

    out = pd.DataFrame(
        {
            "competitor_id": df["competitor_id"],
            "chain_id": df["Chain Id"].astype(str),
            "chain_name": df["Chain Name"].astype(str),
            "store_name": df["StoreName"].fillna("").astype(str),
            "address": df["Address"].fillna("").astype(str),
            "city": df["City"].fillna("").astype(str),
            "province": df["Province"].fillna("").astype(str),
            "postal_code": df["Postal Code"].fillna("").astype(str),
            "latitude": df["Latitude"].astype(float),
            "longitude": df["Longitude"].astype(float),
            "competitor_type": df["competitor_type"],
            "intensity_weight": df["intensity_weight"].astype(float),
        }
    )
    assert len(out) == config.EXPECTED_COMPETITORS, f"Expected {config.EXPECTED_COMPETITORS}, got {len(out)}"
    return out


def compute_hex_competition(competitors: pd.DataFrame) -> pd.DataFrame:
    demand = pd.read_parquet(config.H3_DEMAND_R8_PARQUET)
    demand = demand.rename(columns={"h3_cell": "h3_id"})

    comp_rad = np.radians(competitors[["latitude", "longitude"]].to_numpy())
    tree = BallTree(comp_rad, metric="haversine")
    weights = competitors["intensity_weight"].to_numpy()
    chains = competitors["chain_name"].to_numpy()
    ctypes = competitors["competitor_type"].to_numpy()

    origin_rad = np.radians(demand[["hh_weighted_latitude", "hh_weighted_longitude"]].to_numpy())
    r5 = config.COMPETITOR_COUNT_RADII_KM[0] / EARTH_RADIUS_KM
    r10 = config.COMPETITOR_COUNT_RADII_KM[1] / EARTH_RADIUS_KM
    r15 = config.COMPETITOR_INTENSITY_RADIUS_KM / EARTH_RADIUS_KM

    count5 = tree.query_radius(origin_rad, r=r5, count_only=True)
    count10 = tree.query_radius(origin_rad, r=r10, count_only=True)
    idxs_list, dists_list = tree.query_radius(origin_rad, r=r15, return_distance=True, sort_results=True)

    intensities = np.zeros(len(demand), dtype=float)
    nearest_km = np.full(len(demand), np.nan)
    nearest_chain = np.array([None] * len(demand), dtype=object)
    nearest_type = np.array([None] * len(demand), dtype=object)

    for i, (idxs, dists) in enumerate(zip(idxs_list, dists_list)):
        if len(idxs) == 0:
            # still find absolute nearest beyond 15km for labeling
            d, j = tree.query([origin_rad[i]], k=1)
            nearest_km[i] = float(d[0][0] * EARTH_RADIUS_KM)
            nearest_chain[i] = chains[j[0][0]]
            nearest_type[i] = ctypes[j[0][0]]
            continue
        d_km = dists * EARTH_RADIUS_KM
        intensities[i] = float(np.sum(weights[idxs] / (1.0 + d_km)))
        nearest_km[i] = float(d_km[0])
        nearest_chain[i] = chains[idxs[0]]
        nearest_type[i] = ctypes[idxs[0]]

    out = pd.DataFrame(
        {
            "h3_id": demand["h3_id"].astype(str),
            "competitors_within_5km": count5.astype(int),
            "competitors_within_10km": count10.astype(int),
            "competitor_intensity": intensities,
            "nearest_competitor_km": nearest_km,
            "nearest_competitor_chain": nearest_chain,
            "nearest_competitor_type": nearest_type,
        }
    )
    out["competitor_intensity_pct"] = out["competitor_intensity"].rank(pct=True, method="average")
    assert len(out) == config.EXPECTED_HEX_COUNT
    return out


def main() -> None:
    config.BUILD.mkdir(parents=True, exist_ok=True)
    competitors = load_competitors()
    competitors.to_parquet(config.COMPETITOR_STORES_PARQUET, index=False)
    print(f"Wrote {len(competitors)} competitors -> {config.COMPETITOR_STORES_PARQUET}")

    hex_comp = compute_hex_competition(competitors)
    hex_comp.to_parquet(config.H3_COMPETITION_PARQUET, index=False)
    print(f"Wrote hex competition -> {config.H3_COMPETITION_PARQUET}")
    print(hex_comp["competitor_intensity"].describe())


if __name__ == "__main__":
    main()
