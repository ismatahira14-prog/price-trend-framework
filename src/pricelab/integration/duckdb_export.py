"""Write master_long + dimension tables to a single DuckDB file.

This file (``data/processed/pricelab.duckdb`` by default) is committed to git
and is what the deployed Streamlit dashboard reads. It needs no server,
credentials, or network access - it works identically on your laptop and on
Streamlit Community Cloud.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from pricelab.config import data_dir, load_config


def snapshot_path() -> Path:
    rel = (load_config()["database"] or {}).get("snapshot", {}).get(
        "path", "processed/pricelab.duckdb"
    )
    p = data_dir() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_duckdb_snapshot(
    master: pd.DataFrame, dimensions: dict[str, pd.DataFrame], path: str | Path | None = None
) -> Path:
    path = Path(path) if path else snapshot_path()
    con = duckdb.connect(str(path))
    try:
        con.register("master_df", master)
        con.execute("CREATE OR REPLACE TABLE master_long AS SELECT * FROM master_df")
        for name, df in dimensions.items():
            con.register("dim_df", df)
            con.execute(f'CREATE OR REPLACE TABLE dim_{name} AS SELECT * FROM dim_df')
    finally:
        con.close()
    return path
