"""
Prepare Pet Valu network stores and H3→3-nearest-store routing shortlist.

Local only (BallTree / Haversine). No Mapbox calls.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.neighbors import BallTree

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
STORE_XLSX = RAW_DIR / "PET_data_stores - Leo- inclduing Tisol.xlsx"
H3_DEMAND_R8 = PROCESSED_DIR / "h3_demand_r8.parquet"

STORES_OUT = PROCESSED_DIR / "pet_valu_network_stores.parquet"
ROUTING_INPUT_OUT = PROCESSED_DIR / "h3_store_routing_input.parquet"

# Pet Valu-controlled banners (PET Stores sheet). Paulmac's / Total Pet are PET-owned.
NETWORK_BANNERS = {
    "pet valu",
    "chico",
    "bosley's",
    "bosleys",
    "tisol",
    "total pet",
    "paulmac's pets",
    "paulmacs pets",
}

EARTH_RADIUS_KM = 6371.0088
N_NEAREST = 3


def _norm_banner(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def load_pet_valu_network_stores() -> pl.DataFrame:
    raw = pd.read_excel(STORE_XLSX, sheet_name="PET Stores", header=24)
    raw = raw.dropna(axis=1, how="all")
    raw.columns = [str(c).strip() for c in raw.columns]

    required = ["Store Name", "Store Type", "Latitude", "Longitude", "Open Status"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing store columns: {missing}")

    df = raw.copy()
    df["banner_norm"] = df["Store Type"].map(_norm_banner)
    df = df[df["banner_norm"].isin(NETWORK_BANNERS)].copy()
    df = df[df["Latitude"].notna() & df["Longitude"].notna()].copy()
    df = df[df["Open Status"].astype(str).str.lower().str.contains("open", na=False)].copy()

    # Stable unique store id (Chain Id is not unique in source)
    df = df.sort_values(
        ["Store Type", "Store Name", "Address", "City", "Latitude", "Longitude"],
        kind="mergesort",
    ).reset_index(drop=True)
    df["store_id"] = [f"pv_{i:04d}" for i in range(1, len(df) + 1)]

    out = pl.from_pandas(
        df[
            [
                "store_id",
                "Store Name",
                "Store Type",
                "Address",
                "City",
                "Province",
                "Postal Code",
                "Open Status",
                "Latitude",
                "Longitude",
            ]
        ].rename(
            columns={
                "Store Name": "store_name",
                "Store Type": "banner",
                "Address": "address",
                "City": "city",
                "Province": "province",
                "Postal Code": "postal_code",
                "Open Status": "open_status",
                "Latitude": "store_latitude",
                "Longitude": "store_longitude",
            }
        )
    ).with_columns(
        [
            pl.col("store_latitude").cast(pl.Float64),
            pl.col("store_longitude").cast(pl.Float64),
        ]
    )
    return out


def build_routing_shortlist(stores: pl.DataFrame, demand: pl.DataFrame) -> pl.DataFrame:
    store_lats = stores["store_latitude"].to_numpy()
    store_lons = stores["store_longitude"].to_numpy()
    store_ids = stores["store_id"].to_list()
    banners = stores["banner"].to_list()

    origin_lats = demand["hh_weighted_latitude"].to_numpy()
    origin_lons = demand["hh_weighted_longitude"].to_numpy()
    h3_ids = demand["h3_cell"].to_list()

    store_rad = np.radians(np.column_stack([store_lats, store_lons]))
    origin_rad = np.radians(np.column_stack([origin_lats, origin_lons]))

    tree = BallTree(store_rad, metric="haversine")
    dist_rad, idx = tree.query(origin_rad, k=min(N_NEAREST, len(stores)))
    dist_km = dist_rad * EARTH_RADIUS_KM

    rows: list[dict] = []
    for i, h3_id in enumerate(h3_ids):
        for rank in range(dist_km.shape[1]):
            j = int(idx[i, rank])
            rows.append(
                {
                    "h3_id": h3_id,
                    "origin_latitude": float(origin_lats[i]),
                    "origin_longitude": float(origin_lons[i]),
                    "straight_line_rank": rank + 1,
                    "store_id": store_ids[j],
                    "banner": banners[j],
                    "store_latitude": float(store_lats[j]),
                    "store_longitude": float(store_lons[j]),
                    "straight_line_distance_km": float(dist_km[i, rank]),
                }
            )

    return pl.DataFrame(rows).sort(["h3_id", "straight_line_rank"])


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loading stores from: {STORE_XLSX.name}")
    stores = load_pet_valu_network_stores()
    stores.write_parquet(STORES_OUT)
    print(f"Wrote {STORES_OUT.name}: {stores.height:,} stores")
    print(stores.group_by("banner").len().sort("len", descending=True))

    print(f"Loading H3 demand from: {H3_DEMAND_R8.name}")
    demand = pl.read_parquet(H3_DEMAND_R8)
    if "h3_cell" not in demand.columns:
        raise ValueError("Expected h3_cell in demand parquet")
    for col in ("hh_weighted_latitude", "hh_weighted_longitude"):
        if col not in demand.columns:
            raise ValueError(f"Expected {col} in demand parquet")

    shortlist = build_routing_shortlist(stores, demand)
    shortlist.write_parquet(ROUTING_INPUT_OUT)
    print(f"Wrote {ROUTING_INPUT_OUT.name}: {shortlist.height:,} rows")
    print(f"Unique H3 origins: {shortlist['h3_id'].n_unique():,}")
    print(f"Expected Mapbox requests: {shortlist['h3_id'].n_unique():,}")
    print(f"Expected matrix elements: {shortlist.height:,} (= origins × 3)")


if __name__ == "__main__":
    main()
