"""Pakistan Price Trend Framework - dashboard home page.

Run locally:   streamlit run dashboard/app.py
Deployed:      Streamlit Community Cloud, same entry point, reads the
               committed DuckDB snapshot at data/processed/pricelab.duckdb
               (no server, no credentials - see README.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

# Make `import pricelab` work whether this is run from the repo root or not.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pricelab.dashboard.data import SnapshotMissing, cpi_series, load_master_long  # noqa: E402
from pricelab.dashboard.theme import SEQUENTIAL_HUE  # noqa: E402

st.set_page_config(
    page_title="Pakistan Price Trend Framework",
    page_icon="📈",
    layout="wide",
)


@st.cache_data(ttl=3600)
def _load() -> "pd.DataFrame":  # noqa: F821
    return load_master_long()


st.title("📈 A Data-Driven Framework for Price Trend Analysis")
st.caption(
    "Data Collection → Integration → Cleaning → EDA → Factor ID → Forecasting → "
    "Uncertainty → Visualization → Decision Support"
)

try:
    df = _load()
except SnapshotMissing as e:
    st.error(str(e))
    st.stop()

# ---------------------------------------------------------------- KPI row --
general = cpi_series(df, ["General"])["General"].dropna()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Latest General CPI", f"{general.iloc[-1]:.1f}", help="Base: 2015-16 = 100")
if len(general) > 1:
    mom = (general.iloc[-1] / general.iloc[-2] - 1) * 100
    c2.metric("Month-over-month", f"{mom:+.2f}%")
if len(general) > 12:
    yoy = (general.iloc[-1] / general.iloc[-13] - 1) * 100
    c3.metric("Year-over-year", f"{yoy:+.2f}%")
c4.metric("Rows ingested", f"{len(df):,}")

st.divider()

# ---------------------------------------------------------- overview chart --
st.subheader("General CPI over time")
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=general.index,
        y=general.values,
        mode="lines",
        line=dict(color=SEQUENTIAL_HUE, width=2),
        fill="tozeroy",
        fillcolor="rgba(0, 114, 178, 0.08)",
        hovertemplate="%{x|%b %Y}<br>Index: %{y:.1f}<extra></extra>",
    )
)
fig.update_layout(
    height=380,
    margin=dict(l=10, r=10, t=10, b=10),
    xaxis_title=None,
    yaxis_title="Index (2015-16 = 100)",
    plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False),
    yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
)
st.plotly_chart(fig, use_container_width=True)

st.info(
    "Use the pages in the sidebar: **CPI Trends** (compare price groups), "
    "**Crop Production** (district-level area/production/yield), "
    "**Data Explorer** (filter and download the raw tidy table)."
)

with st.expander("What's currently loaded"):
    st.write(
        f"- **Sources:** {', '.join(sorted(df['source'].unique()))}\n"
        f"- **Variables:** {', '.join(sorted(df['variable'].unique()))}\n"
        f"- **Date range:** {df['date'].min().date()} → {df['date'].max().date()}\n"
        f"- **Regions covered:** {df['region'].nunique()}\n\n"
        "Retail commodity prices, weather, trade, fertilizer/diesel/electricity "
        "prices, and wages are not loaded yet - add them to `data/raw/` and "
        "`config/sources.yaml`, they will show up here automatically."
    )
