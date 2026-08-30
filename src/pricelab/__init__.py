"""pricelab - A Data-Driven Framework for Price Trend Analysis.

Phase 0/1 scope: configuration, tidy schema, ingestion, and integration into a
single tidy-long fact table (`data/processed/master_long.parquet`).
"""

__version__ = "0.1.0"

from pricelab.config import data_dir, load_config, repo_root
from pricelab.schema import TIDY_COLUMNS, empty_tidy, validate_tidy

__all__ = [
    "__version__",
    "load_config",
    "data_dir",
    "repo_root",
    "TIDY_COLUMNS",
    "empty_tidy",
    "validate_tidy",
]
