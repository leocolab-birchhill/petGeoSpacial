"""
Stage 1: Convert Canadian postal-code demographics into populated H3 demand points.

Local H3 only — no BigQuery, Mapbox, Google Maps, or API keys.
"""

from __future__ import annotations

import time
from pathlib import Path

import h3
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "data" / "raw" / "postal_code_demos_geocoded.csv"
OUTPUT_DIR = ROOT / "data" / "processed"
RESOLUTIONS = (7, 8, 9)

# Approximate mainland + territorial Canada bounding box
CA_LAT_MIN, CA_LAT_MAX = 41.0, 84.0
CA_LON_MIN, CA_LON_MAX = -141.5, -52.0

# Column aliases accepted by inspection
POSTAL_ALIASES = ("postal_code", "fsaldu", "postalcode", "pc")
LAT_ALIASES = ("latitude", "lat", "y")
LON_ALIASES = ("longitude", "lon", "lng", "long", "x")
HH_ALIASES = ("households_2026", "households", "total_households", "hh")
POP_ALIASES = ("population_2026", "population", "total_population", "pop")


def pick_column(columns: list[str], aliases: tuple[str, ...]) -> str:
    lower_map = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    raise KeyError(f"None of {aliases} found in columns: {columns[:40]}...")


def latlng_to_cells(lats: np.ndarray, lons: np.ndarray, resolution: int) -> list[str]:
    return [h3.latlng_to_cell(float(lat), float(lon), resolution) for lat, lon in zip(lats, lons)]


