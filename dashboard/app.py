"""Pakistan Price Trend Framework - entry point / page router.

Run locally:   streamlit run dashboard/app.py   (or: .\\run.cmd dashboard)
Deployed:      Streamlit Community Cloud, same entry point ("Main file
               path" = dashboard/app.py), reads the committed DuckDB
               snapshot at data/processed/pricelab.duckdb.

NAVIGATION NOTE: this used to just BE the Home page's own content, with the
other pages picked up automatically (as a collapsed left sidebar) from
whatever .py files existed under dashboard/pages/. It's a thin router now -
`st.navigation(..., position="top")` instead, a horizontal bar across the
top of the page rather than a sidebar. `st.set_page_config()` has to live
here (it can only be called once per run, and must be the first Streamlit
command - each page used to call its own copy, back when every page ran as
if it were independently "the app"): every page below had that call removed
from its own file for exactly that reason. The actual Home page content
that used to live directly in this file moved to `dashboard/pages/0_Home.py`
unchanged apart from that (see its own docstring for the small path fixups
that move required) - it's still the `default=True` page, so a fresh visit
lands on it exactly as before.

Every existing page, in its original order, with its original title/icon -
`st.navigation()` doesn't touch what's inside a page, only how you get to
it, so nothing about any individual page's charts/data/behavior changes.
"""

import streamlit as st

st.set_page_config(
    page_title="Pakistan Price Trend Framework",
    page_icon="📈",
    layout="wide",
)

_pages = [
    st.Page("pages/0_Home.py", title="Home", icon="📈", default=True),
    st.Page("pages/1_CPI_Trends.py", title="CPI Trends", icon="📈"),
    st.Page("pages/2_Crop_Production.py", title="Crop Production", icon="🌾"),
    st.Page("pages/3_Data_Explorer.py", title="Data Explorer", icon="🔎"),
    st.Page("pages/4_Inflation_Heatmap.py", title="Inflation Heatmap", icon="🗓"),
]

pg = st.navigation(_pages, position="top")
pg.run()
