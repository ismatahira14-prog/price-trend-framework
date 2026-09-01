"""Crop Production page - district-level area / production / yield."""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pricelab.dashboard.data import crop_slice, crop_variants, load_master_long  # noqa: E402
from pricelab.dashboard.theme import HIGHLIGHT_HUE, SEQUENTIAL_HUE  # noqa: E402

st.set_page_config(
    page_title="Crop Production", page_icon="🌾", layout="wide", initial_sidebar_state="collapsed"
)
st.title("Crop production by district")
st.caption("Answers WHERE the largest supply changes are, for annual crop-year data.")

VARIABLE_LABELS = {
    "crop_production": "Production (000 tonnes)",
    "crop_area": "Area (000 hectares)",
    "crop_yield": "Yield (tonnes/hectare)",
}


@st.cache_data(ttl=3600)
def _load():
    return load_master_long()


df = _load()
crops = crop_variants(df)

col1, col2, col3 = st.columns(3)
crop = col1.selectbox("Crop", crops, index=crops.index("Wheat") if "Wheat" in crops else 0)
variable = col2.selectbox("Measure", list(VARIABLE_LABELS), format_func=VARIABLE_LABELS.get)

years = sorted(
    df.loc[(df.source == "crop_production") & (df.commodity == crop), "date"].unique(),
    reverse=True,
)
year = col3.selectbox("Fiscal year ending", years, format_func=lambda d: str(d)[:10])

top_n = st.slider("Show top N districts", 5, 40, 15)
sub = crop_slice(df, crop, variable, date=year).head(top_n)

if sub.empty:
    st.warning("No data for this combination.")
    st.stop()

colors = [HIGHLIGHT_HUE if i == 0 else SEQUENTIAL_HUE for i in range(len(sub))]
fig = go.Figure(
    go.Bar(
        x=sub["value"],
        y=sub["region"],
        orientation="h",
        marker_color=colors,
        hovertemplate="%{y}<br>" + VARIABLE_LABELS[variable] + ": %{x:.2f}<extra></extra>",
    )
)
fig.update_layout(
    height=max(320, 24 * len(sub)),
    margin=dict(l=10, r=10, t=10, b=10),
    xaxis_title=VARIABLE_LABELS[variable],
    yaxis=dict(autorange="reversed"),
    plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Underlying data")
st.dataframe(
    sub[["region", "value", "unit", "is_imputed"]].reset_index(drop=True),
    use_container_width=True,
)
