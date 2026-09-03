"""Read-only data access for the dashboard, backed by the DuckDB snapshot.

Every function opens a short-lived read-only connection and returns a plain
pandas DataFrame. No streamlit import here on purpose - the dashboard app
wraps these with `st.cache_data`; tests can call them directly.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from pricelab.integration.duckdb_export import snapshot_path


class SnapshotMissing(FileNotFoundError):
    pass


def _connect(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    p = Path(path) if path else snapshot_path()
    if not p.is_file():
        raise SnapshotMissing(
            f"No data snapshot at {p}. Run `python -m pricelab.ingest --all` first."
        )
    return duckdb.connect(str(p), read_only=True)


def load_master_long(path: str | Path | None = None) -> pd.DataFrame:
    con = _connect(path)
    try:
        return con.execute("SELECT * FROM master_long").fetchdf()
    finally:
        con.close()


def load_dimension(name: str, path: str | Path | None = None) -> pd.DataFrame:
    con = _connect(path)
    try:
        return con.execute(f"SELECT * FROM dim_{name}").fetchdf()
    finally:
        con.close()


def snapshot_info(path: str | Path | None = None) -> dict:
    """Small summary used by the Overview page and health checks."""
    df = load_master_long(path)
    return {
        "rows": len(df),
        "sources": sorted(df["source"].unique()),
        "variables": sorted(df["variable"].unique()),
        "date_min": df["date"].min(),
        "date_max": df["date"].max(),
        "regions": df["region"].nunique(),
    }


def cpi_series(df: pd.DataFrame, groups: list[str] | None = None) -> pd.DataFrame:
    """Wide monthly CPI table: index=date, one column per group."""
    cpi = df[df["variable"] == "cpi_index"]
    if groups:
        cpi = cpi[cpi["commodity"].isin(groups)]
    return cpi.pivot_table(index="date", columns="commodity", values="value").sort_index()


def latest_change_table(wide: pd.DataFrame) -> pd.DataFrame:
    """Latest value, MoM %, YoY % for each column of a wide monthly series."""
    if wide.empty:
        return pd.DataFrame(columns=["latest", "mom_pct", "yoy_pct"])
    latest = wide.iloc[-1]
    mom = wide.pct_change().iloc[-1] * 100
    yoy = wide.pct_change(12).iloc[-1] * 100 if len(wide) > 12 else pd.Series(dtype=float)
    out = pd.DataFrame({"latest": latest, "mom_pct": mom, "yoy_pct": yoy})
    return out.round(2)


def cpi_change_table(series: pd.Series) -> pd.DataFrame:
    """Month-indexed CPI series -> cpi, MoM %, YoY %, and 3 moving averages.

    - ``ma_3m`` / ``ma_6m``: rolling (trailing) monthly averages - smooth
      trend lines.
    - ``ma_quarter``: the *calendar*-quarter average (Jan-Mar, Apr-Jun, ...),
      held flat across each quarter - a deliberately different, "stepped"
      view from the two rolling averages, not a duplicate of ``ma_3m``.
    """
    s = series.dropna().sort_index()
    out = pd.DataFrame({"cpi": s})
    out["mom_pct"] = s.pct_change() * 100
    out["yoy_pct"] = s.pct_change(12) * 100
    out["ma_3m"] = s.rolling(3).mean()
    out["ma_6m"] = s.rolling(6).mean()
    quarterly = s.resample("QE").mean()
    out["ma_quarter"] = quarterly.reindex(out.index, method="ffill")
    return out


def group_change_table(df: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Real, per-CPI-group MoM/YoY change - long format: date, group, mom_pct,
    yoy_pct, mom_abs, yoy_abs.

    This is the actual PBS CPI series for each of the 12 COICOP groups (no
    mock/placeholder values) - the basis for the "What caused the inflation
    spike?" breakdown, its Percentage/Absolute Value toggle (mom_abs/yoy_abs
    are the plain index-point change - ``wide.diff()``/``wide.diff(12)`` -
    the natural "absolute" counterpart to the pct-change columns, not the
    raw index level itself: that would give both the MoM and YoY chart the
    exact same single-snapshot bars in absolute mode, losing the MoM-vs-YoY
    distinction the two charts exist to compare), and the two archive
    tables below it.
    """
    wide = cpi_series(df, groups)
    mom_long = (wide.pct_change() * 100).stack().reset_index()
    mom_long.columns = ["date", "group", "mom_pct"]
    yoy_long = (wide.pct_change(12) * 100).stack().reset_index()
    yoy_long.columns = ["date", "group", "yoy_pct"]
    mom_abs_long = wide.diff().stack().reset_index()
    mom_abs_long.columns = ["date", "group", "mom_abs"]
    yoy_abs_long = wide.diff(12).stack().reset_index()
    yoy_abs_long.columns = ["date", "group", "yoy_abs"]
    out = (
        mom_long.merge(yoy_long, on=["date", "group"], how="outer")
        .merge(mom_abs_long, on=["date", "group"], how="outer")
        .merge(yoy_abs_long, on=["date", "group"], how="outer")
    )
    return out.sort_values(["date", "group"]).reset_index(drop=True)


def with_relative_magnitude(
    long_df: pd.DataFrame, group_col: str, magnitude_col: str = "mom_pct"
) -> pd.DataFrame:
    """Rank rows within each `group_col` value by |magnitude_col| (1 = biggest
    mover that period) and label the tier via
    ``pricelab.dashboard.factors.classify_relative_magnitude``.

    This is a REAL, computed ranking - not a fabricated basket-weight
    contribution (which this project's data does not include).
    """
    from pricelab.dashboard.factors import classify_relative_magnitude  # avoid a top-level cycle

    out = long_df.copy()
    abs_val = out[magnitude_col].abs()
    out["rank"] = abs_val.groupby(out[group_col]).rank(ascending=False, method="first")
    counts = abs_val.groupby(out[group_col]).transform("count")
    out["relative_magnitude"] = [
        classify_relative_magnitude(int(r), int(n)) if pd.notna(r) else "n/a"
        for r, n in zip(out["rank"], counts)
    ]
    return out


def selected_period_group_table(long_df: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """The 12-group breakdown for one month, ranked by |MoM change| (largest first)."""
    sub = with_relative_magnitude(long_df, group_col="date").loc[lambda d: d["date"] == date]
    return sub.sort_values("rank").reset_index(drop=True)


def yearly_group_change_table(long_df: pd.DataFrame) -> pd.DataFrame:
    """Per-group calendar-year averages of the real monthly MoM %/YoY % series,
    ranked by |avg YoY change| within each year."""
    yearly = long_df.dropna(subset=["yoy_pct"]).copy()
    yearly["year"] = yearly["date"].dt.year
    agg = yearly.groupby(["year", "group"], as_index=False).agg(
        mom_pct=("mom_pct", "mean"), yoy_pct=("yoy_pct", "mean")
    )
    return with_relative_magnitude(agg, group_col="year", magnitude_col="yoy_pct")


def crop_variants(df: pd.DataFrame) -> list[str]:
    return sorted(df.loc[df["source"] == "crop_production", "commodity"].unique())


def crop_slice(df: pd.DataFrame, commodity: str, variable: str, date=None) -> pd.DataFrame:
    sub = df[
        (df["source"] == "crop_production")
        & (df["commodity"] == commodity)
        & (df["variable"] == variable)
    ]
    if date is not None:
        sub = sub[sub["date"] == date]
    return sub.sort_values("value", ascending=False)
