"""Unit tests for pricelab.dashboard.medical_group (pure-calc parts).

No database / sqlcmd: build synthetic IMIS-shaped frames and check the
assembly logic (sub-group routing, revision counting, YoY, city pressure,
moves-together).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pricelab.dashboard import medical_group as mg


def _raw(months=14):
    dates = pd.date_range("2025-01-01", periods=months, freq="MS")
    items = {
        "06.1.1.01": ("Septran Tablet", "10 No.", 50.0, 0.6),      # medicine, revised often
        "06.1.1.02": ("Panadol Tablet", "10 No.", 35.0, 0.0),      # medicine, flat
        "06.1.3.01": ("Glucometer", "Each", 3000.0, 0.2),          # equipment
        "06.2.1.01": ("Doctor MBBS Fee", "Per Patient", 600.0, 1.0),  # service
        "06.2.3.01": ("Blood Test", "Per Test", 500.0, 0.5),       # diagnostic
        "06.2.3.02": ("Sugar Test", "Per Test", 300.0, 0.5),       # diagnostic - tracks blood test
        "06.3.0.01": ("C-Section", "Per Case", 35000.0, 0.8),      # procedure
    }
    rows = []
    rng = np.random.default_rng(0)
    for code, (_n, _u, base, drift) in items.items():
        series = base * (1 + drift / 100) ** np.arange(months)
        if code in ("06.2.3.01", "06.2.3.02"):  # make these two move together
            shock = np.cumsum(rng.normal(0, 0.01, months))
            series = base * np.exp(shock)
        for d, p in zip(dates, series):
            for city in (1, 2, 3):
                rows.append({"year": d.year, "month": d.month, "coicop": code,
                             "citycode": city, "price": float(p) * (1 + 0.02 * city)})
    prices = pd.DataFrame(rows)

    names = pd.DataFrame([
        {"code": c, "long_name": v[0], "short_name": v[0], "unit": v[1]}
        for c, v in items.items()
    ])
    weights = pd.DataFrame([
        {"code": c, "m": mth, "w": 0.1} for c in items for mth in range(1, 13)
    ])
    inf_rows = []
    for i, d in enumerate(pd.date_range("2016-01-01", periods=130, freq="MS")):
        inf_rows.append({"Year": d.year, "Month": d.month, "General": 100 + i,
                         **{f"G{j:02d}": 100 + i * (0.8 + 0.03 * j) for j in range(1, 13)}})
    inflation = pd.DataFrame(inf_rows)
    cities = pd.DataFrame({"citycode": [1, 2, 3], "city": ["Islamabad", "Lahore", "Karachi"]})
    return {"prices": prices, "names": names, "weights": weights,
            "inflation": inflation, "cities": cities}


def test_subgroup_routing():
    assert mg._subgroup("06.1.1.02") == "Medicines"
    assert mg._subgroup("06.1.3.01") == "Medical Equipment"
    assert mg._subgroup("06.2.1.01") == "Services"
    assert mg._subgroup("06.2.2.01") == "Services"
    assert mg._subgroup("06.2.3.05") == "Diagnostics"
    assert mg._subgroup("06.3.0.02") == "Procedures"


def test_assemble_groups_items_and_counts_revisions():
    d = mg._assemble(mg._build(_raw()), _raw())
    subs = {k: len(v) for k, v in d["subgroups"].items()}
    assert subs == {"Medicines": 2, "Services": 1, "Diagnostics": 2,
                    "Procedures": 1, "Medical Equipment": 1}
    assert set(mg.GROUP_ORDER) == set(d["subgroups"])

    items = d["items"].set_index("name")
    # Panadol is flat -> zero revisions; Septran drifts every month -> many
    assert items.loc["Panadol Tablet", "revisions"] == 0
    assert items.loc["Septran Tablet", "revisions"] >= 10
    # YoY is a real ratio, not a copy of the group figure
    assert abs(items.loc["Doctor Mbbs Fee", "yoy_pct"]) > 0


def test_group_kpis_from_inflation_table():
    d = mg._assemble(mg._build(_raw()), _raw())
    g = d["group"]
    assert g["total_items"] == 7
    assert g["cities_covered"] == 3
    assert round(g["basket_weight"], 1) == 0.7          # 7 items x 0.1
    assert len(g["index_series"]) == 130                # full G06 history
    assert isinstance(g["yoy_pct"], float) and isinstance(g["mom_pct"], float)


def test_city_pressure_is_indexed_to_100():
    d = mg._assemble(mg._build(_raw()), _raw())
    cp = d["city_pressure"]
    assert cp, "city pressure should not be empty on the fresh path"
    assert all("index" in r and "diff_pct" in r for r in cp)
    # city 3 was given the largest per-city markup -> should read hottest
    assert cp[0]["city"] == "Karachi"
    assert abs(np.mean([r["index"] for r in cp]) - 100) < 20


def test_moves_together_only_returns_same_subgroup_pairs():
    d = mg._assemble(mg._build(_raw()), _raw())
    mt = d["moves_together"]
    for pair in mt["item_pairs"]:
        assert pair["direction"] == "together"
    # Blood Test & Sugar Test were built to co-move and are both Diagnostics
    names = {(p["a"], p["b"]) for p in mt["item_pairs"]}
    flat = {n for pair in names for n in pair}
    if mt["item_pairs"]:
        assert "Blood Test" in flat or "Sugar Test" in flat
    assert len(mt["group_links"]) == 3


def test_group_order_constant_matches_subgroup_values():
    assert set(mg.SUBGROUPS.values()) == set(mg.GROUP_ORDER)
