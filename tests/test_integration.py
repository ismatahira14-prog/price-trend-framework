import os

import pandas as pd

from pricelab.config import data_dir
from pricelab.schema import KEY_COLUMNS, validate_tidy


def test_master_is_valid_and_unique(ingest_result):
    m = ingest_result.master
    validate_tidy(m)
    assert not m.duplicated(subset=KEY_COLUMNS).any()
    assert ingest_result.dropped_duplicates == 0


def test_expected_sources_and_variables(ingest_result):
    m = ingest_result.master
    assert {"inflation_cpi_groups", "crop_production"} <= set(m["source"])
    assert {"cpi_index", "crop_area", "crop_production", "crop_yield"} <= set(m["variable"])
    assert len(ingest_result.dimensions) == 3


def test_cpi_row_count(ingest_result):
    m = ingest_result.master
    cpi = m[m["source"] == "inflation_cpi_groups"]
    # 13 groups x N months
    assert len(cpi) % 13 == 0


def test_data_dir_env_override(monkeypatch, tmp_path):
    from pricelab import config

    monkeypatch.setenv("PRICELAB_DATA_DIR", str(tmp_path))
    config.repo_root.cache_clear()  # not affected, but harmless
    assert config.data_dir() == tmp_path
    monkeypatch.delenv("PRICELAB_DATA_DIR")
    assert config.data_dir() == config.repo_root() / "data"
    assert os.path.isdir(data_dir())
