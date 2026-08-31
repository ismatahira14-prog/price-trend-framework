"""Pakistan Price Trend Framework - Home: CPI spike & factor-analysis dashboard.

Run locally:   streamlit run dashboard/app.py   (or: .\\run.cmd dashboard)
Deployed:      Streamlit Community Cloud, same entry point, reads the
               committed DuckDB snapshot at data/processed/pricelab.duckdb.

Page flow (see README.md "Spike & factor analysis" for the full write-up):
  KPIs -> main CPI chart (Index / Monthly / Yearly change tabs, with event
  bands) -> click a point -> page scrolls to "What Caused the Inflation
  Spike?" -> factor-contribution chart + two tables, filtered to that period.

The contributing-factor numbers below the chart are PLACEHOLDER data - see
`pricelab.dashboard.factors` for exactly what's real (the events) vs mock
(the per-item contributions).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pricelab.dashboard.data import (  # noqa: E402
    SnapshotMissing,
    cpi_change_table,
    cpi_series,
    load_master_long,
)
from pricelab.dashboard.factors import (  # noqa: E402
    EVENTS,
    events_covering,
    generate_mock_monthly_factors,
    generate_mock_yearly_factors,
)
from pricelab.dashboard.theme import (  # noqa: E402
    DECREASE_COLOR,
    FACTOR_COLORS,
    INCREASE_COLOR,
    MA_3M_COLOR,
    MA_6M_COLOR,
    MA_QUARTER_COLOR,
    SEQUENTIAL_HUE,
)

st.set_page_config(page_title="Pakistan Price Trend Framework", page_icon="📈", layout="wide")

ANCHOR_ID = "factor-analysis-anchor"


@st.cache_data(ttl=3600)
def _load() -> pd.DataFrame:
    return load_master_long()


@st.cache_data(ttl=3600)
def _change_table(_df: pd.DataFrame) -> pd.DataFrame:
    general = cpi_series(_df, ["General"])["General"]
    return cpi_change_table(general)


@st.cache_data(ttl=3600)
def _monthly_factors(_ct: pd.DataFrame) -> pd.DataFrame:
    return generate_mock_monthly_factors(_ct)


@st.cache_data(ttl=3600)
def _yearly_factors(_ct: pd.DataFrame) -> pd.DataFrame:
    return generate_mock_yearly_factors(_ct)


def _register_click(event: dict | None, chart_key: str, ct: pd.DataFrame) -> None:
    """Update session_state.selected_period only on a genuinely NEW click."""
    points = ((event or {}).get("selection") or {}).get("points") or []
    if not points:
        return
    raw_x = points[0].get("x")
    seen = st.session_state.setdefault("_last_click_raw", {})
    if seen.get(chart_key) == raw_x:
        return  # same selection as last rerun - not a new click
    seen[chart_key] = raw_x
    try:
        clicked = pd.Timestamp(raw_x).replace(day=1)
    except (ValueError, TypeError):
        return
    if clicked not in ct.index:
        clicked = ct.index[ct.index.get_indexer([clicked], method="nearest")[0]]
    st.session_state["selected_period"] = clicked
    # Also push into the manual selectbox's own state (must happen BEFORE that
    # widget is instantiated below) - otherwise Streamlit keeps the selectbox's
    # last value and silently overwrites this click a few lines down.
    st.session_state["period_picker"] = clicked
    st.session_state["trigger_scroll"] = True


def _pack_event_rows(events: list[dict]) -> list[tuple[dict, int]]:
    """Greedy interval scheduling: only give two events the same label row if
    their date ranges don't overlap, so labels never collide."""
    row_end: list[pd.Timestamp] = []
    packed: list[tuple[dict, int]] = []
    for e in sorted(events, key=lambda e: e["start"]):
        row = next((r for r, end in enumerate(row_end) if end < e["start"]), None)
        if row is None:
            row = len(row_end)
            row_end.append(e["end"])
        else:
            row_end[row] = e["end"]
        packed.append((e, row))
    return packed


