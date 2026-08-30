"""The tidy-long schema - the contract between ingestion and every later module.

One row = one observation of one ``variable`` for one ``commodity`` in one
``region`` at one ``date``, from one ``source``.
"""

from __future__ import annotations

import pandas as pd

TIDY_COLUMNS: list[str] = [
    "date",          # datetime64[ns]  - period start
    "freq",          # str  - "M" | "W" | "A"
    "region",        # str  - canonical region name
    "region_level",  # str  - "national" | "province" | "division" | "district"
    "commodity",     # str  - canonical commodity / CPI group  (may be "" for pure macro)
    "variable",      # str  - e.g. "cpi_index", "crop_area", "crop_production", "crop_yield"
    "value",         # float
    "unit",          # str
    "source",        # str  - key from config/sources.yaml
    "is_imputed",    # bool
]

# Columns that together uniquely identify a row.
KEY_COLUMNS: list[str] = ["date", "freq", "region", "commodity", "variable", "source"]

# Columns that must never be null.
NON_NULL_COLUMNS: list[str] = [
    "date",
    "freq",
    "region",
    "region_level",
    "variable",
    "value",
    "unit",
    "source",
    "is_imputed",
]

VALID_FREQ = {"M", "W", "A", "D", "Q"}
VALID_LEVELS = {"national", "province", "division", "district"}


def empty_tidy() -> pd.DataFrame:
    """A correctly-typed empty tidy frame."""
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in TIDY_COLUMNS})
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = df["value"].astype("float64")
    df["is_imputed"] = df["is_imputed"].astype("bool")
    return df


def coerce_tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder columns, coerce dtypes, and fill optional nulls with sane defaults."""
    missing = [c for c in TIDY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Frame is missing tidy columns: {missing}")
    out = df.loc[:, TIDY_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"])
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["commodity"] = out["commodity"].fillna("").astype(str)
    for c in ("freq", "region", "region_level", "variable", "unit", "source"):
        out[c] = out[c].astype(str).str.strip()
    out["is_imputed"] = out["is_imputed"].fillna(False).astype(bool)
    return out


class SchemaError(ValueError):
    """Raised when a frame violates the tidy contract."""


def validate_tidy(df: pd.DataFrame, *, allow_empty: bool = True) -> pd.DataFrame:
    """Validate a tidy frame. Returns the (column-ordered) frame or raises ``SchemaError``."""
    missing = [c for c in TIDY_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"Missing columns: {missing}")

    df = df.loc[:, TIDY_COLUMNS]

    if df.empty:
        if allow_empty:
            return df
        raise SchemaError("Frame is empty")

    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        raise SchemaError("'date' must be datetime64")
    if not pd.api.types.is_numeric_dtype(df["value"]):
        raise SchemaError("'value' must be numeric")
    if not pd.api.types.is_bool_dtype(df["is_imputed"]):
        raise SchemaError("'is_imputed' must be boolean")

    for col in NON_NULL_COLUMNS:
        n = int(df[col].isna().sum())
        if n:
            raise SchemaError(f"Column '{col}' has {n} null value(s)")

    bad_freq = sorted(set(df["freq"]) - VALID_FREQ)
    if bad_freq:
        raise SchemaError(f"Invalid freq value(s): {bad_freq}")

    bad_lvl = sorted(set(df["region_level"]) - VALID_LEVELS)
    if bad_lvl:
        raise SchemaError(f"Invalid region_level value(s): {bad_lvl}")

    dups = df.duplicated(subset=KEY_COLUMNS, keep=False)
    if dups.any():
        sample = df.loc[dups, KEY_COLUMNS].head(5).to_dict("records")
        raise SchemaError(
            f"{int(dups.sum())} duplicate rows on key {KEY_COLUMNS}; sample: {sample}"
        )
    return df
