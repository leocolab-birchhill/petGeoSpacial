# Data Contract

Exact schemas for every pipeline input and output. Field names deliberately reuse the
existing repo conventions (`h3_id`, `driving_duration_minutes`, `national_demand_percentile`, …).
All paths relative to `map/pipeline/` unless noted.

---

## 1. Inputs (exist today — do not modify)

### 1.1 `../../data/processed/h3_r8_demographic_demand_ranking.parquet`
53,959 rows, one per populated H3 R8 hex. 58 columns; the ones this app consumes:

- Identity: `h3_id` (str, e.g. `882b9bc715fffff`), `province`, `is_rural_h3` (bool)
- Size: `households`, `population`
- Demand: `base_addressable_demand`, `adjusted_addressable_demand`,
  `addressable_household_demand`, `demand_index_per_household`,
  `adjusted_demand_index_per_household`
- Factors: `income_factor`, `housing_factor`, `family_factor`, `age_factor`,
  `stabilized_income`, `ground_oriented_share`, `high_rise_share`, `family_share`,
  `age_25_64_share`
- Ranks: `national_demand_rank`, `national_demand_percentile` (0–1),
  `province_demand_rank`, `province_demand_percentile`
- Quality: `contributing_postal_code_count`, `coordinate_precision_flag`
  (`urban_local` | `rural_fsa_centroid_imprecise`), `flag_income_imputed`,
  `flag_missing_housing_base`, `flag_missing_household_type_base`,
  `flag_missing_population`, `flag_has_low_hh_postal`, `flag_extreme_demand_index`

Note: this table has **no lat/lon** — compute hex centroid via `h3.cell_to_latlng`,
or household-weighted centroid from `h3_demand_r8.parquet`
(`hh_weighted_latitude/longitude`). Use the h3 geometric centroid for geometry,
hh-weighted for routing origin consistency.

### 1.2 `../../data/runtime/mapbox_matrix_cache/{h3_id}.json` (46,085 files today; grows to 53,959)
```json
{
  "h3_id": "88024c4153fffff",
  "routing_profile": "mapbox/driving",
  "request_timestamp_utc": "...",
  "http_status": 200, "mapbox_code": "Ok", "success": true, "error": null,
  "billable_elements": 3,
  "raw_response_path": "...",
  "parsed_destinations": [
    {"dest_index": 1, "mapbox_code": "Ok",
     "duration_seconds": 812.4, "distance_meters": 11320.0,
     "driving_duration_minutes": 13.54, "driving_distance_km": 11.32,
     "null_route": false}
  ]
}
```
- `dest_index` is 1-based and aligns with `straight_line_rank` in 1.3.
- `null_route: true` ⇒ metrics are null (Arctic/no-road hexes). A file can have all
  three destinations null.
- Some entries may have `success: false` — treat like missing.

### 1.3 `../../data/processed/h3_store_routing_input.parquet`
161,877 rows = 53,959 hexes × 3 candidate stores.
`h3_id`, `origin_latitude`, `origin_longitude`, `straight_line_rank` (1–3),
`store_id` (`pv_NNNN`), `banner`, `store_latitude`, `store_longitude`,
`straight_line_distance_km`. **Join key for cache destinations**: (`h3_id`,
`straight_line_rank` == `dest_index`).

