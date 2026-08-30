"""Loader: generic dimension / lookup sheet.

Reads a sheet as-is, trims column names and string cells, drops fully-empty
rows, and returns it. ``build_master`` persists the result to
``data/interim/<source_key>.parquet`` and does **not** add it to master_long.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from pricelab.ingestion.base import register_loader, source_frame


@register_loader("reference_table")
def load_reference_table(cfg: dict[str, Any]) -> pd.DataFrame:
    df = source_frame(cfg)
    df.columns = [str(c).strip() for c in df.columns]
    text_cols = df.select_dtypes(include=["object", "string"]).columns
    for c in text_cols:
        df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    df = df.replace({"NULL": pd.NA, "": pd.NA})
    df = df.dropna(axis=0, how="all")
    return df.reset_index(drop=True)
