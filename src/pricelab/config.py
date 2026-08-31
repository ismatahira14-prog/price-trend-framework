"""Configuration and path resolution.

`data_dir()` is the single seam that makes the project run unchanged on Colab:
set the environment variable ``PRICELAB_DATA_DIR`` (e.g. to a mounted Google
Drive folder) and every loader follows.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

try:  # optional; loads a local .env if present
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass

_CONFIG_FILES = ("sources", "commodities", "regions", "analysis", "database")


@functools.lru_cache(maxsize=1)
def repo_root() -> Path:
    """Repository root (the folder containing ``config/`` and ``src/``)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config").is_dir() and (parent / "pyproject.toml").is_file():
            return parent
    # Fallback: two levels up from src/pricelab/
    return here.parents[2]


def config_dir() -> Path:
    override = os.getenv("PRICELAB_CONFIG_DIR")
    return Path(override) if override else repo_root() / "config"


def data_dir() -> Path:
    """Root of the ``data/`` tree.

    Order of precedence:
      1. ``PRICELAB_DATA_DIR`` environment variable
      2. ``<repo_root>/data``
    """
    override = os.getenv("PRICELAB_DATA_DIR")
    return Path(override).expanduser() if override else repo_root() / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def interim_dir() -> Path:
    d = data_dir() / "interim"
    d.mkdir(parents=True, exist_ok=True)
    return d


def processed_dir() -> Path:
    d = data_dir() / "processed"
    d.mkdir(parents=True, exist_ok=True)
    return d


@functools.lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load and merge every YAML file in ``config/`` into one dict.

    Keys: ``sources``, ``commodities``, ``regions``, ``analysis``.
    """
    cfg: dict[str, Any] = {}
    cdir = config_dir()
    for name in _CONFIG_FILES:
        path = cdir / f"{name}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"Missing config file: {path}")
        with path.open("r", encoding="utf-8") as fh:
            cfg[name] = yaml.safe_load(fh) or {}
    return cfg


def resolve_source_path(rel_path: str) -> Path:
    """Resolve a ``sources.yaml`` ``path:`` value against the data directory."""
    p = Path(rel_path)
    return p if p.is_absolute() else data_dir() / p
