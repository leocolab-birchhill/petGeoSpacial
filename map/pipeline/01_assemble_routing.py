"""Step 01 — Assemble routing metrics from the existing Mapbox Matrix cache.

NO API CALLS. Reads local cache JSONs only.
"""

from __future__ import annotations

import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config


def _merge_outstanding_zip() -> int:
    """Extract cache JSONs not already present. Returns count newly written."""
    zpath = config.OUTSTANDING_ZIP
    if not zpath.exists():
        return 0
    config.MATRIX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    added = 0
    with zipfile.ZipFile(zpath, "r") as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            base = Path(name).name
            dest = config.MATRIX_CACHE_DIR / base
            if dest.exists():
                continue
            dest.write_bytes(zf.read(name))
            added += 1
    return added


def _read_cache(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not data.get("success", False):
        return None
    return data


def _assemble_one(
    h3_id: str,
    shortlist: pd.DataFrame,
    stores: dict[str, str],
    cache_data: dict | None,
) -> dict:
    origin_lat = float(shortlist["origin_latitude"].iloc[0])
    origin_lon = float(shortlist["origin_longitude"].iloc[0])
    row: dict = {
        "h3_id": h3_id,
        "origin_latitude": origin_lat,
        "origin_longitude": origin_lon,
        # Cache pull is complete: missing/failed files are terminal no_route, not "pending".
        "routing_status": "no_route",
        "request_timestamp_utc": None,
        "nearest_pv_minutes": None,
        "nearest_pv_km": None,
        "nearest_pv_store_id": None,
        "avg3_pv_minutes": None,
    }
    for i in range(1, 4):
        row[f"store_id_drive_{i}"] = None
        row[f"banner_drive_{i}"] = None
        row[f"store_name_drive_{i}"] = None
        row[f"driving_minutes_{i}"] = None
        row[f"driving_km_{i}"] = None
        row[f"straight_line_km_drive_{i}"] = None
        row[f"straight_line_rank_of_drive_{i}"] = None
        row[f"store_lat_drive_{i}"] = None
        row[f"store_lon_drive_{i}"] = None

    if cache_data is None:
        # Unusable cache (failed request, corrupt JSON, or absent) → no_route
        return row

    row["request_timestamp_utc"] = cache_data.get("request_timestamp_utc")
    dest_by_rank = {int(d["dest_index"]): d for d in cache_data.get("parsed_destinations", [])}
    candidates = []
    for _, s in shortlist.iterrows():
        rank = int(s["straight_line_rank"])
        dest = dest_by_rank.get(rank)
        if dest is None:
            continue
        null_route = bool(dest.get("null_route"))
        minutes = None if null_route else dest.get("driving_duration_minutes")
        km = None if null_route else dest.get("driving_distance_km")
        sid = s["store_id"]
        candidates.append(
            {
                "store_id": sid,
                "banner": s["banner"],
                "store_name": stores.get(sid),
                "driving_minutes": float(minutes) if minutes is not None else None,
                "driving_km": float(km) if km is not None else None,
                "straight_line_km": float(s["straight_line_distance_km"]),
                "straight_line_rank": rank,
                "store_lat": float(s["store_latitude"]),
                "store_lon": float(s["store_longitude"]),
                "null_route": null_route or minutes is None,
            }
        )

    if not candidates:
        row["routing_status"] = "no_route"
        return row

    ranked = sorted(
        candidates,
        key=lambda c: (c["driving_minutes"] is None, c["driving_minutes"] if c["driving_minutes"] is not None else 1e18),
    )
    non_null = [c for c in ranked if c["driving_minutes"] is not None]
    if not non_null:
        row["routing_status"] = "no_route"
        return row

    row["routing_status"] = "ok"
    for i, c in enumerate(ranked[:3], start=1):
        row[f"store_id_drive_{i}"] = c["store_id"]
        row[f"banner_drive_{i}"] = c["banner"]
        row[f"store_name_drive_{i}"] = c["store_name"]
        row[f"driving_minutes_{i}"] = c["driving_minutes"]
        row[f"driving_km_{i}"] = c["driving_km"]
        row[f"straight_line_km_drive_{i}"] = c["straight_line_km"]
        row[f"straight_line_rank_of_drive_{i}"] = c["straight_line_rank"]
        row[f"store_lat_drive_{i}"] = c["store_lat"]
        row[f"store_lon_drive_{i}"] = c["store_lon"]

    best = non_null[0]
    row["nearest_pv_minutes"] = best["driving_minutes"]
    row["nearest_pv_km"] = best["driving_km"]
    row["nearest_pv_store_id"] = best["store_id"]
    row["avg3_pv_minutes"] = sum(c["driving_minutes"] for c in non_null) / len(non_null)
    return row


def main() -> None:
    config.BUILD.mkdir(parents=True, exist_ok=True)
    added = _merge_outstanding_zip()
    if added:
        print(f"Merged {added} new cache files from outstanding zip")

    routing_input = pd.read_parquet(config.ROUTING_INPUT_PARQUET)
    stores_df = pd.read_parquet(config.NETWORK_STORES_PARQUET)
    stores = dict(zip(stores_df["store_id"], stores_df["store_name"]))

    h3_ids = sorted(routing_input["h3_id"].unique())
    assert len(h3_ids) == config.EXPECTED_HEX_COUNT, (
        f"Expected {config.EXPECTED_HEX_COUNT} hexes, got {len(h3_ids)}"
    )

    cache_paths = {p.stem: p for p in config.MATRIX_CACHE_DIR.glob("*.json")}
    print(f"Cache files available: {len(cache_paths)} / {len(h3_ids)}")

    # Preload only needed cache JSON (threaded)
    needed = [h for h in h3_ids if h in cache_paths]
    cache_data: dict[str, dict | None] = {h: None for h in h3_ids}

    def load(h: str) -> tuple[str, dict | None]:
        return h, _read_cache(cache_paths[h])

    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(load, h) for h in needed]
        for i, fut in enumerate(as_completed(futs), start=1):
            h, data = fut.result()
            cache_data[h] = data
            if i % 10000 == 0:
                print(f"  loaded cache {i}/{len(needed)}")

    grouped = {h: g for h, g in routing_input.groupby("h3_id", sort=False)}
    rows = []
    for i, h3_id in enumerate(h3_ids, start=1):
        rows.append(_assemble_one(h3_id, grouped[h3_id], stores, cache_data.get(h3_id)))
        if i % 10000 == 0:
            print(f"  assembled {i}/{len(h3_ids)}")

    wide = pd.DataFrame(rows)
    ok = int((wide["routing_status"] == "ok").sum())
    no_route = int((wide["routing_status"] == "no_route").sum())
    pending = int((wide["routing_status"] == "pending").sum())
    assert ok + no_route + pending == len(wide)

    wide.to_parquet(config.ROUTING_WIDE_PARQUET, index=False)
    coverage = {
        "total": int(len(wide)),
        "ok": ok,
        "no_route": no_route,
        "pending": pending,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    config.ROUTING_COVERAGE_JSON.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    print(f"Wrote {config.ROUTING_WIDE_PARQUET}")
    print(f"Coverage: ok={ok} no_route={no_route} pending={pending} ({100*ok/len(wide):.1f}% ok)")


if __name__ == "__main__":
    main()
