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
