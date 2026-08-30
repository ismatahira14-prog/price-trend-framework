import pandas as pd

from pricelab.config import load_config
from pricelab.ingestion.cpi_groups import load_cpi_groups


def _cfg():
    src = load_config()["sources"]["inflation_cpi_groups"]
    return {**src, "_key": "inflation_cpi_groups"}


def test_shape_and_schema():
    df = load_cpi_groups(_cfg())
    assert (df["variable"] == "cpi_index").all()
    assert (df["region"] == "Pakistan").all()
    assert (df["freq"] == "M").all()
    # 13 group columns; ~121 months
    assert df["commodity"].nunique() == 13
    assert 120 <= df["date"].dt.to_period("M").nunique() <= 200


def test_fiscal_month_is_calendar_month():
    df = load_cpi_groups(_cfg())
    first = df.sort_values("date")["date"].iloc[0]
    assert first == pd.Timestamp("2016-07-01")


def test_general_index_rises_over_time():
    df = load_cpi_groups(_cfg())
    g = df[df["commodity"] == "General"].sort_values("date")
    assert g["value"].iloc[0] < g["value"].iloc[-1]
    assert g["value"].iloc[0] < 150 < g["value"].iloc[-1]