### 1.4 `../../data/processed/pet_valu_network_stores.parquet`
870 rows: `store_id`, `store_name`, `banner` (Pet Valu 614 · Chico 115 · Bosley's 104 ·
Paulmac's Pets 15 · Total Pet 14 · Tisol 8), `address`, `city`, `province`,
`postal_code`, `open_status`, `store_latitude`, `store_longitude`.

### 1.5 `../../data/raw/PET_data_stores - Leo- inclduing Tisol.xlsx`, sheet `Canadian Competitors`
Read with `pd.read_excel(..., sheet_name="Canadian Competitors", header=15)`, drop
all-NaN columns, drop rows with null `Chain Name` → **817 rows**, columns:
`Chain Id`, `Chain Name`, `StoreName`, `Address`, `City`, `Postal Code`, `Province`,
`Country`, `Phone Number`, `Open Status` (all `Open`), `Store Hours`, `Latitude`,
`Longitude` (0 missing), `First Appeared Open`, `Last Seen Open`, `SIC`, `NAICS`.

### 1.6 `../../data/processed/postal_code_h3_crosswalk.parquet`
762,311 rows: `postal_code`, `latitude`, `longitude`, `households`, `population`,
`h3_r7`, `h3_r8`, `h3_r9`. Source for the postal-point tile layer and FSA search index.

### 1.7 `../../data/processed/h3_demand_r7.parquet` / `h3_demand_r8.parquet`
`h3_cell`, `h3_resolution`, `postal_code_count`, `total_households`,
`total_population`, `hh_weighted_latitude`, `hh_weighted_longitude`.

---

## 2. `build/h3_routing_wide.parquet` (output of 01)

One row per `h3_id` in the routing input — **all 53,959, including uncached**.

| column | type | notes |
|---|---|---|
| `h3_id` | str | |
| `routing_status` | str | `ok` \| `no_route` \| `pending` (see PLAN §3.1) |
| `store_id_drive_{1,2,3}` | str? | ranked by `driving_duration_minutes` asc, nulls last |
| `banner_drive_{1,2,3}` | str? | |
| `store_name_drive_{1,2,3}` | str? | joined from 1.4 |
| `driving_minutes_{1,2,3}` | f64? | |
| `driving_km_{1,2,3}` | f64? | |
| `straight_line_km_drive_{1,2,3}` | f64? | |
| `straight_line_rank_of_drive_{1,2,3}` | i8? | original haversine rank of that store |
| `store_lat_drive_{1,2,3}` / `store_lon_drive_{1,2,3}` | f64? | for drawing selection lines |
| `nearest_pv_minutes` / `nearest_pv_km` / `nearest_pv_store_id` | f64?/f64?/str? | = drive_1 |
| `avg3_pv_minutes` | f64? | mean of non-null driving minutes |
| `origin_latitude` / `origin_longitude` | f64 | from routing input |
| `request_timestamp_utc` | str? | from cache |

Naming matches the existing `h3_pet_valu_routing_summary_wide.parquet` stub where
fields overlap. Also emit `build/routing_coverage.json`:
`{"total": 53959, "ok": ..., "no_route": ..., "pending": ..., "generated_at": ...}`.

## 3. Outputs of 02

### 3.1 `build/competitor_stores.parquet` (817 rows)
`competitor_id` (`comp_0001`…), `chain_id`, `chain_name`, `store_name`, `address`,
`city`, `province`, `postal_code`, `latitude`, `longitude`,
`competitor_type` (`mass_merchant` | `specialty_chain` | `independent_boutique` |
`services_other` — mapping fixed in `config.py`, see PLAN §3.3),
`intensity_weight` (f64: 1.0 retail types, 0.25 services_other).

### 3.2 `build/h3_competition.parquet` (one row per R8 hex, 53,959)
`h3_id`, `competitors_within_5km` (i32), `competitors_within_10km` (i32),
`competitor_intensity` (f64, Σ weight/(1+d_km) within 15 km),
`competitor_intensity_pct` (f64 0–1 national percentile),
`nearest_competitor_km` (f64?), `nearest_competitor_chain` (str?),
`nearest_competitor_type` (str?). Distances = haversine from hh-weighted centroid.

## 4. `build/h3_master.parquet` (output of 03) — one row per R8 hex

Join of 1.1 ⋈ §2 ⋈ §3.2 plus derived:

| column | type | notes |
|---|---|---|
| everything from §1.1 consumed list, §2, §3.2 | | pass-through |
| `access_gap_pct` | f64? | national pct-rank of `nearest_pv_minutes` (higher = worse access); null unless `routing_status='ok'` |
| `opportunity_score` | f64? | 0–100, PLAN §3.4; null unless routing ok |
| `opportunity_pct` | f64? | national percentile of score |
| `market_class` | str | `true_whitespace` \| `proven_market_no_pv` \| `competitive_infill` \| `weak_whitespace` \| `other` \| `pending_routing` |
| `cluster_id` | i32? | from §4.1, null if not in a cluster |
| `centroid_lat` / `centroid_lon` | f64 | h3 geometric centroid |

### 4.1 `build/clusters.parquet`
`cluster_id`, `hex_count`, `total_addressable_demand`, `mean_opportunity_score`,
`dominant_class`, `province`, `anchor_city` (city of nearest network store to the
demand-weighted centroid), `centroid_lat`, `centroid_lon`, `bbox` (minx,miny,maxx,maxy),
`member_h3_ids` (list<str>).

### 4.2 `build/h3_r7_rollup.parquet`
`h3_r7_id` + household-weighted means of: `opportunity_score`,
`adjusted_addressable_demand` (sum, not mean), `nearest_pv_minutes`,
`avg3_pv_minutes`, `competitor_intensity`, `national_demand_percentile`; plus
`households` (sum), `dominant_class` (mode weighted by households),
`pending_share` (share of child hexes pending). Parent via `h3.cell_to_parent(h3_id, 7)`.

## 5. Outputs of 04

### 5.1 Tile-input GeoJSON (newline-delimited, `build/geojson/`) — NOT served to browser
**`h3_r8.geojson.nd`** — Polygon per hex (`h3.cells_to_geo`), properties **capped to
this list** (tile size budget):
`h3_id`, `opportunity_score` (round 1), `market_class`,
`adjusted_addressable_demand` (round 0), `national_demand_percentile` (round 3),
`nearest_pv_minutes` (round 1), `avg3_pv_minutes` (round 1),
`competitor_intensity` (round 2), `competitor_intensity_pct` (round 3),
`province`, `is_rural_h3` (0/1), `routing_status`, `households` (round 0),
`cluster_id`, `data_confidence` (0/1: 1 if `flag_income_imputed` or
`coordinate_precision_flag='rural_fsa_centroid_imprecise'`).

**`h3_r7.geojson.nd`** — same property names from the r7 rollup (+`pending_share`,
no `cluster_id`), so the app reuses one paint-expression builder.

**`postal_points.geojson.nd`** — Point; props: `postal_code`, `households`, `is_rural` (0/1).

### 5.2 `app/public/data/stores.geojson` (~1,687 points, one FeatureCollection)
Props: `kind` (`network` | `competitor`), `id`, `name`, `banner_or_chain`,
`competitor_type` (null for network), `city`, `province`, `address`.

### 5.3 `app/public/data/clusters.geojson`
MultiPolygon outlines (dissolved boundaries) with §4.1 fields except
`member_h3_ids` (keep `hex_count`); plus separate `clusters_list.json` with the full
ranked table including `member_h3_ids` for the UI list/zoom-to.

### 5.4 `app/public/data/details/{h3_id[:5]}.json` (sharded detail records)
Key = first 5 chars of `h3_id` (~1,300 shards, ~40 hexes each). Value per hex = full
§4 master row (all fields) plus `routes`: array of ≤3
`{rank, store_id, store_name, banner, driving_minutes, driving_km, straight_line_km,
straight_line_rank, store_lat, store_lon, null_route}` and
`origin: {lat, lon}`. Shape:
```json
{ "882b9": { "882b9bc715fffff": { ...master fields..., "routes": [...], "origin": {...} } } }
```
(top-level key repeats the shard prefix for self-description; app indexes
`shard[prefix][h3_id]`).

### 5.5 `app/public/data/meta.json`
```json
{
  "generated_at": "ISO8601",
  "routing_coverage": {"total": 53959, "ok": 0, "no_route": 0, "pending": 0},
  "score_weights": {"demand": 0.5, "access": 0.3, "competition": 0.2},
  "class_thresholds": { ... from config.py ... },
  "metric_domains": {
    "opportunity_score": {"breaks": [..7 quantile breaks p5–p95..], "min":0, "max":100},
    "adjusted_addressable_demand": {"breaks":[...]},
    "nearest_pv_minutes": {"breaks":[...]},
    "avg3_pv_minutes": {"breaks":[...]},
    "competitor_intensity": {"breaks":[...]},
    "national_demand_percentile": {"breaks":[...]}
  },
  "provinces": ["AB","BC", ...],
  "counts": {"hexes": 53959, "network_stores": 870, "competitors": 817, "clusters": 0}
}
```

### 5.6 `app/public/data/fsa_index.json`
`{"search": [{"label":"M5V — Toronto ON","kind":"fsa","lat":..,"lon":..,"zoom":11}, {"label":"Pet Valu — Queen St W, Toronto","kind":"store","lat":..,"lon":..,"zoom":13}, ...]}`
FSA centroids = household-weighted mean of postal coords per FSA from §1.6.

## 6. Tile archives (output of 05)

| file | layers | zooms | source |
|---|---|---|---|
| `app/public/tiles/hexes.pmtiles` | `h3_r7` (z3–7), `h3_r8` (z6–13) | | §5.1 |
| `app/public/tiles/postal.pmtiles` | `postal` (z11–14) | | §5.1 |

## 7. Invariants / checks (assert in pipeline)

- `h3_master` row count == ranking row count == 53,959.
- `ok + no_route + pending == 53959`; pending shrinks toward 0 as cache lands, code
  paths unchanged.
- `driving_minutes_1 <= driving_minutes_2 <= driving_minutes_3` where non-null.
- Every `market_class ∈` the 6 allowed values; `pending_routing` iff `routing_status != 'ok'`.
- All 817 competitors classified (no unmapped `chain_name` — raise if ChainXY adds a chain).
- stores.geojson features == 870 + 817.
