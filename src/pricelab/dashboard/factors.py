"""Real, dated macro/global events shown on the CPI chart and the Global
Events table - plus a magnitude-ranking helper for the (now real, not mock)
per-CPI-group breakdown.

Every event below is a widely-reported, publicly documented event (pandemic,
war, shipping disruption, monetary-policy shift, commodity shock). We do NOT
claim any of them caused a specific Pakistan CPI move - only that it was
active during the shown window. See ``scope`` ("global" vs "domestic") and
``labeled_on_chart`` for how each is used:

- Every event gets a shaded band + hover tooltip on the CPI chart (temporal
  context).
- Only a curated subset (``labeled_on_chart: True``) also gets a visible text
  label on the chart, to avoid crowding - these are the ones most plausibly
  time-aligned with a visible move in *this* CPI series.
- Only ``scope == "global"`` events appear in the "Global Events" table.
  ``scope == "domestic"`` events (Pakistan-specific) are chart-only.

As of writing, two events are still ongoing (no real end date exists) - they
are capped at the CPI data's last available month purely for drawing a
band, and ``is_ongoing=True`` is what the UI uses to print "Ongoing" instead
of a fabricated end date.
"""

from __future__ import annotations

import pandas as pd

from pricelab.config import load_config
from pricelab.dashboard.theme import EVENT_BAND_HUES

EVENTS: list[dict] = [
    {
        "name": "COVID-19 Pandemic",
        "short_name": "COVID-19",
        "start": "2020-03-01",
        "end": "2021-12-31",
        "is_ongoing": False,
        "scope": "global",
        "category": "Pandemic",
        "channels": ["Supply chains", "Labor markets", "Transport", "Demand"],
        "description": "Global pandemic lockdowns disrupted supply chains, transport, and demand worldwide.",
        "labeled_on_chart": True,
    },
    {
        "name": "Global Supply-Chain Disruption",
        "short_name": "Supply Chain",
        "start": "2021-06-01",
        "end": "2022-06-30",
        "is_ongoing": False,
        "scope": "global",
        "category": "Supply chain / Logistics",
        "channels": ["Shipping", "Manufacturing inputs", "Consumer goods"],
        "description": "Post-pandemic shipping bottlenecks and input shortages pushed up global goods prices.",
        "labeled_on_chart": True,
    },
    {
        "name": "Suez Canal Blockage (Ever Given)",
        "short_name": "Suez Blockage",
        "start": "2021-03-23",
        "end": "2021-03-29",
        "is_ongoing": False,
        "scope": "global",
        "category": "Shipping / Logistics",
        "channels": ["Global shipping", "Container availability"],
        "description": "A six-day blockage of the Suez Canal delayed an estimated $9bn/day of trade and briefly disrupted global shipping schedules.",
        "labeled_on_chart": False,
    },
    {
        "name": "2020 Oil Price Crash",
        "short_name": "Oil Price Crash",
        "start": "2020-03-01",
        "end": "2020-04-30",
        "is_ongoing": False,
        "scope": "global",
        "category": "Energy shock (disinflationary)",
        "channels": ["Fuel", "Transport", "Energy"],
        "description": "Collapsing global travel demand crashed oil prices (WTI briefly traded negative) - a temporary DISinflationary pressure, unlike most events on this list.",
        "labeled_on_chart": False,
    },
    {
        "name": "Russia-Ukraine War",
        "short_name": "Russia-Ukraine War",
        "start": "2022-02-24",
        "end": "2023-06-30",  # acute global commodity-shock phase shown on the chart
        "is_ongoing": True,  # the conflict itself; see note in the Global Events table
        "scope": "global",
        "category": "Geopolitical conflict / War",
        "channels": ["Energy", "Food", "Fertilizer", "Freight"],
        "description": "War-driven spikes in global energy, food, and fertilizer prices. The chart band shows the acute 2022-2023 commodity-shock phase; the conflict itself is ongoing.",
        "labeled_on_chart": True,
    },
    {
        "name": "China Zero-COVID Policy & Lockdowns",
        "short_name": "China Zero-COVID",
        "start": "2022-03-01",
        "end": "2022-12-07",
        "is_ongoing": False,
        "scope": "global",
        "category": "Supply chain / Pandemic policy",
        "channels": ["Manufacturing", "Electronics", "Global supply chains"],
        "description": "Extended lockdowns in major Chinese manufacturing hubs added further strain to global supply chains.",
        "labeled_on_chart": False,
    },
    {
        "name": "2022 Pakistan Floods",
        "short_name": "Pakistan Floods",
        "start": "2022-06-14",
        "end": "2022-09-30",
        "is_ongoing": False,
        "scope": "domestic",
        "category": "Climate / domestic supply shock",
        "channels": ["Food (crops)", "Infrastructure", "Transport"],
        "description": "Catastrophic floods damaged crops and infrastructure, disrupting domestic food supply. Pakistan-specific, not a global event.",
        "labeled_on_chart": True,
    },
    {
        "name": "Global Fertilizer Price Shock",
        "short_name": "Fertilizer Shock",
        "start": "2021-09-01",
        "end": "2022-12-31",
        "is_ongoing": False,
        "scope": "global",
        "category": "Commodity shock",
        "channels": ["Fertilizer", "Agriculture", "Food production costs"],
        "description": "Natural-gas price spikes (compounded by the war in Ukraine, a major fertilizer exporter) drove global fertilizer prices sharply higher, raising farm input costs.",
        "labeled_on_chart": False,
    },
    {
        "name": "US Federal Reserve Rapid Rate Hikes",
        "short_name": "Fed Rate Hikes",
        "start": "2022-03-01",
        "end": "2023-07-31",
        "is_ongoing": False,
        "scope": "global",
        "category": "Monetary policy",
        "channels": ["Exchange rates", "Import costs", "Capital flows"],
        "description": "One of the fastest US rate-hike cycles in decades strengthened the US dollar, raising import and debt-servicing costs for import-reliant, dollar-borrowing economies.",
        "labeled_on_chart": False,
    },
    {
        "name": "Currency Devaluation & Energy Price Reform",
        "short_name": "Currency Devaluation",
        "start": "2023-01-01",
        "end": "2023-07-31",
        "is_ongoing": False,
        "scope": "domestic",
        "category": "Monetary / fiscal policy",
        "channels": ["Fuel", "Electricity", "Imports"],
        "description": "IMF-program currency depreciation and fuel/energy price adjustments drove Pakistan's CPI to record highs. Pakistan-specific, not a global event.",
        "labeled_on_chart": True,
    },
    {
        "name": "Red Sea Shipping Disruptions",
        "short_name": "Red Sea Disruption",
        "start": "2023-11-01",
        "end": None,  # ongoing as of writing
        "is_ongoing": True,
        "scope": "global",
        "category": "Shipping / Logistics",
        "channels": ["Global shipping", "Freight costs", "Suez route diversions"],
        "description": "Attacks on Red Sea shipping forced vessels onto longer routes around Africa, raising freight costs and transit times.",
        "labeled_on_chart": False,
    },
]

