"""Group 06 (Health / "Medical Group") data for the Medical Group dashboard.

Pure data assembly from IMIS - no Streamlit import (the page wraps this
with ``st.cache_data``). Everything here is filtered to COICOP group 06 and
derived only from the supplied CPI data; nothing is fabricated.

COICOP sub-classes -> the dashboard's five groups:
    06.1.1  Pharmaceutical products      -> Medicines
    06.1.3  Therapeutic appliances/equip -> Medical Equipment
    06.2.1  Medical services             -> Services
    06.2.2  Dental services              -> Services
    06.2.3  Paramedical / lab services   -> Diagnostics
    06.3.0  Hospital services            -> Procedures
"""

from __future__ import annotations

import glob
import io
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pricelab.config import interim_dir
from pricelab.dashboard.data import ImisDataError
from pricelab.integration.sql_export import REQUIRED_DATABASE, _engine, connection_config

GROUP_CODE = "06"
GROUP_NAME = "Health"

# sub-class prefix -> (dashboard group label, sort order)
SUBGROUPS: dict[str, str] = {
    "06.1.1": "Medicines",
    "06.2.1": "Services",
    "06.2.2": "Services",
    "06.3.0": "Procedures",
    "06.2.3": "Diagnostics",
    "06.1.3": "Medical Equipment",
}
GROUP_ORDER = ["Medicines", "Services", "Diagnostics", "Procedures", "Medical Equipment"]

_CACHE = "medical_group_06.parquet"
_CACHE_TTL_S = 6 * 3600


def _subgroup(code: str) -> str:
    return SUBGROUPS.get(code[:6], "Other")


# --------------------------------------------------------------------------- #
# IMIS readers
# --------------------------------------------------------------------------- #

