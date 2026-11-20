"""Read-only data access for the dashboard, backed by the DuckDB snapshot.

Every function opens a short-lived read-only connection and returns a plain
pandas DataFrame. No streamlit import here on purpose - the dashboard app
wraps these with `st.cache_data`; tests can call them directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from pricelab.integration.duckdb_export import snapshot_path
from pricelab.integration.harmonize import canon_commodity
from pricelab.integration.sql_export import REQUIRED_DATABASE, _engine


class SnapshotMissing(FileNotFoundError):
    pass


class ImisDataError(RuntimeError):
    """The IMIS dashboard source is unavailable or has an unexpected schema."""


_INFLATION_COLUMNS = ["General", *(f"G{i:02d}" for i in range(1, 13))]


def load_imis_inflation() -> pd.DataFrame:
    """Load Home-page CPI data directly and read-only from IMIS.

    The database name is checked again on the live connection. This is
    intentionally fail-closed: no fallback to Excel, DuckDB, or another SQL
    Server database is allowed for the default page.
    """
    try:
        from sqlalchemy import text
    except ImportError as exc:  # pragma: no cover - dependency error at deployment
        raise ImisDataError("SQL Server dependencies are not installed") from exc

    engine = _engine()
    try:
        with engine.connect() as connection:
            actual_database = connection.execute(text("SELECT DB_NAME()" )).scalar_one()
            if str(actual_database).casefold() != REQUIRED_DATABASE.casefold():
                raise ImisDataError(
                    f"Refusing data access: expected {REQUIRED_DATABASE!r}, "
                    f"connected to {actual_database!r}"
                )
            groups = pd.read_sql(
                text("SELECT [Code], [Description] FROM [dbo].[PriceGroup]"), connection
            )
            inflation = pd.read_sql(
                text(
                    "SELECT [Year], [Month], [General], [G01], [G02], [G03], "
                    "[G04], [G05], [G06], [G07], [G08], [G09], [G10], [G11], [G12] "
                    "FROM [dbo].[Inflation] ORDER BY [Year], [Month]"
                ),
                connection,
            )
    finally:
        engine.dispose()

    code_to_group: dict[str, str] = {"General": "General"}
    for row in groups.itertuples(index=False):
        if pd.isna(row.Code) or pd.isna(row.Description):
            continue
        code = int(float(row.Code))
        column = "General" if code == 0 else f"G{code:02d}"
        code_to_group[column] = canon_commodity(str(row.Description).strip())

    missing_groups = sorted(set(_INFLATION_COLUMNS) - set(code_to_group))
    missing_columns = sorted(set(["Year", "Month", *_INFLATION_COLUMNS]) - set(inflation.columns))
    if missing_groups or missing_columns:
        raise ImisDataError(
            f"Unexpected IMIS schema (missing group mappings={missing_groups}, "
            f"missing Inflation columns={missing_columns})"
        )

    long = inflation.melt(
        id_vars=["Year", "Month"],
        value_vars=_INFLATION_COLUMNS,
        var_name="group_code",
        value_name="value",
    ).dropna(subset=["value"])
    dates = pd.to_datetime(
        {"year": long["Year"], "month": long["Month"], "day": 1}, errors="coerce"
    )
    if dates.isna().any():
        raise ImisDataError("IMIS Inflation contains an invalid Year/Month value")

    return pd.DataFrame(
        {
            "date": dates,
            "freq": "M",
            "region": "Pakistan",
            "region_level": "national",
            "commodity": long["group_code"].map(code_to_group),
            "variable": "cpi_index",
            "value": pd.to_numeric(long["value"], errors="coerce"),
            "unit": "2015-16 = 100",
            "source": "IMIS.dbo.Inflation",
            "is_imputed": False,
        }
    ).sort_values(["date", "commodity"]).reset_index(drop=True)


_WEIGHT_COLS = [f"Weight{i}" for i in range(6)]


def load_imis_item_drilldown(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    """Load item weights and city-price summaries directly from IMIS.

    Weight0 is the overall basket and Weight1..Weight5 are the five
    quantiles. CPI prices are first deduplicated to one arithmetic mean per
    period/item/city, then summarized to an item-level geometric mean across
    cities. Only positive prices participate in the GM.

    ``dbo.CPI`` is scanned raw and aggregated in pandas: the equivalent
    server-side query (``TRY_CONVERT``/``REPLACE`` in a CTE + ``STRING_AGG``
    over 266k char rows) produces a catastrophic plan - minutes, and slow
    enough to crash pyodbc under load. The plain scan is a few seconds.
    """
    try:
        from sqlalchemy import text
    except ImportError as exc:  # pragma: no cover
        raise ImisDataError("SQL Server dependencies are not installed") from exc

    engine = _engine()
    try:
        with engine.connect() as connection:
            actual_database = connection.execute(text("SELECT DB_NAME()")).scalar_one()
            if str(actual_database).casefold() != REQUIRED_DATABASE.casefold():
                raise ImisDataError(
                    f"Refusing data access: expected {REQUIRED_DATABASE!r}, "
                    f"connected to {actual_database!r}"
                )
            prices = pd.read_sql(
                text("SELECT [year],[month],[coicop],[citycode],[price] FROM [dbo].[CPI]"),
                connection,
            )
            mapped = pd.read_sql(
                text("SELECT DISTINCT [cpi] AS city FROM [dbo].[PVD] WHERE [cpi] <> 0"),
                connection,
            )
            cpi_cities = pd.read_sql(
                text("SELECT TRY_CONVERT(int,[CityCode]) AS city FROM [dbo].[CPI_CITY]"),
                connection,
            )
            weights = pd.read_sql(
                text(
                    "SELECT RTRIM([ItemCode]) AS ItemCode, TRY_CONVERT(int,[Month]) AS m, "
                    + ", ".join(f"[{c}]" for c in _WEIGHT_COLS)
                    + " FROM [dbo].[CPI_WT]"
                ),
                connection,
            )
            items = pd.read_sql(
                text(
                    "SELECT RTRIM([ItemCode]) AS ItemCode, "
                    "LTRIM(RTRIM([DescriptionLong])) AS DescriptionLong, "
                    "LTRIM(RTRIM([Description])) AS [Description], "
                    "LTRIM(RTRIM([Unit])) AS Unit FROM [dbo].[CPI_ITEMS]"
                ),
                connection,
            )
    finally:
        engine.dispose()

    prices["year"] = pd.to_numeric(prices["year"], errors="coerce")
    prices["month"] = pd.to_numeric(prices["month"], errors="coerce")
    prices["city"] = pd.to_numeric(prices["citycode"], errors="coerce")
    prices["price"] = pd.to_numeric(prices["price"], errors="coerce")
    prices["ItemCode"] = prices["coicop"].str.strip().str.replace("-", ".", regex=False)
    prices = prices.dropna(subset=["year", "month", "city", "price"])
    prices = prices[prices["price"] > 0]
    prices[["year", "month", "city"]] = prices[["year", "month", "city"]].astype(int)

    prices["date"] = pd.to_datetime(
        dict(year=prices["year"], month=prices["month"], day=1), errors="coerce"
    )
    lo, hi = pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize()
    prices = prices[(prices["date"] >= lo) & (prices["date"] <= hi)]

    keep_cities = set(mapped["city"].dropna().astype(int)) & set(cpi_cities["city"].dropna().astype(int))
    prices = prices[prices["city"].isin(keep_cities)]
    if prices.empty:
        return pd.DataFrame(
            columns=["year", "month", "GroupCode", "ItemCode", "ItemDescription", "Unit",
                     *_WEIGHT_COLS, "GMPrice", "CityCount", "MinCityPrice", "MaxCityPrice",
                     "CityPricesJson"]
        )

    city_px = (
        prices.groupby(["year", "month", "ItemCode", "city"], as_index=False)["price"]
        .mean()
        .rename(columns={"price": "CityPrice"})
    )
    city_px = city_px[city_px["CityPrice"] > 0].sort_values(
        ["year", "month", "ItemCode", "city"]
    )

    keys = ["year", "month", "ItemCode"]
    grp = city_px.assign(logp=np.log(city_px["CityPrice"])).groupby(keys, sort=False)
    item_px = grp.agg(
        GMPrice=("logp", lambda s: float(np.exp(s.mean()))),
        CityCount=("CityPrice", "size"),
        MinCityPrice=("CityPrice", "min"),
        MaxCityPrice=("CityPrice", "max"),
    ).reset_index()
    pairs = (
        city_px.assign(
            _pair=[
                [int(c), round(float(p), 4)]
                for c, p in zip(city_px["city"], city_px["CityPrice"])
            ]
        )
        .groupby(keys, sort=False)["_pair"]
        .agg(list)
        .apply(json.dumps)
        .rename("CityPricesJson")
        .reset_index()
    )
    item_px = item_px.merge(pairs, on=keys)

    w = weights.copy()
    w["ItemCode"] = w["ItemCode"].str.strip()
    merged = item_px.merge(w, left_on=["ItemCode", "month"], right_on=["ItemCode", "m"], how="inner")

    it = items.copy()
    it["ItemCode"] = it["ItemCode"].str.strip()
    it["ItemDescription"] = (
        it["DescriptionLong"].where(it["DescriptionLong"].astype(bool))
        .fillna(it["Description"].where(it["Description"].astype(bool)))
        .fillna(it["ItemCode"])
    )
    it["Unit"] = it["Unit"].where(it["Unit"].astype(bool))
    merged = merged.merge(
        it[["ItemCode", "ItemDescription", "Unit"]], on="ItemCode", how="inner"
    )

    merged["GroupCode"] = merged["ItemCode"].str.slice(0, 2)
    out = merged[
        ["year", "month", "GroupCode", "ItemCode", "ItemDescription", "Unit",
         *_WEIGHT_COLS, "GMPrice", "CityCount", "MinCityPrice", "MaxCityPrice", "CityPricesJson"]
    ]
    return (
        out.sort_values(
            ["year", "month", "GroupCode", "Weight0", "ItemCode"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)
    )


def load_imis_cpi_district_map() -> pd.DataFrame:
    """Return the authoritative IMIS CPI-city to PVD-district mapping."""
    try:
        from sqlalchemy import text
    except ImportError as exc:  # pragma: no cover
        raise ImisDataError("SQL Server dependencies are not installed") from exc

    engine = _engine()
    query = text(
        """
        SELECT RTRIM(p.[pvid]) AS ProvinceCode,
               LTRIM(RTRIM(p.[pv])) AS ProvinceName,
               RTRIM(p.[dvid]) AS DivisionCode,
               LTRIM(RTRIM(p.[dv])) AS DivisionName,
               RTRIM(p.[dsid]) AS DistrictCode,
               LTRIM(RTRIM(p.[ds])) AS DistrictName,
               p.[cpi] AS CityCode,
               LTRIM(RTRIM(c.[CityName])) AS CityName
        FROM [dbo].[PVD] p
        INNER JOIN [dbo].[CPI_CITY] c
            ON TRY_CONVERT(int, c.[CityCode]) = p.[cpi]
        WHERE p.[cpi] <> 0
        ORDER BY p.[cpi], p.[dsid]
        """
    )
    try:
        with engine.connect() as connection:
            actual_database = connection.execute(text("SELECT DB_NAME()")).scalar_one()
            if str(actual_database).casefold() != REQUIRED_DATABASE.casefold():
                raise ImisDataError(
                    f"Refusing data access: expected {REQUIRED_DATABASE!r}, "
                    f"connected to {actual_database!r}"
                )
            result = pd.read_sql(query, connection)
    finally:
        engine.dispose()
    return result


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
