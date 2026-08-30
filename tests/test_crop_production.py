import pandas as pd

from pricelab.config import load_config
from pricelab.ingestion.crop_production import _fiscal_year_end, load_crop_production


def _cfg():
    src = load_config()["sources"]["crop_production"]
    return {**src, "_key": "crop_production"}


def test_fiscal_year_end_parsing():
    assert _fiscal_year_end("2024-25", "06-30") == pd.Timestamp("2025-06-30")
    assert _fiscal_year_end("2021-22", "06-30") == pd.Timestamp("2022-06-30")
    assert pd.isna(_fiscal_year_end("garbage", "06-30"))


def test_variables_and_units():
    df = load_crop_production(_cfg())
    assert set(df["variable"]) == {"crop_area", "crop_production", "crop_yield"}
    units = df.groupby("variable")["unit"].agg(set)
    assert units["crop_area"] == {"000_hectares"}
    assert units["crop_yield"] == {"tonnes_per_hectare"}
    assert (df["freq"] == "A").all()


def test_computed_yield_is_flagged_imputed_and_consistent():
    df = load_crop_production(_cfg())
    y = df[df["variable"] == "crop_yield"]
    assert y["is_imputed"].any()
    merged = (
        df.pivot_table(
            index=["date", "region", "commodity"], columns="variable", values="value"
        )
        .dropna()
    )
    approx = merged["crop_production"] / merged["crop_area"]
    # where yield was computed it must equal production/area
    close = (approx - merged["crop_yield"]).abs() < 1e-6
    assert close.mean() > 0.5