def _sqlcmd() -> str | None:
    for cand in (
        shutil.which("sqlcmd"),
        *glob.glob(r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\*\Tools\Binn\sqlcmd.EXE"),
        *glob.glob(r"C:\Program Files\Microsoft SQL Server\*\Tools\Binn\SQLCMD.EXE"),
    ):
        if cand and Path(cand).is_file():
            return cand
    return None


def _cpi_group06_city_prices() -> pd.DataFrame:
    """Group-06 city-level mean prices via ``sqlcmd`` -> CSV.

    A pyodbc fetch of the 266k-row dbo.CPI intermittently crashes the
    interpreter on this box ("PyEval_SaveThread ... GIL"); sqlcmd is a
    native tool and does the whole group-06 aggregation server-side in ~1s.
    Columns: year, month, coicop, citycode, price.
    """
    exe = _sqlcmd()
    if not exe:
        raise ImisDataError("sqlcmd not found - cannot read dbo.CPI safely on this machine")
    cfg = connection_config()
    server = cfg.get("server") or "localhost"
    if cfg.get("port"):
        server = f"{server},{cfg['port']}"
    auth = ["-E"] if cfg.get("trusted_connection", True) else [
        "-U", cfg.get("username", ""), "-P", cfg.get("password", "")
    ]
    query = (
        "SET NOCOUNT ON;"
        "SELECT CONCAT(TRY_CONVERT(int,[year]),'|',TRY_CONVERT(int,[month]),'|',"
        "REPLACE(RTRIM([coicop]),'-','.'),'|',TRY_CONVERT(int,[citycode]),'|',"
        "AVG(CASE WHEN [price]>0 THEN [price] END)) "
        "FROM dbo.CPI "
        "WHERE LEFT(REPLACE(RTRIM([coicop]),'-','.'),3)='06.' "
        "GROUP BY TRY_CONVERT(int,[year]),TRY_CONVERT(int,[month]),"
        "REPLACE(RTRIM([coicop]),'-','.'),TRY_CONVERT(int,[citycode])"
    )
    with tempfile.NamedTemporaryFile("r", suffix=".csv", delete=False, encoding="utf-8") as fh:
        out_path = fh.name
    try:
        proc = subprocess.run(
            [exe, "-S", server, *auth, "-d", REQUIRED_DATABASE, "-b", "-h", "-1",
             "-W", "-s", "|", "-Q", query, "-o", out_path],
            capture_output=True, text=True, timeout=280,
        )
        text_out = Path(out_path).read_text(encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise ImisDataError(f"sqlcmd failed: {proc.stderr.strip() or text_out[:200]}")
        df = pd.read_csv(
            io.StringIO(text_out), sep="|", header=None, engine="python",
            names=["year", "month", "coicop", "citycode", "price"],
            on_bad_lines="skip",
        )
    finally:
        Path(out_path).unlink(missing_ok=True)
    df = df.dropna(subset=["year", "month", "coicop", "citycode", "price"])
    if df.empty:
        raise ImisDataError("sqlcmd returned no group-06 price rows")
    return df


def _query() -> dict[str, pd.DataFrame]:
    try:
        from sqlalchemy import text
    except ImportError as exc:  # pragma: no cover
        raise ImisDataError("SQL Server dependencies are not installed") from exc

    engine = _engine()
    try:
        with engine.connect() as cn:
            actual = cn.execute(text("SELECT DB_NAME()")).scalar_one()
            if str(actual).casefold() != REQUIRED_DATABASE.casefold():
                raise ImisDataError(
                    f"Refusing data access: expected {REQUIRED_DATABASE!r}, connected to {actual!r}"
                )
            names = pd.read_sql(
                text(
                    "SELECT RTRIM([ItemCode]) AS code, "
                    "LTRIM(RTRIM([DescriptionLong])) AS long_name, "
                    "LTRIM(RTRIM([Description])) AS short_name, "
                    "LTRIM(RTRIM([Unit])) AS unit FROM [dbo].[CPI_ITEMS]"
                ),
                cn,
            )
            weights = pd.read_sql(
                text(
                    "SELECT RTRIM([ItemCode]) AS code, TRY_CONVERT(int,[Month]) AS m, "
                    "[Weight0] AS w FROM [dbo].[CPI_WT]"
                ),
                cn,
            )
            inflation = pd.read_sql(
                text(
                    "SELECT [Year],[Month],[General],"
                    + ",".join(f"[G{i:02d}]" for i in range(1, 13))
                    + " FROM [dbo].[Inflation] ORDER BY [Year],[Month]"
                ),
                cn,
            )
            cities = pd.read_sql(
                text(
                    "SELECT TRY_CONVERT(int,c.[CityCode]) AS citycode, "
                    "LTRIM(RTRIM(c.[CityName])) AS city FROM [dbo].[CPI_CITY] c"
                ),
                cn,
            )
    finally:
        engine.dispose()
    return {
        "prices": _cpi_group06_city_prices(), "names": names, "weights": weights,
        "inflation": inflation, "cities": cities,
    }


def _clean_name(s: pd.Series) -> pd.Series:
    return (
        s.str.replace(r"[^\x20-\x7E]", " ", regex=True)  # drop mojibake / non-ASCII
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .str.title()
    )


def _build(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One tidy item-month price panel for group 06 + attached metadata."""
    p = raw["prices"].copy()
    p["year"] = pd.to_numeric(p["year"], errors="coerce")
    p["month"] = pd.to_numeric(p["month"], errors="coerce")
    p["price"] = pd.to_numeric(p["price"], errors="coerce")
    p["citycode"] = pd.to_numeric(p["citycode"], errors="coerce")
    p["code"] = p["coicop"].str.strip().str.replace("-", ".", regex=False)
    p = p[
        (p["price"] > 0) & p["year"].notna() & p["month"].notna()
        & p["citycode"].notna() & p["code"].str.startswith(GROUP_CODE + ".")
    ]
    if p.empty:
        raise ImisDataError("IMIS dbo.CPI has no usable group-06 prices")

    p["date"] = pd.to_datetime(
        dict(year=p["year"].astype(int), month=p["month"].astype(int), day=1)
    )
    city = p.groupby(["date", "code", "citycode"], as_index=False)["price"].mean()
    panel = city.groupby(["date", "code"], as_index=False).agg(
        price=("price", "mean"), cities=("price", "size")
    )

    n = raw["names"]
    n["name"] = _clean_name(n["long_name"].where(n["long_name"].astype(bool), n["short_name"]))
    n["unit"] = n["unit"].where(n["unit"].astype(bool))
    panel = panel.merge(n[["code", "name", "unit"]], on="code", how="left")
    panel["name"] = panel["name"].fillna(panel["code"])
    panel["subgroup"] = panel["code"].map(_subgroup)
    panel["city_of_price"] = None  # placeholder, real per-city handled elsewhere
    return panel.sort_values(["date", "code"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Public: everything the page needs, in one call
# --------------------------------------------------------------------------- #

def load_medical_group(*, use_cache: bool = True) -> dict:
    cache = interim_dir() / _CACHE
    raw = None
    if use_cache and cache.is_file() and (time.time() - cache.stat().st_mtime) < _CACHE_TTL_S:
        try:
            return _assemble(pd.read_parquet(cache), _cached_side_tables(cache))
        except Exception:  # noqa: BLE001
            pass
    try:
        raw = _query()
        panel = _build(raw)
        # keep only the group-06 price rows for the cache (small)
        raw["prices"] = raw["prices"].assign(
            _c=raw["prices"]["coicop"].str.strip().str.replace("-", ".", regex=False)
        )
        raw["prices"] = raw["prices"][raw["prices"]["_c"].str.startswith("06.")].drop(columns="_c")
    except Exception:
        if use_cache and cache.is_file():
            return _assemble(pd.read_parquet(cache), _cached_side_tables(cache))
        raise
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(cache, index=False)
        _write_side_tables(cache, raw)
    except Exception:  # noqa: BLE001
        pass
    return _assemble(panel, raw)


def _side_path(cache: Path, name: str) -> Path:
    return cache.with_name(cache.stem + f"__{name}.parquet")


def _write_side_tables(cache: Path, raw: dict) -> None:
    for name in ("inflation", "weights", "cities", "prices"):
        raw[name].to_parquet(_side_path(cache, name), index=False)


def _cached_side_tables(cache: Path) -> dict:
    def _read(name: str) -> pd.DataFrame:
        p = _side_path(cache, name)
        return pd.read_parquet(p) if p.is_file() else pd.DataFrame()

    return {
        "inflation": _read("inflation"), "weights": _read("weights"),
        "cities": _read("cities"), "prices": _read("prices"), "names": pd.DataFrame(),
    }


def _assemble(panel: pd.DataFrame, raw: dict) -> dict:
    matrix = panel.pivot_table(index="date", columns="code", values="price").sort_index()
    latest = matrix.iloc[-1]
    prev = matrix.iloc[-2] if len(matrix) > 1 else latest
    yr = matrix.iloc[-13] if len(matrix) >= 13 else matrix.iloc[0]
    revisions = (matrix.diff().abs() > 1e-6).sum().astype(int)

    meta = panel.drop_duplicates("code").set_index("code")
    wl = (
        raw["weights"].sort_values("m").groupby("code")["w"].last()
        if not raw["weights"].empty else pd.Series(dtype=float)
    )
    cities_now = panel.loc[panel["date"] == matrix.index[-1]].set_index("code")["cities"]

    items = pd.DataFrame({
        "code": matrix.columns,
        "name": [meta.loc[c, "name"] for c in matrix.columns],
        "unit": [meta.loc[c, "unit"] for c in matrix.columns],
        "subgroup": [meta.loc[c, "subgroup"] for c in matrix.columns],
        "price_now": latest.round(2).values,
        "mom_pct": ((latest / prev - 1) * 100).round(1).values,
        "yoy_pct": ((latest / yr - 1) * 100).round(1).values,
        "weight": [round(float(wl.get(c, np.nan)), 3) for c in matrix.columns],
        "revisions": [int(revisions.get(c, 0)) for c in matrix.columns],
        "cities": [int(cities_now.get(c, 0)) for c in matrix.columns],
    })

    # --- group-level (from dbo.Inflation G06) ---
    inf = raw["inflation"].copy()
    inf["date"] = pd.to_datetime(dict(year=inf["Year"], month=inf["Month"], day=1))
    inf = inf.sort_values("date").set_index("date")
    g06 = inf["G06"].astype(float)
    grp = {
        "name": "Medical Group",
        "total_items": int(len(items)),
        "cities_covered": int(cities_now.max()) if len(cities_now) else int(panel["cities"].max()),
        "basket_weight": round(float(items["weight"].sum(skipna=True)), 2),
        "index_now": round(float(g06.iloc[-1]), 1),
        "mom_pct": round(float((g06.iloc[-1] / g06.iloc[-2] - 1) * 100), 1),
        "yoy_pct": round(float((g06.iloc[-1] / g06.iloc[-13] - 1) * 100), 1),
        "index_series": [
            {"date": d.strftime("%Y-%m"), "value": round(float(v), 1)}
            for d, v in g06.items()
        ],
        "as_of": g06.index[-1].strftime("%b %Y"),
    }

    # --- revisions timeline: cumulative items with >=1 revision, by month ---
    diffed = (matrix.diff().abs() > 1e-6)
    first_rev = diffed.apply(lambda col: col[col].index.min() if col.any() else pd.NaT)
    timeline = [
        {"date": d.strftime("%Y-%m"),
         "count": int((first_rev <= d).sum())}
        for d in matrix.index
    ]

    # --- most revised ---
    most_revised = (
        items.sort_values(["revisions", "weight"], ascending=[False, False])
        .head(6)[["name", "subgroup", "revisions"]]
        .to_dict("records")
    )

    # --- city price pressure: group-06 mean price index by city vs national ---
    city_pressure = _city_pressure(raw)

    # --- "moves together" (plain, no r shown) ---
    moves_together = _moves_together(matrix, items, inf)

    return {
        "group": grp,
        "items": items,
        "subgroups": {g: items[items["subgroup"] == g].to_dict("records") for g in GROUP_ORDER},
        "revisions_timeline": timeline,
        "most_revised": most_revised,
        "city_pressure": city_pressure,
        "moves_together": moves_together,
        "coverage": {
            "months": int(len(matrix)),
            "date_min": matrix.index.min().strftime("%b %Y"),
            "date_max": matrix.index.max().strftime("%b %Y"),
        },
    }


def _city_pressure(raw: dict) -> list[dict]:
    """Each city's latest group-06 average price relative to the all-city
    average (index, 100 = national). Only computable when the raw price rows
    are available (fresh load); returns [] from a cache-only path."""
    p = raw.get("prices")
    if p is None or p.empty:
        return []
    p = p.copy()
    p["price"] = pd.to_numeric(p["price"], errors="coerce")
    p["citycode"] = pd.to_numeric(p["citycode"], errors="coerce")
    p["year"] = pd.to_numeric(p["year"], errors="coerce")
    p["month"] = pd.to_numeric(p["month"], errors="coerce")
    p["code"] = p["coicop"].str.strip().str.replace("-", ".", regex=False)
    p = p[(p["price"] > 0) & p["code"].str.startswith("06.") & p["citycode"].notna()]
    last = p.sort_values(["year", "month"]).groupby("code").tail(1)[["year", "month"]].iloc[0]
    p = p[(p["year"] == last["year"]) & (p["month"] == last["month"])]
    # each city vs each item -> ratio to item's all-city mean -> city mean ratio
    item_mean = p.groupby("code")["price"].transform("mean")
    p = p.assign(rel=p["price"] / item_mean)
    by_city = p.groupby("citycode")["rel"].mean().mul(100)
    cmap = raw["cities"].set_index("citycode")["city"] if not raw["cities"].empty else pd.Series(dtype=str)
    out = [
        {"city": str(cmap.get(int(cc), int(cc))), "index": round(float(v), 0),
         "diff_pct": round(float(v - 100), 0)}
        for cc, v in by_city.items()
    ]
    return sorted(out, key=lambda r: r["diff_pct"], reverse=True)


def _moves_together(matrix: pd.DataFrame, items: pd.DataFrame, inf: pd.DataFrame) -> dict:
    name = items.set_index("code")["name"]
    sub = items.set_index("code")["subgroup"]
    ch = np.log(matrix.where(matrix > 0)).diff().dropna(how="all")
    ch = ch.loc[:, ch.std() > 1e-9]
    pairs = []
    cols = list(ch.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            x, y = cols[i], cols[j]
            # only surface pairs within the same dashboard sub-group - a
            # cross-group "pair" from 18 noisy months isn't a real relationship
            if sub.get(x) != sub.get(y):
                continue
            a, b = ch[x].dropna(), ch[y].dropna()
            common = a.index.intersection(b.index)
            if len(common) < 8:
                continue
            r = float(np.corrcoef(a[common], b[common])[0, 1])
            if np.isfinite(r) and r >= 0.55:
                pairs.append((x, y, r))
    pairs.sort(key=lambda t: t[2], reverse=True)
    top_pairs = [
        {"a": str(name.get(x, x)), "b": str(name.get(y, y)), "direction": "together"}
        for x, y, _ in pairs[:3]
    ]

    # which other CPI groups the Health index tracks most closely
    gi = inf.copy()
    gcols = [f"G{i:02d}" for i in range(1, 13)]
    gch = np.log(gi[gcols].astype(float).where(lambda d: d > 0)).diff().dropna()
    base = gch["G06"]
    grp_links = (
        gch.drop(columns=["G06"]).corrwith(base).sort_values(ascending=False).head(3)
    )
    labels = {
        "G01": "Food", "G02": "Alcohol & Tobacco", "G03": "Clothing", "G04": "Housing & Utilities",
        "G05": "Household", "G07": "Transport", "G08": "Communication", "G09": "Recreation",
        "G10": "Education", "G11": "Restaurants & Hotels", "G12": "Misc goods & services",
    }
    group_links = [{"group": labels.get(k, k)} for k in grp_links.index]
    return {"item_pairs": top_pairs, "group_links": group_links}
