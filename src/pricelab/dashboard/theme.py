"""Shared chart palette.

Okabe-Ito: the standard colorblind-safe categorical palette. Colors are
assigned to a FIXED order of names (never "the next unused hue"), so a
series keeps the same color no matter what else is filtered in or out.
"""

from __future__ import annotations

OKABE_ITO: list[str] = [
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # bluish green
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
    "#F0E442",  # yellow
    "#000000",  # black
]

MAX_SERIES = len(OKABE_ITO)

# Fixed order for the 13 CPI groups (matches config/commodities.yaml). Deciding
# this order once, up front, means "General" and "Food" always get the same
# color across every page and every filter combination.
CPI_GROUP_ORDER: list[str] = [
    "General",
    "Food & Non-Alcoholic Beverages",
    "Transport",
    "Housing, Water, Electricity, Gas & Fuels",
    "Health",
    "Education",
    "Clothing & Footwear",
    "Communication",
    "Restaurants & Hotels",
    "Recreation & Culture",
    "Furnishing & Household Equipment",
    "Alcoholic Beverages & Tobacco",
    "Miscellaneous Goods & Services",
]

# Sensible default selection for the CPI Trends page: General + the groups
# most tied to the framework's WHY drivers (food, transport, housing/energy).
CPI_DEFAULT_GROUPS: list[str] = [
    "General",
    "Food & Non-Alcoholic Beverages",
    "Transport",
    "Housing, Water, Electricity, Gas & Fuels",
]

# A single, consistent hue for "ranked magnitude" bar charts (one measure,
# many categories) - see references/color-formula.md: sequential = one hue.
SEQUENTIAL_HUE = "#0072B2"
HIGHLIGHT_HUE = "#D55E00"


def color_map(names: list[str]) -> dict[str, str]:
    """Fixed name -> color mapping, in the order `names` is given."""
    return {name: OKABE_ITO[i % MAX_SERIES] for i, name in enumerate(names)}


CPI_COLORS: dict[str, str] = color_map(CPI_GROUP_ORDER)

# ---------------------------------------------------------------------------
# Spike / factor-analysis additions (Home page)
# ---------------------------------------------------------------------------

# Polarity pair for month-over-month / year-over-year change bars: rising
# prices vs falling prices. Reuses the two hues already used elsewhere so
# "increase" always means the same color across the whole dashboard.
INCREASE_COLOR = HIGHLIGHT_HUE  # vermillion - price level going up
DECREASE_COLOR = SEQUENTIAL_HUE  # blue - price level going down
NEUTRAL_GRAY = "rgba(128,128,128,0.35)"

# Moving averages sit on top of the CPI line itself - same hue family,
# distinguished by weight/dash rather than a competing color.
MA_3M_COLOR = "#56B4E9"  # sky blue - light, short-window
MA_6M_COLOR = "#CC79A7"  # reddish purple - medium window
MA_QUARTER_COLOR = "#009E73"  # bluish green - stepped calendar-quarter average

# Contributing-factor identity: reuse CPI_COLORS so "Transport" is the same
# color here as on the CPI Trends page. "Other" isn't a CPI group, so it gets
# one more fixed Okabe-Ito slot not already claimed by the default factors.
FACTOR_ORDER: list[str] = [
    "Food & Non-Alcoholic Beverages",
    "Transport",
    "Housing, Water, Electricity, Gas & Fuels",
    "Health",
    "Other",
]
FACTOR_COLORS: dict[str, str] = {**CPI_COLORS, "Other": OKABE_ITO[6]}

IMPACT_COLORS = {
    "High": HIGHLIGHT_HUE,
    "Medium": "#E69F00",
    "Low": "#888888",
}

# One fixed, low-opacity fill per event band, drawn from the same categorical
# set so events never clash with the increase/decrease or factor colors.
EVENT_BAND_HUES: list[str] = [OKABE_ITO[i] for i in (0, 1, 2, 3, 5)]
