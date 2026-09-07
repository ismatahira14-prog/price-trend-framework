"""Inflation heat map - monthly change by CPI group.

Rendered on its own page (dashboard/pages/4_Inflation_Heatmap.py) AND inline
on the Home page directly below the "Inflation by Group" bar charts. Both
call `render_inflation_heatmap()` so the two stay byte-for-byte identical in
appearance, controls, data and logic - there is exactly one implementation.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from pricelab.dashboard.data import cpi_series, load_master_long
from pricelab.dashboard.theme import CPI_GROUP_ICONS, CPI_GROUP_ORDER

# Shared with the Home page's group bar charts (see pricelab.dashboard.theme)
# so the same icon always means the same group everywhere in the dashboard.
GROUP_ICONS = CPI_GROUP_ICONS
GROUP_LABELS = {
    "Food & Non-Alcoholic Beverages": "Food",
    "Transport": "Transport",
    "Housing, Water, Electricity, Gas & Fuels": "Housing",
    "Health": "Health",
    "Education": "Education",
    "Clothing & Footwear": "Clothing",
    "Communication": "Communication",
    "Restaurants & Hotels": "Restaurants",
    "Recreation & Culture": "Recreation",
    "Furnishing & Household Equipment": "Furnishing",
    "Alcoholic Beverages & Tobacco": "Alcohol & Tobacco",
    "Miscellaneous Goods & Services": "Miscellaneous",
}
GROUP_CODES = {
    "Food & Non-Alcoholic Beverages": "01",
    "Alcoholic Beverages & Tobacco": "02",
    "Clothing & Footwear": "03",
    "Housing, Water, Electricity, Gas & Fuels": "04",
    "Furnishing & Household Equipment": "05",
    "Health": "06",
    "Transport": "07",
    "Communication": "08",
    "Recreation & Culture": "09",
    "Education": "10",
    "Restaurants & Hotels": "11",
    "Miscellaneous Goods & Services": "12",
}


@st.cache_data(ttl=3600)
def _load():
    return load_master_long()


def _value_gradient_factory(max_negative, max_positive):
    def _value_gradient(value):
        if pd.isna(value) or value == 0:
            return ""
        if value < 0:
            intensity = min(abs(value) / max_negative, 1)
            red = int(240 - 120 * intensity)
            green = int(253 - 15 * intensity)
            blue = int(244 - 120 * intensity)
            return f"background-color: rgb({red}, {green}, {blue}); color: #14532D"
        intensity = min(value / max_positive, 1)
        red = int(254 - 55 * intensity)
        green = int(242 - 150 * intensity)
        blue = int(242 - 150 * intensity)
        if value > 20:
            return f"background-color: rgb({red}, {green}, {blue}); color: #7F1D1D; font-weight: 600"
        return f"background-color: rgb({red}, {green}, {blue}); color: #7F1D1D"

    return _value_gradient


_INTRO_CAPTION = "Rows are months and columns are CPI groups. Values are percentage changes."


def render_inflation_heatmap(*, show_title: bool = True, caption_at_bottom: bool = False) -> None:
    """Render the full interactive inflation heat map in place.

    `show_title` toggles the `st.title("Inflation heat map")` heading.
    `caption_at_bottom` moves the "Rows are months..." intro caption from
    above the controls to below the table (used by the Home page's inline
    copy, which has no heading of its own). Every control, the table, the
    CSV download and the footnote are always rendered. Uses
    `load_master_long()` / `cpi_series()` - the same data and logic as the
    rest of the dashboard, no placeholder values.
    """
    if show_title:
        st.title("Inflation heat map")
    if not caption_at_bottom:
        st.caption(_INTRO_CAPTION)

    df = _load()
    available = sorted(
        (group for group in CPI_GROUP_ORDER[1:] if group in set(df["commodity"])),
        key=lambda group: int(GROUP_CODES[group]),
    )
    measure = st.radio(
        "Inflation measure",
        options=["Year-over-year", "Month-over-month"],
        horizontal=True,
    )

    wide = cpi_series(df, available)
    periods = wide.pct_change(12 if measure == "Year-over-year" else 1) * 100
    periods = periods.reindex(columns=available).dropna(how="all")

    if periods.empty:
        st.warning("No inflation changes are available for the selected data.")
        return

    if "heatmap_years" not in st.session_state:
        st.session_state.heatmap_years = 5

    st.markdown("**Show recent inflation**")
    year_buttons = st.columns(5)
    for years, button in zip(range(1, 6), year_buttons):
        if button.button(f"{years} year" if years == 1 else f"{years} years", use_container_width=True):
            st.session_state.heatmap_years = years

    min_date, max_date = periods.index.min(), periods.index.max()
    default_start = max(min_date, max_date - pd.DateOffset(months=12 * st.session_state.heatmap_years - 1))
    start, end = st.slider(
        "Date range",
        min_value=min_date.to_pydatetime(),
        max_value=max_date.to_pydatetime(),
        value=(default_start.to_pydatetime(), max_date.to_pydatetime()),
        format="MMM YYYY",
    )
    periods = periods.loc[start:end].iloc[::-1]

    table = periods.copy()
    table.index = table.index.strftime("%b %Y")
    table.index.name = "Month"
    table = table.round(2)
    display_table = table.rename(
        columns={
            group: (
                f"{GROUP_ICONS.get(group, '•')} {GROUP_LABELS.get(group, group)}"
            )
            for group in table.columns
        }
    )

    finite_values = table.to_numpy()
    finite_values = finite_values[~pd.isna(finite_values)]
    max_negative = abs(finite_values[finite_values < 0].min()) if (finite_values < 0).any() else 1
    max_positive = finite_values[finite_values > 0].max() if (finite_values > 0).any() else 1

    styled = (
        display_table.style.map(_value_gradient_factory(max_negative, max_positive))
        .format(precision=2, na_rep="-")
    )
    st.dataframe(styled, use_container_width=True, height=720)
    st.download_button(
        "Download heat table as CSV",
        data=table.to_csv().encode("utf-8"),
        file_name="inflation_heat_table.csv",
        mime="text/csv",
    )

    if caption_at_bottom:
        st.caption(_INTRO_CAPTION)

    st.caption(
        "Green indicates falling prices, red indicates rising prices. "
        "Source: Pakistan Bureau of Statistics (PBS) Consumer Price Index."
    )
