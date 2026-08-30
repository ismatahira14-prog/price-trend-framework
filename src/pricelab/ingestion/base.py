"""Loader registry + shared helpers for ingestion."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from pricelab.config import resolve_source_path

# A loader takes the resolved source config dict and returns a DataFrame.
# Fact loaders return tidy-long rows (see pricelab.schema).
# Dimension loaders return an arbitrary cleaned table (persisted to data/interim).
Loader = Callable[[dict[str, Any]], pd.DataFrame]

LOADERS: dict[str, Loader] = {}


def register_loader(name: str) -> Callable[[Loader], Loader]:
    def deco(fn: Loader) -> Loader:
        if name in LOADERS:
            raise ValueError(f"Loader {name!r} already registered")
        LOADERS[name] = fn
        return fn

    return deco


def get_loader(name: str) -> Loader:
    try:
        return LOADERS[name]
    except KeyError:
        raise KeyError(
            f"Unknown loader {name!r}. Registered: {sorted(LOADERS)}"
        ) from None


def read_excel(path: str | Path, sheet: str | int = 0, **kwargs: Any) -> pd.DataFrame:
    """Read an Excel sheet even if the file is currently open in Excel.

    Excel holds a write lock but allows shared reads; ``pandas.read_excel`` opens
    without sharing and fails with a PermissionError. We copy the bytes through a
    shared-read handle first.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")
    try:
        return pd.read_excel(path, sheet_name=sheet, engine="openpyxl", **kwargs)
    except PermissionError:
        with open(path, "rb") as fh:  # shared read works around the Excel lock
            data = fh.read()
        return pd.read_excel(io.BytesIO(data), sheet_name=sheet, engine="openpyxl", **kwargs)


def source_frame(source_cfg: dict[str, Any], **kwargs: Any) -> pd.DataFrame:
    """Read the sheet named by a ``sources.yaml`` entry."""
    path = resolve_source_path(source_cfg["path"])
    return read_excel(path, source_cfg.get("sheet", 0), **kwargs)


def run_source(key: str, source_cfg: dict[str, Any]) -> pd.DataFrame:
    """Dispatch one source entry to its loader, tagging rows with ``source=key``."""
    loader = get_loader(source_cfg["loader"])
    cfg = {**source_cfg, "_key": key}
    df = loader(cfg)
    if source_cfg.get("kind") == "fact" and "source" in df.columns:
        df["source"] = key
    return df
