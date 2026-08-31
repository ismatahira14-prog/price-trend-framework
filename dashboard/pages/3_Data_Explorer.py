"""Data Explorer page - filter and download the raw tidy table."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pricelab.dashboard.data import load_master_long  # noqa: E402

st.set_page_config(page_title="Data Explorer", page_icon="🔎", layout="wide")
st.title("Data Explorer")
st.caption("Browse master_long directly - the same table as data/processed/master_long.csv.")


@st.cache_data(ttl=3600)
def _load():
    return load_master_long()


df = _load()

c1, c2, c3, c4 = st.columns(4)
sources = c1.multiselect("Source", sorted(df["source"].unique()))
variables = c2.multiselect("Variable", sorted(df["variable"].unique()))
levels = c3.multiselect("Region level", sorted(df["region_level"].unique()))
region_query = c4.text_input("Region contains")

view = df
if sources:
    view = view[view["source"].isin(sources)]
if variables:
    view = view[view["variable"].isin(variables)]
if levels:
    view = view[view["region_level"].isin(levels)]
if region_query:
    view = view[view["region"].str.contains(region_query, case=False, na=False)]

st.caption(f"{len(view):,} of {len(df):,} rows")
st.dataframe(view.sort_values("date"), use_container_width=True, height=520)

st.download_button(
    "Download filtered rows as CSV",
    data=view.to_csv(index=False).encode("utf-8"),
    file_name="master_long_filtered.csv",
    mime="text/csv",
)
