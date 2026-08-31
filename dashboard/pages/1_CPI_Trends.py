"""CPI Trends page - compare price-group indices over time."""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pricelab.dashboard.data import cpi_series, latest_change_table, load_master_long  # noqa: E402
from pricelab.dashboard.theme import (  # noqa: E402
    CPI_COLORS,
    CPI_DEFAULT_GROUPS,
    CPI_GROUP_ORDER,
    MAX_SERIES,
)

st.set_page_config(page_title="CPI Trends", page_icon="📈", layout="wide")
st.title("CPI Trends by group")
st.caption("Answers WHAT changed and WHEN, for the monthly CPI index (2015-16 = 100).")


@st.cache_data(ttl=3600)
def _load():
    return load_master_long()


df = _load()
available = [g for g in CPI_GROUP_ORDER if g in set(df["commodity"])]

selected = st.multiselect(
    "CPI groups",
    options=available,
    default=[g for g in CPI_DEFAULT_GROUPS if g in available],
)
if len(selected) > MAX_SERIES:
    st.warning(f"Showing the first {MAX_SERIES} of {len(selected)} selected groups for readability.")
    selected = selected[:MAX_SERIES]

wide = cpi_series(df, selected)
if wide.empty:
    st.warning("Pick at least one CPI group above.")
    st.stop()

min_d, max_d = wide.index.min(), wide.index.max()
start, end = st.slider(
    "Date range",
    min_value=min_d.to_pydatetime(),
    max_value=max_d.to_pydatetime(),
    value=(min_d.to_pydatetime(), max_d.to_pydatetime()),
    format="MMM YYYY",
)
wide = wide.loc[start:end]

fig = go.Figure()
for col in selected:
    if col not in wide.columns:
        continue
    fig.add_trace(
        go.Scatter(
            x=wide.index,
            y=wide[col],
            mode="lines",
            name=col,
            line=dict(color=CPI_COLORS.get(col, "#888"), width=2),
            hovertemplate=f"{col}<br>%{{x|%b %Y}}: %{{y:.1f}}<extra></extra>",
        )
    )
fig.update_layout(
    height=460,
    margin=dict(l=10, r=10, t=10, b=10),
    yaxis_title="Index (2015-16 = 100)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    xaxis=dict(showgrid=False),
    yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Latest reading & change")
st.dataframe(
    latest_change_table(wide).rename(
        columns={"latest": "Latest index", "mom_pct": "MoM %", "yoy_pct": "YoY %"}
    ),
    use_container_width=True,
)
