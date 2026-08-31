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
