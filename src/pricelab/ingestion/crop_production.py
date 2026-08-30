"""Loader: district-level annual crop area / production / yield.

Raw workbook ``crops intern.xlsx`` with three sheets:
  * ``CropData`` - facts: id, District, Area, Production, Yield, fiscalyear,
                   CropId, dist_code, dist_desc
  * ``Crops``    - crop dimension: id, name, Type
  * ``ds``       - region hierarchy: pvid, dvid, dsid, ds, dv, pv

Emits three tidy variables per (district, crop, fiscal year):
``crop_area`` (000 hectares), ``crop_production`` (000 tonnes),
``crop_yield`` (tonnes/hectare). Yield is recomputed from the aggregated area &
production (``is_imputed = True``) whenever the raw ``Yield`` column is blank.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from pricelab.config import load_config, resolve_source_path
from pricelab.ingestion.base import read_excel, register_loader
from pricelab.integration.harmonize import canon_commodity, canon_region, region_level_for
from pricelab.schema import coerce_tidy

_FY_RE = re.compile(r"^\s*(\d{4})\s*[-/]\s*(\d{2,4})\s*$")

_GROUP = ["date", "freq", "region", "region_level", "commodity", "source"]


def _fiscal_year_end(fy: str, mmdd: str) -> pd.Timestamp | pd.NaT:
    m = _FY_RE.match(str(fy))
    if not m:
        return pd.NaT
    return pd.Timestamp(f"{int(m.group(1)) + 1}-{mmdd}")


@register_loader("crop_production")
def load_crop_production(cfg: dict[str, Any]) -> pd.DataFrame:
    path = resolve_source_path(cfg["path"])
    facts = read_excel(path, cfg.get("sheet", "CropData"))
    crops = read_excel(path, "Crops")
    facts.columns = [str(c).strip() for c in facts.columns]
    crops.columns = [str(c).strip() for c in crops.columns]

    crop_name = dict(zip(crops["id"], crops["name"].astype(str)))
    crop_raw = facts["CropId"].map(crop_name).fillna(facts["CropId"].astype(str))

    mmdd = (load_config()["analysis"] or {}).get("fiscal_year_end", "06-30")
    region_src = facts["dist_desc"] if "dist_desc" in facts.columns else facts["District"]

    rows = pd.DataFrame(
        {
            "date": facts["fiscalyear"].map(lambda v: _fiscal_year_end(v, mmdd)),
            "freq": "A",
            "region": region_src.map(canon_region),
            "region_level": region_src.map(region_level_for),
            "commodity": crop_raw.map(lambda v: canon_commodity(v, track=False)),
            "source": cfg["_key"],
            "area": pd.to_numeric(facts.get("Area"), errors="coerce"),
            "production": pd.to_numeric(facts.get("Production"), errors="coerce"),
            "raw_yield": pd.to_numeric(facts.get("Yield"), errors="coerce"),
        }
    )
    rows = rows.dropna(subset=["date"])
    rows = rows[(rows["region"] != "") & (rows["commodity"] != "")]

    agg = rows.groupby(_GROUP, as_index=False).agg(
        area=("area", "sum"),
        production=("production", "sum"),
        raw_yield=("raw_yield", "mean"),
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        computed_yield = agg["production"] / agg["area"].replace(0, np.nan)
    agg["yield_val"] = agg["raw_yield"].where(agg["raw_yield"].notna(), computed_yield)
    agg["yield_imputed"] = agg["raw_yield"].isna() & computed_yield.notna()

    never = pd.Series(False, index=agg.index)
    specs = [
        ("crop_area", "area", "000_hectares", never),
        ("crop_production", "production", "000_tonnes", never),
        ("crop_yield", "yield_val", "tonnes_per_hectare", agg["yield_imputed"]),
    ]
    parts = []
    for variable, col, unit, imputed in specs:
        p = agg[_GROUP].copy()
        p["variable"] = variable
        p["value"] = agg[col].values
        p["unit"] = unit
        p["is_imputed"] = imputed.values
        parts.append(p)

    out = pd.concat(parts, ignore_index=True).dropna(subset=["value"])
    return coerce_tidy(out)