def _add_event_bands(fig: go.Figure, hover_y: float, x_min, x_max) -> int:
    """Returns the number of label rows used, so the caller can size the top margin.

    Labels are short (see EVENTS[i]["short_name"]), vertical, and anchored at
    each band's START rather than its center: horizontal text width doesn't
    scale with the time axis, so two short-duration events close together in
    time (but not overlapping) could still collide as horizontal text even
    though their date ranges don't overlap. Vertical text has almost no
    horizontal footprint, which is what actually fixes that; row-packing
    (by real date overlap) remains as a second line of defense for bands
    that genuinely do overlap.
    """
    packed = _pack_event_rows(EVENTS)
    n_rows = max((row for _, row in packed), default=-1) + 1
    for e, row in packed:
        start, end = max(e["start"], x_min), min(e["end"], x_max)
        if start >= end:
            continue
        fig.add_vrect(
            x0=start, x1=end, fillcolor=e["color"], opacity=0.10, line_width=0, layer="below"
        )
        fig.add_annotation(
            x=start,
            y=1.02 + 0.03 * row,
            yref="paper",
            text=e.get("short_name", e["name"]),
            showarrow=False,
            font=dict(size=9, color="#666"),
            textangle=-90,
            xanchor="left",
            yanchor="bottom",
        )
        fig.add_trace(
            go.Scatter(
                x=[start + (end - start) / 2],
                y=[hover_y],
                mode="markers",
                marker=dict(size=10, color=e["color"], opacity=0.01),
                showlegend=False,
                hoverinfo="skip",
                hovertemplate=f"<b>{e['name']}</b><br>{e['description']}<extra></extra>",
            )
        )
    return n_rows


def _add_click_catcher(fig: go.Figure, dates) -> None:
    """An invisible, full-height column per date on a hidden secondary axis.

    Bar charts near zero (small dips) render as a sliver a few pixels tall,
    which is nearly impossible to click precisely. This adds one transparent
    full-height bar per month, on its own overlaid y-axis, so clicking
    ANYWHERE in that month's column selects it - regardless of how tall the
    real (visible) bar is. hoverinfo="skip" keeps it out of tooltips, and
    hovermode="x" (set in _base_layout) keeps the real series' own tooltips
    working normally alongside it.
    """
    fig.add_trace(
        go.Bar(
            x=dates,
            y=[1] * len(dates),
            yaxis="y2",
            marker_color="rgba(0,0,0,0)",
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        yaxis2=dict(overlaying="y", range=[0, 1], visible=False, fixedrange=True),
        barmode="overlay",
    )


def _base_layout(fig: go.Figure, y_title: str, *, event_rows: int = 0) -> None:
    # Vertical event labels need real headroom above the plot (their text runs
    # upward, not sideways) - 130px comfortably fits the longest short_name
    # ("Currency Devaluation"); +20px per extra row for genuinely overlapping events.
    top_margin = 130 + 20 * max(event_rows - 1, 0)
    fig.update_layout(
        height=440 + top_margin - 130,
        margin=dict(l=10, r=10, t=top_margin, b=10),
        yaxis_title=y_title,
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
        clickmode="event+select",
        hovermode="x",
    )


# ------------------------------------------------------------------------- #
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

ct = _change_table(df)
if ct.empty:
    st.warning("No CPI data available yet.")
    st.stop()

st.session_state.setdefault("selected_period", ct.index[-1])
st.session_state.setdefault("trigger_scroll", False)

# ------------------------------------------------------------------- KPIs --
latest = ct.iloc[-1]
peak_yoy_date = ct["yoy_pct"].idxmax() if ct["yoy_pct"].notna().any() else None
peak_yoy_val = ct["yoy_pct"].max() if peak_yoy_date is not None else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latest General CPI", f"{latest['cpi']:.1f}", help="Base: 2015-16 = 100")
c2.metric(
    "Month-over-month",
    f"{latest['mom_pct']:+.2f}%" if pd.notna(latest["mom_pct"]) else "n/a",
)
c3.metric(
    "Year-over-year",
    f"{latest['yoy_pct']:+.2f}%" if pd.notna(latest["yoy_pct"]) else "n/a",
)
c4.metric(
    "Highest recorded inflation (YoY)",
    f"{peak_yoy_val:+.1f}%" if peak_yoy_val is not None else "n/a",
    help=f"Recorded {peak_yoy_date:%b %Y}" if peak_yoy_date is not None else None,
)

st.divider()

# ---------------------------------------------------------- main analysis --
st.subheader("General CPI over time")
st.caption(
    "Click any point on a chart below to jump to its factor analysis further down the page. "
    "Shaded bands mark major events - hover a band for a short explanation."
)

x_min, x_max = ct.index.min(), ct.index.max()
tab_index, tab_mom, tab_yoy = st.tabs(
    ["📈 Index & moving averages", "📊 Month-over-month change", "📆 Year-over-year change"]
)

with tab_index:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ct.index, y=ct["cpi"], mode="lines", name="CPI (General)",
            line=dict(color=SEQUENTIAL_HUE, width=2.5),
            hovertemplate="%{x|%b %Y}<br>CPI: %{y:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ct.index, y=ct["ma_3m"], mode="lines", name="3-month moving avg",
            line=dict(color=MA_3M_COLOR, width=1.5, dash="dot"),
            hovertemplate="%{x|%b %Y}<br>3M avg: %{y:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ct.index, y=ct["ma_6m"], mode="lines", name="6-month moving avg",
            line=dict(color=MA_6M_COLOR, width=1.5, dash="dash"),
            hovertemplate="%{x|%b %Y}<br>6M avg: %{y:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ct.index, y=ct["ma_quarter"], mode="lines", name="Calendar-quarter avg",
            line=dict(color=MA_QUARTER_COLOR, width=1.5, shape="hv"),
            hovertemplate="%{x|%b %Y}<br>Quarter avg: %{y:.1f}<extra></extra>",
        )
    )
    n_rows = _add_event_bands(fig, hover_y=ct["cpi"].max() * 1.03, x_min=x_min, x_max=x_max)
    _add_click_catcher(fig, ct.index)  # lines are thin - make the whole column clickable
    _base_layout(fig, "Index (2015-16 = 100)", event_rows=n_rows)
    ev_index = st.plotly_chart(
        fig, use_container_width=True, on_select="rerun", key="chart_index", selection_mode="points"
    )
    _register_click(ev_index, "chart_index", ct)