def main() -> None:
    t0 = time.perf_counter()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Source: {SOURCE_FILE.resolve()}")

    # Peek columns without loading all demographics
    schema_cols = pl.scan_csv(SOURCE_FILE).collect_schema().names()
    postal_col = pick_column(schema_cols, POSTAL_ALIASES)
    lat_col = pick_column(schema_cols, LAT_ALIASES)
    lon_col = pick_column(schema_cols, LON_ALIASES)
    hh_col = pick_column(schema_cols, HH_ALIASES)
    pop_col = pick_column(schema_cols, POP_ALIASES)

    selected = {
        "postal_code": postal_col,
        "latitude": lat_col,
        "longitude": lon_col,
        "households": hh_col,
        "population": pop_col,
    }
    print("Columns selected:")
    for logical, physical in selected.items():
        print(f"  {logical} <- {physical}")

    usecols = list(dict.fromkeys(selected.values()))
    raw = pl.read_csv(SOURCE_FILE, columns=usecols).rename(
        {v: k for k, v in selected.items()}
    )
    n_source = raw.height
    print(f"Loaded {n_source:,} rows")

    # --- Data quality / rejection tagging ---
    # Start with all rows; assign first matching rejection reason.
    qc = raw.with_columns(
        [
            pl.col("postal_code").cast(pl.Utf8).str.to_uppercase().str.replace_all(r"\s+", "").alias("postal_code"),
            pl.col("latitude").cast(pl.Float64),
            pl.col("longitude").cast(pl.Float64),
            pl.col("households").cast(pl.Float64).fill_null(0.0),
            pl.col("population").cast(pl.Float64).fill_null(0.0),
        ]
    ).with_row_index("row_id")

    null_coords = pl.col("latitude").is_null() | pl.col("longitude").is_null()
    reversed_coords = (
        pl.col("latitude").is_between(CA_LON_MIN, CA_LON_MAX)
        & pl.col("longitude").is_between(CA_LAT_MIN, CA_LAT_MAX)
        & ~null_coords
    )
    invalid_canada = (
        ~null_coords
        & ~reversed_coords
        & ~(
            pl.col("latitude").is_between(CA_LAT_MIN, CA_LAT_MAX)
            & pl.col("longitude").is_between(CA_LON_MIN, CA_LON_MAX)
        )
    )
    zero_hh = pl.col("households") <= 0

    # Duplicate postal codes: keep first occurrence; mark later rows as rejected
    first_pc_ids = (
        qc.unique(subset=["postal_code"], keep="first").select("row_id")["row_id"].implode()
    )
    is_dup_pc = ~pl.col("row_id").is_in(first_pc_ids)

    # Duplicate coordinates among otherwise-valid rows are reported, not rejected
    coord_key = pl.concat_str(
        [pl.col("latitude").cast(pl.Utf8), pl.lit("|"), pl.col("longitude").cast(pl.Utf8)]
    )

    tagged = qc.with_columns(
        [
            pl.when(null_coords)
            .then(pl.lit("null_coordinates"))
            .when(reversed_coords)
            .then(pl.lit("reversed_lat_lon"))
            .when(invalid_canada)
            .then(pl.lit("invalid_canadian_coordinates"))
            .when(zero_hh)
            .then(pl.lit("zero_households"))
            .when(is_dup_pc)
            .then(pl.lit("duplicate_postal_code"))
            .otherwise(pl.lit(None))
            .alias("rejection_reason"),
            coord_key.alias("coord_key"),
        ]
    )

    rejected = tagged.filter(pl.col("rejection_reason").is_not_null()).select(
        [
            "postal_code",
            "latitude",
            "longitude",
            "households",
            "population",
            "rejection_reason",
        ]
    )
    rejected_path = OUTPUT_DIR / "coordinate_rejections.csv"
    rejected.write_csv(rejected_path)
    print(f"Rejected records: {rejected.height:,} -> {rejected_path.name}")

    valid = tagged.filter(pl.col("rejection_reason").is_null()).select(
        ["postal_code", "latitude", "longitude", "households", "population", "coord_key"]
    )
    n_valid = valid.height
    n_rejected = rejected.height
    assert n_valid + n_rejected == n_source

    n_dup_coords = n_valid - valid.select("coord_key").unique().height
    print(f"Valid postal-code records: {n_valid:,}")
    print(f"Duplicate-coordinate notes (kept, not rejected): {n_dup_coords:,} records share a coordinate with another valid PC")

    hh_before = float(valid["households"].sum())
    pop_before = float(valid["population"].sum())
    print(f"Pre-aggregation totals — households: {hh_before:,.0f}, population: {pop_before:,.0f}")

    # --- H3 indexing ---
    lats = valid["latitude"].to_numpy()
    lons = valid["longitude"].to_numpy()

    crosswalk = valid.drop("coord_key")
    for res in RESOLUTIONS:
        t_h3 = time.perf_counter()
        cells = latlng_to_cells(lats, lons, res)
        crosswalk = crosswalk.with_columns(pl.Series(f"h3_r{res}", cells))
        print(f"H3 r{res}: {len(cells):,} cells assigned in {time.perf_counter() - t_h3:.1f}s")

    crosswalk_path = OUTPUT_DIR / "postal_code_h3_crosswalk.parquet"
    crosswalk.write_parquet(crosswalk_path)
    print(f"Wrote {crosswalk_path.name}")

    summary_rows: list[dict] = []

    for res in RESOLUTIONS:
        h3_col = f"h3_r{res}"
        agg = (
            crosswalk.group_by(h3_col)
            .agg(
                [
                    pl.col("postal_code").n_unique().alias("postal_code_count"),
                    pl.col("households").sum().alias("total_households"),
                    pl.col("population").sum().alias("total_population"),
                    (
                        (pl.col("latitude") * pl.col("households")).sum()
                        / pl.col("households").sum()
                    ).alias("hh_weighted_latitude"),
                    (
                        (pl.col("longitude") * pl.col("households")).sum()
                        / pl.col("households").sum()
                    ).alias("hh_weighted_longitude"),
                ]
            )
            .rename({h3_col: "h3_cell"})
            .with_columns(pl.lit(res).alias("h3_resolution"))
            .select(
                [
                    "h3_cell",
                    "h3_resolution",
                    "postal_code_count",
                    "total_households",
                    "total_population",
                    "hh_weighted_latitude",
                    "hh_weighted_longitude",
                ]
            )
            .sort("total_households", descending=True)
        )

        out_path = OUTPUT_DIR / f"h3_demand_r{res}.parquet"
        agg.write_parquet(out_path)

        hh_after = float(agg["total_households"].sum())
        pop_after = float(agg["total_population"].sum())
        if abs(hh_after - hh_before) > 1e-3 or abs(pop_after - pop_before) > 1e-3:
            raise AssertionError(
                f"Reconciliation failed at r{res}: "
                f"hh {hh_before} vs {hh_after}, pop {pop_before} vs {pop_after}"
            )

        n_hex = agg.height
        pc_per_hex = agg["postal_code_count"]
        hh_per_hex = agg["total_households"]
        unique_pcs = int(crosswalk["postal_code"].n_unique())

        # Route-pair estimates: each hexagon tested against N nearby stores
        route_pairs_3 = n_hex * 3
        route_pairs_6 = n_hex * 6

        summary_rows.append(
            {
                "h3_resolution": res,
                "populated_h3_cells": n_hex,
                "valid_postal_code_records": n_valid,
                "rejected_records": n_rejected,
                "unique_postal_codes": unique_pcs,
                "avg_postal_codes_per_hexagon": float(pc_per_hex.mean()),
                "median_postal_codes_per_hexagon": float(pc_per_hex.median()),
                "avg_households_per_hexagon": float(hh_per_hex.mean()),
                "median_households_per_hexagon": float(hh_per_hex.median()),
                "total_households": hh_after,
                "total_population": pop_after,
                "estimated_route_pairs_3_stores": route_pairs_3,
                "estimated_route_pairs_6_stores": route_pairs_6,
                "household_reconciliation_ok": abs(hh_after - hh_before) < 1e-3,
                "population_reconciliation_ok": abs(pop_after - pop_before) < 1e-3,
            }
        )
        print(
            f"r{res}: {n_hex:,} populated H3 demand points | "
            f"avg PC/hex={pc_per_hex.mean():.2f} | "
            f"avg HH/hex={hh_per_hex.mean():.1f} | "
            f"wrote {out_path.name}"
        )

    summary = pl.DataFrame(summary_rows)
    summary_path = OUTPUT_DIR / "h3_resolution_summary.csv"
    summary.write_csv(summary_path)

    # Rejection reason breakdown
    if rejected.height:
        print("\nRejection breakdown:")
        for row in (
            rejected.group_by("rejection_reason")
            .len()
            .sort("len", descending=True)
            .iter_rows(named=True)
        ):
            print(f"  {row['rejection_reason']}: {row['len']:,}")
    else:
        print("\nNo rejected records.")

    elapsed = time.perf_counter() - t0
    print(f"\nWrote {summary_path.name}")
    print(f"Total processing time: {elapsed:.1f}s")

    # Recommendation: r8 balances spatial detail vs route-pair explosion for retail
    r7 = summary_rows[0]["populated_h3_cells"]
    r8 = summary_rows[1]["populated_h3_cells"]
    r9 = summary_rows[2]["populated_h3_cells"]
    print("\n=== STAGE 1 RESULTS ===")
    print(f"Source file: {SOURCE_FILE.name}")
    print(
        "Columns: "
        + ", ".join(f"{k}={v}" for k, v in selected.items())
    )
    print(f"Processing time: {elapsed:.1f}s")
    print(f"H3 demand points - r7: {r7:,} | r8: {r8:,} | r9: {r9:,}")
    print(
        "Recommended next-stage resolution: 8 "
        "(~edge ~0.46 km; enough detail for neighbourhood demand without "
        f"the r9 route-pair load of {summary_rows[2]['estimated_route_pairs_6_stores']:,})"
    )
    for row in summary_rows:
        print(
            f"  r{row['h3_resolution']}: cells={row['populated_h3_cells']:,} "
            f"avg_pc={row['avg_postal_codes_per_hexagon']:.2f} "
            f"med_pc={row['median_postal_codes_per_hexagon']:.1f} "
            f"avg_hh={row['avg_households_per_hexagon']:.1f} "
            f"med_hh={row['median_households_per_hexagon']:.1f} "
            f"routes_3={row['estimated_route_pairs_3_stores']:,} "
            f"routes_6={row['estimated_route_pairs_6_stores']:,}"
        )


if __name__ == "__main__":
    main()
