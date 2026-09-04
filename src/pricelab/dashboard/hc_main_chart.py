"""The `hc_main_chart` custom Streamlit component.

Lives in the `pricelab` package - a normally-`import`ed module - rather
than inline in `dashboard/pages/0_Home.py` where it started, because
`components.declare_component()` needs `inspect.getmodule()` to resolve its
OWN calling frame's module, and that fails ("module is None. This should
never happen.", confirmed live) when the calling code is a page script
`exec`'d by `st.navigation()`'s `pg.run()` rather than loaded as a real,
`sys.modules`-registered module the normal way - which `dashboard/app.py`
itself (the actual entry point Streamlit loads directly) is, but a page
under `dashboard/pages/` that `st.navigation()` routes to is not. A plain
`import` from here doesn't have that problem, so the component is declared
here once and `hc_main_chart` is exported for the page to call.

Unlike `st.components.v1.html` (display-only, no way back to Python), a
real component can call `Streamlit.setComponentValue(...)`, which is what
lets clicking a chart point feed a value back into Python - the same job
Plotly's `on_select` did for the old chart. No build step/npm/React needed:
the Streamlit Components JS protocol is just a handful of documented
`postMessage` calls (componentReady / render / setComponentValue /
setFrameHeight), small enough to hand-write directly below rather than pull
in a whole component-scaffolding toolchain for it.

A real page navigation was tried first for click-to-navigate (`?selected_
period=<month>` + `st.query_params`) and confirmed live NOT to work:
`components.html`'s iframe sandbox has no `allow-top-navigation` (or the
user-activation variant), so both a direct `location.href` assignment and a
same-document `history.pushState` + manually dispatched `popstate` were
silently ignored by the browser / not picked up by Streamlit's frontend. A
declared component's `setComponentValue` sidesteps the whole issue - it's a
`postMessage`, which isn't subject to the sandbox's navigation flags at all.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# This file lives at src/pricelab/dashboard/hc_main_chart.py - four levels
# below the repo root, which is where the dashboard/ directory (containing
# the actual highstock.js asset and where the generated component frontend
# is written) lives as a sibling of src/.
_DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "dashboard"
_HC_MAIN_CHART_DIR = _DASHBOARD_DIR / "components" / "hc_main_chart"


@st.cache_data
def _highstock_js() -> str:
    """Highcharts Stock, bundled locally (dashboard/assets/highstock.js)
    rather than loaded from code.highcharts.com at runtime - verified live
    that a CDN <script src> silently fails to render in some sandboxed/
    restricted network environments; inlining the actual JS removes that
    dependency entirely, for every viewer, not just the ones this was
    tested in.

    Licensing note: Highcharts is free for non-commercial/personal/student
    use; a commercial license is required for commercial deployment - see
    https://www.highcharts.com/license.
    """
    return (_DASHBOARD_DIR / "assets" / "highstock.js").read_text(encoding="utf-8")


@st.cache_resource
def _write_hc_main_chart_component() -> str:
    """Write the static frontend for the `hc_main_chart` custom Streamlit
    component and return its directory (for `components.declare_component`).

    This still has all the same pieces this chart's earlier plain
    `components.html` embed had - the 1x/2x/5x/10x + Reset zoom buttons, and
    the plain-HTML event-name overlay (see `_event_plotbands`'s docstring in
    `dashboard/pages/0_Home.py` for why that's not a Highcharts plotBand
    `label`) - just packaged as a real component's frontend instead of a
    `components.html` payload, and with an added click handler that reports
    the clicked point's month back to Python instead of doing nothing with it.
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
