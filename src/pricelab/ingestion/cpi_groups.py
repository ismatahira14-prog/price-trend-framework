"""Loader: monthly CPI index by COICOP group (Inflation.xlsx / Sheet1).

Raw layout: columns ``Year``, ``Month`` (calendar 1-12), then one column per
CPI group (``General`` + 12 COICOP groups). One row per month, 2016-07 -> latest.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from pricelab.config import load_config
from pricelab.ingestion.base import register_loader, source_frame
from pricelab.integration.harmonize import canon_commodity
from pricelab.schema import coerce_tidy

_ID_COLS = ("Year", "Month")


@register_loader("cpi_groups")
def load_cpi_groups(cfg: dict[str, Any]) -> pd.DataFrame:
    raw = source_frame(cfg)
    raw.columns = [str(c).strip() for c in raw.columns]

    id_cols = [c for c in _ID_COLS if c in raw.columns]
    if len(id_cols) != 2:
        raise ValueError(
            f"cpi_groups: expected columns {_ID_COLS}, got {list(raw.columns)[:5]}..."
        )
    value_cols = [c for c in raw.columns if c not in id_cols]

    long = raw.melt(
        id_vars=id_cols,
        value_vars=value_cols,
        var_name="group",
        value_name="value",
    )
    long = long.dropna(subset=["value"])

    year = pd.to_numeric(long["Year"], errors="coerce").astype("Int64")
    month = pd.to_numeric(long["Month"], errors="coerce").astype("Int64")
    long = long.loc[year.notna() & month.notna()].copy()
    long["date"] = pd.to_datetime(
        {
            "year": year.loc[long.index].astype(int),
            "month": month.loc[long.index].astype(int),
            "day": 1,
        }
    )

    base_label = (load_config()["analysis"] or {}).get("cpi_base_label", "index")

    out = pd.DataFrame(
        {
            "date": long["date"].values,
            "freq": "M",
            "region": "Pakistan",
            "region_level": "national",
            "commodity": [canon_commodity(g) for g in long["group"]],
            "variable": "cpi_index",
            "value": pd.to_numeric(long["value"], errors="coerce").values,
            "unit": base_label,
            "source": cfg["_key"],
            "is_imputed": False,
        }
    )
    out = out.dropna(subset=["value"])
    return coerce_tidy(out)
