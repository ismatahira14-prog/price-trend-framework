import pandas as pd
import pytest

from pricelab.dashboard.data import (
    SnapshotMissing,
    cpi_change_table,
    cpi_series,
    crop_slice,
    crop_variants,
    latest_change_table,
    load_master_long,
)
from pricelab.integration.duckdb_export import snapshot_path


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
