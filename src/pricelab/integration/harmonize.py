"""Canonicalize free-text region / commodity / unit strings.

Region names are validated against the district/division/province hierarchy in
the ``region_hierarchy`` source (``crops intern.xlsx`` / ``ds`` sheet) plus the
explicit entries in ``config/regions.yaml``. Commodity names are validated
against ``config/commodities.yaml``.

Values that match nothing are returned lightly-cleaned (title-cased) and, when
``track=True``, recorded in a module-level registry so the ingestion report can
list exactly which aliases to add.
"""

from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import Iterable

from pricelab.config import load_config, resolve_source_path

_WS = re.compile(r"\s+")
_SUFFIX = re.compile(r"\s+(district|division|protected area|agency|tribal area)$")

_UNMAPPED: dict[str, set[str]] = defaultdict(set)


def unmapped() -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in _UNMAPPED.items() if v}


def reset_unmapped() -> None:
    _UNMAPPED.clear()


def _norm(s: str) -> str:
    return _WS.sub(" ", str(s).strip().lower())


def _title(s: str) -> str:
    return _WS.sub(" ", str(s).strip()).title()


def _strip_suffix(key: str) -> str:
    return _SUFFIX.sub("", key).strip()


# --------------------------------------------------------------------------- #
# commodities
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _commodity_alias_map() -> dict[str, str]:
    cfg = load_config()["commodities"] or {}
    out: dict[str, str] = {}
    for entry in cfg.get("commodities", []):
        canonical = entry["canonical"]
        out[_norm(canonical)] = canonical
        for alias in entry.get("aliases", []) or []:
            out[_norm(alias)] = canonical
    return out


def canon_commodity(value: str | None, *, track: bool = True) -> str:
    if value is None or isinstance(value, float):
        return ""
    key = _norm(value)
    if not key or key in {"nan", "null", "none"}:
        return ""
    hit = _commodity_alias_map().get(key)
    if hit:
        return hit
    if track:
        _UNMAPPED["commodity"].add(str(value).strip())
    return _title(value)


# --------------------------------------------------------------------------- #
# regions
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _region_yaml() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    cfg = load_config()["regions"] or {}
    alias_map: dict[str, str] = {}
    level_map: dict[str, str] = {}
    for entry in cfg.get("regions", []):
        canonical = entry["canonical"]
        level = entry.get("level", "district")
        for name in [canonical, *(entry.get("aliases", []) or [])]:
            alias_map[_norm(name)] = canonical
            level_map[_norm(name)] = level
    district_aliases = {
        _norm(k): v for k, v in (cfg.get("district_aliases", {}) or {}).items()
    }
    return alias_map, level_map, district_aliases


@lru_cache(maxsize=1)
def _hierarchy() -> tuple[dict[str, str], dict[str, str], dict[str, tuple[str, str]]]:
    """Load district/division names from the region_hierarchy source.

    Returns (name->canonical, name->level, district->(division, province)).
    """
    from pricelab.ingestion.base import read_excel  # local import avoids a cycle

    name_map: dict[str, str] = {}
    level_map: dict[str, str] = {}
    rollup: dict[str, tuple[str, str]] = {}

    sources = load_config()["sources"] or {}
    scfg = sources.get("region_hierarchy")
    if not scfg:
        return name_map, level_map, rollup
    try:
        df = read_excel(resolve_source_path(scfg["path"]), scfg.get("sheet", "ds"))
    except FileNotFoundError:
        return name_map, level_map, rollup
    df.columns = [str(c).strip().lower() for c in df.columns]
    if not {"ds", "dv", "pv"} <= set(df.columns):
        return name_map, level_map, rollup

    for _, r in df.iterrows():
        district = _title(_strip_suffix(_norm(r["ds"])))
        division = _title(_strip_suffix(_norm(r["dv"])))
        province = _title(str(r["pv"]).strip())
        for raw, canon, lvl in (
            (r["ds"], district, "district"),
            (r["dv"], division, "division"),
        ):
            name_map[_norm(raw)] = canon
            name_map[_strip_suffix(_norm(raw))] = canon
            level_map[_norm(raw)] = lvl
            level_map[_strip_suffix(_norm(raw))] = lvl
        if district:
            rollup[_norm(district)] = (division, province)
    return name_map, level_map, rollup


def canon_region(value: str | None, *, track: bool = True) -> str:
    if value is None:
        return ""
    key = _norm(value)
    if not key or key in {"nan", "null", "none"}:
        return ""

    alias_map, _lvl, district_aliases = _region_yaml()
    hier_names, _hlvl, _roll = _hierarchy()
    stripped = _strip_suffix(key)

    for k in (key, stripped):
        if k in alias_map:
            return alias_map[k]
        if k in district_aliases:
            return district_aliases[k]
        if k in hier_names:
            return hier_names[k]

    if track:
        _UNMAPPED["region"].add(str(value).strip())
    return _title(stripped)


def region_level_for(value: str | None, default: str = "district") -> str:
    key = _norm(value or "")
    stripped = _strip_suffix(key)
    _alias, yaml_lvl, _da = _region_yaml()
    _names, hier_lvl, _roll = _hierarchy()
    for k in (key, stripped):
        if k in yaml_lvl:
            return yaml_lvl[k]
        if k in hier_lvl:
            return hier_lvl[k]
    return default


def region_rollup(canonical_region: str) -> tuple[str, str]:
    """(division, province) for a canonical district name; ('','') if unknown."""
    _n, _l, roll = _hierarchy()
    return roll.get(_norm(canonical_region), ("", ""))


# --------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------- #
_UNIT_ALIASES = {
    "per litre": "PKR_per_litre",
    "per liter": "PKR_per_litre",
    "per kg": "PKR_per_kg",
    "each": "PKR_per_unit",
    "000 hectares": "000_hectares",
    "000 tonnes": "000_tonnes",
    "tonnes per hectare": "tonnes_per_hectare",
}


def canon_unit(value: str | None) -> str:
    if value is None:
        return ""
    key = _norm(value)
    if not key or key in {"nan", "null", "none"}:
        return ""
    return _UNIT_ALIASES.get(key, str(value).strip())


def canon_regions(values: Iterable[str | None]) -> list[str]:
    return [canon_region(v) for v in values]
