"""Spike/factor analysis: real events + a MOCK contributing-factors dataset.

Two very different kinds of content live here:

1. ``EVENTS`` - real, dated, well-documented macro events. These are used to
   shade bands on the CPI chart and are NOT invented: each is a widely
   reported event whose timing plausibly overlaps the CPI period shown. We
   deliberately do not claim an exact causal magnitude ("X% of the spike was
   event Y") - that number does not exist yet.

2. ``generate_mock_monthly_factors`` / ``generate_mock_yearly_factors`` -
   *placeholder* per-item contribution data (Food/Transport/Housing/Health/
   Other), generated deterministically so a given month always looks the
   same across reruns. This exists purely to build and demo the click ->
   scroll -> table interaction end to end. **Nothing in these two functions
   is real data.**

Target schema (once real per-item weighted CPI contributions are available -
e.g. a new `sources.yaml` entry built from item-level SPI/CPI weights):

    date, year, month, cpi, mom_change_pct, yoy_change_pct,
    ma_3m, ma_6m, ma_quarter, factor, item, item_change_pct,
    contribution_pct, impact, event, event_description

To swap in real data: replace the two ``generate_mock_*`` functions with
loaders that read a new tidy source (e.g. ``variable == "item_contribution"``
in master_long) and return frames with the same columns used below
(``factor``, ``item_change_pct``, ``contribution_pct``, ``impact``) - nothing
in dashboard/app.py needs to change.
"""

from __future__ import annotations

import random

import pandas as pd

from pricelab.dashboard.theme import EVENT_BAND_HUES, FACTOR_ORDER

# --------------------------------------------------------------------------- #
# 1. Real, dated events (Pakistan CPI context, 2016-present)
# --------------------------------------------------------------------------- #
EVENTS: list[dict] = [
    {
        "name": "COVID-19 Pandemic",
        "short_name": "COVID-19",
        "start": "2020-03-01",
        "end": "2021-12-31",
        "description": "Global pandemic lockdowns disrupted supply chains, transport, and demand worldwide.",
    },
    {
        "name": "Global Supply-Chain Disruption",
        "short_name": "Supply Chain",
        "start": "2021-06-01",
        "end": "2022-06-30",
        "description": "Post-pandemic shipping bottlenecks and input shortages pushed up global goods prices.",
    },
    {
        "name": "Russia-Ukraine War",
        "short_name": "Russia-Ukraine War",
        "start": "2022-02-24",
        "end": "2023-06-30",
        "description": "War-driven spikes in global energy, food, and fertilizer prices.",
    },
    {
        "name": "2022 Pakistan Floods",
        "short_name": "Pakistan Floods",
        "start": "2022-06-14",
        "end": "2022-09-30",
        "description": "Catastrophic floods damaged crops and infrastructure, disrupting domestic food supply.",
    },
    {
        "name": "Currency Devaluation & Energy Price Reform",
        "short_name": "Currency Devaluation",
        "start": "2023-01-01",
        "end": "2023-07-31",
        "description": "IMF-program currency depreciation and fuel/energy price adjustments drove CPI to record highs.",
    },
]
for _i, _e in enumerate(EVENTS):
    _e["start"] = pd.Timestamp(_e["start"])
    _e["end"] = pd.Timestamp(_e["end"])
    _e["color"] = EVENT_BAND_HUES[_i % len(EVENT_BAND_HUES)]


def events_covering(date: pd.Timestamp) -> list[dict]:
    """Events whose [start, end] window contains `date`."""
    return [e for e in EVENTS if e["start"] <= date <= e["end"]]


# --------------------------------------------------------------------------- #
# 2. MOCK contributing-factor data - clearly placeholder, deterministic
# --------------------------------------------------------------------------- #
def classify_impact(contribution_pct: float) -> str:
    if contribution_pct >= 25:
        return "High"
    if contribution_pct >= 10:
        return "Medium"
    return "Low"


def _mock_weights(seed_key: str, n: int) -> list[float]:
    """n positive weights summing to 100, stable for a given seed_key."""
    rng = random.Random(seed_key)
    raw = [rng.uniform(0.5, 1.5) for _ in range(n)]
    total = sum(raw)
    return [round(100 * r / total, 1) for r in raw]


def _mock_rows_for_period(period_label: str, seed_key: str, overall_change: float) -> list[dict]:
    weights = _mock_weights(seed_key, len(FACTOR_ORDER))
    rng = random.Random(seed_key + "-item")
    rows = []
    for factor, contribution in zip(FACTOR_ORDER, weights):
        # A plausible-looking (not real) item-level change: roughly tracks
        # the overall change, scaled by this factor's share of it.
        item_change = round(overall_change * (0.5 + contribution / 100) * rng.uniform(0.8, 1.3), 2)
        rows.append(
            {
                "period": period_label,
                "factor": factor,
                "item_change_pct": item_change,
                "contribution_pct": contribution,
                "impact": classify_impact(contribution),
            }
        )
    return sorted(rows, key=lambda r: -r["contribution_pct"])


def generate_mock_monthly_factors(change_table: pd.DataFrame) -> pd.DataFrame:
    """MOCK per-item factor breakdown for every month in `change_table`.

    Parameters
    ----------
    change_table : output of ``pricelab.dashboard.data.cpi_change_table``
        (indexed by month-start date, has a ``mom_pct`` column).
    """
    all_rows = []
    for date, row in change_table.dropna(subset=["mom_pct"]).iterrows():
        label = date.strftime("%b %Y")
        for r in _mock_rows_for_period(label, f"m-{date.date()}", row["mom_pct"]):
            all_rows.append(
                {
                    "date": date,
                    "year": date.year,
                    "month": label,
                    "cpi_change_pct": round(row["mom_pct"], 2),
                    **r,
                }
            )
    return pd.DataFrame(all_rows)


def generate_mock_yearly_factors(change_table: pd.DataFrame) -> pd.DataFrame:
    """MOCK per-item factor breakdown for every calendar year in `change_table`."""
    yearly = change_table.dropna(subset=["yoy_pct"]).copy()
    yearly["year"] = yearly.index.year
    by_year = yearly.groupby("year")["yoy_pct"].mean()

    all_rows = []
    for year, avg_yoy in by_year.items():
        for r in _mock_rows_for_period(str(year), f"y-{year}", avg_yoy):
            all_rows.append({"year": year, "cpi_change_pct": round(avg_yoy, 2), **r})
    return pd.DataFrame(all_rows)
