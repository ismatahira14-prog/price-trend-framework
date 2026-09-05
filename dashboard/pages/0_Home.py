"""Pakistan Price Trend Framework - Home page: CPI index & change dashboard.

Run locally:   streamlit run dashboard/app.py   (or: .\\run.cmd dashboard)
Deployed:      Streamlit Community Cloud, same entry point, reads the
               committed DuckDB snapshot at data/processed/pricelab.duckdb.

This file is one page of the app, registered (with the other pages under
`dashboard/pages/`) via `st.navigation()` in the actual entry point,
`dashboard/app.py` - that's the thin router that owns `st.set_page_config()`
and the top navigation bar; this file is just this one page's content (the
"default" page, i.e. what a fresh visit lands on) and imports/paths here are
one level deeper (`dashboard/pages/`) than `dashboard/`'s own files because
of that.

DATA-INTEGRITY NOTE: every number in "What caused the inflation spike?" and
the Month-by-Month/Year-by-Year archive tables is REAL (the actual PBS CPI
series for each of the 12 COICOP groups - see
`pricelab.dashboard.data.group_change_table`). "Relative magnitude" is a
computed rank among the 12 groups that period, NOT an official basket-weight
contribution percentage (this project's data has no official CPI weights).

CHARTING NOTE: the main Inflation Index & Change chart is Highcharts (full-
width, drag-to-pan, 1x/2x/5x/10x zoom), embedded via a small hand-written
custom Streamlit component (`hc_main_chart`, see `dashboard/components/
hc_main_chart/`) rather than `st.components.v1.html` - unlike that, a real
component can send a value back to Python (`Streamlit.setComponentValue`),
which is what lets clicking a point still jump to "What caused the inflation
spike?" with that month selected, same as the old Plotly chart's `on_select`
did. No build step/npm/React - the Streamlit Components JS protocol is just
a few `postMessage` calls, small enough to hand-write directly (a real page
navigation was tried first and doesn't work: Streamlit's `components.html`
iframe sandbox has no `allow-top-navigation`, confirmed live). The period
picker (a plain selectbox) still works independently too. The 12-group
breakdown is now a pair of Highcharts bar charts (MoM and YoY, side by
side, sharing a Percentage/Absolute Value toggle - see
`_highcharts_group_bars`) rather than one Plotly bar chart. The separate
"Month-to-Month vs Year-to-Year comparison" section (two Highcharts Stock
line charts with their own range selector/navigator) has been removed.

The header banner embeds `dashboard/pbs_logo.jpg` (user-supplied).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# This file lives in dashboard/pages/, one level deeper than the assets/
# logo/generated-component paths below actually are (dashboard/) - every
# asset path in this file is built off this, not a bare Path(__file__).parent.
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent

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
    global_events,
    load_inflation_bands,
)
from pricelab.dashboard.hc_main_chart import hc_main_chart  # noqa: E402
from pricelab.dashboard.theme import (  # noqa: E402
    CPI_GROUP_ORDER,
    DECREASE_COLOR,
    HIGHLIGHT_HUE,
    INCREASE_COLOR,
    INFLATION_BAND_FILLS,
    MA_QUARTER_COLOR,
    PBS_GREEN,
    PBS_GREEN_DARK,
    SEQUENTIAL_HUE,
)

GROUPS_12 = CPI_GROUP_ORDER[1:]  # everything except "General" - the 12 COICOP groups
CORE_EVENTS = [e for e in EVENTS if e["core_chart_event"]]
SOURCE_NOTE = "Source: Pakistan Bureau of Statistics (PBS) Consumer Price Index · base 2015-16 = 100"
ANCHOR_ID = "spike-section-anchor"  # scroll target for the main chart's click-to-navigate

# Highcharts's default axis-label color is a light theme-neutral gray, tuned
# for a plain white card - against this page's chart cards it reads as
# washed-out/blurry. Every axis on every Highcharts chart on this page uses
# these two styles explicitly instead of the library default.
AXIS_LABEL_STYLE = {"color": "#333333", "fontSize": "11px"}
AXIS_TITLE_STYLE = {"color": "#222222", "fontSize": "12px", "fontWeight": "600"}


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


def _event_plotbands(x_min: pd.Timestamp, x_max: pd.Timestamp) -> list[dict]:
    """Highcharts xAxis.plotBands for the 4 core events (COVID-19, the 2022
    floods, the Russia-Ukraine war, the 2023 currency devaluation) - the
    shaded regions only. The other dated events (see the Global Events
    table) are deliberately left off the chart to keep it readable.

    No `label` here on purpose - see the history below. The NAMES are
    rendered as a plain HTML/CSS overlay instead (see `_event_label_data`
    and the JS in `_highcharts_main_chart`).

    Why not Highcharts's own plotBand `label` option (several attempts,
    all verified live in a real browser and all with a genuine problem):
    - A rotated (`rotation: -90`) label is positioned CENTERED on its pivot
      and extends *symmetrically* in both directions by its own rendered
      length - a single shared `y` offset is only ever correct for one
      specific text length; short labels look fine, long ones ("Russia-
      Ukraine War", "Currency Devaluation") dip into the plot below or get
      clipped above, depending which way the offset was tuned.
    - Per-label sizing (offsetting `y` by each label's own estimated
      length) fixed that in principle, but the actual relationship between
      Highcharts's rotated-label geometry and its真 rendered on-screen
      position didn't match the documented pivot-plus-half-width model
      closely enough to calibrate reliably - an attempt at a generous
      empirical correction overshot and made `chart.marginTop` so large the
      plot area collapsed to nothing.
    - `useHTML` (for a background box, needed since these can land over the
      CPI/MoM/YoY lines) combined with `rotation` made Highcharts constrain
      the label to the band's own on-screen pixel width, silently
      truncating short-duration bands ("Pakistan Floods" -> "Pa...").
    - Horizontal placement is time-based by default (each band's own
      position on the axis), which shrinks - and can overlap - as the
      viewport narrows; two events close in time (2022 floods, Russia-
      Ukraine war) need a viewport-independent fixed-pixel separation, which
      a Highcharts-native label option doesn't provide on its own.

    A plain HTML overlay sidesteps all four: real `getBoundingClientRect()`
    collision detection (not estimated text-pixel-width math) and CSS
    `writing-mode: vertical-rl` (properly laid-out vertical text, no
    rotation-pivot arithmetic) are both dramatically more robust than
    fighting Highcharts's own rotated SVG label positioning.
    """
    bands = []
    for e in CORE_EVENTS:
        start, end = max(e["start"], x_min), min(e["end"], x_max)
        if start >= end:
            continue
        bands.append(
            {
                "from": int(start.timestamp() * 1000),
                "to": int(end.timestamp() * 1000),
                "color": e["color"] + "38",  # ~22% alpha, matches the old Plotly opacity
            }
        )
    return bands


def _event_label_data(x_min: pd.Timestamp, x_max: pd.Timestamp) -> list[dict]:
    """[{x, text, title}, ...] for the 4 core events - plain data (not a
    Highcharts option) consumed by the JS overlay in `_highcharts_main_chart`
    that draws their names above the chart. `x` is each band's START date
    (not center) in epoch ms, matching where `_event_plotbands` starts
    shading."""
    out = []
    for e in CORE_EVENTS:
        start, end = max(e["start"], x_min), min(e["end"], x_max)
        if start >= end:
            continue
        out.append(
            {
                "x": int(start.timestamp() * 1000),
                "text": e.get("short_name", e["name"]),
                "title": e["description"],
            }
        )
    return out


def _severity_plotbands(y_lo: float, y_hi: float) -> list[dict]:
    """Highcharts yAxis.plotBands for the deflation/low/moderate/high/very-high
    tiers (config-driven - see config/analysis.yaml: inflation_bands, NOT
    hard-coded here). Unbounded ends extend +-1000 to bleed past the visible
    range instead of leaving a gap at the axis edge.

    `useHTML` gives each label a light background so it stays legible
    wherever it lands - including directly on top of the CPI/MoM/YoY lines,
    which a plain-text label (no backing box) does not survive against a
    busy chart.
    """
    bands = []
    for i, b in enumerate(load_inflation_bands()):
        lo = b["min"] if b["min"] is not None else y_lo - 1000
        hi = b["max"] if b["max"] is not None else y_hi + 1000
        bands.append(
            {
                "from": lo,
                "to": hi,
                "color": INFLATION_BAND_FILLS[i % len(INFLATION_BAND_FILLS)],
                "label": {
                    "useHTML": True,
                    "text": (
                        f'<span style="font-size:9px; line-height:9px; '
                        f'background:rgba(255,255,255,0.85); color:#333; '
                        f'font-weight:600; padding:1px 4px; border-radius:3px; '
                        f'white-space:nowrap;">{b["label"]}</span>'
                    ),
                    "align": "right",
                    "x": -6,
                },
            }
        )
    return bands


@st.cache_data
def _highstock_js() -> str:
    """Highcharts Stock, bundled locally (dashboard/assets/highstock.js) rather
    than loaded from code.highcharts.com at runtime. Verified live that a
    CDN <script src> silently fails to render in some sandboxed/restricted
    network environments - inlining the actual JS removes that dependency
    entirely, for every viewer, not just the ones this was tested in.

    Licensing note: Highcharts is free for non-commercial/personal/student use;
    a commercial license is required for commercial deployment - see
    https://www.highcharts.com/license.
    """
    return (_DASHBOARD_DIR / "assets" / "highstock.js").read_text(encoding="utf-8")


def _group_bar_points(values: pd.Series) -> list[dict | None]:
    """One Highcharts bar-chart point per value: color by sign (matching
    the increase/decrease pair used everywhere else on this page) and a
    pre-formatted `custom.label` string (e.g. "+3.56%") for the data label
    and tooltip - `{point.y:+.2f}` isn't a token Highcharts's own format-
    string mini-language supports (no forced leading "+"), so the exact
    "+X.XX" look this page already uses elsewhere is precomputed in Python
    instead and read back via the `point.custom` namespace Highcharts
    reserves for exactly this.
    """
    points = []
    for v in values:
        if pd.isna(v):
            points.append(None)  # renders as a gap, not a fabricated zero
            continue
        points.append(
            {
                "y": round(float(v), 2),
                "color": INCREASE_COLOR if v >= 0 else DECREASE_COLOR,
                "custom": {"label": f"{v:+.2f}"},
            }
        )
    return points


def _highcharts_group_bars(
    left_id: str,
    right_id: str,
    *,
    categories: list[str],
    left_pct: pd.Series,
    left_abs: pd.Series,
    left_title: str,
    right_pct: pd.Series,
    right_abs: pd.Series,
    right_title: str,
    period_label: str,
    height: int = 400,
) -> None:
    """Two side-by-side Highcharts horizontal bar charts (MoM and YoY
    inflation by group), sharing one Percentage/Absolute Value toggle.

    Both series' Percentage AND Absolute Value data are computed in Python
    upfront and embedded together; the toggle buttons are plain HTML/JS
    (matching the main chart's 1x/2x/5x/10x zoom buttons) that call
    `series.setData(..., true)` on the ALREADY-LIVE chart instances - a
    smooth Highcharts-native animated transition between the two datasets,
    per the spec ("smooth and visually polished"), which a Streamlit-side
    toggle can't give: that would tear down and recreate this whole
    `components.html` iframe on every click (a full reload has no
    continuity for an in-place animation), so the toggle has to live
    inside the same iframe as the charts it controls - and both charts
    have to be created in that ONE iframe, since separate `components.html`
    calls are separate, cross-origin-isolated iframes that can't reach into
    each other's `window` to update one another's chart instance anyway.

    `categories` is a single shared list, in a single order, used verbatim
    for both charts - see the call site for why (same source order, not
    independently re-sorted).

    `left_title`/`right_title` and `period_label` render as each chart's own
    native Highcharts `title`/`subtitle`, not a plain HTML heading sitting
    next to the chart - deliberately, so both travel WITH the chart if a
    viewer downloads/exports it on its own (e.g. right-click -> save image,
    or a future Highcharts "exporting" button): text outside the chart's own
    SVG isn't part of that image, so a period shown only via the page's
    shared "Selected period" selectbox above both charts would silently be
    lost from either one's export.
    """
    left_pct_pts = _group_bar_points(left_pct)
    left_abs_pts = _group_bar_points(left_abs)
    right_pct_pts = _group_bar_points(right_pct)
    right_abs_pts = _group_bar_points(right_abs)
    subtitle_text = f"Selected period: {period_label}"

    def _bar_chart_options(chart_id: str, name: str, data: list, y_title: str, title_text: str) -> dict:
        return {
            "chart": {
                "type": "bar",
                "backgroundColor": "transparent",
                "style": {"fontFamily": "inherit"},
                "height": height,
            },
            "title": {"text": title_text, "align": "left", "style": {"color": "#222222", "fontSize": "15px", "fontWeight": "700"}},
            "subtitle": {"text": subtitle_text, "align": "left", "style": {"color": "#666666", "fontSize": "11px"}},
            "xAxis": {
                "categories": categories,
                "labels": {"style": AXIS_LABEL_STYLE},
                "lineColor": "rgba(128,128,128,0.3)",
            },
            "yAxis": {
                "title": {"text": y_title, "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE},
                "gridLineColor": "rgba(128,128,128,0.15)",
                "plotLines": [{"value": 0, "color": "#999999", "width": 1, "zIndex": 3}],
            },
            "legend": {"enabled": False},
            "credits": {"enabled": False},
            "plotOptions": {
                "bar": {
                    "dataLabels": {
                        "enabled": True,
                        "format": "{point.custom.label}",
                        "style": {"fontSize": "11px", "fontWeight": "600", "color": "#333333", "textOutline": "none"},
                    },
                    "animation": {"duration": 500},
                }
            },
            "tooltip": {
                "headerFormat": "",
                "pointFormat": f"<b>{{point.category}}</b><br/>{name}: " + "{point.custom.label}",
            },
            "series": [{"name": name, "data": data}],
        }

    left_config = _bar_chart_options(left_id, "MoM", left_pct_pts, "Month-to-month change (%)", left_title)
    right_config = _bar_chart_options(right_id, "YoY", right_pct_pts, "Year-to-year change (%)", right_title)

    components.html(
        f"""
        <div style="margin-bottom:10px; display:flex; gap:8px;">
            <button onclick="__setGroupBarMode('pct')" id="{left_id}-btn-pct" class="hc-zoom-btn hc-mode-btn hc-mode-btn-active">Percentage</button>
            <button onclick="__setGroupBarMode('abs')" id="{left_id}-btn-abs" class="hc-zoom-btn hc-mode-btn">Absolute Value</button>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:20px;">
            <div style="flex:1 1 380px; min-width:280px;">
                <div id="{left_id}" style="width:100%;"></div>
            </div>
            <div style="flex:1 1 380px; min-width:280px;">
                <div id="{right_id}" style="width:100%;"></div>
            </div>
        </div>
        <style>
            .hc-zoom-btn {{
                font: 12px -apple-system, sans-serif; padding: 4px 12px; margin-right: 4px;
                border: 1px solid #d0d0d0; border-radius: 4px; background: #fafafa;
                color: #333; cursor: pointer;
            }}
            .hc-zoom-btn:hover {{ background: #eef2f6; border-color: #a8c5e0; }}
            .hc-mode-btn-active {{ background: #e3edf7; border-color: #7fa8cf; font-weight: 600; color: #1a3a5c; }}
        </style>
        <script>{_highstock_js()}</script>
        <script>
            var __leftPct = {json.dumps(left_pct_pts)};
            var __leftAbs = {json.dumps(left_abs_pts)};
            var __rightPct = {json.dumps(right_pct_pts)};
            var __rightAbs = {json.dumps(right_abs_pts)};

            var __leftChart = Highcharts.chart('{left_id}', {json.dumps(left_config)});
            var __rightChart = Highcharts.chart('{right_id}', {json.dumps(right_config)});

            var __groupBarMode = 'pct';
            function __setGroupBarMode(mode) {{
                if (mode === __groupBarMode) return;
                __groupBarMode = mode;
                var pct = mode === 'pct';
                __leftChart.series[0].setData(pct ? __leftPct : __leftAbs, true, {{duration: 500}});
                __rightChart.series[0].setData(pct ? __rightPct : __rightAbs, true, {{duration: 500}});
                __leftChart.yAxis[0].setTitle({{text: pct ? 'Month-to-month change (%)' : 'Month-to-month change (index points)'}});
                __rightChart.yAxis[0].setTitle({{text: pct ? 'Year-to-year change (%)' : 'Year-to-year change (index points)'}});
                document.getElementById('{left_id}-btn-pct').classList.toggle('hc-mode-btn-active', pct);
                document.getElementById('{left_id}-btn-abs').classList.toggle('hc-mode-btn-active', !pct);
                setTimeout(__resizeGroupBarsFrame, 550);  // after the 500ms setData animation
            }}

            // The fixed `height=` components.html is given below (sized for
            // the side-by-side layout) isn't enough once flex-wrap stacks
            // the two charts on a narrow viewport - confirmed live, the
            // second (Year-to-Year) chart was silently clipped off entirely,
            // not just visually cramped. `window.frameElement` reaches the
            // actual <iframe> element in the parent document (available
            // here since this iframe carries `allow-same-origin`) - resize
            // it to the real rendered content height instead of trusting
            // the static guess, on load and again on viewport resize.
            //
            // Resizing the <iframe> alone isn't enough either - confirmed
            // live: Streamlit wraps it in its own div (`data-testid=
            // "stElementContainer"`) with a fixed CSS height matching the
            // ORIGINAL static guess. That div's overflow is "visible" (not
            // clipped), but a fixed-height box in normal document flow
            // doesn't grow to fit an overflowing child - later elements on
            // the page (the archive table right below this) still get
            // positioned as if this block were only its original height,
            // so the grown iframe would paint underneath/behind them
            // instead of pushing them down. Resize that wrapper too.
            function __resizeGroupBarsFrame() {{
                if (!window.frameElement) return;
                var h = document.documentElement.scrollHeight;
                window.frameElement.style.height = h + 'px';
                var wrapper = window.frameElement.parentElement;
                if (wrapper) {{ wrapper.style.height = h + 'px'; }}
            }}
            __resizeGroupBarsFrame();
            window.addEventListener('resize', function() {{ setTimeout(__resizeGroupBarsFrame, 250); }});
        </script>
        """,
        height=height + 60,
    )


# `hc_main_chart` (the custom component that lets clicking the main chart
# feed a value back into Python) lives in pricelab.dashboard.hc_main_chart,
# not here - see that module's own docstring for why: it needs to be a
# normally-`import`ed module, which a page `exec`'d by st.navigation()'s
# pg.run() is not, and components.declare_component() breaks without one.


# ------------------------------------------------------------------------- #
# Header (PBS-style banner with the real logo)
# ------------------------------------------------------------------------- #
_logo_path = _DASHBOARD_DIR / "pbs_logo_trimmed.png"
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
        height: 84px; flex-shrink: 0;
        background: white; border-radius: 8px; padding: 8px 14px;
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

# ------------------------------------------------------------------- KPIs --
latest = ct.iloc[-1]
peak_yoy_date = ct["yoy_pct"].idxmax() if ct["yoy_pct"].notna().any() else None
peak_yoy_val = ct["yoy_pct"].max() if peak_yoy_date is not None else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Latest General CPI", f"{latest['cpi']:.2f}", help="Base: 2015-16 = 100")
c2.metric(
    "Month-over-month", f"{latest['mom_pct']:+.2f}%" if pd.notna(latest["mom_pct"]) else "n/a"
)
c3.metric(
    "Year-over-year", f"{latest['yoy_pct']:+.2f}%" if pd.notna(latest["yoy_pct"]) else "n/a"
)
c4.metric(
    "Highest recorded inflation (YoY)",
    f"{peak_yoy_val:+.2f}%" if peak_yoy_val is not None else "n/a",
    help=f"Recorded {peak_yoy_date:%b %Y}" if peak_yoy_date is not None else None,
)
st.caption(SOURCE_NOTE + f" · {ct.index.min():%b %Y} – {ct.index.max():%b %Y}")

st.divider()

# ---------------------------------------------------------- main analysis --
# The Inflation Index & Change chart - full width (no reserved side column),
# Highcharts (see the module docstring for why), every series independently
# toggleable via the legend, drag-to-pan, and a 1x/2x/5x/10x zoom-factor
# button row + Reset. Bands are opt-in via the checkboxes below (off by
# default - they're context, not always wanted).
st.subheader("📈 Inflation index & change (%)")
b1, b2 = st.columns(2)
show_event_bands = b1.checkbox("Show major-event bands", value=False)
show_magnitude_bands = b2.checkbox("Show inflation-severity bands", value=False)

x_min, x_max = ct.index.min(), ct.index.max()
y_lo = min(ct["mom_pct"].min(skipna=True), ct["yoy_pct"].min(skipna=True))
y_hi = max(ct["mom_pct"].max(skipna=True), ct["yoy_pct"].max(skipna=True))
pad = (y_hi - y_lo) * 0.08 or 1.0
y_lo, y_hi = y_lo - pad, y_hi + pad

_main_chart_clicked = hc_main_chart(
    {
        "chart": {
            "backgroundColor": "transparent",
            "style": {"fontFamily": "inherit"},
            # Reserve headroom above the plot for the event-name overlay (see
            # _event_label_data and the JS below) so it prints above the
            # CPI/MoM/YoY lines instead of on top of them. 110px fits
            # "Currency Devaluation" (the longest of the 4 core event names,
            # ~97px tall in vertical CSS writing-mode at 9px, measured live)
            # with a little room to spare - tightened down from an earlier
            # 150px that left a visibly large gap above the chart (reported
            # live). Flat 20px with bands off.
            "marginTop": 110 if show_event_bands else 20,
            # Plain mouse-drag PANS (spec: "click and drag ... to move
            # through the time series") rather than the Highcharts Stock
            # default of drag-to-zoom-a-rectangle - the two are alternate
            # behaviors for the same gesture. `panKey`/`zooming.type` are
            # deliberately omitted (not set to None/null) rather than
            # explicitly disabled - Highcharts's config merge treats an
            # unset key as "use the default", which for panKey is exactly
            # "no modifier key needed", and null-vs-unset is not guaranteed
            # to behave identically for every option.
            "panning": {"enabled": True, "type": "x"},
        },
        "title": {"text": None},
        "rangeSelector": {"enabled": False},  # replaced by the 1x/2x/5x/10x buttons above the chart
        "navigator": {"enabled": True},
        "scrollbar": {"enabled": True},
        "xAxis": {
            "type": "datetime",
            "labels": {"style": AXIS_LABEL_STYLE},
            # Highcharts Stock defaults xAxis.ordinal to True (built for
            # trading data with weekend/holiday gaps): it registers its own
            # chart-level "pan" handler that pre-empts the default linear
            # pan-by-pixel-delta behavior with gap-aware positions, and for
            # a plain continuous monthly series that handler's own extremes
            # math never resolves, silently swallowing every drag - the
            # chart never moves. Our CPI series has no gaps, so this is off.
            "ordinal": False,
            "plotBands": _event_plotbands(x_min, x_max) if show_event_bands else [],
        },
        # Not a Highcharts option - our own data, read by the JS overlay in
        # _highcharts_main_chart to draw the 4 core events' NAMES above the
        # chart (see _event_plotbands's docstring for why they aren't drawn
        # via Highcharts's own plotBand `label` option).
        "eventLabels": _event_label_data(x_min, x_max) if show_event_bands else [],
        "yAxis": [
            {
                "title": {"text": "Index (2015-16 = 100)", "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE},
                "opposite": False,
                "gridLineColor": "rgba(128,128,128,0.15)",
            },
            {
                "title": {"text": "Change (%)", "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE},
                "opposite": True,
                "min": y_lo, "max": y_hi,
                "gridLineWidth": 0,
                "plotBands": _severity_plotbands(y_lo, y_hi) if show_magnitude_bands else [],
                "plotLines": [{"value": 0, "color": "#333333", "width": 1.5, "zIndex": 3}],
            },
        ],
        "tooltip": {"shared": True, "xDateFormat": "%b %Y"},
        "legend": {"enabled": True},
        "credits": {"enabled": False},
        "series": [
            {
                "name": "CPI (General)", "type": "area", "yAxis": 0,
                "color": SEQUENTIAL_HUE, "fillOpacity": 0.10, "lineWidth": 3,
                "data": [[int(ts.timestamp() * 1000), round(float(v), 2)] for ts, v in ct["cpi"].items()],
                "tooltip": {"valueDecimals": 2},
            },
            {
                "name": "Month-over-month (%)", "type": "line", "yAxis": 1,
                "color": MA_QUARTER_COLOR, "lineWidth": 2,
                "data": [
                    [int(ts.timestamp() * 1000), round(float(v), 2)]
                    for ts, v in ct["mom_pct"].dropna().items()
                ],
                "tooltip": {"valueDecimals": 2, "valueSuffix": "%"},
            },
            {
                "name": "Year-over-year (%)", "type": "line", "yAxis": 1,
                "color": HIGHLIGHT_HUE, "lineWidth": 3,
                "data": [
                    [int(ts.timestamp() * 1000), round(float(v), 2)]
                    for ts, v in ct["yoy_pct"].dropna().items()
                ],
                "tooltip": {"valueDecimals": 2, "valueSuffix": "%"},
            },
        ],
    },
    key="hc-main-chart",
)

# Dedupe against the last-seen click - same pattern the old Plotly chart's
# `_register_click` used, since a component keeps returning the SAME value
# on every subsequent rerun (e.g. toggling a checkbox below) until a NEW
# point is clicked, not just once.
if _main_chart_clicked and _main_chart_clicked != st.session_state.get("_last_main_chart_click"):
    st.session_state["_last_main_chart_click"] = _main_chart_clicked
    try:
        _clicked_ts = pd.Timestamp(_main_chart_clicked)
        _nearest = ct.index[ct.index.get_indexer([_clicked_ts], method="nearest")[0]]
        st.session_state["selected_period"] = _nearest
        st.session_state["period_picker"] = _nearest
        st.session_state["_trigger_scroll"] = True
        # A monotonic counter, not just a bool: components.html's iframe only
        # re-executes its <script> when its content actually changes - a
        # static script string worked once (first click) then silently did
        # nothing on every later click, since Streamlit saw identical srcdoc
        # content and didn't reload the iframe (confirmed live). Embedding
        # this ever-increasing number in the script (below) guarantees the
        # content differs on every genuine click.
        st.session_state["_scroll_nonce"] = st.session_state.get("_scroll_nonce", 0) + 1
    except (ValueError, TypeError, IndexError):
        pass

if show_event_bands:
    _legend_chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:16px;font-size:0.82rem;">'
        f'<span style="width:12px;height:12px;border-radius:3px;background:{e["color"]};'
        f'display:inline-block;"></span>{e.get("short_name", e["name"])}</span>'
        for e in CORE_EVENTS
    )
    st.markdown(f'<div style="margin:2px 0 10px;">{_legend_chips}</div>', unsafe_allow_html=True)

st.divider()

# ------------------------------------------------------ what caused the spike -
st.markdown(f'<div id="{ANCHOR_ID}"></div>', unsafe_allow_html=True)
if st.session_state.get("_trigger_scroll"):
    components.html(
        f"""
        <script>
            // nonce {st.session_state.get("_scroll_nonce", 0)} - forces this
            // iframe's content to differ from the last one, see the comment
            // where _scroll_nonce is incremented
            setTimeout(function() {{
                var doc = window.parent.document;
                var el = doc.getElementById('{ANCHOR_ID}');
                if (el) {{ el.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}
            }}, 200);
        </script>
        """,
        height=1,
    )
    st.session_state["_trigger_scroll"] = False

st.session_state.setdefault("selected_period", ct.index[-1])
selected = st.session_state["selected_period"]
options = list(ct.index[::-1])
picked = st.selectbox(
    "Selected period",
    options=options,
    index=options.index(selected) if selected in options else 0,
    format_func=lambda d: d.strftime("%B %Y"),
    key="period_picker",
)
if picked != selected:
    st.session_state["selected_period"] = picked
    selected = picked

period_groups = selected_period_group_table(group_long, selected)

if not period_groups.empty:
    # Canonical group order for BOTH bar charts, computed ONCE here (by MoM
    # % that period, matching this chart's original/existing sort) - the
    # Year-to-Year chart reuses this exact row order rather than sorting
    # itself by its own yoy values, so the two stay visually comparable
    # group-for-group. Switching Percentage/Absolute Value doesn't re-sort
    # either (same reasoning: bars jumping around on toggle would defeat
    # the comparison this pair exists for).
    sorted_for_chart = period_groups.sort_values("mom_pct", ascending=True)
    _highcharts_group_bars(
        "hc-group-mom",
        "hc-group-yoy",
        categories=sorted_for_chart["group"].tolist(),
        left_pct=sorted_for_chart["mom_pct"],
        left_abs=sorted_for_chart["mom_abs"],
        left_title="Month-to-Month Inflation by Group",
        right_pct=sorted_for_chart["yoy_pct"],
        right_abs=sorted_for_chart["yoy_abs"],
        right_title="Year-to-Year Inflation by Group",
        # Native chart title/subtitle, not the page's shared selectbox -
        # see _highcharts_group_bars's docstring for why: so the period
        # travels with either chart if it's downloaded/exported on its own.
        period_label=f"{selected:%B %Y}",
    )

    spike_display = period_groups[["group", "mom_pct", "yoy_pct", "relative_magnitude"]].rename(
        columns={
            "group": "Inflation Group",
            "mom_pct": "Month-to-Month Change (%)",
            "yoy_pct": "Year-to-Year Change (%)",
            "relative_magnitude": "Relative Magnitude",
        }
    )
    st.dataframe(
        spike_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Month-to-Month Change (%)": st.column_config.NumberColumn(format="%.2f"),
            "Year-to-Year Change (%)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption(f"{SOURCE_NOTE}. Relative Magnitude = rank among the 12 groups that month, not an official weight.")
else:
    st.warning("No per-group data available for this period yet.")

st.divider()

# ------------------------------------------------------------- Table 1 ----
st.subheader("Month-by-Month Inflation Change & Contributing Factors")

monthly_ranked = with_relative_magnitude(group_long.dropna(subset=["mom_pct"]), group_col="date")
monthly_ranked["Month"] = monthly_ranked["date"].dt.strftime("%b %Y")

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
    monthly_display,
    use_container_width=True,
    height=320,
    hide_index=True,
    column_config={
        "Month-to-Month Change (%)": st.column_config.NumberColumn(format="%.2f"),
        "Year-to-Year Change (%)": st.column_config.NumberColumn(format="%.2f"),
    },
)

# ------------------------------------------------------------- Table 2 ----
st.subheader("Year-by-Year Inflation Change & Contributing Factors")
st.caption("Calendar-year averages of the monthly series.")

yearly_ranked = _yearly_groups(group_long)

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
    yearly_display,
    use_container_width=True,
    height=320,
    hide_index=True,
    column_config={
        "Avg Month-to-Month Change (%)": st.column_config.NumberColumn(format="%.2f"),
        "Avg Year-to-Year Change (%)": st.column_config.NumberColumn(format="%.2f"),
    },
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
        "**CPI Trends**, **Crop Production**, **Data Explorer**, and **Inflation Heatmap** "
        "are in the navigation bar at the top of the page.\n\n"
        f"- **Sources:** {', '.join(sorted(df['source'].unique()))}\n"
        f"- **Date range:** {df['date'].min().date()} → {df['date'].max().date()}\n"
        f"- **Regions covered:** {df['region'].nunique()}"
    )
