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
  .hc-controls {{
      display:flex; align-items:center; justify-content:flex-end; gap:12px;
      margin:0 0 5px; color:#253c32; font-size:11px; white-space:nowrap;
      overflow:visible;
  }}
  .hc-actions {{ display:flex; align-items:center; justify-content:flex-end; gap:5px; }}
  .hc-period, .hc-icon-btn, .hc-menu summary {{
      height:30px; border:1px solid #c8d8d0; border-radius:7px; background:#fff;
      color:#21382e; font:600 11px -apple-system, sans-serif; padding:0 8px;
      cursor:pointer; box-shadow:0 1px 2px rgba(18,49,37,.04);
      box-sizing:border-box; display:flex; align-items:center; gap:6px;
  }}
  .hc-period {{ appearance:auto; min-width:72px; }}
  .hc-icon-btn {{ width:30px; padding:0; justify-content:center; font-size:15px; text-decoration:none; }}
  .hc-action-icon {{ width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
  .hc-period:hover, .hc-icon-btn:hover, .hc-menu summary:hover {{ border-color:#0b6e4f; color:#07533c; background:#f3faf7; }}
  .hc-menu {{ position:relative; }}
  .hc-menu summary {{ list-style:none; }}
  .hc-menu summary::-webkit-details-marker {{ display:none; }}
  .hc-menu-panel {{
      position:absolute; z-index:20; right:0; top:34px; min-width:210px;
      padding:9px 11px; background:#fff; border:1px solid #d7e3dd;
      border-radius:10px; box-shadow:0 10px 28px rgba(18,49,37,.16);
  }}
  .hc-menu-panel label {{ display:flex; align-items:center; gap:8px; padding:6px 2px; cursor:pointer; }}
  .hc-menu-panel input {{ accent-color:#0b6e4f; }}
  @media (max-width: 560px) {{
      .hc-controls {{ gap:7px; }}
      .hc-actions {{ overflow-x:auto; }}
  }}
</style>
</head>
<body>
<div class="hc-controls">
  <div class="hc-actions">
    <span aria-hidden="true">◷</span>
    <select id="hc-display-period" class="hc-period" onchange="__applyPeriod()" title="Display period">
        <option value="12">1Y · 12 months</option>
        <option value="36">3Y · 36 months</option>
        <option value="60" selected>5Y · 60 months</option>
        <option value="120">10Y · 120 months</option>
        <option value="all">All data</option>
    </select>
    <details class="hc-menu">
      <summary title="Choose visible chart series">≋ Series</summary>
      <div class="hc-menu-panel">
        <label><input type="checkbox" data-series="0" checked onchange="__toggleSeries(this)"> CPI index (absolute)</label>
        <label><input type="checkbox" data-series="1" checked onchange="__toggleSeries(this)"> Month-over-month (MoM)</label>
        <label><input type="checkbox" data-series="2" checked onchange="__toggleSeries(this)"> Year-over-year (YoY)</label>
      </div>
    </details>
    <details class="hc-menu">
      <summary title="Add contextual bands to the chart">▥ Overlays</summary>
      <div class="hc-menu-panel">
        <label><input id="hc-events" type="checkbox" onchange="__toggleOverlays()"> Major events</label>
        <label><input id="hc-severity" type="checkbox" onchange="__toggleOverlays()"> Inflation severity</label>
      </div>
    </details>
    <button type="button" onclick="__downloadPng()" class="hc-icon-btn" title="Capture chart image (PNG)" aria-label="Capture chart image as PNG"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.4-2h7.2L17 7h3v12H4V7Z"/><circle cx="12" cy="13" r="3.5"/></svg></button>
    <a id="hc-excel-download" class="hc-icon-btn" title="Download chart data (Excel)" aria-label="Download chart data as Excel"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 11h7M9 15h7M9 19h7M12 9v10"/></svg></a>
  </div>
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

    function __applyPeriod() {{
        if (!__chart) return;
        var ax = __chart.xAxis[0], ext = ax.getExtremes();
        var value = document.getElementById('hc-display-period').value;
        if (value === 'all') {{ ax.setExtremes(ext.dataMin, ext.dataMax); return; }}
        var months = parseInt(value, 10), end = new Date(ext.dataMax);
        var start = Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - months + 1, 1);
        ax.setExtremes(Math.max(ext.dataMin, start), ext.dataMax);
    }}

    function __toggleSeries(input) {{
        if (!__chart) return;
        var series = __chart.series[parseInt(input.dataset.series, 10)];
        if (!series) return;
        series.setVisible(input.checked, false);
        __reflowAxes();
    }}

    var __emptyState = null;
    function __reflowAxes() {{
        if (!__chart) return;
        var cpiOn = !!(__chart.series[0] && __chart.series[0].visible);
        var changeOn = !!((__chart.series[1] && __chart.series[1].visible)
            || (__chart.series[2] && __chart.series[2].visible));
        if (cpiOn && changeOn) {{
            __chart.yAxis[0].update({{visible:true, top:'0%', height:'58%', gridLineWidth:1}}, false);
            __chart.yAxis[1].update({{visible:true, top:'66%', height:'28%', gridLineWidth:1}}, false);
        }} else if (cpiOn) {{
            __chart.yAxis[0].update({{visible:true, top:'0%', height:'92%', gridLineWidth:1}}, false);
            __chart.yAxis[1].update({{visible:false, gridLineWidth:0}}, false);
        }} else if (changeOn) {{
            __chart.yAxis[0].update({{visible:false, gridLineWidth:0}}, false);
            __chart.yAxis[1].update({{visible:true, top:'0%', height:'92%', gridLineWidth:1}}, false);
        }} else {{
            __chart.yAxis[0].update({{visible:false, gridLineWidth:0}}, false);
            __chart.yAxis[1].update({{visible:false, gridLineWidth:0}}, false);
        }}
        // Recompute extremes from only visible series after every layout
        // transition. Only touch the two analytical axes: Highcharts Stock
        // also owns internal navigator axes, and resetting those caused
        // stray/misaligned grid lines after series toggles.
        [__chart.yAxis[0], __chart.yAxis[1]].forEach(function(axis) {{
            if (axis && axis.visible) axis.setExtremes(null, null, false);
        }});
        __chart.redraw();
        if (__emptyState) {{ __emptyState.destroy(); __emptyState = null; }}
        if (!cpiOn && !changeOn) {{
            __emptyState = __chart.renderer.label(
                'No series selected — use the Series menu to display data',
                __chart.plotLeft + (__chart.plotWidth / 2),
                __chart.plotTop + (__chart.plotHeight / 2)
            ).attr({{align:'center', zIndex:8, padding:10, r:7, fill:'#F4F7F5', stroke:'#D7E3DD'}})
             .css({{color:'#607269', fontSize:'12px', fontWeight:'600'}}).add();
        }}
    }}

    // Click-to-navigate: after a click reports its month back to Python (which
    // reruns and re-selects that period in the group bar charts below), bring
    // that section into view. Done from inside THIS component - not a separate
    // components.html scroll iframe on the page, which Streamlit rendered at a
    // stray ~460px tall and left a big blank gap above the bars (reported
    // live). The parent rerun keeps shifting layout for a beat (this
    // component re-renders, the bars' own iframe self-resizes), so re-issue
    // the scroll on an interval for ~5s, stopping once the target holds still.
    function __scrollParentToGroupBars() {{
        var doc;
        try {{ doc = window.parent.document; }} catch (e) {{ return; }}
        var started = Date.now(), lastTop = null, stable = 0;
        function step() {{
            var el = doc.getElementById('spike-section-anchor');
            if (el) {{
                el.scrollIntoView({{block: 'start', behavior: 'auto'}});
                var top = el.getBoundingClientRect().top;
                if (lastTop !== null && Math.abs(top - lastTop) < 3) stable++; else stable = 0;
                lastTop = top;
            }}
            if (Date.now() - started < 5000 && stable < 5) setTimeout(step, 150);
        }}
        setTimeout(step, 120);
    }}

    function __toggleOverlays() {{
        if (!__chart) return;
        var available = __chart.options.availableOverlays || {{}};
        var eventsOn = document.getElementById('hc-events').checked;
        var severityOn = document.getElementById('hc-severity').checked;
        __chart.options.eventLabels = eventsOn ? (available.eventLabels || []) : [];
        __chart.xAxis[0].update({{plotBands: eventsOn ? (available.eventBands || []) : []}}, false);
        __chart.yAxis[1].update({{plotBands: severityOn ? (available.severityBands || []) : []}}, false);
        __chart.redraw();
    }}

    function __downloadPng() {{
        if (!__chart) return;
        var svgNode = __chart.container.querySelector('svg');
        if (!svgNode) return;
        var svg = new XMLSerializer().serializeToString(svgNode);
        var blob = new Blob([svg], {{type:'image/svg+xml;charset=utf-8'}});
        var url = URL.createObjectURL(blob);
        var image = new Image();
        image.onload = function() {{
            var scale = 2, canvas = document.createElement('canvas');
            canvas.width = __chart.chartWidth * scale; canvas.height = __chart.chartHeight * scale;
            var ctx = canvas.getContext('2d');
            ctx.scale(scale, scale); ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, __chart.chartWidth, __chart.chartHeight); ctx.drawImage(image, 0, 0);
            URL.revokeObjectURL(url);
            canvas.toBlob(function(png) {{
                var link = document.createElement('a');
                link.href = URL.createObjectURL(png); link.download = 'inflation-index-and-change.png';
                document.body.appendChild(link); link.click(); link.remove();
                setTimeout(function() {{ URL.revokeObjectURL(link.href); }}, 1000);
            }}, 'image/png');
        }};
        image.src = url;
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
        var excel = (args.config && args.config.excelDownload) || {{}};
        var excelLink = document.getElementById('hc-excel-download');
        excelLink.href = 'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,' + (excel.base64 || '');
        excelLink.download = excel.filename || 'chart-data.xlsx';
        chartDiv.style.height = (height - 46) + 'px';
        if (__chart) {{ __chart.destroy(); __chart = null; }}
        __chart = Highcharts.stockChart('hc-main-chart', args.config);
        __applyPeriod();
        __reflowAxes();

        // Turn a millisecond x-value into a "YYYY-MM-01" string and report it
        // back to Python + scroll to the group bars. Shared by both click
        // paths below. The chart-level handler passes a CONTINUOUS x value
        // (wherever the cursor is), which near a month boundary can sit a few
        // hours into the previous month and truncate to the wrong one - so
        // snap to the NEAREST month start (data points are the 1st of each
        // month, UTC). A point click already passes an exact 1st-of-month x,
        // for which this snap is a no-op.
        function __selectMonth(ms) {{
            var d = new Date(ms);
            var m = d.getUTCMonth() + (d.getUTCDate() >= 15 ? 1 : 0);
            var snapped = new Date(Date.UTC(d.getUTCFullYear(), m, 1));
            var ymd = snapped.getUTCFullYear() + '-'
                + String(snapped.getUTCMonth() + 1).padStart(2, '0') + '-01';
            setValue(ymd);
            __scrollParentToGroupBars();
        }}

        __chart.update({{plotOptions: {{series: {{
            cursor: 'pointer',
            // Clicking DIRECTLY on a line/point/area consumes the event as a
            // point (or series) click - the chart-level handler below never
            // sees it (reported live: "works under the CPI line, not on the
            // lines"). Handle those here too: the clicked point's own `x` is
            // the exact month. (Purely additive - no tooltip/hover/marker
            // options touched.)
            point: {{ events: {{ click: function() {{ __selectMonth(this.x); }} }} }},
            events: {{ click: function(e) {{
                if (e && e.point) __selectMonth(e.point.x);
            }} }}
        }}}}}}, false);

        // Chart-level click handles everywhere else in the plot - the large
        // areas not close to any of the 3 series (CPI 0-300ish vs MoM/YoY
        // roughly -25..+30, so most of the plot isn't near a line). Hands
        // back the x-axis VALUE under the cursor directly - "click anywhere
        // on the timeline", not "click exactly on a data point".
        Highcharts.addEvent(__chart, 'click', function(e) {{
            if (!e.xAxis || !e.xAxis[0]) return;
            __selectMonth(e.xAxis[0].value);
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
    # Design-system rule: every analytical chart owns a meaningful native
    # title. Surrounding page headings and toolbar labels are not substitutes
    # because they disappear when a chart is downloaded or reused.
    title = str((config.get("title") or {}).get("text") or "").strip()
    if not title:
        raise ValueError("Every chart must define a non-empty native title.text")
    return _hc_main_chart_component(config=config, height=height, key=key, default=None)