with tab_mom:
    colors = [INCREASE_COLOR if v >= 0 else DECREASE_COLOR for v in ct["mom_pct"].fillna(0)]
    fig = go.Figure(
        go.Bar(
            x=ct.index, y=ct["mom_pct"], marker_color=colors, name="MoM % change",
            hovertemplate="%{x|%b %Y}<br>MoM: %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color="rgba(128,128,128,0.5)", line_width=1)
    n_rows = _add_event_bands(
        fig,
        hover_y=(ct["mom_pct"].max(skipna=True) or 1) * 1.15,
        x_min=x_min,
        x_max=x_max,
    )
    _add_click_catcher(fig, ct.index)  # small dips near 0% are a sliver-thin, hard-to-click bar
    _base_layout(fig, "Month-over-month change (%)", event_rows=n_rows)
    ev_mom = st.plotly_chart(
        fig, use_container_width=True, on_select="rerun", key="chart_mom", selection_mode="points"
    )
    _register_click(ev_mom, "chart_mom", ct)
    st.caption("🔴 Vermillion = price level rose that month · 🔵 Blue = price level fell.")

with tab_yoy:
    colors = [INCREASE_COLOR if v >= 0 else DECREASE_COLOR for v in ct["yoy_pct"].fillna(0)]
    fig = go.Figure(
        go.Bar(
            x=ct.index, y=ct["yoy_pct"], marker_color=colors, name="YoY % change",
            hovertemplate="%{x|%b %Y}<br>YoY: %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color="rgba(128,128,128,0.5)", line_width=1)
    n_rows = _add_event_bands(
        fig,
        hover_y=(ct["yoy_pct"].max(skipna=True) or 1) * 1.1,
        x_min=x_min,
        x_max=x_max,
    )
    _add_click_catcher(fig, ct.index)  # small dips near 0% are a sliver-thin, hard-to-click bar
    _base_layout(fig, "Year-over-year change (%)", event_rows=n_rows)
    ev_yoy = st.plotly_chart(
        fig, use_container_width=True, on_select="rerun", key="chart_yoy", selection_mode="points"
    )
    _register_click(ev_yoy, "chart_yoy", ct)
    st.caption("Compares each month's CPI to the same month one year earlier.")

with st.expander("Major events shown on these charts"):
    for e in EVENTS:
        st.markdown(
            f"**{e['name']}** &nbsp; ({e['start']:%b %Y} – {e['end']:%b %Y})  \n{e['description']}"
        )

st.divider()

# ---------------------------------------------------------- other pages ---
st.subheader("Other analytics")
st.info(
    "**CPI Trends** (sidebar) compares any set of price groups side by side. "
    "**Crop Production** (sidebar) shows district-level area/production/yield. "
    "**Data Explorer** (sidebar) lets you filter and download the raw table."
)

st.divider()

# -------------------------------------------------- factor analysis anchor -
st.markdown(f'<div id="{ANCHOR_ID}"></div>', unsafe_allow_html=True)
if st.session_state.get("trigger_scroll"):
    components.html(
        f"""
        <script>
            setTimeout(function() {{
                var doc = window.parent.document;
                var el = doc.getElementById('{ANCHOR_ID}');
                if (el) {{ el.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}
            }}, 150);
        </script>
        """,
        height=1,
    )
    st.session_state["trigger_scroll"] = False

st.subheader("🔍 What caused the inflation spike?")

selected = st.session_state["selected_period"]
options = list(ct.index[::-1])
picked = st.selectbox(
    "Selected period (click a chart above, or pick one here)",
    options=options,
    index=options.index(selected) if selected in options else 0,
    format_func=lambda d: d.strftime("%B %Y"),
    key="period_picker",
)
if picked != selected:
    st.session_state["selected_period"] = picked
    selected = picked

row = ct.loc[selected]
active_events = events_covering(selected)

st.markdown(f"**Selected period: {selected:%B %Y}**")
m1, m2, m3, m4 = st.columns(4)
m1.metric("CPI", f"{row['cpi']:.1f}")
m2.metric("MoM change", f"{row['mom_pct']:+.2f}%" if pd.notna(row["mom_pct"]) else "n/a")
m3.metric("YoY change", f"{row['yoy_pct']:+.2f}%" if pd.notna(row["yoy_pct"]) else "n/a")
m4.metric("Major event", active_events[0]["name"] if active_events else "None on record")
if active_events:
    for e in active_events:
        st.caption(f"📌 **{e['name']}**: {e['description']}")

st.caption(
    "🧪 The contributing-factor breakdown below is **placeholder/demo data** "
    "(see `pricelab.dashboard.factors`) until real per-item weighted CPI "
    "contributions are ingested. The interaction (click → scroll → filter) is fully functional."
)

# ------------------------------------------------------- factor breakdown --
monthly_factors = _monthly_factors(ct)
month_label = selected.strftime("%b %Y")
month_rows = monthly_factors[monthly_factors["month"] == month_label].sort_values(
    "contribution_pct", ascending=True
)

if not month_rows.empty:
    fig = go.Figure(
        go.Bar(
            x=month_rows["contribution_pct"],
            y=month_rows["factor"],
            orientation="h",
            marker_color=[FACTOR_COLORS.get(f, "#888") for f in month_rows["factor"]],
            text=[f"{v:.0f}%" for v in month_rows["contribution_pct"]],
            textposition="outside",
            hovertemplate="%{y}<br>Contribution: %{x:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=30, t=10, b=10),
        xaxis_title="Contribution to that month's CPI change (%, demo data)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
    )
    st.plotly_chart(fig, use_container_width=True)

    badges = "  ".join(
        f":{'red' if r.impact == 'High' else 'orange' if r.impact == 'Medium' else 'gray'}"
        f"[{r.factor}: {r.impact}]"
        for r in month_rows.sort_values("contribution_pct", ascending=False).itertuples()
    )
    st.markdown(badges)

st.divider()

# ------------------------------------------------------------- Table 1 ----
st.subheader("Month-by-Month Inflation Change & Contributing Factors")
st.caption("🧪 Demo data. Rows for the selected month are highlighted.")


def _highlight_month(row: pd.Series) -> list[str]:
    is_sel = row["Month"] == month_label
    return ["background-color: rgba(0,114,178,0.15)" if is_sel else "" for _ in row]


monthly_display = monthly_factors[
    ["month", "cpi_change_pct", "factor", "item_change_pct", "contribution_pct", "impact"]
].rename(
    columns={
        "month": "Month",
        "cpi_change_pct": "CPI Change (%)",
        "factor": "Factor / Item",
        "item_change_pct": "Item Price Change (%)",
        "contribution_pct": "Contribution (%)",
        "impact": "Impact",
    }
)
st.dataframe(
    monthly_display.style.apply(_highlight_month, axis=1),
    use_container_width=True,
    height=320,
)

# ------------------------------------------------------------- Table 2 ----
st.subheader("Year-by-Year Inflation Change & Contributing Factors")
st.caption("🧪 Demo data. Rows for the selected year are highlighted.")

yearly_factors = _yearly_factors(ct)
selected_year = selected.year


def _highlight_year(row: pd.Series) -> list[str]:
    is_sel = row["Year"] == selected_year
    return ["background-color: rgba(0,114,178,0.15)" if is_sel else "" for _ in row]


yearly_display = yearly_factors[
    ["year", "cpi_change_pct", "factor", "item_change_pct", "contribution_pct", "impact"]
].rename(
    columns={
        "year": "Year",
        "cpi_change_pct": "CPI Change (%)",
        "factor": "Factor / Item",
        "item_change_pct": "Item Price Change (%)",
        "contribution_pct": "Contribution (%)",
        "impact": "Impact",
    }
)
st.dataframe(
    yearly_display.style.apply(_highlight_year, axis=1),
    use_container_width=True,
    height=320,
)

with st.expander("Data coverage"):
    st.write(
        f"- **Sources:** {', '.join(sorted(df['source'].unique()))}\n"
        f"- **Variables:** {', '.join(sorted(df['variable'].unique()))}\n"
        f"- **Date range:** {df['date'].min().date()} → {df['date'].max().date()}\n"
        f"- **Regions covered:** {df['region'].nunique()}\n\n"
        "Retail commodity prices, weather, trade, fertilizer/diesel/electricity "
        "prices, and wages are not loaded yet - once a per-item, weighted CPI "
        "contribution source is added, it replaces the demo data above with no "
        "UI changes needed."
    )
