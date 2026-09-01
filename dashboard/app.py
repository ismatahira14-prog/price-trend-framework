"""Pakistan Price Trend Framework - Home: CPI spike & factor-analysis dashboard.

Run locally:   streamlit run dashboard/app.py   (or: .\\run.cmd dashboard)
Deployed:      Streamlit Community Cloud, same entry point, reads the
               committed DuckDB snapshot at data/processed/pricelab.duckdb.

DATA-INTEGRITY NOTE: every number in "What caused the inflation spike?" is
REAL (the actual PBS CPI series for each of the 12 COICOP groups - see
`pricelab.dashboard.data.group_change_table`). "Relative magnitude" is a
computed rank among the 12 groups that period, NOT an official basket-weight
contribution percentage (this project's data has no official CPI weights).

The header banner embeds `dashboard/pbs_logo.jpg` (user-supplied).
"""

from __future__ import annotations

import base64
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
    group_change_table,
    load_master_long,
    selected_period_group_table,
    with_relative_magnitude,
    yearly_group_change_table,
)
from pricelab.dashboard.factors import (  # noqa: E402
    EVENTS,
    events_covering,
    global_events,
    load_inflation_bands,
)
from pricelab.dashboard.theme import (  # noqa: E402
    CPI_GROUP_ORDER,
    DECREASE_COLOR,
    HIGHLIGHT_HUE,
    INCREASE_COLOR,
    INFLATION_BAND_FILLS,
    MA_3M_COLOR,
    MA_6M_COLOR,
    MA_QUARTER_COLOR,
    PBS_GREEN,
    PBS_GREEN_DARK,
    SEQUENTIAL_HUE,
)

st.set_page_config(
    page_title="Pakistan Price Trend Framework",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ANCHOR_ID = "factor-analysis-anchor"
GROUPS_12 = CPI_GROUP_ORDER[1:]  # everything except "General" - the 12 COICOP groups
CORE_EVENTS = [e for e in EVENTS if e["core_chart_event"]]
SOURCE_NOTE = "Source: Pakistan Bureau of Statistics (PBS) Consumer Price Index · base 2015-16 = 100"


@st.cache_data(ttl=3600)
def _load() -> pd.DataFrame:
    return load_master_long()


@st.cache_data(ttl=3600)
def _change_table(_df: pd.DataFrame) -> pd.DataFrame:
    general = cpi_series(_df, ["General"])["General"]
    return cpi_change_table(general)


@st.cache_data(ttl=3600)
def _group_long(_df: pd.DataFrame) -> pd.DataFrame:
    return group_change_table(_df, GROUPS_12)


@st.cache_data(ttl=3600)
def _yearly_groups(_long: pd.DataFrame) -> pd.DataFrame:
    return yearly_group_change_table(_long)


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
    """Shade + label + name-only-hover the 4 core events (COVID-19, the 2022
    floods, the Russia-Ukraine war, the 2023 currency devaluation). The other
    dated events (see the Global Events table) are deliberately left off the
    charts to keep them readable. Returns the number of label rows used, so
    the caller can size the top margin.

    Labels are short, vertical, and anchored at each band's START rather than
    its center: horizontal text width doesn't scale with the time axis, so
    two short-duration events close in time (but not overlapping) could still
    collide as horizontal text. Row-packing (by real date overlap) is a
    second line of defense for the rare case two core events do overlap.
    """
    packed = _pack_event_rows(CORE_EVENTS)
    n_rows = max((row for _, row in packed), default=-1) + 1
    for e, row in packed:
        start, end = max(e["start"], x_min), min(e["end"], x_max)
        if start >= end:
            continue
        fig.add_vrect(
            x0=start, x1=end, fillcolor=e["color"], opacity=0.22, line_width=0, layer="below"
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
                hovertemplate=f"<b>{e.get('short_name', e['name'])}</b><extra></extra>",
            )
        )
    return n_rows


def _add_inflation_bands(fig: go.Figure, y_lo: float, y_hi: float) -> None:
    """Horizontal deflation/low/moderate/high/very-high bands (config-driven -
    see config/analysis.yaml: inflation_bands, NOT hard-coded here)."""
    for i, b in enumerate(load_inflation_bands()):
        lo = b["min"] if b["min"] is not None else y_lo - 100
        hi = b["max"] if b["max"] is not None else y_hi + 100
        fig.add_hrect(
            y0=lo, y1=hi,
            fillcolor=INFLATION_BAND_FILLS[i % len(INFLATION_BAND_FILLS)],
            line_width=0, layer="below",
        )
        vis_lo, vis_hi = max(lo, y_lo), min(hi, y_hi)
        if vis_lo < vis_hi:
            fig.add_annotation(
                x=1.0, xref="paper", xanchor="left",
                y=(vis_lo + vis_hi) / 2, yref="y",
                text=b["label"], showarrow=False,
                font=dict(size=9, color="#555"),
            )


