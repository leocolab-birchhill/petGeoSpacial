"""
Demographic addressable-demand model and H3 R8 ranking.

Builds postal-level demand factors from Environics demographics, aggregates to
H3 resolution 8, and ranks all populated hexagons (rural and non-rural).

Does not touch Mapbox routing inputs, caches, or job scripts.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEMOS = ROOT / "data" / "raw" / "postal_code_demos_geocoded.csv"
DEFAULT_CROSSWALK = ROOT / "data" / "processed" / "postal_code_h3_crosswalk.parquet"
DEFAULT_PROCESSED = ROOT / "data" / "processed"
DEFAULT_OUTPUT = ROOT / "data" / "output"

INCOME_FLOOR = 20_000.0
INCOME_CEILING = 500_000.0
INCOME_HH_MIN = 25.0
INCOME_REF = 100_000.0

# Default: no rural-specific demand multiplier (housing/family/income already
# capture rural structure). Configurable; clipped to keep impact modest.
DEFAULT_RURAL_ADJUSTMENT_FACTOR = 1.0
RURAL_ADJUSTMENT_FACTOR_MIN = 0.95
RURAL_ADJUSTMENT_FACTOR_MAX = 1.05
DEFAULT_RURAL_HH_SHARE_THRESHOLD = 0.50
# Illustrative sensitivity factor used only when configured factor == 1.0
ILLUSTRATIVE_RURAL_SENSITIVITY_FACTOR = 1.02

PROVINCE_BY_FSA_PREFIX: dict[str, str] = {
    "A": "NL",
    "B": "NS",
    "C": "PE",
    "E": "NB",
    "G": "QC",
    "H": "QC",
    "J": "QC",
    "K": "ON",
    "L": "ON",
    "M": "ON",
    "N": "ON",
    "P": "ON",
    "R": "MB",
    "S": "SK",
    "T": "AB",
    "V": "BC",
    "X": "NT_NU",
    "Y": "YT",
}

DEMO_COLUMNS = [
    "postal_code",
    "fsa",
    "postal_region",
    "is_rural_postal_code",
    "population_2026",
    "households_2026",
    "household_type_base",
    "family_households",
    "housing_structure_base",
    "single_detached_households",
    "semi_detached_households",
    "apartment_5plus_storey_households",
    "income_household_base",
    "median_household_income_2026",
    "aggregate_household_income_2026",
    "population_age_25_44",
    "population_age_45_64",
]


def clip(value: float, lo: float, hi: float) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return float("nan")
    return max(lo, min(hi, value))


def clip_rural_adjustment_factor(factor: float) -> float:
    return clip(float(factor), RURAL_ADJUSTMENT_FACTOR_MIN, RURAL_ADJUSTMENT_FACTOR_MAX)


def income_factor_from_stabilized(stabilized_income: float) -> float:
    if stabilized_income is None or stabilized_income <= 0 or math.isnan(stabilized_income):
        return float("nan")
    return clip(math.sqrt(stabilized_income / INCOME_REF), 0.80, 1.30)


def housing_factor_from_shares(
    ground_oriented_share: float,
    high_rise_share: float,
    national_ground_oriented_share: float,
    national_high_rise_share: float,
) -> float:
    raw = (
        1.0
        + 0.10 * (ground_oriented_share - national_ground_oriented_share)
        - 0.05 * (high_rise_share - national_high_rise_share)
    )
    return clip(raw, 0.90, 1.10)


def family_factor_from_share(family_share: float, national_family_share: float) -> float:
    return clip(1.0 + 0.15 * (family_share - national_family_share), 0.925, 1.075)


def age_factor_from_share(age_25_64_share: float, national_age_25_64_share: float) -> float:
    return clip(1.0 + 0.10 * (age_25_64_share - national_age_25_64_share), 0.95, 1.05)


def safe_ratio(numer: float, denom: float) -> float:
    if denom is None or denom <= 0 or numer is None:
        return float("nan")
    return float(numer) / float(denom)


def province_from_fsa_prefix(prefix: str | None) -> str:
    if not prefix:
        return "UNKNOWN"
    return PROVINCE_BY_FSA_PREFIX.get(str(prefix).upper()[:1], "UNKNOWN")


def is_rural_fsa_rule(fsa: str | None) -> bool:
    """Canadian rural FSA rule: second character is '0'."""
    if not fsa or len(str(fsa)) < 2:
        return False
    return str(fsa).upper()[1] == "0"


def resolve_is_rural(is_rural_flag: bool | None, fsa: str | None) -> bool:
    """True if source flag or FSA second-character rule marks rural."""
    return bool(is_rural_flag) or is_rural_fsa_rule(fsa)


def rural_flag_expr() -> pl.Expr:
    return (
        pl.col("is_rural_postal_code").fill_null(False)
        | (pl.col("fsa").str.to_uppercase().str.slice(1, 1) == "0")
    ).alias("is_rural")


def compute_national_benchmarks(df: pl.DataFrame) -> dict[str, float]:
    """National shares/income from summed numerators and denominators."""
    agg = df.select(
        [
            pl.col("aggregate_household_income_2026").sum().alias("agg_income"),
            pl.col("income_household_base").sum().alias("income_base"),
            (
                pl.col("single_detached_households") + pl.col("semi_detached_households")
            )
            .sum()
            .alias("ground_oriented"),
            pl.col("apartment_5plus_storey_households").sum().alias("high_rise"),
            pl.col("housing_structure_base").sum().alias("housing_base"),
            pl.col("family_households").sum().alias("family_hh"),
            pl.col("household_type_base").sum().alias("hh_type_base"),
            (pl.col("population_age_25_44") + pl.col("population_age_45_64"))
            .sum()
            .alias("age_25_64"),
            pl.col("population_2026").sum().alias("population"),
            pl.col("households_2026").sum().alias("households"),
        ]
    ).row(0, named=True)

    return {
        "national_income": safe_ratio(agg["agg_income"], agg["income_base"]),
        "national_ground_oriented_share": safe_ratio(
            agg["ground_oriented"], agg["housing_base"]
        ),
        "national_high_rise_share": safe_ratio(agg["high_rise"], agg["housing_base"]),
        "national_family_share": safe_ratio(agg["family_hh"], agg["hh_type_base"]),
        "national_age_25_64_share": safe_ratio(agg["age_25_64"], agg["population"]),
        "national_households": float(agg["households"]),
        "national_population": float(agg["population"]),
    }


def build_fsa_income_benchmarks(df: pl.DataFrame) -> pl.DataFrame:
    """FSA income = SUM(aggregate_household_income) / SUM(income_household_base)."""
    return (
        df.group_by("fsa")
        .agg(
            [
                pl.col("aggregate_household_income_2026").sum().alias("fsa_agg_income"),
                pl.col("income_household_base").sum().alias("fsa_income_base"),
            ]
        )
        .with_columns(
            pl.when(pl.col("fsa_income_base") > 0)
            .then(pl.col("fsa_agg_income") / pl.col("fsa_income_base"))
            .otherwise(None)
            .alias("fsa_income")
        )
        .select(["fsa", "fsa_income", "fsa_income_base"])
    )


def stabilize_income_expr(national_income: float) -> pl.Expr:
    reliable_pc = (
        (pl.col("households_2026") >= INCOME_HH_MIN)
        & pl.col("median_household_income_2026").is_between(INCOME_FLOOR, INCOME_CEILING)
    )
    return (
        pl.when(reliable_pc)
        .then(pl.col("median_household_income_2026"))
        .when(pl.col("fsa_income").is_not_null() & (pl.col("fsa_income") > 0))
        .then(pl.col("fsa_income"))
        .otherwise(pl.lit(national_income))
        .alias("stabilized_income")
    )


def income_source_expr() -> pl.Expr:
    reliable_pc = (
        (pl.col("households_2026") >= INCOME_HH_MIN)
        & pl.col("median_household_income_2026").is_between(INCOME_FLOOR, INCOME_CEILING)
    )
    return (
        pl.when(reliable_pc)
        .then(pl.lit("postal_median"))
        .when(pl.col("fsa_income").is_not_null() & (pl.col("fsa_income") > 0))
        .then(pl.lit("fsa_benchmark"))
        .otherwise(pl.lit("national_fallback"))
        .alias("income_source")
    )


def add_postal_factors(
    df: pl.DataFrame,
    benchmarks: dict[str, float],
    rural_adjustment_factor: float = DEFAULT_RURAL_ADJUSTMENT_FACTOR,
) -> pl.DataFrame:
    """Apply the same base demand formula to rural and non-rural postal codes."""
    ng = benchmarks["national_ground_oriented_share"]
    nh = benchmarks["national_high_rise_share"]
    nf = benchmarks["national_family_share"]
    na = benchmarks["national_age_25_64_share"]
    national_income = benchmarks["national_income"]
    rural_factor = clip_rural_adjustment_factor(rural_adjustment_factor)

    out = df.with_columns(
        [
            stabilize_income_expr(national_income),
            income_source_expr(),
            pl.when(pl.col("housing_structure_base") > 0)
            .then(
                (pl.col("single_detached_households") + pl.col("semi_detached_households"))
                / pl.col("housing_structure_base")
            )
            .otherwise(None)
            .alias("ground_oriented_share"),
            pl.when(pl.col("housing_structure_base") > 0)
            .then(
                pl.col("apartment_5plus_storey_households")
                / pl.col("housing_structure_base")
            )
            .otherwise(None)
            .alias("high_rise_share"),
            pl.when(pl.col("household_type_base") > 0)
            .then(pl.col("family_households") / pl.col("household_type_base"))
            .otherwise(None)
            .alias("family_share"),
            pl.when(pl.col("population_2026") > 0)
            .then(
                (pl.col("population_age_25_44") + pl.col("population_age_45_64"))
                / pl.col("population_2026")
            )
            .otherwise(None)
            .alias("age_25_64_share"),
        ]
    ).with_columns(
        [
            (pl.col("stabilized_income") / INCOME_REF)
            .sqrt()
            .clip(0.80, 1.30)
            .alias("income_factor"),
            (
                pl.lit(1.0)
                + 0.10 * (pl.col("ground_oriented_share") - ng)
                - 0.05 * (pl.col("high_rise_share") - nh)
            )
            .clip(0.90, 1.10)
            .alias("housing_factor"),
            (pl.lit(1.0) + 0.15 * (pl.col("family_share") - nf))
            .clip(0.925, 1.075)
            .alias("family_factor"),
            (pl.lit(1.0) + 0.10 * (pl.col("age_25_64_share") - na))
            .clip(0.95, 1.05)
            .alias("age_factor"),
        ]
    ).with_columns(
        (
            pl.col("households_2026")
            * pl.col("income_factor")
            * pl.col("housing_factor")
            * pl.col("family_factor")
            * pl.col("age_factor")
        ).alias("base_addressable_demand")
    ).with_columns(
        [
            # Optional rural multiplier only; default 1.0 (no automatic penalty/boost).
            pl.when(pl.col("is_rural"))
            .then(pl.col("base_addressable_demand") * pl.lit(rural_factor))
            .otherwise(pl.col("base_addressable_demand"))
            .alias("adjusted_addressable_demand"),
            pl.when(pl.col("is_rural"))
            .then(pl.lit(rural_factor))
            .otherwise(pl.lit(1.0))
            .alias("rural_adjustment_applied"),
        ]
    ).with_columns(
        [
            # Backward-compatible alias: unadjusted base demand
            pl.col("base_addressable_demand").alias("addressable_household_demand"),
            (
                pl.col("base_addressable_demand") / pl.col("households_2026")
            ).alias("demand_index_per_household"),
        ]
    )
    return out


def load_analysis_frame(
    demos_path: Path,
    crosswalk_path: Path,
) -> pl.DataFrame:
    demos = pl.read_csv(demos_path, columns=DEMO_COLUMNS).with_columns(
        [
            pl.col("postal_code")
            .cast(pl.Utf8)
            .str.to_uppercase()
            .str.replace_all(r"\s+", "")
            .alias("postal_code"),
            pl.col("fsa").cast(pl.Utf8).str.to_uppercase().str.replace_all(r"\s+", ""),
            pl.col("is_rural_postal_code").cast(pl.Boolean),
        ]
    )

    numeric_cols = [
        c
        for c in DEMO_COLUMNS
        if c not in {"postal_code", "fsa", "postal_region", "is_rural_postal_code"}
    ]
    demos = demos.with_columns([pl.col(c).cast(pl.Float64) for c in numeric_cols])
    demos = demos.with_columns(rural_flag_expr())

    crosswalk = (
        pl.read_parquet(crosswalk_path)
        .select(["postal_code", "h3_r8", "latitude", "longitude"])
        .with_columns(
            pl.col("postal_code")
            .cast(pl.Utf8)
            .str.to_uppercase()
            .str.replace_all(r"\s+", "")
        )
    )

    joined = demos.join(crosswalk, on="postal_code", how="inner")

    # All populated H3-assigned postal codes (rural + non-rural)
    analysis = joined.filter(
        (pl.col("households_2026") > 0) & pl.col("h3_r8").is_not_null()
    )

    prefix = (
        pl.when(pl.col("postal_region").is_not_null())
        .then(pl.col("postal_region").cast(pl.Utf8).str.to_uppercase().str.slice(0, 1))
        .otherwise(pl.col("fsa").str.slice(0, 1))
    )
    analysis = analysis.with_columns(
        prefix.replace_strict(PROVINCE_BY_FSA_PREFIX, default="UNKNOWN").alias("province")
    )
    return analysis


def aggregate_to_h3(
    postal: pl.DataFrame,
    benchmarks: dict[str, float],
    rural_hh_share_threshold: float = DEFAULT_RURAL_HH_SHARE_THRESHOLD,
) -> pl.DataFrame:
    """Sum demand and raw counts (including rural); recalculate shares/factors at H3."""
    ng = benchmarks["national_ground_oriented_share"]
    nh = benchmarks["national_high_rise_share"]
    nf = benchmarks["national_family_share"]
    na = benchmarks["national_age_25_64_share"]

    hex_agg = (
        postal.group_by("h3_r8")
        .agg(
            [
                pl.col("postal_code").n_unique().alias("contributing_postal_code_count"),
                pl.col("households_2026").sum().alias("households"),
                pl.col("population_2026").sum().alias("population"),
                pl.col("base_addressable_demand").sum().alias("base_addressable_demand"),
                pl.col("adjusted_addressable_demand")
                .sum()
                .alias("adjusted_addressable_demand"),
                pl.col("aggregate_household_income_2026")
                .sum()
                .alias("aggregate_household_income_2026"),
                pl.col("income_household_base").sum().alias("income_household_base"),
                (
                    pl.col("single_detached_households") + pl.col("semi_detached_households")
                )
                .sum()
                .alias("ground_oriented_households"),
                pl.col("apartment_5plus_storey_households")
                .sum()
                .alias("apartment_5plus_storey_households"),
                pl.col("housing_structure_base").sum().alias("housing_structure_base"),
                pl.col("family_households").sum().alias("family_households"),
                pl.col("household_type_base").sum().alias("household_type_base"),
                (pl.col("population_age_25_44") + pl.col("population_age_45_64"))
                .sum()
                .alias("population_age_25_64"),
                (
                    (pl.col("stabilized_income") * pl.col("households_2026")).sum()
                    / pl.col("households_2026").sum()
                ).alias("stabilized_income"),
                pl.col("province")
                .sort_by(pl.col("households_2026"), descending=True)
                .first()
                .alias("province"),
                # Rural composition
                pl.col("households_2026")
                .filter(pl.col("is_rural"))
                .sum()
                .fill_null(0.0)
                .alias("rural_household_count"),
                pl.col("population_2026")
                .filter(pl.col("is_rural"))
                .sum()
                .fill_null(0.0)
                .alias("rural_population"),
                pl.col("postal_code")
                .filter(pl.col("is_rural"))
                .n_unique()
                .alias("rural_postal_code_count"),
                # Data-quality rollups
                (pl.col("income_source") == "postal_median")
                .sum()
                .alias("n_income_postal_median"),
                (pl.col("income_source") == "fsa_benchmark")
                .sum()
                .alias("n_income_fsa_benchmark"),
                (pl.col("income_source") == "national_fallback")
                .sum()
                .alias("n_income_national_fallback"),
                (pl.col("housing_structure_base") <= 0)
                .any()
                .alias("flag_missing_housing_base"),
                (pl.col("household_type_base") <= 0)
                .any()
                .alias("flag_missing_household_type_base"),
                (pl.col("population_2026") <= 0).any().alias("flag_missing_population"),
                (pl.col("households_2026") < INCOME_HH_MIN)
                .any()
                .alias("flag_has_low_hh_postal"),
                (pl.col("income_source") != "postal_median")
                .any()
                .alias("flag_income_imputed"),
                pl.col("is_rural").any().alias("_has_rural_pc"),
            ]
        )
        .rename({"h3_r8": "h3_id"})
    )

    hex_agg = (
        hex_agg.filter(pl.col("households") > 0)
        .with_columns(
            [
                (pl.col("rural_household_count") / pl.col("households")).alias(
                    "rural_household_share"
                ),
                pl.col("base_addressable_demand").alias("addressable_household_demand"),
            ]
        )
        .with_columns(
            [
                (pl.col("rural_household_share") >= rural_hh_share_threshold).alias(
                    "is_rural_h3"
                ),
                # Rural FSA points often represent large catchments — imprecise for H3
                pl.when(pl.col("_has_rural_pc"))
                .then(pl.lit("rural_fsa_centroid_imprecise"))
                .otherwise(pl.lit("urban_local"))
                .alias("coordinate_precision_flag"),
                # Map filter helpers
                pl.lit(True).alias("filter_all_areas"),
                pl.lit(True).alias("filter_rural_included"),
                (pl.col("rural_household_share") < rural_hh_share_threshold).alias(
                    "filter_rural_excluded"
                ),
                (pl.col("rural_household_share") >= rural_hh_share_threshold).alias(
                    "filter_rural_only"
                ),
                pl.when(pl.col("housing_structure_base") > 0)
                .then(pl.col("ground_oriented_households") / pl.col("housing_structure_base"))
                .otherwise(None)
                .alias("ground_oriented_share"),
                pl.when(pl.col("housing_structure_base") > 0)
                .then(
                    pl.col("apartment_5plus_storey_households")
                    / pl.col("housing_structure_base")
                )
                .otherwise(None)
                .alias("high_rise_share"),
                pl.when(pl.col("household_type_base") > 0)
                .then(pl.col("family_households") / pl.col("household_type_base"))
                .otherwise(None)
                .alias("family_share"),
                pl.when(pl.col("population") > 0)
                .then(pl.col("population_age_25_64") / pl.col("population"))
                .otherwise(None)
                .alias("age_25_64_share"),
                (pl.col("base_addressable_demand") / pl.col("households")).alias(
                    "demand_index_per_household"
                ),
                (pl.col("adjusted_addressable_demand") / pl.col("households")).alias(
                    "adjusted_demand_index_per_household"
                ),
            ]
        )
        .with_columns(
            [
                (pl.col("stabilized_income") / INCOME_REF)
                .sqrt()
                .clip(0.80, 1.30)
                .alias("income_factor"),
                (
                    pl.lit(1.0)
                    + 0.10 * (pl.col("ground_oriented_share") - ng)
                    - 0.05 * (pl.col("high_rise_share") - nh)
                )
                .clip(0.90, 1.10)
                .alias("housing_factor"),
                (pl.lit(1.0) + 0.15 * (pl.col("family_share") - nf))
                .clip(0.925, 1.075)
                .alias("family_factor"),
                (pl.lit(1.0) + 0.10 * (pl.col("age_25_64_share") - na))
                .clip(0.95, 1.05)
                .alias("age_factor"),
            ]
        )
        .drop("_has_rural_pc")
    )
    return hex_agg


def _rank_percentile(df: pl.DataFrame, value_col: str, rank_alias: str, pct_alias: str) -> pl.DataFrame:
    n = df.height
    if n == 0:
        return df.with_columns(
            [
                pl.lit(None).cast(pl.Int64).alias(rank_alias),
                pl.lit(None).cast(pl.Float64).alias(pct_alias),
            ]
        )
    return df.with_columns(
        pl.col(value_col)
        .rank(method="ordinal", descending=True)
        .cast(pl.Int64)
        .alias(rank_alias)
    ).with_columns(
        ((pl.lit(n) - pl.col(rank_alias) + 1) / pl.lit(n)).alias(pct_alias)
    )


def add_ranks(hex_df: pl.DataFrame) -> pl.DataFrame:
    ranked = _rank_percentile(
        hex_df,
        "base_addressable_demand",
        "national_base_demand_rank",
        "national_base_demand_percentile",
    )
    ranked = _rank_percentile(
        ranked,
        "adjusted_addressable_demand",
        "national_adjusted_demand_rank",
        "national_adjusted_demand_percentile",
    )

    # Backward-compatible aliases (base / unadjusted)
    ranked = ranked.with_columns(
        [
            pl.col("national_base_demand_rank").alias("national_demand_rank"),
            pl.col("national_base_demand_percentile").alias("national_demand_percentile"),
        ]
    )

    # Province ranks on base demand
    ranked = ranked.with_columns(
        [
            pl.col("base_addressable_demand")
            .rank(method="ordinal", descending=True)
            .over("province")
            .cast(pl.Int64)
            .alias("province_demand_rank"),
            pl.col("h3_id").count().over("province").alias("_prov_n"),
        ]
    ).with_columns(
        (
            (pl.col("_prov_n") - pl.col("province_demand_rank") + 1) / pl.col("_prov_n")
        ).alias("province_demand_percentile")
    ).drop("_prov_n")

    # Rural-only / non-rural-only ranks (within each subset; null outside)
    rural = ranked.filter(pl.col("is_rural_h3"))
    nonrural = ranked.filter(~pl.col("is_rural_h3"))
    rural = _rank_percentile(
        rural,
        "base_addressable_demand",
        "rural_only_demand_rank",
        "rural_only_demand_percentile",
    ).select(
        ["h3_id", "rural_only_demand_rank", "rural_only_demand_percentile"]
    )
    nonrural = _rank_percentile(
        nonrural,
        "base_addressable_demand",
        "nonrural_only_demand_rank",
        "nonrural_only_demand_percentile",
    ).select(
        ["h3_id", "nonrural_only_demand_rank", "nonrural_only_demand_percentile"]
    )

    ranked = (
        ranked.join(rural, on="h3_id", how="left")
        .join(nonrural, on="h3_id", how="left")
    )

    q01 = ranked["demand_index_per_household"].quantile(0.01)
    q99 = ranked["demand_index_per_household"].quantile(0.99)
    ranked = ranked.with_columns(
        (
            (pl.col("demand_index_per_household") <= q01)
            | (pl.col("demand_index_per_household") >= q99)
        ).alias("flag_extreme_demand_index")
    )
    return ranked.sort("national_base_demand_rank")


def select_output_columns(df: pl.DataFrame) -> pl.DataFrame:
    cols = [
        "h3_id",
        "province",
        "households",
        "population",
        "is_rural_h3",
        "rural_household_count",
        "rural_household_share",
        "rural_population",
        "rural_postal_code_count",
        "coordinate_precision_flag",
        "base_addressable_demand",
        "adjusted_addressable_demand",
        "addressable_household_demand",
        "demand_index_per_household",
        "adjusted_demand_index_per_household",
        "stabilized_income",
        "income_factor",
        "ground_oriented_share",
        "high_rise_share",
        "housing_factor",
        "family_share",
        "family_factor",
        "age_25_64_share",
        "age_factor",
        "national_base_demand_rank",
        "national_base_demand_percentile",
        "national_adjusted_demand_rank",
        "national_adjusted_demand_percentile",
        "national_demand_rank",
        "national_demand_percentile",
        "rural_only_demand_rank",
        "rural_only_demand_percentile",
        "nonrural_only_demand_rank",
        "nonrural_only_demand_percentile",
        "province_demand_rank",
        "province_demand_percentile",
        "filter_all_areas",
        "filter_rural_included",
        "filter_rural_excluded",
        "filter_rural_only",
        "contributing_postal_code_count",
        "n_income_postal_median",
        "n_income_fsa_benchmark",
        "n_income_national_fallback",
        "flag_missing_housing_base",
        "flag_missing_household_type_base",
        "flag_missing_population",
        "flag_has_low_hh_postal",
        "flag_income_imputed",
        "flag_extreme_demand_index",
        "ground_oriented_households",
        "apartment_5plus_storey_households",
        "housing_structure_base",
        "family_households",
        "household_type_base",
        "population_age_25_64",
        "aggregate_household_income_2026",
        "income_household_base",
    ]
    return df.select([c for c in cols if c in df.columns])


def _factor_dist_lines(df: pl.DataFrame, label: str) -> list[str]:
    lines = [f"### {label}"]
    if df.height == 0:
        lines.append("- (no rows)")
        return lines
    for col in [
        "income_factor",
        "housing_factor",
        "family_factor",
        "age_factor",
        "demand_index_per_household",
    ]:
        if col not in df.columns:
            continue
        s = df[col].drop_nulls()
        if s.len() == 0:
            continue
        lines.append(
            f"- {col}: min={s.min():.4f} p25={s.quantile(0.25):.4f} "
            f"median={s.median():.4f} p75={s.quantile(0.75):.4f} max={s.max():.4f}"
        )
    return lines


def build_validation_report(
    postal: pl.DataFrame,
    ranked: pl.DataFrame,
    benchmarks: dict[str, float],
    meta: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# Demographic Demand Model — Validation Report")
    lines.append("")
    lines.append("## Totals")
    lines.append(f"- Analysis postal codes: {postal.height:,}")
    lines.append(f"- Ranked H3 R8 hexagons: {ranked.height:,}")
    lines.append(f"- Total households (raw): {postal['households_2026'].sum():,.0f}")
    lines.append(f"- Total population: {postal['population_2026'].sum():,.0f}")
    lines.append(
        f"- Total base addressable demand: "
        f"{postal['base_addressable_demand'].sum():,.2f}"
    )
    lines.append(
        f"- Total adjusted addressable demand: "
        f"{postal['adjusted_addressable_demand'].sum():,.2f}"
    )
    hh_postal = float(postal["households_2026"].sum())
    hh_hex = float(ranked["households"].sum())
    base_postal = float(postal["base_addressable_demand"].sum())
    base_hex = float(ranked["base_addressable_demand"].sum())
    lines.append(f"- Household reconciliation |delta|: {abs(hh_postal - hh_hex):.6f}")
    lines.append(f"- Base demand reconciliation |delta|: {abs(base_postal - base_hex):.6f}")
    lines.append("")

    rural_pc = postal.filter(pl.col("is_rural"))
    nonrural_pc = postal.filter(~pl.col("is_rural"))
    lines.append("## Rural vs non-rural (postal)")
    lines.append(
        f"- Rural PCs: {rural_pc.height:,} | HH={rural_pc['households_2026'].sum():,.0f} | "
        f"base_demand={rural_pc['base_addressable_demand'].sum():,.1f}"
    )
    lines.append(
        f"- Non-rural PCs: {nonrural_pc.height:,} | HH={nonrural_pc['households_2026'].sum():,.0f} | "
        f"base_demand={nonrural_pc['base_addressable_demand'].sum():,.1f}"
    )
    lines.append(
        f"- Rural HH share of analysis: "
        f"{safe_ratio(float(rural_pc['households_2026'].sum()), hh_postal):.4f}"
    )
    lines.append("")

    rural_h3 = ranked.filter(pl.col("is_rural_h3"))
    nonrural_h3 = ranked.filter(~pl.col("is_rural_h3"))
    lines.append("## Rural vs non-rural (H3)")
    lines.append(
        f"- Rural hexes (is_rural_h3): {rural_h3.height:,} | "
        f"HH={rural_h3['households'].sum():,.0f} | "
        f"base_demand={rural_h3['base_addressable_demand'].sum():,.1f}"
    )
    lines.append(
        f"- Non-rural hexes: {nonrural_h3.height:,} | "
        f"HH={nonrural_h3['households'].sum():,.0f} | "
        f"base_demand={nonrural_h3['base_addressable_demand'].sum():,.1f}"
    )
    imprecise = ranked.filter(
        pl.col("coordinate_precision_flag") == "rural_fsa_centroid_imprecise"
    )
    lines.append(
        f"- Hexes with rural coordinate-precision flag: {imprecise.height:,} "
        f"(HH={imprecise['households'].sum():,.0f})"
    )
    lines.append("")

    lines.append("## National benchmarks (sum/sum, full analysis universe)")
    for key in [
        "national_income",
        "national_ground_oriented_share",
        "national_high_rise_share",
        "national_family_share",
        "national_age_25_64_share",
    ]:
        lines.append(f"- {key}: {benchmarks[key]:.6f}")
    lines.append("")

    lines.extend(_factor_dist_lines(ranked, "Factor distributions — all H3"))
    lines.append("")
    lines.extend(_factor_dist_lines(rural_h3, "Factor distributions — rural H3"))
    lines.append("")
    lines.extend(_factor_dist_lines(nonrural_h3, "Factor distributions — non-rural H3"))
    lines.append("")

    lines.append("## Missing / quality flags (H3 counts)")
    for col in [
        "flag_missing_housing_base",
        "flag_missing_household_type_base",
        "flag_missing_population",
        "flag_has_low_hh_postal",
        "flag_income_imputed",
        "flag_extreme_demand_index",
    ]:
        n_true = int(ranked.filter(pl.col(col) == True).height)  # noqa: E712
        lines.append(f"- {col}: {n_true:,}")
    lines.append("")

    src = postal.group_by("income_source").len().sort("len", descending=True)
    lines.append("## Postal income source mix")
    for row in src.iter_rows(named=True):
        lines.append(f"- {row['income_source']}: {row['len']:,}")
    lines.append("")

    lines.append("## Extreme rankings")
    lines.append("### Highest base demand (all)")
    for row in ranked.head(10).iter_rows(named=True):
        lines.append(
            f"- #{row['national_base_demand_rank']} {row['h3_id']} "
            f"({'rural' if row['is_rural_h3'] else 'non-rural'}, {row['province']}): "
            f"base={row['base_addressable_demand']:.1f} adj={row['adjusted_addressable_demand']:.1f} "
            f"hh={row['households']:.0f} rural_share={row['rural_household_share']:.2f} "
            f"coord={row['coordinate_precision_flag']}"
        )
    lines.append("### Highest base demand (rural-only)")
    for row in rural_h3.sort("rural_only_demand_rank").head(5).iter_rows(named=True):
        lines.append(
            f"- rural#{row['rural_only_demand_rank']} {row['h3_id']} ({row['province']}): "
            f"base={row['base_addressable_demand']:.1f} hh={row['households']:.0f} "
            f"rural_share={row['rural_household_share']:.2f}"
        )
    lines.append("### Highest base demand (non-rural-only)")
    for row in nonrural_h3.sort("nonrural_only_demand_rank").head(5).iter_rows(named=True):
        lines.append(
            f"- nonrural#{row['nonrural_only_demand_rank']} {row['h3_id']} ({row['province']}): "
            f"base={row['base_addressable_demand']:.1f} hh={row['households']:.0f}"
        )
    lines.append("")

    lines.append("## Household coverage")
    lines.append(
        f"- Source H3-assigned analysis HH: {hh_postal:,.0f} "
        f"(rural {float(rural_pc['households_2026'].sum()):,.0f} + "
        f"non-rural {float(nonrural_pc['households_2026'].sum()):,.0f})"
    )
    lines.append(
        "- Note: postal codes with null coordinates remain excluded (no H3 cell); "
        "density is not used to reduce demand."
    )
    lines.append("")

    lines.append("## Run metadata")
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def build_sensitivity_report(
    ranked_off: pl.DataFrame,
    ranked_on: pl.DataFrame,
    factor_off: float,
    factor_on: float,
    meta: dict[str, Any],
) -> str:
    """Compare national rankings with rural adjustment off vs on."""
    lines = [
        "# Rural Adjustment Sensitivity",
        "",
        f"- Adjustment OFF factor: {factor_off}",
        f"- Adjustment ON factor: {factor_on}",
        f"- Default production factor: {meta.get('rural_adjustment_factor')}",
        "",
        "## Rationale",
        "- Default rural adjustment = 1.0 (no change).",
        "- Housing, family, and income factors already reflect rural structure "
        "(e.g. higher detached share); an extra rural multiplier would double-count.",
        "- No independent pet-ownership or rural spend signal is available.",
        "- Configurable factor is capped to "
        f"[{RURAL_ADJUSTMENT_FACTOR_MIN}, {RURAL_ADJUSTMENT_FACTOR_MAX}].",
        "",
    ]

    off = ranked_off.select(
        [
            "h3_id",
            "is_rural_h3",
            pl.col("base_addressable_demand").alias("demand_off"),
            pl.col("national_base_demand_rank").alias("rank_off"),
        ]
    )
    on = ranked_on.select(
        [
            "h3_id",
            pl.col("adjusted_addressable_demand").alias("demand_on"),
            pl.col("national_adjusted_demand_rank").alias("rank_on"),
        ]
    )
    cmp_ = off.join(on, on="h3_id", how="inner").with_columns(
        (pl.col("rank_on") - pl.col("rank_off")).alias("rank_delta")
    )

    lines.append("## Totals")
    lines.append(f"- Demand OFF (base sum): {cmp_['demand_off'].sum():,.2f}")
    lines.append(f"- Demand ON (adjusted sum): {cmp_['demand_on'].sum():,.2f}")
    lines.append(
        f"- Absolute difference: {abs(float(cmp_['demand_on'].sum()) - float(cmp_['demand_off'].sum())):,.2f}"
    )
    lines.append("")

    moved = cmp_.filter(pl.col("rank_delta") != 0)
    lines.append("## Rank movement")
    lines.append(f"- Hexes with rank change: {moved.height:,} / {cmp_.height:,}")
    if moved.height:
        lines.append(f"- Max rank improvement (more negative delta): {moved['rank_delta'].min()}")
        lines.append(f"- Max rank decline: {moved['rank_delta'].max()}")
        rural_moved = moved.filter(pl.col("is_rural_h3"))
        lines.append(f"- Rural hexes moved: {rural_moved.height:,}")
    else:
        lines.append("- No rank changes (ON ≡ OFF at this factor).")
    lines.append("")

    lines.append("## Top 10 by OFF (base)")
    for row in cmp_.sort("rank_off").head(10).iter_rows(named=True):
        lines.append(
            f"- off#{row['rank_off']} → on#{row['rank_on']} {row['h3_id']} "
            f"rural={row['is_rural_h3']} demand_off={row['demand_off']:.1f} "
            f"demand_on={row['demand_on']:.1f}"
        )
    lines.append("")
    lines.append("## Top 10 by ON (adjusted)")
    for row in cmp_.sort("rank_on").head(10).iter_rows(named=True):
        lines.append(
            f"- on#{row['rank_on']} ← off#{row['rank_off']} {row['h3_id']} "
            f"rural={row['is_rural_h3']} demand_on={row['demand_on']:.1f} "
            f"demand_off={row['demand_off']:.1f}"
        )
    lines.append("")
    return "\n".join(lines)


def run_pipeline(
    demos_path: Path = DEFAULT_DEMOS,
    crosswalk_path: Path = DEFAULT_CROSSWALK,
    processed_dir: Path = DEFAULT_PROCESSED,
    output_dir: Path = DEFAULT_OUTPUT,
    rural_adjustment_factor: float = DEFAULT_RURAL_ADJUSTMENT_FACTOR,
    rural_hh_share_threshold: float = DEFAULT_RURAL_HH_SHARE_THRESHOLD,
) -> dict[str, Path]:
    t0 = time.perf_counter()
    processed_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    rural_factor = clip_rural_adjustment_factor(rural_adjustment_factor)

    print(f"Demos: {demos_path}")
    print(f"Crosswalk: {crosswalk_path}")
    print(f"Rural adjustment factor (clipped): {rural_factor}")
    print(f"Rural H3 HH-share threshold: {rural_hh_share_threshold}")

    analysis = load_analysis_frame(demos_path, crosswalk_path)
    n_rural = analysis.filter(pl.col("is_rural")).height
    n_nonrural = analysis.filter(~pl.col("is_rural")).height
    print(
        f"Analysis postal codes (populated, H3-assigned): {analysis.height:,} "
        f"(rural={n_rural:,}, non-rural={n_nonrural:,})"
    )

    benchmarks = compute_national_benchmarks(analysis)
    fsa_income = build_fsa_income_benchmarks(analysis)
    analysis = analysis.join(fsa_income, on="fsa", how="left")
    postal = add_postal_factors(analysis, benchmarks, rural_adjustment_factor=rural_factor)

    postal_path = processed_dir / "postal_demographic_demand.parquet"
    postal.write_parquet(postal_path)
    print(f"Wrote {postal_path}")

    hex_agg = aggregate_to_h3(
        postal, benchmarks, rural_hh_share_threshold=rural_hh_share_threshold
    )
    ranked = add_ranks(hex_agg)
    ranked_out = select_output_columns(ranked)

    ranking_parquet = processed_dir / "h3_r8_demographic_demand_ranking.parquet"
    ranking_csv = processed_dir / "h3_r8_demographic_demand_ranking.csv"
    ranked_out.write_parquet(ranking_parquet)
    ranked_out.write_csv(ranking_csv)
    print(f"Wrote {ranking_parquet} ({ranked_out.height:,} hexagons)")
    print(f"Wrote {ranking_csv}")

    # Sensitivity: OFF = base (factor 1.0); ON = configured adjusted
    # If configured factor is already 1.0, also materialize an illustrative ON run.
    postal_off = add_postal_factors(analysis, benchmarks, rural_adjustment_factor=1.0)
    hex_off = add_ranks(
        aggregate_to_h3(
            postal_off, benchmarks, rural_hh_share_threshold=rural_hh_share_threshold
        )
    )
    if abs(rural_factor - 1.0) < 1e-12:
        sens_factor_on = ILLUSTRATIVE_RURAL_SENSITIVITY_FACTOR
        postal_on = add_postal_factors(
            analysis, benchmarks, rural_adjustment_factor=sens_factor_on
        )
        hex_on = add_ranks(
            aggregate_to_h3(
                postal_on, benchmarks, rural_hh_share_threshold=rural_hh_share_threshold
            )
        )
        # Persist illustrative adjusted columns alongside production (factor=1) master
        sens_note = (
            f"Production factor is 1.0; sensitivity ON uses illustrative "
            f"{sens_factor_on} (not applied to master output)."
        )
    else:
        sens_factor_on = rural_factor
        hex_on = ranked
        sens_note = "Sensitivity ON uses the configured production rural adjustment."

    meta = {
        "demos_path": str(demos_path),
        "crosswalk_path": str(crosswalk_path),
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
        "n_postal": postal.height,
        "n_postal_rural": n_rural,
        "n_postal_nonrural": n_nonrural,
        "n_hex": ranked_out.height,
        "n_hex_rural": ranked_out.filter(pl.col("is_rural_h3")).height,
        "n_hex_nonrural": ranked_out.filter(~pl.col("is_rural_h3")).height,
        "rural_adjustment_factor": rural_factor,
        "rural_hh_share_threshold": rural_hh_share_threshold,
        "rural_adjustment_rationale": (
            "Default 1.0 — no automatic rural penalty/boost; "
            "housing/family/income already capture rural structure."
        ),
        "sensitivity_note": sens_note,
    }

    benchmarks_payload = {
        **benchmarks,
        "rural_adjustment_factor": rural_factor,
        "rural_hh_share_threshold": rural_hh_share_threshold,
        "rural_adjustment_factor_bounds": [
            RURAL_ADJUSTMENT_FACTOR_MIN,
            RURAL_ADJUSTMENT_FACTOR_MAX,
        ],
    }
    benchmarks_path = processed_dir / "demographic_demand_national_benchmarks.json"
    with benchmarks_path.open("w", encoding="utf-8") as f:
        json.dump(benchmarks_payload, f, indent=2)
    print(f"Wrote {benchmarks_path}")

    report = build_validation_report(postal, ranked_out, benchmarks, meta)
    report_path = output_dir / "demographic_demand_validation.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path}")

    sens = build_sensitivity_report(
        hex_off, hex_on, factor_off=1.0, factor_on=sens_factor_on, meta=meta
    )
    sens_path = output_dir / "demographic_demand_rural_sensitivity.md"
    sens_path.write_text(sens, encoding="utf-8")
    print(f"Wrote {sens_path}")

    # Compact sensitivity table (top ranks)
    sens_table = (
        hex_off.select(
            [
                "h3_id",
                "is_rural_h3",
                "province",
                pl.col("base_addressable_demand").alias("demand_adjustment_off"),
                pl.col("national_base_demand_rank").alias("rank_adjustment_off"),
            ]
        )
        .join(
            hex_on.select(
                [
                    "h3_id",
                    pl.col("adjusted_addressable_demand").alias("demand_adjustment_on"),
                    pl.col("national_adjusted_demand_rank").alias("rank_adjustment_on"),
                ]
            ),
            on="h3_id",
            how="inner",
        )
        .with_columns(
            (pl.col("rank_adjustment_on") - pl.col("rank_adjustment_off")).alias(
                "rank_delta_on_minus_off"
            )
        )
        .sort("rank_adjustment_off")
    )
    sens_csv = processed_dir / "demographic_demand_rural_sensitivity.csv"
    sens_table.write_csv(sens_csv)
    print(f"Wrote {sens_csv}")

    print("\n=== DEMOGRAPHIC DEMAND RANKING (rural included) ===")
    print(f"Postal codes: {postal.height:,} (rural={n_rural:,})")
    print(
        f"H3 R8 hexagons: {ranked_out.height:,} "
        f"(rural_h3={meta['n_hex_rural']:,}, nonrural_h3={meta['n_hex_nonrural']:,})"
    )
    print(
        f"Total raw households: {postal['households_2026'].sum():,.0f} | "
        f"base demand: {postal['base_addressable_demand'].sum():,.1f} | "
        f"adjusted demand: {postal['adjusted_addressable_demand'].sum():,.1f}"
    )
    print(f"Elapsed: {meta['elapsed_seconds']}s")
    for row in ranked_out.head(3).iter_rows(named=True):
        print(
            f"  base#{row['national_base_demand_rank']} {row['h3_id']} "
            f"{'rural' if row['is_rural_h3'] else 'non-rural'} "
            f"base={row['base_addressable_demand']:.1f} "
            f"hh={row['households']:.0f}"
        )

    return {
        "postal": postal_path,
        "ranking_parquet": ranking_parquet,
        "ranking_csv": ranking_csv,
        "benchmarks": benchmarks_path,
        "validation": report_path,
        "sensitivity_md": sens_path,
        "sensitivity_csv": sens_csv,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build demographic demand H3 R8 ranking (rural included)"
    )
    p.add_argument("--demos", type=Path, default=DEFAULT_DEMOS)
    p.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    p.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument(
        "--rural-adjustment-factor",
        type=float,
        default=DEFAULT_RURAL_ADJUSTMENT_FACTOR,
        help=(
            f"Optional multiplier applied only to rural postal demand "
            f"(default {DEFAULT_RURAL_ADJUSTMENT_FACTOR}; clipped to "
            f"[{RURAL_ADJUSTMENT_FACTOR_MIN}, {RURAL_ADJUSTMENT_FACTOR_MAX}]). "
            "Use 1.0 for no rural-specific adjustment."
        ),
    )
    p.add_argument(
        "--rural-hh-share-threshold",
        type=float,
        default=DEFAULT_RURAL_HH_SHARE_THRESHOLD,
        help="is_rural_h3 if rural_household_share >= threshold (default 0.50).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    run_pipeline(
        demos_path=args.demos,
        crosswalk_path=args.crosswalk,
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        rural_adjustment_factor=args.rural_adjustment_factor,
        rural_hh_share_threshold=args.rural_hh_share_threshold,
    )


if __name__ == "__main__":
    main()
