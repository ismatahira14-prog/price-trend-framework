import pandas as pd
import pytest

from pricelab.dashboard.data import (
    SnapshotMissing,
    cpi_change_table,
    cpi_series,
    crop_slice,
    crop_variants,
    group_change_table,
    latest_change_table,
    load_master_long,
    selected_period_group_table,
    with_relative_magnitude,
    yearly_group_change_table,
)
from pricelab.dashboard.theme import CPI_GROUP_ORDER
from pricelab.integration.duckdb_export import snapshot_path

GROUPS_12 = CPI_GROUP_ORDER[1:]


@pytest.fixture(scope="module")
def snapshot_df():
    if not snapshot_path().is_file():
        pytest.skip("no duckdb snapshot yet - run `python -m pricelab.ingest --all` first")
    return load_master_long()


def test_missing_snapshot_raises(tmp_path):
    with pytest.raises(SnapshotMissing):
        load_master_long(tmp_path / "nope.duckdb")


def test_cpi_series_is_wide_and_sorted(snapshot_df):
    wide = cpi_series(snapshot_df, ["General", "Transport"])
    assert list(wide.columns) == sorted(wide.columns) or set(wide.columns) == {
        "General",
        "Transport",
    }
    assert wide.index.is_monotonic_increasing


def test_latest_change_table_has_expected_columns(snapshot_df):
    wide = cpi_series(snapshot_df, ["General"])
    table = latest_change_table(wide)
    assert set(table.columns) == {"latest", "mom_pct", "yoy_pct"}
    assert "General" in table.index


def test_cpi_change_table_columns_and_quarter_step(snapshot_df):
    general = cpi_series(snapshot_df, ["General"])["General"]
    ct = cpi_change_table(general)
    assert list(ct.columns) == ["cpi", "mom_pct", "yoy_pct", "ma_3m", "ma_6m", "ma_quarter"]
    assert ct.index.is_monotonic_increasing
    assert pd.isna(ct["mom_pct"].iloc[0])  # no prior month to compare the first row against
    # quarter average is constant within any single calendar quarter
    q = ct["ma_quarter"].dropna()
    grouped = q.groupby(q.index.to_period("Q")).nunique()
    assert (grouped <= 1).all()


def test_crop_helpers(snapshot_df):
    crops = crop_variants(snapshot_df)
    assert "Wheat" in crops
    sub = crop_slice(snapshot_df, "Wheat", "crop_production")
    assert (sub["commodity"] == "Wheat").all()
    assert sub["value"].is_monotonic_decreasing


@pytest.fixture(scope="module")
def group_long(snapshot_df):
    return group_change_table(snapshot_df, GROUPS_12)


def test_group_change_table_covers_all_12_real_groups(group_long):
    assert set(group_long["group"]) == set(GROUPS_12)
    assert "General" not in set(group_long["group"])  # General is the aggregate, not a "group"


def test_with_relative_magnitude_ranks_within_each_date(group_long):
    ranked = with_relative_magnitude(group_long.dropna(subset=["mom_pct"]), group_col="date")
    assert {"rank", "relative_magnitude"} <= set(ranked.columns)
    one_month = ranked[ranked["date"] == ranked["date"].iloc[-1]]
    assert sorted(one_month["rank"].dropna()) == list(range(1, len(one_month) + 1))
    assert set(one_month["relative_magnitude"]) <= {"High", "Medium", "Low"}


def test_selected_period_group_table_is_ranked_by_abs_mom(group_long):
    date = group_long["date"].max()
    period = selected_period_group_table(group_long, date)
    assert len(period) == len(GROUPS_12)
    assert period["rank"].tolist() == sorted(period["rank"].tolist())
    abs_vals = period["mom_pct"].abs().tolist()
    assert abs_vals == sorted(abs_vals, reverse=True)


def test_yearly_group_change_table_is_ranked_per_year(group_long):
    yearly = yearly_group_change_table(group_long)
    assert {"year", "group", "mom_pct", "yoy_pct", "relative_magnitude"} <= set(yearly.columns)
    one_year = yearly[yearly["year"] == yearly["year"].max()]
    assert set(one_year["relative_magnitude"]) <= {"High", "Medium", "Low"}