def _add_click_catcher(fig: go.Figure, dates) -> None:
    """An invisible, full-height column per date on a hidden secondary axis.

    Values near zero render as a sliver a few pixels tall, nearly impossible
    to click precisely. This adds one transparent full-height bar per month,
    on its own overlaid y-axis with a FIXED [0,1] range, so clicking ANYWHERE
    in that month's column selects it - regardless of how small the real
    value is. hoverinfo="skip" keeps it out of tooltips, and hovermode="x"
    (set in _base_layout) keeps the real series' own tooltips working
    alongside it.

    IMPORTANT: never call ``fig.update_yaxes(...)`` (no selector) after this -
    it touches every y-axis including this hidden one, silently breaking the
    click target. Set the primary axis range via `_base_layout`'s `y_range`.
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


def _base_layout(
    fig: go.Figure,
    y_title: str,
    *,
    event_rows: int = 0,
    right_margin: int = 10,
    y_range: list[float] | None = None,
) -> None:
    # Vertical event labels need real headroom above the plot (their text runs
    # upward, not sideways) - 130px comfortably fits the longest short_name;
    # +20px per extra row for genuinely overlapping labeled events.
    top_margin = 130 + 20 * max(event_rows - 1, 0)
    yaxis_cfg = dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
    if y_range is not None:
        yaxis_cfg["range"] = y_range
    fig.update_layout(
        height=440 + top_margin - 130,
        margin=dict(l=10, r=right_margin, t=top_margin, b=10),
        yaxis_title=y_title,
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0),
        xaxis=dict(showgrid=False),
        yaxis=yaxis_cfg,
        clickmode="event+select",
        hovermode="x",
    )


# ------------------------------------------------------------------------- #
# Header (PBS-style banner with the real logo)
# ------------------------------------------------------------------------- #
_logo_path = Path(__file__).parent / "pbs_logo_trimmed.png"
_logo_html = (
    f'<img class="logo" src="data:image/png;base64,'
    f'{base64.b64encode(_logo_path.read_bytes()).decode()}"/>'
    if _logo_path.is_file()
    else '<div class="badge">PBS</div>'
)

st.markdown(
    f"""
    <style>
    .pbs-header {{
        background: linear-gradient(90deg, {PBS_GREEN_DARK}, {PBS_GREEN});
        color: white; padding: 14px 22px; border-radius: 8px;
        display: flex; align-items: center; gap: 16px; margin-bottom: 8px;
    }}
    .pbs-header .logo {{
        height: 96px; flex-shrink: 0;
    }}
    .pbs-header .badge {{
        background: white; color: {PBS_GREEN_DARK}; font-weight: 700;
        border-radius: 50%; width: 44px; height: 44px; flex-shrink: 0;
        display: flex; align-items: center; justify-content: center; font-size: 13px;
    }}
    .pbs-header h1 {{ font-size: 1.35rem; margin: 0; color: white; }}
    .pbs-header p {{ margin: 2px 0 0; font-size: 0.82rem; opacity: 0.92; }}
    </style>
    <div class="pbs-header">
        {_logo_html}
        <div>
            <h1>Price Trend Framework</h1>
            <p>Pakistan Consumer Price Index · Statistical Dashboard</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
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

group_long = _group_long(df)

st.session_state.setdefault("selected_period", ct.index[-1])
st.session_state.setdefault("trigger_scroll", False)

# ------------------------------------------------------------------- KPIs --
latest = ct.iloc[-1]
peak_yoy_date = ct["yoy_pct"].idxmax() if ct["yoy_pct"].notna().any() else None
peak_yoy_val = ct["yoy_pct"].max() if peak_yoy_date is not None else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latest General CPI", f"{latest['cpi']:.1f}", help="Base: 2015-16 = 100")
c2.metric(
    "Month-over-month", f"{latest['mom_pct']:+.2f}%" if pd.notna(latest["mom_pct"]) else "n/a"
)
c3.metric(
    "Year-over-year", f"{latest['yoy_pct']:+.2f}%" if pd.notna(latest["yoy_pct"]) else "n/a"
)
c4.metric(
    "Highest recorded inflation (YoY)",
    f"{peak_yoy_val:+.1f}%" if peak_yoy_val is not None else "n/a",
    help=f"Recorded {peak_yoy_date:%b %Y}" if peak_yoy_date is not None else None,
)
st.caption(SOURCE_NOTE + f" · {ct.index.min():%b %Y} – {ct.index.max():%b %Y}")

