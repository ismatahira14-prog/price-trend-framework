import pandas as pd
import pytest

from pricelab.dashboard.data import cpi_change_table
from pricelab.dashboard.factors import (
    EVENTS,
    classify_impact,
    events_covering,
    generate_mock_monthly_factors,
    generate_mock_yearly_factors,
)
from pricelab.dashboard.theme import FACTOR_ORDER


@pytest.fixture
def change_table():
    idx = pd.date_range("2018-01-01", "2024-12-01", freq="MS")
    # a smooth-ish upward series so pct_change/rolling all produce real numbers
    values = 100 + pd.Series(range(len(idx))) * 0.8
    return cpi_change_table(pd.Series(values.values, index=idx))


def test_events_are_dated_and_ordered():
    assert len(EVENTS) >= 3
    for e in EVENTS:
        assert e["start"] < e["end"]
        assert e["color"]


def test_events_covering_finds_known_event():
    covid = pd.Timestamp("2020-06-01")
    names = [e["name"] for e in events_covering(covid)]
    assert "COVID-19 Pandemic" in names


def test_classify_impact_thresholds():
    assert classify_impact(30) == "High"
    assert classify_impact(15) == "Medium"
    assert classify_impact(5) == "Low"


def test_monthly_factors_sum_to_100_and_are_deterministic(change_table):
    a = generate_mock_monthly_factors(change_table)
    b = generate_mock_monthly_factors(change_table)
    pd.testing.assert_frame_equal(a, b)  # same seed -> identical mock output

    assert set(a["factor"].unique()) == set(FACTOR_ORDER)
    totals = a.groupby("month")["contribution_pct"].sum()
    assert (totals.round(0) == 100).all()


def test_yearly_factors_keyed_by_calendar_year(change_table):
    y = generate_mock_yearly_factors(change_table)
    assert set(y["year"]) <= set(change_table.index.year)
    totals = y.groupby("year")["contribution_pct"].sum()
    assert (totals.round(0) == 100).all()
