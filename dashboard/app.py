"""Pakistan Price Trend Framework - Home: CPI index & change dashboard.

Run locally:   streamlit run dashboard/app.py   (or: .\\run.cmd dashboard)
Deployed:      Streamlit Community Cloud, same entry point, reads the
               committed DuckDB snapshot at data/processed/pricelab.duckdb.

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
breakdown bar chart in that section, and the M/M vs Y/Y comparison charts
further down (still plain `st.components.v1.html`, no click behavior needed
there), are otherwise unchanged.

The header banner embeds `dashboard/pbs_logo.jpg` (user-supplied).
"""

from __future__ import annotations

import base64
import json
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
    global_events,
    load_inflation_bands,
)
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

st.set_page_config(
    page_title="Pakistan Price Trend Framework",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
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


def _highcharts_series(series: pd.Series, name: str) -> dict:
    """One [timestamp_ms, value] Highcharts Stock series - NaNs dropped (Highcharts
    plots a gap, which is correct; it doesn't need pandas' NaN representation).

    color/negativeColor use the same increase/decrease pair as everywhere else
    on this page (e.g. the 12-group breakdown bars) - each chart here shows a
    single measure, so color is free to carry "rising vs falling" instead of
    series identity (the chart's own title already says which measure it is).
    """
    s = series.dropna()
    return {
        "name": name,
        "data": [[int(ts.timestamp() * 1000), round(float(v), 2)] for ts, v in s.items()],
        "color": INCREASE_COLOR,
        "negativeColor": DECREASE_COLOR,
        "lineWidth": 2,
        "threshold": 0,
    }


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
    return (Path(__file__).parent / "assets" / "highstock.js").read_text(encoding="utf-8")


def _highcharts_stock(chart_id: str, config: dict, *, height: int = 420) -> None:
    """Embed one Highcharts Stock chart. Config is plain Python -> json.dumps
    handles it; Highcharts Stock (not plain Highcharts) is used specifically
    for its built-in range selector + navigator, matching the "time
    range/zoom" control this page's spec asks for.

    This chart is read-only w.r.t. Streamlit - Highcharts has no first-party
    Streamlit integration, unlike Plotly's `on_select`. "What caused the
    inflation spike?" uses its own selectbox instead of a chart click.
    """
    spec_json = json.dumps(config)
    components.html(
        f"""
        <div id="{chart_id}" style="width:100%;height:{height - 20}px;"></div>
        <script>{_highstock_js()}</script>
        <script>
            Highcharts.stockChart('{chart_id}', {spec_json});
        </script>
        """,
        height=height,
    )


_HC_MAIN_CHART_DIR = Path(__file__).parent / "components" / "hc_main_chart"


@st.cache_resource
def _write_hc_main_chart_component() -> str:
    """Write the static frontend for the `hc_main_chart` custom Streamlit
    component and return its directory (for `components.declare_component`).

    Unlike `st.components.v1.html` (display-only, no way back to Python),
    a real component can call `Streamlit.setComponentValue(...)`, which is
    what lets clicking a chart point feed a value back into Python - the
    same job Plotly's `on_select` did for the old chart. No build step/npm/
    React needed: the Streamlit Components JS protocol is just a handful of
    documented `postMessage` calls (componentReady / render / setComponentValue
    / setFrameHeight), small enough to hand-write directly below rather than
    pull in a whole component-scaffolding toolchain for it.

    This still has all the same pieces `_highcharts_stock`'s main-chart
    predecessor had - the 1x/2x/5x/10x + Reset zoom buttons, and the plain-
    HTML event-name overlay (see `_event_plotbands`'s docstring for why
    that's not a Highcharts plotBand `label`) - just packaged as a real
    component's frontend instead of a `components.html` payload, and with
    an added click handler that reports the clicked point's month back to
    Python instead of doing nothing with it.

    A real page navigation was tried first for click-to-navigate (`?selected_
    period=<month>` + `st.query_params`) and confirmed live NOT to work:
    `components.html`'s iframe sandbox has no `allow-top-navigation` (or the
    user-activation variant), so both a direct `location.href` assignment and
    a same-document `history.pushState` + manually dispatched `popstate` were
    silently ignored by the browser / not picked up by Streamlit's frontend.
    A declared component's `setComponentValue` sidesteps the whole issue -
    it's a `postMessage`, which isn't subject to the sandbox's navigation
    flags at all.
    """
    _HC_MAIN_CHART_DIR.mkdir(parents=True, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; font-family: -apple-system, sans-serif; overflow: hidden; }}
  .hc-zoom-btn {{
      font: 12px -apple-system, sans-serif; padding: 4px 12px; margin-right: 4px;
      border: 1px solid #d0d0d0; border-radius: 4px; background: #fafafa;
      color: #333; cursor: pointer;
  }}
  .hc-zoom-btn:hover {{ background: #eef2f6; border-color: #a8c5e0; }}
</style>
</head>
<body>
<div style="margin-bottom:8px;">
    <button onclick="__zoom(1)" class="hc-zoom-btn">1x</button>
    <button onclick="__zoom(2)" class="hc-zoom-btn">2x</button>
    <button onclick="__zoom(5)" class="hc-zoom-btn">5x</button>
    <button onclick="__zoom(10)" class="hc-zoom-btn">10x</button>
    <button onclick="__reset()" class="hc-zoom-btn" style="margin-left:10px;">Reset</button>
</div>
<div id="hc-main-chart" style="width:100%;position:relative;"></div>
<script>{_highstock_js()}</script>
<script>
    // ---- Minimal hand-written Streamlit Components JS protocol - see
    // https://docs.streamlit.io/develop/concepts/custom-components/create
    function sendToStreamlit(type, data) {{
        window.parent.postMessage(Object.assign({{isStreamlitMessage: true, type: type}}, data), "*");
    }}
    function setFrameHeight(h) {{ sendToStreamlit("streamlit:setFrameHeight", {{height: h}}); }}
    function setValue(v) {{ sendToStreamlit("streamlit:setComponentValue", {{value: v, dataType: "json"}}); }}

    var __chart = null;

    function __zoom(factor) {{
        if (!__chart) return;
        var ax = __chart.xAxis[0];
        var ext = ax.getExtremes();
        var span = (ext.dataMax - ext.dataMin) / factor;
        ax.setExtremes(Math.max(ext.dataMin, ext.dataMax - span), ext.dataMax);
    }}
    function __reset() {{
        if (!__chart) return;
        var ax = __chart.xAxis[0];
        var ext = ax.getExtremes();
        ax.setExtremes(ext.dataMin, ext.dataMax);
    }}

    function __renderEventLabels() {{
        var chart = __chart;
        var container = document.getElementById('hc-main-chart');
        var old = container.querySelector('.hc-event-label-overlay');
        if (old) old.remove();
        var items = chart.options.eventLabels || [];
        if (!items.length) return;
        var overlay = document.createElement('div');
        overlay.className = 'hc-event-label-overlay';
        overlay.style.cssText = 'position:absolute; left:0; top:0; width:100%; '
            + 'height:' + chart.plotTop + 'px; pointer-events:none; overflow:hidden;';
        container.appendChild(overlay);
        var ax = chart.xAxis[0];
        var ext = ax.getExtremes();
        var divs = [];
        items.forEach(function(ev) {{
            if (ev.x < ext.min || ev.x > ext.max) return;  // off-screen - skip
            var px = ax.toPixels(ev.x, false);
            var div = document.createElement('div');
            div.textContent = ev.text;
            if (ev.title) div.title = ev.title;
            div.style.cssText = 'position:absolute; top:4px; left:' + px + 'px; '
                + 'writing-mode:vertical-rl; font-size:9px; font-weight:600; '
                + 'color:#333333; white-space:nowrap; pointer-events:auto; cursor:help;';
            overlay.appendChild(div);
            divs.push(div);
        }});
        // Real collision detection (actual rendered boxes), not estimated
        // text width - push each label right of the one before it if
        // they'd otherwise touch, regardless of length or viewport size.
        divs.sort(function(a, b) {{ return parseFloat(a.style.left) - parseFloat(b.style.left); }});
        for (var i = 1; i < divs.length; i++) {{
            var prevRect = divs[i - 1].getBoundingClientRect();
            var curRect = divs[i].getBoundingClientRect();
            var gapNeeded = 10;
            if (curRect.left < prevRect.right + gapNeeded) {{
                var shift = (prevRect.right + gapNeeded) - curRect.left;
                divs[i].style.left = (parseFloat(divs[i].style.left) + shift) + 'px';
            }}
        }}
    }}

    function __buildChart(args) {{
        var height = args.height || 520;
        var chartDiv = document.getElementById('hc-main-chart');
        chartDiv.style.height = (height - 46) + 'px';
        if (__chart) {{ __chart.destroy(); __chart = null; }}
        __chart = Highcharts.stockChart('hc-main-chart', args.config);
        __chart.update({{plotOptions: {{series: {{cursor: 'pointer'}}}}}}, false);
        // Chart-level click (not per-series): a series' own 'click' event
        // only fires when the click lands close to that series's actual
        // rendered line/area - with 3 series on very different scales (CPI
        // 0-300ish vs MoM/YoY roughly -25 to +30), most of the plot area
        // isn't "close" to any of them, so most clicks were silently
        // swallowed (verified live - clicking away from a line produced
        // zero setValue calls). `chart.events.click` fires anywhere in the
        // plot and hands back the x-axis VALUE under the cursor directly
        // via `e.xAxis[0].value`, matching "click anywhere on the
        // timeline" rather than "click exactly on a data point".
        Highcharts.addEvent(__chart, 'click', function(e) {{
            if (!e.xAxis || !e.xAxis[0]) return;
            var d = new Date(e.xAxis[0].value);
            var ymd = d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-01';
            setValue(ymd);
        }});
        __renderEventLabels();
        Highcharts.addEvent(__chart, 'redraw', __renderEventLabels);
        setFrameHeight(height);
    }}

    function onRender(event) {{
        if (!event.data || event.data.type !== "streamlit:render") return;
        __buildChart(event.data.args);
    }}
    window.addEventListener("message", onRender);
    sendToStreamlit("streamlit:componentReady", {{apiVersion: 1}});
</script>
</body>
</html>
"""
    (_HC_MAIN_CHART_DIR / "index.html").write_text(html, encoding="utf-8")
    return str(_HC_MAIN_CHART_DIR)


_hc_main_chart_component = components.declare_component(
    "hc_main_chart", path=_write_hc_main_chart_component()
)


def hc_main_chart(config: dict, *, height: int = 520, key: str | None = None) -> str | None:
    """Call the `hc_main_chart` custom component. Returns the clicked
    point's month as an ISO date string if the user has clicked a point on
    the chart, else None - exactly like the old Plotly chart's `on_select`
    return value, just shaped differently. Like that old value, Streamlit
    keeps returning the SAME clicked value on every subsequent rerun until a
    NEW point is clicked - dedupe against the last-seen value (see the call
    site) before reacting to it, the same way the old `_register_click` did.
    """
    return _hc_main_chart_component(config=config, height=height, key=key, default=None)


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
    sorted_for_chart = period_groups.sort_values("mom_pct", ascending=True)
    _spike_fig = go.Figure(
        go.Bar(
            x=sorted_for_chart["mom_pct"],
            y=sorted_for_chart["group"],
            orientation="h",
            marker_color=[
                INCREASE_COLOR if v >= 0 else DECREASE_COLOR for v in sorted_for_chart["mom_pct"]
            ],
            text=[f"{v:+.2f}%" for v in sorted_for_chart["mom_pct"]],
            textposition="outside",
            hovertemplate="%{y}<br>MoM: %{x:+.2f}%<extra></extra>",
        )
    )
    _spike_fig.update_layout(
        height=360,
        margin=dict(l=10, r=40, t=10, b=10),
        xaxis_title="Month-over-month change that period (%)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=True, zerolinecolor="#999"),
    )
    st.plotly_chart(_spike_fig, use_container_width=True)

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

# ------------------------------------------------- M/M & Y/Y comparison (Highcharts) -
st.subheader("Month-to-Month vs Year-to-Year comparison")
st.caption(
    "Drag across either chart to zoom, use the range buttons or the navigator scrollbar "
    "below the chart to move through time."
)

hc_mom, hc_yoy = st.columns(2)
_hc_shared_xaxis = {
    "type": "datetime",
    "labels": {"style": AXIS_LABEL_STYLE},
}
_hc_shared_rangeselector = {
    "selected": 4,
    "buttons": [
        {"type": "year", "count": 1, "text": "1y"},
        {"type": "year", "count": 3, "text": "3y"},
        {"type": "year", "count": 5, "text": "5y"},
        {"type": "year", "count": 10, "text": "10y"},
        {"type": "all", "text": "All"},
    ],
}

with hc_mom:
    st.markdown("**Month-to-Month (%)**")
    _highcharts_stock(
        "hc-mom-chart",
        {
            "chart": {"backgroundColor": "transparent", "style": {"fontFamily": "inherit"}},
            "title": {"text": None},
            "rangeSelector": _hc_shared_rangeselector,
            "xAxis": _hc_shared_xaxis,
            "yAxis": {
                "title": {"text": "MoM change (%)", "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE},
                "opposite": False,
            },
            "tooltip": {"valueDecimals": 2, "valueSuffix": "%", "shared": True},
            "series": [_highcharts_series(ct["mom_pct"], "Month-over-month (%)")],
            "credits": {"enabled": False},
        },
    )

with hc_yoy:
    st.markdown("**Year-to-Year (%)**")
    _highcharts_stock(
        "hc-yoy-chart",
        {
            "chart": {"backgroundColor": "transparent", "style": {"fontFamily": "inherit"}},
            "title": {"text": None},
            "rangeSelector": _hc_shared_rangeselector,
            "xAxis": _hc_shared_xaxis,
            "yAxis": {
                "title": {"text": "YoY change (%)", "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE},
                "opposite": False,
            },
            "tooltip": {"valueDecimals": 2, "valueSuffix": "%", "shared": True},
            "series": [_highcharts_series(ct["yoy_pct"], "Year-over-year (%)")],
            "credits": {"enabled": False},
        },
    )

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
        "**CPI Trends**, **Crop Production**, and **Data Explorer** are in the sidebar "
        "(collapsed by default - click the `>>` at the top-left to open it).\n\n"
        f"- **Sources:** {', '.join(sorted(df['source'].unique()))}\n"
        f"- **Date range:** {df['date'].min().date()} → {df['date'].max().date()}\n"
        f"- **Regions covered:** {df['region'].nunique()}"
    )