st.divider()

# ---------------------------------------------------------- main analysis --
x_min, x_max = ct.index.min(), ct.index.max()
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("📈 Index & moving averages")
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
    n_rows_l = _add_event_bands(fig, hover_y=ct["cpi"].max() * 1.03, x_min=x_min, x_max=x_max)
    _add_click_catcher(fig, ct.index)
    _base_layout(fig, "Index (2015-16 = 100)", event_rows=n_rows_l)
    ev_index = st.plotly_chart(
        fig, use_container_width=True, on_select="rerun", key="chart_index", selection_mode="points"
    )
    _register_click(ev_index, "chart_index", ct)

with col_right:
    st.subheader("Month-to-Month & Year-to-Year inflation")
    y_lo = min(ct["mom_pct"].min(skipna=True), ct["yoy_pct"].min(skipna=True))
    y_hi = max(ct["mom_pct"].max(skipna=True), ct["yoy_pct"].max(skipna=True))
    pad = (y_hi - y_lo) * 0.08 or 1.0
    y_lo, y_hi = y_lo - pad, y_hi + pad

    fig = go.Figure()
    _add_inflation_bands(fig, y_lo, y_hi)
    fig.add_hline(y=0, line_color="#333333", line_width=1.5)  # deflation vs inflation, unmissable
    fig.add_trace(
        go.Scatter(
            x=ct.index, y=ct["mom_pct"], mode="lines", name="Month-over-month (%)",
            line=dict(color=SEQUENTIAL_HUE, width=2),
            hovertemplate="%{x|%b %Y}<br>MoM: %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ct.index, y=ct["yoy_pct"], mode="lines", name="Year-over-year (%)",
            line=dict(color=HIGHLIGHT_HUE, width=2.5),
            hovertemplate="%{x|%b %Y}<br>YoY: %{y:+.2f}%<extra></extra>",
        )
    )
    n_rows_r = _add_event_bands(fig, hover_y=y_hi * 0.92, x_min=x_min, x_max=x_max)
    _add_click_catcher(fig, ct.index)
    _base_layout(fig, "Change (%)", event_rows=n_rows_r, right_margin=95, y_range=[y_lo, y_hi])
    ev_combined = st.plotly_chart(
        fig, use_container_width=True, on_select="rerun", key="chart_combined", selection_mode="points"
    )
    _register_click(ev_combined, "chart_combined", ct)

_legend_chips = "".join(
    f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:16px;font-size:0.82rem;">'
    f'<span style="width:12px;height:12px;border-radius:3px;background:{e["color"]};'
    f'display:inline-block;"></span>{e.get("short_name", e["name"])}</span>'
    for e in CORE_EVENTS
)
st.markdown(
    f'<div style="margin:2px 0 10px;">{_legend_chips}</div>', unsafe_allow_html=True
)
st.caption("Click a point on either chart to see what caused that spike ↓")

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
m1.metric("General CPI", f"{row['cpi']:.1f}")
m2.metric("General MoM", f"{row['mom_pct']:+.2f}%" if pd.notna(row["mom_pct"]) else "n/a")
m3.metric("General YoY", f"{row['yoy_pct']:+.2f}%" if pd.notna(row["yoy_pct"]) else "n/a")
m4.metric("Event active", active_events[0]["name"] if active_events else "None on record")
if active_events:
    st.caption(
        "📌 " + " · ".join(e["name"] for e in active_events) + " (context, not a causal claim)"
    )

# ------------------------------------------------------- 12-group breakdown -
period_groups = selected_period_group_table(group_long, selected)

