"""
Mapbox Matrix routing: each H3 origin → 3 nearest Pet Valu-network stores.

Billing model (Mapbox docs): elements = sources × destinations.
With sources=0 and destinations=1;2;3, each request costs 1×3 = 3 elements.
annotations=duration,distance does NOT increase element count.

Hard stop: never exceed MAX_BILLABLE_ELEMENTS new matrix elements in a run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import requests

ROOT = Path(__file__).resolve().parent

# Populated by bind_data_paths() — local uses data/{processed,runtime,output};
# Databricks/PETGEO_DATA_ROOT keeps a flat layout under the remote root.
DATA_ROOT: Path
ROUTING_INPUT: Path
CACHE_DIR: Path
RAW_DIR: Path
CHECKPOINT_PATH: Path
AUDIT_PATH: Path
LONG_OUT: Path
WIDE_OUT: Path
FAIL_OUT: Path


def bind_data_paths(
    data_root: Path | str | None = None,
    *,
    flat: bool | None = None,
) -> None:
    """
    Bind input/cache/output paths.

    Local (no PETGEO_DATA_ROOT):
      data/processed/h3_store_routing_input.parquet
      data/runtime/mapbox_matrix_cache|mapbox_raw_responses
      data/output/*.parquet|csv

    Databricks / PETGEO_DATA_ROOT: flat filenames under that root (unchanged).
    """
    global DATA_ROOT, ROUTING_INPUT, CACHE_DIR, RAW_DIR
    global CHECKPOINT_PATH, AUDIT_PATH, LONG_OUT, WIDE_OUT, FAIL_OUT

    env_root = os.environ.get("PETGEO_DATA_ROOT", "").strip()
    if data_root is not None:
        DATA_ROOT = Path(data_root)
        use_flat = True if flat is None else flat
    elif env_root:
        DATA_ROOT = Path(env_root)
        use_flat = True if flat is None else flat
    else:
        DATA_ROOT = ROOT / "data"
        use_flat = False if flat is None else flat

    if use_flat:
        ROUTING_INPUT = DATA_ROOT / "h3_store_routing_input.parquet"
        CACHE_DIR = DATA_ROOT / "mapbox_matrix_cache"
        RAW_DIR = DATA_ROOT / "mapbox_raw_responses"
        CHECKPOINT_PATH = DATA_ROOT / "mapbox_matrix_checkpoint.parquet"
        AUDIT_PATH = DATA_ROOT / "mapbox_request_audit.parquet"
        LONG_OUT = DATA_ROOT / "h3_pet_valu_routing_results_long.parquet"
        WIDE_OUT = DATA_ROOT / "h3_pet_valu_routing_summary_wide.parquet"
        FAIL_OUT = DATA_ROOT / "h3_pet_valu_routing_failures.csv"
    else:
        ROUTING_INPUT = DATA_ROOT / "processed" / "h3_store_routing_input.parquet"
        CACHE_DIR = DATA_ROOT / "runtime" / "mapbox_matrix_cache"
        RAW_DIR = DATA_ROOT / "runtime" / "mapbox_raw_responses"
        CHECKPOINT_PATH = DATA_ROOT / "output" / "mapbox_matrix_checkpoint.parquet"
        AUDIT_PATH = DATA_ROOT / "output" / "mapbox_request_audit.parquet"
        LONG_OUT = DATA_ROOT / "output" / "h3_pet_valu_routing_results_long.parquet"
        WIDE_OUT = DATA_ROOT / "output" / "h3_pet_valu_routing_summary_wide.parquet"
        FAIL_OUT = DATA_ROOT / "output" / "h3_pet_valu_routing_failures.csv"


bind_data_paths()

PROFILE = "mapbox/driving"
ANNOTATIONS = "duration,distance"
SOURCES = "0"
DESTINATIONS = "1;2;3"

# Hard caps for this project stage
MAX_BILLABLE_ELEMENTS = 220_000
MAX_HTTP_CALLS = 220_000
ELEMENTS_PER_REQUEST = 3

DEFAULT_RPS = 0.9  # Mapbox limit is 60 requests/minute
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 2  # 3 attempts/origin worst case: 161,877 calls


def redact_secrets(text: str, token: str | None = None) -> str:
    out = text
    if token:
        out = out.replace(token, "***TOKEN***")
    out = re.sub(r"access_token=[^&\s]+", "access_token=***TOKEN***", out)
    out = re.sub(r"(pk|sk)\.[A-Za-z0-9.\-_]+", r"\1.***TOKEN***", out)
    return out


def running_on_databricks() -> bool:
    return bool(
        os.environ.get("DATABRICKS_RUNTIME_VERSION")
        or os.environ.get("DATABRICKS_JOB_ID")
        or Path("/databricks").exists()
    )


def ssl_verify_setting() -> bool | str:
    """
    Corporate SSL inspection often breaks certifi on laptops. Override with:
      MAPBOX_SSL_VERIFY=0
      MAPBOX_SSL_VERIFY=/path/to/corp-ca.pem

    On Databricks, default to verified SSL unless explicitly overridden.
    """
    raw = os.environ.get("MAPBOX_SSL_VERIFY", "").strip()
    if not raw:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    path = Path(raw)
    if path.exists():
        return str(path)
    return True


def load_token() -> str:
    # Prefer process env (Databricks secret → env), then local .envs (gitignored)
    token = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
    if token:
        return token

    # Optional Databricks dbutils secret injection via wrapper notebook/script
    # is expected to set MAPBOX_ACCESS_TOKEN before invoking this module.

    if not running_on_databricks():
        env_path = ROOT / ".envs"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "MAPBOX_ACCESS_TOKEN":
                    token = value.strip().strip('"').strip("'")
                    if token:
                        return token
    raise RuntimeError(
        "MAPBOX_ACCESS_TOKEN not found. Set the env var, inject a Databricks "
        "secret, or add it to local .envs"
    )


def cache_path_for(h3_id: str) -> Path:
    return CACHE_DIR / f"{h3_id}.json"


_SUCCESS_CACHE: set[str] | None = None


def load_successful_cache_ids(force_reload: bool = False) -> set[str]:
    """
    Build the set of successfully cached H3 ids with one directory scan.
    Critical on DBFS/Volumes where per-file exists()/open() is expensive.
    """
    global _SUCCESS_CACHE
    if _SUCCESS_CACHE is not None and not force_reload:
        return _SUCCESS_CACHE

    successful: set[str] = set()
    if not CACHE_DIR.exists():
        _SUCCESS_CACHE = successful
        return successful

    for path in CACHE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("success") and payload.get("http_status") == 200:
            successful.add(path.stem)

    _SUCCESS_CACHE = successful
    print(
        f"Loaded successful cache index: {len(successful):,} ids from {CACHE_DIR}",
        flush=True,
    )
    return successful


def is_cached(h3_id: str) -> bool:
    return h3_id in load_successful_cache_ids()


def mark_cached_success(h3_id: str) -> None:
    global _SUCCESS_CACHE
    if _SUCCESS_CACHE is None:
        _SUCCESS_CACHE = set()
    _SUCCESS_CACHE.add(h3_id)


def build_matrix_url(
    origin_lon: float,
    origin_lat: float,
    store_coords: list[tuple[float, float]],
    token: str,
) -> str:
    # coordinates: 0=origin, 1..3=stores ; Mapbox wants lon,lat
    parts = [f"{origin_lon},{origin_lat}"]
    for lon, lat in store_coords:
        parts.append(f"{lon},{lat}")
    coord_str = ";".join(parts)
    base = f"https://api.mapbox.com/directions-matrix/v1/{PROFILE}/{coord_str}"
    query = urllib.parse.urlencode(
        {
            "annotations": ANNOTATIONS,
            "sources": SOURCES,
            "destinations": DESTINATIONS,
            "access_token": token,
        }
    )
    return f"{base}?{query}"


def request_matrix(
    url: str,
    timeout: float,
    max_retries: int,
    token: str,
    verify: bool | str,
) -> tuple[int, dict[str, Any] | None, str | None, int]:
    """Returns status, body, error, and number of HTTP attempts."""
    last_err: str | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        try:
            attempts += 1
            resp = requests.get(url, timeout=timeout, verify=verify)
            status = resp.status_code
            try:
                body = resp.json()
            except Exception:
                body = None
            if status == 200 and isinstance(body, dict):
                return status, body, None, attempts
            # Retryable
            if status in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                if status == 429:
                    wait = max(60.0, float(retry_after or 60))
                else:
                    wait = min(60.0, (2**attempt) + (0.1 * attempt))
                last_err = redact_secrets(
                    f"HTTP {status}: {resp.text[:300]}", token
                )
                time.sleep(wait)
                continue
            if isinstance(body, dict):
                err = str(body.get("message") or body.get("code") or resp.text[:300])
            else:
                err = resp.text[:300]
            return (
                status,
                body if isinstance(body, dict) else None,
                redact_secrets(err, token),
                attempts,
            )
        except requests.Timeout:
            last_err = "timeout"
            time.sleep(min(60.0, 2**attempt))
        except requests.RequestException as exc:
            last_err = redact_secrets(str(exc), token)
            time.sleep(min(60.0, 2**attempt))
    return 0, None, last_err or "unknown_error", attempts


def parse_matrix_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse one successful matrix response into 3 destination rows."""
    durations = body.get("durations")
    distances = body.get("distances")
    code = body.get("code")
    rows: list[dict[str, Any]] = []
    for dest_idx in range(3):
        dur_s = None
        dist_m = None
        if (
            isinstance(durations, list)
            and durations
            and isinstance(durations[0], list)
            and dest_idx < len(durations[0])
        ):
            dur_s = durations[0][dest_idx]
        if (
            isinstance(distances, list)
            and distances
            and isinstance(distances[0], list)
            and dest_idx < len(distances[0])
        ):
            dist_m = distances[0][dest_idx]

        null_route = dur_s is None or dist_m is None
        rows.append(
            {
                "dest_index": dest_idx + 1,  # matches destinations 1;2;3 order
                "mapbox_code": code,
                "duration_seconds": dur_s,
                "distance_meters": dist_m,
                "driving_duration_minutes": None
                if dur_s is None
                else float(dur_s) / 60.0,
                "driving_distance_km": None
                if dist_m is None
                else float(dist_m) / 1000.0,
                "null_route": null_route,
            }
        )
    return rows


class RateLimiter:
    def __init__(self, rps: float):
        self.min_interval = 1.0 / max(rps, 0.1)
        self._last = 0.0

    def wait(self) -> None:
        now = time.perf_counter()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.perf_counter()


def dry_run(shortlist: pl.DataFrame) -> None:
    origins = shortlist["h3_id"].n_unique()
    expected_requests = origins
    expected_elements = origins * ELEMENTS_PER_REQUEST

    cached_ids = load_successful_cache_ids(force_reload=True)
    origin_ids = set(shortlist["h3_id"].unique().to_list())
    cached = len(origin_ids & cached_ids)
    new_requests = origins - cached
    new_elements = new_requests * ELEMENTS_PER_REQUEST

    print("=== DRY RUN (no Mapbox calls) ===")
    print(f"DATA_ROOT:                     {DATA_ROOT}")
    print(f"On Databricks:                 {running_on_databricks()}")
    print(f"H3 origins (resolution 8):     {origins:,}")
    print(f"Expected Mapbox requests:      {expected_requests:,}")
    print(f"Expected matrix elements:      {expected_elements:,}  (= origins × 3)")
    print(f"Already cached requests:       {cached:,}")
    print(f"New requests needed:           {new_requests:,}")
    print(f"New matrix elements needed:    {new_elements:,}")
    print(
        "Annotations note: duration+distance returns both metrics in the same "
        "3 elements; it does NOT double billable elements."
    )
    print(f"Hard stop threshold:           {MAX_BILLABLE_ELEMENTS:,} new elements")
    print(
        f"Worst-case HTTP calls:         "
        f"{new_requests * (DEFAULT_MAX_RETRIES + 1):,} "
        f"(cap {MAX_HTTP_CALLS:,})"
    )
    if new_elements > MAX_BILLABLE_ELEMENTS:
        print(
            f"STOP CHECK-IN REQUIRED: new elements {new_elements:,} exceed "
            f"{MAX_BILLABLE_ELEMENTS:,}."
        )
    else:
        print(
            f"Under cap: {new_elements:,} <= {MAX_BILLABLE_ELEMENTS:,}. Safe to run."
        )


def assemble_outputs(shortlist: pl.DataFrame) -> None:
    """Build long/wide/failure tables from cache + shortlist (no API calls)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    LONG_OUT.parent.mkdir(parents=True, exist_ok=True)

    base = shortlist.sort(["h3_id", "straight_line_rank"])
    all_h3 = base["h3_id"].unique(maintain_order=True).to_list()
    short_by_h3 = {
        (h3_key[0] if isinstance(h3_key, tuple) else h3_key): group.sort(
            "straight_line_rank"
        )
        for h3_key, group in base.group_by("h3_id", maintain_order=True)
    }
    # Normalize keys to str
    short_by_h3 = {str(k): v for k, v in short_by_h3.items()}

    long_rows: list[dict[str, Any]] = []
    fail_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    n_missing = 0
    n_failed_request = 0

    for h3_id in map(str, all_h3):
        g = short_by_h3.get(h3_id)
        if g is None or g.height != 3:
            fail_rows.append(
                {
                    "h3_id": h3_id,
                    "failure_type": "shortlist_incomplete",
                    "detail": f"expected 3 stores, got {0 if g is None else g.height}",
                }
            )
            continue

        cache_file = cache_path_for(h3_id)
        if not cache_file.exists():
            n_missing += 1
            continue

        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        audit_rows.append(
            {
                "h3_id": h3_id,
                "routing_profile": payload.get("routing_profile", PROFILE),
                "request_timestamp_utc": payload.get("request_timestamp_utc"),
                "http_status": payload.get("http_status"),
                "mapbox_code": payload.get("mapbox_code"),
                "raw_response_path": payload.get("raw_response_path"),
                "success": payload.get("success"),
                "error": payload.get("error"),
                "billable_elements": payload.get(
                    "billable_elements", ELEMENTS_PER_REQUEST
                ),
            }
        )

        if not payload.get("success"):
            n_failed_request += 1
            fail_rows.append(
                {
                    "h3_id": h3_id,
                    "failure_type": "request_failed",
                    "detail": str(payload.get("error") or payload.get("http_status")),
                }
            )
            continue

        parsed = payload.get("parsed_destinations") or []
        by_dest = {int(p["dest_index"]): p for p in parsed}
        stores = g.to_dicts()

        for store in stores:
            rank = int(store["straight_line_rank"])
            p = by_dest.get(rank, {})
            null_route = bool(p.get("null_route", True))
            long_rows.append(
                {
                    "h3_id": h3_id,
                    "origin_latitude": store["origin_latitude"],
                    "origin_longitude": store["origin_longitude"],
                    "store_id": store["store_id"],
                    "banner": store["banner"],
                    "store_latitude": store["store_latitude"],
                    "store_longitude": store["store_longitude"],
                    "straight_line_rank": rank,
                    "straight_line_distance_km": store["straight_line_distance_km"],
                    "driving_duration_minutes": p.get("driving_duration_minutes"),
                    "driving_distance_km": p.get("driving_distance_km"),
                    "null_route": null_route,
                    "mapbox_code": p.get("mapbox_code") or payload.get("mapbox_code"),
                    "http_status": payload.get("http_status"),
                    "routing_profile": payload.get("routing_profile", PROFILE),
                    "request_timestamp_utc": payload.get("request_timestamp_utc"),
                    "raw_response_path": payload.get("raw_response_path"),
                }
            )
            if null_route:
                fail_rows.append(
                    {
                        "h3_id": h3_id,
                        "failure_type": "null_route",
                        "detail": (
                            f"straight_line_rank={rank}, store_id={store['store_id']}"
                        ),
                    }
                )

    print(
        f"Assemble status: routed_rows={len(long_rows):,} | "
        f"not_yet_requested={n_missing:,} | "
        f"failed_requests={n_failed_request:,} | "
        f"null_or_other_fail_log={len(fail_rows):,}",
        flush=True,
    )

    if not long_rows:
        print("No successful routing rows to assemble yet.")
        if fail_rows:
            pl.DataFrame(fail_rows).write_csv(FAIL_OUT)
            print(f"Wrote {FAIL_OUT.name}: {len(fail_rows):,} rows")
        return

    long_df = pl.DataFrame(long_rows)

    # Final rank by driving time; null routes ranked last within each H3 cell
    long_df = (
        long_df.sort(
            ["h3_id", "null_route", "driving_duration_minutes"],
            descending=[False, False, False],
            nulls_last=True,
        )
        .with_columns(
            pl.col("h3_id").cum_count().over("h3_id").alias("final_rank_by_driving_time")
        )
        .sort(["h3_id", "final_rank_by_driving_time"])
    )
    long_df.write_parquet(LONG_OUT)
    print(f"Wrote {LONG_OUT.name}: {long_df.height:,} rows")

    # Wide summary: 1st/2nd/3rd by driving time
    wide = (
        long_df.filter(pl.col("final_rank_by_driving_time") == 1)
        .select(
            [
                "h3_id",
                "origin_latitude",
                "origin_longitude",
                pl.col("store_id").alias("store_id_drive_1"),
                pl.col("banner").alias("banner_drive_1"),
                pl.col("driving_duration_minutes").alias("driving_minutes_1"),
                pl.col("driving_distance_km").alias("driving_km_1"),
                pl.col("straight_line_distance_km").alias("straight_line_km_drive_1"),
                pl.col("straight_line_rank").alias("straight_line_rank_of_drive_1"),
                pl.col("null_route").alias("null_route_1"),
            ]
        )
    )
    for final_rank in (2, 3):
        part = long_df.filter(
            pl.col("final_rank_by_driving_time") == final_rank
        ).select(
            [
                "h3_id",
                pl.col("store_id").alias(f"store_id_drive_{final_rank}"),
                pl.col("banner").alias(f"banner_drive_{final_rank}"),
                pl.col("driving_duration_minutes").alias(
                    f"driving_minutes_{final_rank}"
                ),
                pl.col("driving_distance_km").alias(f"driving_km_{final_rank}"),
                pl.col("straight_line_distance_km").alias(
                    f"straight_line_km_drive_{final_rank}"
                ),
                pl.col("straight_line_rank").alias(
                    f"straight_line_rank_of_drive_{final_rank}"
                ),
                pl.col("null_route").alias(f"null_route_{final_rank}"),
            ]
        )
        wide = wide.join(part, on="h3_id", how="left")

    # Also keep straight-line 1/2/3 store ids for audit
    for sl_rank in (1, 2, 3):
        sl = (
            long_df.filter(pl.col("straight_line_rank") == sl_rank)
            .select(
                [
                    "h3_id",
                    pl.col("store_id").alias(f"store_id_straight_{sl_rank}"),
                    pl.col("straight_line_distance_km").alias(
                        f"straight_line_km_{sl_rank}"
                    ),
                ]
            )
        )
        wide = wide.join(sl, on="h3_id", how="left")

    wide = wide.sort("h3_id")
    wide.write_parquet(WIDE_OUT)
    print(f"Wrote {WIDE_OUT.name}: {wide.height:,} rows")

    fail_df = pl.DataFrame(fail_rows) if fail_rows else pl.DataFrame(
        {"h3_id": [], "failure_type": [], "detail": []}
    )
    fail_df.write_csv(FAIL_OUT)
    print(f"Wrote {FAIL_OUT.name}: {fail_df.height:,} rows")

    if audit_rows:
        pl.DataFrame(audit_rows).write_parquet(AUDIT_PATH)
        print(f"Wrote {AUDIT_PATH.name}: {len(audit_rows):,} rows")


def run_live(
    shortlist: pl.DataFrame,
    token: str,
    rps: float,
    timeout: float,
    max_retries: int,
    limit: int | None,
) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Indexing shortlist by H3 id...", flush=True)
    ordered = shortlist.sort(["h3_id", "straight_line_rank"])
    h3_ids = ordered["h3_id"].unique(maintain_order=True).to_list()
    if limit is not None:
        h3_ids = h3_ids[:limit]
        ordered = ordered.filter(pl.col("h3_id").is_in(h3_ids))

    cached_ids = load_successful_cache_ids(force_reload=True)
    todo = [h for h in h3_ids if h not in cached_ids]
    cached = len(h3_ids) - len(todo)
    print(
        f"Live run: {len(h3_ids):,} origins in scope | "
        f"{cached:,} cached | {len(todo):,} new requests "
        f"({len(todo) * ELEMENTS_PER_REQUEST:,} new elements)",
        flush=True,
    )

    if len(todo) * ELEMENTS_PER_REQUEST > MAX_BILLABLE_ELEMENTS:
        raise SystemExit(
            f"STOP / CHECK-IN: new elements "
            f"{len(todo) * ELEMENTS_PER_REQUEST:,} exceed "
            f"{MAX_BILLABLE_ELEMENTS:,}. Refusing to start."
        )
    worst_case_calls = len(todo) * (max_retries + 1)
    if worst_case_calls > MAX_HTTP_CALLS:
        raise SystemExit(
            f"STOP / CHECK-IN: worst-case HTTP calls {worst_case_calls:,} exceed "
            f"{MAX_HTTP_CALLS:,}. Reduce --max-retries or scope."
        )

    # Index only in-scope shortlist rows by h3
    by_h3: dict[str, list[dict]] = {}
    for row in ordered.to_dicts():
        by_h3.setdefault(row["h3_id"], []).append(row)
    print(f"Indexed {len(by_h3):,} origins. Starting requests...", flush=True)

    limiter = RateLimiter(rps)
    verify = ssl_verify_setting()
    if verify is False:
        print(
            "WARNING: SSL verification disabled (MAPBOX_SSL_VERIFY=0). "
            "Use only on trusted corporate networks.",
            flush=True,
        )
        # Avoid urllib3 InsecureRequestWarning noise in long runs
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    new_elements_spent = 0
    http_calls_made = 0
    successes = 0
    failures = 0
    t0 = time.perf_counter()

    for n, h3_id in enumerate(todo, start=1):
        if http_calls_made + max_retries + 1 > MAX_HTTP_CALLS:
            print(
                f"\nSTOP / CHECK-IN: next origin could exceed "
                f"{MAX_HTTP_CALLS:,} HTTP calls (made={http_calls_made:,}).",
                flush=True,
            )
            break
        if new_elements_spent + ELEMENTS_PER_REQUEST > MAX_BILLABLE_ELEMENTS:
            print(
                f"\nSTOP / CHECK-IN: next request would exceed "
                f"{MAX_BILLABLE_ELEMENTS:,} new billable elements "
                f"(spent={new_elements_spent:,}).",
                flush=True,
            )
            break

        stores = by_h3[h3_id]
        if len(stores) != 3:
            failures += 1
            continue

        origin_lat = stores[0]["origin_latitude"]
        origin_lon = stores[0]["origin_longitude"]
        store_coords = [
            (s["store_longitude"], s["store_latitude"]) for s in stores
        ]
        url = build_matrix_url(origin_lon, origin_lat, store_coords, token)

        limiter.wait()
        ts = datetime.now(timezone.utc).isoformat()
        http_status, body, err, attempts = request_matrix(
            url, timeout, max_retries, token=token, verify=verify
        )
        http_calls_made += attempts

        # Count billable elements only when Mapbox returned an HTTP response.
        # Pure transport/SSL failures never reached Mapbox and are not billed.
        reached_mapbox = http_status > 0
        if reached_mapbox:
            new_elements_spent += ELEMENTS_PER_REQUEST

        raw_path = RAW_DIR / f"{h3_id}.json"
        mapbox_code = None
        success = False
        parsed: list[dict[str, Any]] = []
        if http_status == 200 and isinstance(body, dict):
            mapbox_code = body.get("code")
            success = mapbox_code == "Ok"
            if success:
                parsed = parse_matrix_body(body)
                successes += 1
            else:
                failures += 1
                err = err or f"mapbox_code={mapbox_code}"
        else:
            failures += 1

        raw_payload = {
            "h3_id": h3_id,
            "routing_profile": PROFILE,
            "request_timestamp_utc": ts,
            "http_status": http_status,
            "mapbox_code": mapbox_code,
            "success": success,
            "error": err,
            "billable_elements": ELEMENTS_PER_REQUEST if reached_mapbox else 0,
            "annotations": ANNOTATIONS,
            "sources": SOURCES,
            "destinations": DESTINATIONS,
            "response_body": body,
        }
        raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")

        cache_payload = {
            "h3_id": h3_id,
            "routing_profile": PROFILE,
            "request_timestamp_utc": ts,
            "http_status": http_status,
            "mapbox_code": mapbox_code,
            "success": success,
            "error": err,
            "billable_elements": ELEMENTS_PER_REQUEST if reached_mapbox else 0,
            "raw_response_path": str(raw_path),
            "parsed_destinations": parsed,
        }
        # Only cache successful paid responses as complete; failed ones remain
        # retryable via is_cached() == False, but keep audit artifact on disk.
        cache_path_for(h3_id).write_text(
            json.dumps(cache_payload), encoding="utf-8"
        )
        if success:
            mark_cached_success(h3_id)

        if n % 100 == 0 or n == len(todo):
            elapsed = time.perf_counter() - t0
            rate = n / elapsed if elapsed else 0
            print(
                f"  [{n:,}/{len(todo):,}] success={successes:,} fail={failures:,} "
                f"elements_spent={new_elements_spent:,} "
                f"http_calls={http_calls_made:,} "
                f"rate={rate:.2f} req/s",
                flush=True,
            )

    # Checkpoint summary
    checkpoint = pl.DataFrame(
        {
            "finished_utc": [datetime.now(timezone.utc).isoformat()],
            "origins_in_scope": [len(h3_ids)],
            "new_requests_attempted": [successes + failures],
            "successes": [successes],
            "failures": [failures],
            "new_elements_spent": [new_elements_spent],
            "http_calls_made": [http_calls_made],
        }
    )
    checkpoint.write_parquet(CHECKPOINT_PATH)
    print(f"Wrote {CHECKPOINT_PATH.name}")
    print(
        f"Done live segment: successes={successes:,}, failures={failures:,}, "
        f"new_elements_spent={new_elements_spent:,}, "
        f"http_calls_made={http_calls_made:,}"
    )

    assemble_outputs(shortlist)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mapbox Matrix routing for H3 Pet Valu accessibility"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report expected requests/elements/cache; make no Mapbox calls",
    )
    parser.add_argument(
        "--assemble-only",
        action="store_true",
        help="Rebuild output tables from cache only (no Mapbox calls)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on number of H3 origins to process (for testing)",
    )
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    args = parser.parse_args()

    print(f"DATA_ROOT={DATA_ROOT}", flush=True)
    if not ROUTING_INPUT.exists():
        raise SystemExit(
            f"Missing {ROUTING_INPUT}. Run prepare_routing_inputs.py locally "
            "or upload h3_store_routing_input.parquet to PETGEO_DATA_ROOT."
        )

    shortlist = pl.read_parquet(ROUTING_INPUT)
    print(
        f"Loaded shortlist: {shortlist.height:,} rows, "
        f"{shortlist['h3_id'].n_unique():,} H3 origins",
        flush=True,
    )

    if args.dry_run:
        dry_run(shortlist)
        return

    if args.assemble_only:
        assemble_outputs(shortlist)
        return

    token = load_token()
    print("Mapbox token loaded from environment / .envs")
    run_live(
        shortlist=shortlist,
        token=token,
        rps=args.rps,
        timeout=args.timeout,
        max_retries=args.max_retries,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
