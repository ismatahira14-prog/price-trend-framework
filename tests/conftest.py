"""Shared fixtures. Tests run against the real Excel files in ``data/raw``."""

from __future__ import annotations

import pytest

from pricelab.config import raw_dir


@pytest.fixture(scope="session", autouse=True)
def _require_raw_data():
    missing = [
        name
        for name in ("Inflation.xlsx", "CPI ITEMs.xlsx", "crops intern.xlsx")
        if not (raw_dir() / name).is_file()
    ]
    if missing:
        pytest.skip(f"raw data files not present: {missing}")


@pytest.fixture(scope="session")
def ingest_result():
    from pricelab.ingest import run

    return run(all=True, write=False)