if not period_groups.empty:
    sorted_for_chart = period_groups.sort_values("mom_pct", ascending=True)
    fig = go.Figure(
        go.Bar(
            x=sorted_for_chart["mom_pct"],
            y=sorted_for_chart["group"],
            orientation="h",
            marker_color=[
                INCREASE_COLOR if v >= 0 else DECREASE_COLOR for v in sorted_for_chart["mom_pct"]
            ],
            text=[f"{v:+.1f}%" for v in sorted_for_chart["mom_pct"]],
            textposition="outside",
            hovertemplate="%{y}<br>MoM: %{x:+.2f}%<extra></extra>",
        )
    )
    fig.update_layout(
        height=360,
        margin=dict(l=10, r=40, t=10, b=10),
        xaxis_title="Month-over-month change that period (%)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=True, zerolinecolor="#999"),
    )
    st.plotly_chart(fig, use_container_width=True)

    display = period_groups[["group", "mom_pct", "yoy_pct", "relative_magnitude"]].rename(
        columns={
            "group": "Inflation Group",
            "mom_pct": "Month-to-Month Change (%)",
            "yoy_pct": "Year-to-Year Change (%)",
            "relative_magnitude": "Relative Magnitude",
        }
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(f"{SOURCE_NOTE}. Relative Magnitude = rank among the 12 groups that month, not an official weight.")
else:
    st.warning("No per-group data available for this period yet.")

st.divider()

# ------------------------------------------------------------- Table 1 ----
st.subheader("Month-by-Month Inflation Change & Contributing Factors")
st.caption("Rows for the selected month are highlighted.")

month_label = selected.strftime("%b %Y")
monthly_ranked = with_relative_magnitude(group_long.dropna(subset=["mom_pct"]), group_col="date")
monthly_ranked["Month"] = monthly_ranked["date"].dt.strftime("%b %Y")


def _highlight_month(row: pd.Series) -> list[str]:
    is_sel = row["Month"] == month_label
    return ["background-color: rgba(0,114,178,0.15)" if is_sel else "" for _ in row]


monthly_display = monthly_ranked[
    ["Month", "group", "mom_pct", "yoy_pct", "relative_magnitude"]
].rename(
    columns={
        "group": "Inflation Group",
        "mom_pct": "Month-to-Month Change (%)",
        "yoy_pct": "Year-to-Year Change (%)",
        "relative_magnitude": "Relative Magnitude",
    }
)
st.dataframe(
    monthly_display.style.apply(_highlight_month, axis=1),
    use_container_width=True,
    height=320,
)

# ------------------------------------------------------------- Table 2 ----
st.subheader("Year-by-Year Inflation Change & Contributing Factors")
st.caption("Calendar-year averages of the monthly series. Rows for the selected year are highlighted.")

yearly_ranked = _yearly_groups(group_long)
selected_year = selected.year


def _highlight_year(row: pd.Series) -> list[str]:
    is_sel = row["Year"] == selected_year
    return ["background-color: rgba(0,114,178,0.15)" if is_sel else "" for _ in row]


yearly_display = yearly_ranked[["year", "group", "mom_pct", "yoy_pct", "relative_magnitude"]].rename(
    columns={
        "year": "Year",
        "group": "Inflation Group",
        "mom_pct": "Avg Month-to-Month Change (%)",
        "yoy_pct": "Avg Year-to-Year Change (%)",
        "relative_magnitude": "Relative Magnitude",
    }
)
st.dataframe(
    yearly_display.style.apply(_highlight_year, axis=1),
    use_container_width=True,
    height=320,
)

st.caption(SOURCE_NOTE)
st.divider()

# ------------------------------------------------------------ Global Events -
st.subheader("Global Events")
st.caption(
    "Major globally-significant events with a plausible inflation channel. Temporal overlap is "
    "context, not proof of causation. Domestic events (2022 floods, 2023 currency devaluation) "
    "are shown on the charts above but excluded here - this table is global events only."
)

ge_rows = [
    {
        "Global Event": e["name"],
        "Start Date": e["start"].strftime("%b %Y"),
        "End Date": "Ongoing" if e.get("is_ongoing") else e["end"].strftime("%b %Y"),
        "Category": e["category"],
        "Main Channels": ", ".join(e["channels"]),
        "Potential Inflation Impact": e["description"],
        "Shown on chart": "Yes" if e["core_chart_event"] else "No",
    }
    for e in global_events()
]
st.dataframe(pd.DataFrame(ge_rows), use_container_width=True, hide_index=True)

with st.expander("Other pages & data coverage"):
    st.write(
        "**CPI Trends**, **Crop Production**, and **Data Explorer** are in the sidebar "
        "(collapsed by default - click the `>>` at the top-left to open it).\n\n"
        f"- **Sources:** {', '.join(sorted(df['source'].unique()))}\n"
        f"- **Date range:** {df['date'].min().date()} → {df['date'].max().date()}\n"
        f"- **Regions covered:** {df['region'].nunique()}"
    )
