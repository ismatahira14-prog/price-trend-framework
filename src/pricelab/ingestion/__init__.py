"""Ingestion layer: one loader per raw source shape -> tidy-long rows.

Importing this package registers every built-in loader.
"""

from pricelab.ingestion import cpi_groups, crop_production, reference_table  # noqa: F401
from pricelab.ingestion.base import LOADERS, get_loader, register_loader, run_source

__all__ = ["LOADERS", "get_loader", "register_loader", "run_source"]
