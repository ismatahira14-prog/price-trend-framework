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

# One representative emoji per CPI group - shared so every page that labels
# a group by name (the Inflation Heatmap's column headers, the Home page's
# group bar charts) uses the exact same icon for it, not a page-specific
# guess. No entry for "General" (the all-groups aggregate, not itself one of
# the 12 COICOP groups - see CPI_GROUP_ORDER's own comment).
CPI_GROUP_ICONS: dict[str, str] = {
    "Food & Non-Alcoholic Beverages": "🍎",
    "Transport": "🚗",
    "Housing, Water, Electricity, Gas & Fuels": "🏠",
    "Health": "🏥",
    "Education": "🎓",
    "Clothing & Footwear": "👕",
    "Communication": "📱",
    "Restaurants & Hotels": "🍽️",
    "Recreation & Culture": "🎭",
    "Furnishing & Household Equipment": "🛋️",
    "Alcoholic Beverages & Tobacco": "🍷",
    "Miscellaneous Goods & Services": "🛍️",
}

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

# One fixed, low-opacity fill per event band. Cycles through all 8 Okabe-Ito
# hues (there are more dated events than colors, so a little reuse across
# non-adjacent events is fine - each band is independently hoverable/labeled).
EVENT_BAND_HUES: list[str] = OKABE_ITO

# Horizontal inflation-MAGNITUDE bands (Deflation -> Very high, on the
# combined MoM/YoY chart). A severity ramp (blue -> green -> yellow -> orange
# -> red), deliberately NOT the categorical Okabe-Ito set: it encodes ordered
# magnitude, not category identity. Opacity is deliberately higher than a
# typical "background" tint so the 5 tiers stay visually distinguishable from
# each other, while the two data lines (drawn on top, full opacity) still
# read as the primary content. Order matches config/analysis.yaml: inflation_bands.
INFLATION_BAND_FILLS: list[str] = [
    "rgba(0,114,178,0.16)",   # Deflation - blue
    "rgba(0,158,115,0.14)",   # Low inflation - green ("safe")
    "rgba(240,196,25,0.20)",  # Moderate inflation - yellow
    "rgba(230,159,0,0.22)",   # High inflation - orange
    "rgba(213,94,0,0.24)",    # Very high inflation - red/vermillion
]

# PBS-style header banner (see dashboard/app.py module docstring: this is a
# generic government-statistics color scheme, not an official PBS asset).
PBS_GREEN = "#0B6E4F"
PBS_GREEN_DARK = "#054A34"
