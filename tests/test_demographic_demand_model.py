"""Unit tests for demographic demand factors, rural inclusion, and H3 aggregation."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from demographic_demand_model import (  # noqa: E402
    add_ranks,
    add_postal_factors,
    aggregate_to_h3,
    age_factor_from_share,
    build_fsa_income_benchmarks,
    clip,
    clip_rural_adjustment_factor,
    compute_national_benchmarks,
    family_factor_from_share,
    housing_factor_from_shares,
    income_factor_from_stabilized,
    is_rural_fsa_rule,
    province_from_fsa_prefix,
    resolve_is_rural,
    safe_ratio,
)


def _base_postal_frame(**overrides):
    base = {
        "postal_code": ["A", "B", "C"],
        "fsa": ["M5V", "K0A", "M5V"],
        "households_2026": [30.0, 20.0, 10.0],
        "median_household_income_2026": [100_000.0, 100_000.0, 100_000.0],
        "aggregate_household_income_2026": [3_000_000.0, 2_000_000.0, 1_000_000.0],
        "income_household_base": [30.0, 20.0, 10.0],
        "single_detached_households": [10.0, 18.0, 2.0],
        "semi_detached_households": [0.0, 0.0, 0.0],
        "apartment_5plus_storey_households": [10.0, 0.0, 6.0],
        "housing_structure_base": [30.0, 20.0, 10.0],
        "family_households": [18.0, 16.0, 5.0],
        "household_type_base": [30.0, 20.0, 10.0],
        "population_age_25_44": [40.0, 30.0, 20.0],
        "population_age_45_64": [30.0, 20.0, 10.0],
        "population_2026": [100.0, 80.0, 40.0],
        "h3_r8": ["h_urban", "h_rural", "h_urban"],
        "province": ["ON", "ON", "ON"],
        "is_rural_postal_code": [False, True, False],
        "is_rural": [False, True, False],
    }
    base.update(overrides)
    return pl.DataFrame(base)


def test_clip():
    assert clip(0.5, 0.8, 1.3) == 0.8
    assert clip(1.0, 0.8, 1.3) == 1.0
    assert clip(2.0, 0.8, 1.3) == 1.3


def test_income_factor_caps():
    assert income_factor_from_stabilized(100_000) == pytest.approx(1.0)
    assert income_factor_from_stabilized(10_000) == pytest.approx(0.80)
    assert income_factor_from_stabilized(1_000_000) == pytest.approx(1.30)
    assert math.isnan(income_factor_from_stabilized(-1))


def test_housing_family_age_factor_caps():
    assert housing_factor_from_shares(1.0, 0.0, 0.0, 0.0) == pytest.approx(1.10)
    assert housing_factor_from_shares(0.0, 1.0, 1.0, 0.0) == pytest.approx(0.90)
    assert family_factor_from_share(1.0, 0.0) == pytest.approx(1.075)
    assert family_factor_from_share(0.0, 1.0) == pytest.approx(0.925)
    assert age_factor_from_share(1.0, 0.0) == pytest.approx(1.05)
    assert age_factor_from_share(0.0, 1.0) == pytest.approx(0.95)


def test_rural_identification():
    assert is_rural_fsa_rule("K0A")
    assert is_rural_fsa_rule("k0a1a1")
    assert not is_rural_fsa_rule("M5V")
    assert resolve_is_rural(True, "M5V")
    assert resolve_is_rural(False, "K0A")
    assert not resolve_is_rural(False, "M5V")
    assert resolve_is_rural(None, "A0A")


def test_rural_adjustment_factor_clip():
    assert clip_rural_adjustment_factor(1.0) == 1.0
    assert clip_rural_adjustment_factor(1.20) == 1.05
    assert clip_rural_adjustment_factor(0.50) == 0.95


def test_national_benchmarks_use_sums_not_mean_of_percents():
    df = pl.DataFrame(
        {
            "aggregate_household_income_2026": [100.0, 300.0],
            "income_household_base": [1.0, 3.0],
            "single_detached_households": [8.0, 2.0],
            "semi_detached_households": [0.0, 0.0],
            "apartment_5plus_storey_households": [2.0, 8.0],
            "housing_structure_base": [10.0, 10.0],
            "family_households": [9.0, 1.0],
            "household_type_base": [10.0, 10.0],
            "population_age_25_44": [40.0, 10.0],
            "population_age_45_64": [20.0, 10.0],
            "population_2026": [100.0, 100.0],
            "households_2026": [10.0, 10.0],
        }
    )
    b = compute_national_benchmarks(df)
    assert b["national_income"] == pytest.approx(100.0)
    assert b["national_ground_oriented_share"] == pytest.approx(0.5)
    assert b["national_high_rise_share"] == pytest.approx(0.5)
    assert b["national_family_share"] == pytest.approx(0.5)

    df2 = pl.DataFrame(
        {
            "aggregate_household_income_2026": [0.0, 0.0],
            "income_household_base": [1.0, 1.0],
            "single_detached_households": [9.0, 1.0],
            "semi_detached_households": [0.0, 0.0],
            "apartment_5plus_storey_households": [0.0, 0.0],
            "housing_structure_base": [10.0, 90.0],
            "family_households": [0.0, 0.0],
            "household_type_base": [1.0, 1.0],
            "population_age_25_44": [0.0, 0.0],
            "population_age_45_64": [0.0, 0.0],
            "population_2026": [1.0, 1.0],
            "households_2026": [1.0, 1.0],
        }
    )
    b2 = compute_national_benchmarks(df2)
    mean_of_shares = (0.9 + 1.0 / 90.0) / 2.0
    sum_sum = 10.0 / 100.0
    assert b2["national_ground_oriented_share"] == pytest.approx(sum_sum)
    assert b2["national_ground_oriented_share"] != pytest.approx(mean_of_shares)


def test_same_base_formula_for_rural_and_no_default_discount():
    df = _base_postal_frame()
    benchmarks = compute_national_benchmarks(df)
    fsa = build_fsa_income_benchmarks(df)
    out = add_postal_factors(df.join(fsa, on="fsa", how="left"), benchmarks, rural_adjustment_factor=1.0)

    for row in out.iter_rows(named=True):
        expected_base = (
            row["households_2026"]
            * row["income_factor"]
            * row["housing_factor"]
            * row["family_factor"]
            * row["age_factor"]
        )
        assert row["base_addressable_demand"] == pytest.approx(expected_base)
        # Default: adjusted == base for rural and non-rural
        assert row["adjusted_addressable_demand"] == pytest.approx(row["base_addressable_demand"])

    rural = out.filter(pl.col("is_rural")).row(0, named=True)
    assert rural["rural_adjustment_applied"] == pytest.approx(1.0)


def test_configurable_rural_adjustment_preserves_base():
    df = _base_postal_frame()
    benchmarks = compute_national_benchmarks(df)
    fsa = build_fsa_income_benchmarks(df)
    out = add_postal_factors(
        df.join(fsa, on="fsa", how="left"), benchmarks, rural_adjustment_factor=1.03
    )
    rural = out.filter(pl.col("is_rural")).row(0, named=True)
    urban = out.filter(~pl.col("is_rural")).row(0, named=True)
    assert rural["adjusted_addressable_demand"] == pytest.approx(
        rural["base_addressable_demand"] * 1.03
    )
    assert urban["adjusted_addressable_demand"] == pytest.approx(
        urban["base_addressable_demand"]
    )


def test_h3_includes_rural_and_flags():
    df = _base_postal_frame()
    benchmarks = compute_national_benchmarks(df)
    fsa = build_fsa_income_benchmarks(df)
    postal = add_postal_factors(df.join(fsa, on="fsa", how="left"), benchmarks)
    hex_df = aggregate_to_h3(postal, benchmarks, rural_hh_share_threshold=0.50)

    assert set(hex_df["h3_id"].to_list()) == {"h_urban", "h_rural"}
    rural_hex = hex_df.filter(pl.col("h3_id") == "h_rural").row(0, named=True)
    urban_hex = hex_df.filter(pl.col("h3_id") == "h_urban").row(0, named=True)

    assert rural_hex["is_rural_h3"] is True
    assert rural_hex["rural_household_share"] == pytest.approx(1.0)
    assert rural_hex["rural_household_count"] == pytest.approx(20.0)
    assert rural_hex["rural_postal_code_count"] == 1
    assert rural_hex["coordinate_precision_flag"] == "rural_fsa_centroid_imprecise"
    assert rural_hex["filter_rural_only"] is True
    assert rural_hex["filter_rural_excluded"] is False

    assert urban_hex["is_rural_h3"] is False
    assert urban_hex["rural_household_share"] == pytest.approx(0.0)
    assert urban_hex["coordinate_precision_flag"] == "urban_local"
    assert urban_hex["filter_rural_excluded"] is True

    # Demand sums reconcile
    assert hex_df["base_addressable_demand"].sum() == pytest.approx(
        postal["base_addressable_demand"].sum()
    )


def test_ranking_rural_and_nonrural_subsets():
    hex_df = pl.DataFrame(
        {
            "h3_id": ["h1", "h2", "h3", "h4"],
            "province": ["ON", "ON", "BC", "BC"],
            "households": [100.0, 50.0, 80.0, 20.0],
            "population": [200.0, 100.0, 160.0, 40.0],
            "base_addressable_demand": [120.0, 40.0, 100.0, 10.0],
            "adjusted_addressable_demand": [120.0, 40.0, 100.0, 10.0],
            "addressable_household_demand": [120.0, 40.0, 100.0, 10.0],
            "demand_index_per_household": [1.2, 0.8, 1.25, 0.5],
            "is_rural_h3": [False, True, False, True],
            "rural_household_share": [0.0, 1.0, 0.0, 1.0],
            "stabilized_income": [100_000.0] * 4,
            "income_factor": [1.0] * 4,
            "ground_oriented_share": [0.5] * 4,
            "high_rise_share": [0.2] * 4,
            "housing_factor": [1.0] * 4,
            "family_share": [0.6] * 4,
            "family_factor": [1.0] * 4,
            "age_25_64_share": [0.5] * 4,
            "age_factor": [1.0] * 4,
            "contributing_postal_code_count": [1, 1, 1, 1],
            "n_income_postal_median": [1, 1, 1, 1],
            "n_income_fsa_benchmark": [0, 0, 0, 0],
            "n_income_national_fallback": [0, 0, 0, 0],
            "flag_missing_housing_base": [False] * 4,
            "flag_missing_household_type_base": [False] * 4,
            "flag_missing_population": [False] * 4,
            "flag_has_low_hh_postal": [False] * 4,
            "flag_income_imputed": [False] * 4,
            "ground_oriented_households": [50.0] * 4,
            "apartment_5plus_storey_households": [20.0] * 4,
            "housing_structure_base": [100.0] * 4,
            "family_households": [60.0] * 4,
            "household_type_base": [100.0] * 4,
            "population_age_25_64": [100.0] * 4,
            "aggregate_household_income_2026": [1e6] * 4,
            "income_household_base": [100.0] * 4,
            "rural_household_count": [0.0, 50.0, 0.0, 20.0],
            "rural_population": [0.0, 100.0, 0.0, 40.0],
            "rural_postal_code_count": [0, 1, 0, 1],
            "coordinate_precision_flag": [
                "urban_local",
                "rural_fsa_centroid_imprecise",
                "urban_local",
                "rural_fsa_centroid_imprecise",
            ],
        }
    )
    ranked = add_ranks(hex_df)
    assert ranked.filter(pl.col("h3_id") == "h1")["national_base_demand_rank"][0] == 1
    # Rural-only: h2 (40) ranks above h4 (10)
    assert ranked.filter(pl.col("h3_id") == "h2")["rural_only_demand_rank"][0] == 1
    assert ranked.filter(pl.col("h3_id") == "h4")["rural_only_demand_rank"][0] == 2
    assert ranked.filter(pl.col("h3_id") == "h1")["rural_only_demand_rank"][0] is None
    # Non-rural-only: h1 then h3
    assert ranked.filter(pl.col("h3_id") == "h1")["nonrural_only_demand_rank"][0] == 1
    assert ranked.filter(pl.col("h3_id") == "h3")["nonrural_only_demand_rank"][0] == 2


def test_province_mapping():
    assert province_from_fsa_prefix("M") == "ON"
    assert province_from_fsa_prefix("V") == "BC"
    assert province_from_fsa_prefix("H") == "QC"
    assert province_from_fsa_prefix(None) == "UNKNOWN"


def test_safe_ratio():
    assert safe_ratio(10, 2) == 5.0
    assert math.isnan(safe_ratio(10, 0))
