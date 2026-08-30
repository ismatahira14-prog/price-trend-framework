"""Run every configured source and assemble ``data/processed/master_long``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from pricelab.config import interim_dir, load_config, processed_dir
from pricelab.ingestion.base import run_source
from pricelab.integration.harmonize import reset_unmapped, unmapped
from pricelab.schema import KEY_COLUMNS, coerce_tidy, empty_tidy, validate_tidy

log = logging.getLogger("pricelab.integration")


@dataclass
class IngestResult:
    master: pd.DataFrame
    facts: dict[str, pd.DataFrame] = field(default_factory=dict)
    dimensions: dict[str, pd.DataFrame] = field(default_factory=dict)
    unmapped: dict[str, list[str]] = field(default_factory=dict)
    dropped_duplicates: int = 0
    paths: dict[str, str] = field(default_factory=dict)


def build_master(only: list[str] | None = None, *, write: bool = True) -> IngestResult:
    """Load sources, harmonize, validate, and (optionally) write outputs.

    Parameters
    ----------
    only : restrict to these source keys (default: all in sources.yaml).
    write : persist parquet/csv outputs.
    """
    reset_unmapped()
    sources: dict = load_config()["sources"] or {}
    keys = list(sources) if only is None else [k for k in sources if k in only]

    result = IngestResult(master=empty_tidy())
    fact_frames: list[pd.DataFrame] = []

    for key in keys:
        scfg = sources[key]
        kind = scfg.get("kind", "fact")
        log.info("loading %s (loader=%s, kind=%s)", key, scfg.get("loader"), kind)
        df = run_source(key, scfg)

        if kind == "dimension":
            result.dimensions[key] = df
            if write:
                path = interim_dir() / f"{key}.parquet"
                df.to_parquet(path, index=False)
                result.paths[key] = str(path)
            continue

        df = validate_tidy(coerce_tidy(df))
        result.facts[key] = df
        fact_frames.append(df)

    if fact_frames:
        master = pd.concat(fact_frames, ignore_index=True)
        before = len(master)
        master = master.drop_duplicates(subset=KEY_COLUMNS, keep="first")
        result.dropped_duplicates = before - len(master)
        master = master.sort_values(KEY_COLUMNS).reset_index(drop=True)
        result.master = validate_tidy(master)

    result.unmapped = unmapped()

    if write and not result.master.empty:
        pq = processed_dir() / "master_long.parquet"
        csv = processed_dir() / "master_long.csv"
        result.master.to_parquet(pq, index=False)
        result.master.to_csv(csv, index=False)
        result.paths["master_long_parquet"] = str(pq)
        result.paths["master_long_csv"] = str(csv)

    return result
