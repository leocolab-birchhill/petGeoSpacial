"""Central configuration for the map data pipeline.

All tunable analytics constants live here (and are exported to app meta.json by
04_export_geojson.py) so the UI can display how scores/classes are computed.

HARD RULE: this pipeline makes NO network calls. Routing comes exclusively from
the existing local Mapbox Matrix cache.
"""

from pathlib import Path

# ---------------------------------------------------------------- paths
PIPELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_DIR.parent.parent  # petGeospacial/
DATA = REPO_ROOT / "data"

# Inputs (existing project artifacts — read-only)
RANKING_PARQUET = DATA / "processed" / "h3_r8_demographic_demand_ranking.parquet"
ROUTING_INPUT_PARQUET = DATA / "processed" / "h3_store_routing_input.parquet"
NETWORK_STORES_PARQUET = DATA / "processed" / "pet_valu_network_stores.parquet"
POSTAL_CROSSWALK_PARQUET = DATA / "processed" / "postal_code_h3_crosswalk.parquet"
H3_DEMAND_R7_PARQUET = DATA / "processed" / "h3_demand_r7.parquet"
H3_DEMAND_R8_PARQUET = DATA / "processed" / "h3_demand_r8.parquet"
STORES_XLSX = DATA / "raw" / "PET_data_stores - Leo- inclduing Tisol.xlsx"
COMPETITOR_SHEET = "Canadian Competitors"
COMPETITOR_HEADER_ROW = 15  # 0-indexed pandas header row
MATRIX_CACHE_DIR = DATA / "runtime" / "mapbox_matrix_cache"
# Optional: newly delivered cache zip (merged by 01 if present, non-destructively)
OUTSTANDING_ZIP = DATA / "runtime" / "mapbox_matrix_cache_outstanding.zip"

# Outputs
BUILD = PIPELINE_DIR / "build"
GEOJSON_DIR = BUILD / "geojson"
APP_PUBLIC = PIPELINE_DIR.parent / "app" / "public"
APP_DATA = APP_PUBLIC / "data"
APP_TILES = APP_PUBLIC / "tiles"
DETAILS_DIR = APP_DATA / "details"

ROUTING_WIDE_PARQUET = BUILD / "h3_routing_wide.parquet"
ROUTING_COVERAGE_JSON = BUILD / "routing_coverage.json"
COMPETITOR_STORES_PARQUET = BUILD / "competitor_stores.parquet"
H3_COMPETITION_PARQUET = BUILD / "h3_competition.parquet"
H3_MASTER_PARQUET = BUILD / "h3_master.parquet"
H3_R7_ROLLUP_PARQUET = BUILD / "h3_r7_rollup.parquet"
CLUSTERS_PARQUET = BUILD / "clusters.parquet"

EXPECTED_HEX_COUNT = 53_959
EXPECTED_NETWORK_STORES = 870
EXPECTED_COMPETITORS = 817

# ------------------------------------------- competitor classification
# Fixed mapping of every chain in the Canadian Competitors sheet (verified counts).
# 02_build_competitors.py must RAISE on any chain_name not present here.
COMPETITOR_TYPE_BY_CHAIN = {
    "PetSmart": "mass_merchant",
    "Petland": "mass_merchant",
    "Global Pet Foods": "specialty_chain",
    "Mondou": "specialty_chain",
    "Ren's Pets": "specialty_chain",
    "Pattes et Griffes": "specialty_chain",
    "Pet Planet": "specialty_chain",
    "Homes Alive Pets": "specialty_chain",
    "Pet Depot": "specialty_chain",
    "EarthWise Pet Supply": "specialty_chain",
    "The Bone & Biscuit Co.": "independent_boutique",
    "Woof Gang Bakery & Grooming": "independent_boutique",
    "Three Dog Bakery": "independent_boutique",
    "VetCor": "services_other",
    "Dogtopia": "services_other",
    "Wild Birds Unlimited": "services_other",
    "Camp Bow Wow": "services_other",
}
# services_other are groom/vet/daycare/bird — downweighted in intensity
INTENSITY_WEIGHT_BY_TYPE = {
    "mass_merchant": 1.0,
    "specialty_chain": 1.0,
    "independent_boutique": 1.0,
    "services_other": 0.25,
}
COMPETITOR_INTENSITY_RADIUS_KM = 15.0  # gravity sum cutoff
COMPETITOR_COUNT_RADII_KM = (5.0, 10.0)

# ------------------------------------------------- opportunity score
SCORE_WEIGHTS = {"demand": 0.5, "access": 0.3, "competition": 0.2}

# ---------------------------------------------- market classification
# See PLAN.md §3.5. Tunable; exported to meta.json.
CLASS_THRESHOLDS = {
    "high_demand_percentile": 0.70,       # national_demand_percentile >=
    "poor_access_minutes_urban": 15.0,    # nearest_pv_minutes >=
    "poor_access_minutes_rural": 25.0,
    "meaningful_competition_pct": 0.60,   # competitor_intensity_pct >=
}
MARKET_CLASSES = [
    "true_whitespace",
    "proven_market_no_pv",
    "competitive_infill",
    "weak_whitespace",
    "other",
    "pending_routing",
]

# ------------------------------------------------------------ clusters
CLUSTER_MIN_HEXES = 3
CLUSTER_MEMBER_SCORE_MIN = 80.0  # OR class in (true_whitespace, proven_market_no_pv)

# ------------------------------------------------------------ export
DETAIL_SHARD_PREFIX_LEN = 5  # h3_id[:5] -> ~1,300 shards
METRIC_BREAK_QUANTILES = [0.05, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95]
TILE_METRICS = [
    "opportunity_score",
    "adjusted_addressable_demand",
    "nearest_pv_minutes",
    "avg3_pv_minutes",
    "competitor_intensity",
    "national_demand_percentile",
]