# Sentinel for "still ongoing, no real end date" - app.py clips every band to
# the CPI data's actual last available month before drawing it, so this only
# needs to be "far enough in the future", never today's wall-clock date.
_ONGOING_SENTINEL = pd.Timestamp("2099-12-31")

for _i, _e in enumerate(EVENTS):
    _e["start"] = pd.Timestamp(_e["start"])
    _e["end"] = pd.Timestamp(_e["end"]) if _e["end"] else _ONGOING_SENTINEL
    _e["color"] = EVENT_BAND_HUES[_i % len(EVENT_BAND_HUES)]


def events_covering(date: pd.Timestamp) -> list[dict]:
    """Events whose [start, end] window contains `date`."""
    return [e for e in EVENTS if e["start"] <= date <= e["end"]]


def global_events() -> list[dict]:
    return [e for e in EVENTS if e["scope"] == "global"]


# --------------------------------------------------------------------------- #
# Relative-magnitude ranking for the (real) per-group CPI breakdown.
#
# We do NOT have official CPI basket weights in this project's data, so we
# cannot compute a true "% contribution to the overall change" without
# fabricating a weight. What we CAN honestly say, from real data alone, is
# how a group's change ranks against the other 11 groups that period.
# --------------------------------------------------------------------------- #
def classify_relative_magnitude(rank: int, total: int) -> str:
    """rank is 1-based, 1 = largest |change| that period."""
    if total <= 0:
        return "Low"
    frac = rank / total
    if frac <= 1 / 3:
        return "High"
    if frac <= 2 / 3:
        return "Medium"
    return "Low"


# --------------------------------------------------------------------------- #
# Inflation-magnitude bands (config/analysis.yaml, NOT hard-coded)
# --------------------------------------------------------------------------- #
def load_inflation_bands() -> list[dict]:
    """[{label, min, max}, ...] from config/analysis.yaml, None = unbounded."""
    return list((load_config()["analysis"] or {}).get("inflation_bands", []))
