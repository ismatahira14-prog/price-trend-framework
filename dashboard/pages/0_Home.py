"""Pakistan Price Trend Framework - Home page: CPI index & change dashboard.

Run locally:   streamlit run dashboard/app.py   (or: .\\run.cmd dashboard)
Deployed:      Streamlit Community Cloud, same entry point, reads the
               the configured IMIS SQL Server database.

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
import io
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
    ImisDataError,
    cpi_change_table,
    cpi_series,
    group_change_table,
    load_imis_cpi_district_map,
    load_imis_inflation,
    load_imis_item_drilldown,
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
    CPI_GROUP_ICONS,
    CPI_GROUP_ORDER,
    CPI_GROUP_CODES,
    CPI_GROUP_SHORT_NAMES,
    DECREASE_COLOR,
    HIGHLIGHT_HUE,
    INCREASE_COLOR,
    INFLATION_BAND_FILLS,
    MA_QUARTER_COLOR,
    OKABE_ITO,
    PBS_GREEN,
    PBS_GREEN_DARK,
    SEQUENTIAL_HUE,
)

GROUPS_12 = CPI_GROUP_ORDER[1:]  # everything except "General" - the 12 COICOP groups
CORE_EVENTS = [e for e in EVENTS if e["core_chart_event"]]
SOURCE_NOTE = (
    "Source: IMIS SQL Server · dbo.Inflation joined to dbo.PriceGroup · "
    "Pakistan Bureau of Statistics (PBS) CPI · base 2015-16 = 100"
)
ANCHOR_ID = "spike-section-anchor"  # scroll target for the main chart's click-to-navigate

# Highcharts's default axis-label color is a light theme-neutral gray, tuned
# for a plain white card - against this page's chart cards it reads as
# washed-out/blurry. Every axis on every Highcharts chart on this page uses
# these two styles explicitly instead of the library default.
AXIS_LABEL_STYLE = {"color": "#333333", "fontSize": "12px"}
AXIS_TITLE_STYLE = {"color": "#222222", "fontSize": "13px", "fontWeight": "600"}
AXIS_TITLE_STYLE = {"color": "#222222", "fontSize": "12px", "fontWeight": "600"}


@st.cache_data(ttl=3600)
def _load() -> pd.DataFrame:
    return load_imis_inflation()


@st.cache_data(ttl=3600)
def _change_table(_df: pd.DataFrame) -> pd.DataFrame:
    general = cpi_series(_df, ["General"])["General"]
    return cpi_change_table(general)


@st.cache_data(ttl=3600)
def _group_long(_df: pd.DataFrame) -> pd.DataFrame:
    return group_change_table(_df, GROUPS_12)


@st.cache_data(ttl=3600)
def _item_drilldown(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    return load_imis_item_drilldown(start_date, end_date)


@st.cache_data(ttl=3600)
def _cpi_district_map() -> pd.DataFrame:
    return load_imis_cpi_district_map()


@st.cache_data
def _price_geojson_levels() -> dict[str, dict]:
    """Load compact province, division, and district price-map boundaries.

    District view replaces Karachi's seven district polygons with the single
    ``dv.geojson`` feature where dvid/code is 18. Source files remain
    untouched. Four decimal places retain roughly 10-metre coordinate
    precision while materially reducing the iframe payload.
    """
    filenames = {"province": "pv.geojson", "division": "dv.geojson", "district": "ds.geojson"}
    levels: dict[str, dict] = {}
    for level, filename in filenames.items():
        path = _DASHBOARD_DIR.parent / "geojson" / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImisDataError(f"GeoJSON boundary data is missing or invalid: {path}") from exc
        if payload.get("type") != "FeatureCollection" or not isinstance(
            payload.get("features"), list
        ):
            raise ImisDataError(f"geojson/{filename} must be a GeoJSON FeatureCollection")
        for feature in payload["features"]:
            properties = feature.get("properties", {})
            if "code" not in properties or "name" not in properties:
                raise ImisDataError(f"Every geojson/{filename} feature requires code and name")
            properties["boundaryLevel"] = level
        levels[level] = payload

    karachi_district_codes = {"146", "147", "148", "149", "150", "154", "166"}
    karachi_divisions = [
        feature
        for feature in levels["division"]["features"]
        if str(feature.get("properties", {}).get("code", "")).strip() == "18"
    ]
    if len(karachi_divisions) != 1:
        raise ImisDataError("geojson/dv.geojson must contain exactly one Karachi division (code 18)")
    levels["district"]["features"] = [
        feature
        for feature in levels["district"]["features"]
        if str(feature.get("properties", {}).get("code", "")).strip()
        not in karachi_district_codes
    ]
    karachi_feature = json.loads(json.dumps(karachi_divisions[0]))
    karachi_feature["properties"] = {
        **karachi_feature.get("properties", {}),
        "boundaryLevel": "district",
        "sourceBoundaryLevel": "division",
        "mapCityCode": 18,
    }
    levels["district"]["features"].append(karachi_feature)

    def compact(value):
        if isinstance(value, list):
            return [compact(part) for part in value]
        if isinstance(value, float):
            return round(value, 4)
        return value

    for payload in levels.values():
        for feature in payload["features"]:
            geometry = feature.get("geometry") or {}
            geometry["coordinates"] = compact(geometry.get("coordinates", []))
    return levels


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


def _group_bar_points(values: pd.Series, full_categories: list[str]) -> list[dict | None]:
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
    for v, full_category in zip(values, full_categories, strict=True):
        if pd.isna(v):
            points.append(None)  # renders as a gap, not a fabricated zero
            continue
        points.append(
            {
                "y": round(float(v), 2),
                "color": INCREASE_COLOR if v >= 0 else DECREASE_COLOR,
                "custom": {"label": f"{v:+.2f}", "fullCategory": full_category},
            }
        )
    return points


def _xlsx_base64(sheets: dict[str, pd.DataFrame]) -> str:
    """Build a formatted in-memory Excel workbook for chart data."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            ws = writer.sheets[name[:31]]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for column in ws.columns:
                width = min(48, max(11, max(len(str(cell.value or "")) for cell in column) + 2))
                ws.column_dimensions[column[0].column_letter].width = width
    return base64.b64encode(output.getvalue()).decode("ascii")


def _highcharts_group_bars(
    left_id: str,
    right_id: str,
    *,
    categories: list[str],
    full_categories: list[str],
    heat_matrix: list[dict],
    heat_groups: list[dict],
    heat_items: dict[str, list[dict]],
    city_prices: dict[str, list[list]],
    district_city_map: list[dict],
    geojson_levels: dict[str, dict],
    drilldown_xlsx: str,
    left_pct: pd.Series,
    left_title: str,
    right_pct: pd.Series,
    right_title: str,
    period_label: str,
    height: int = 374,
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
    left_pct_pts = _group_bar_points(left_pct, full_categories)
    right_pct_pts = _group_bar_points(right_pct, full_categories)
    subtitle_text = f"Selected period: {period_label}"
    left_xlsx = _xlsx_base64({"Monthly movement": pd.DataFrame({
        "CPI Group": full_categories,
        "MoM Percentage": list(left_pct),
    })})
    right_xlsx = _xlsx_base64({"Annual movement": pd.DataFrame({
        "CPI Group": full_categories,
        "YoY Percentage": list(right_pct),
    })})

    # The category axis carries the full group name plus its trailing emoji.
    # Highcharts auto-sizes the left margin, but with several 40+ character
    # names ("Housing, Water, Electricity, Gas & Fuels · 🏠") it clamps the
    # labels and truncates them with an ellipsis - which also clips the
    # emoji, since the emoji is last. Reserve a real left gutter sized from
    # the longest label (≈6.4px per glyph at 12px, + room for the emoji and
    # padding), capped so the plot area never collapses, and let labels wrap
    # onto a second line inside that gutter instead of truncating. A matching
    # responsive rule tightens the gutter and shrinks the label font on
    # narrow viewports so nothing clips there either.
    _longest = max((len(c) for c in categories), default=20)
    _label_width = min(210, max(120, int(_longest * 6.4) + 26))
    _margin_left = _label_width + 16
    _label_width_narrow = max(96, int(_label_width * 0.62))
    _margin_left_narrow = _label_width_narrow + 12

    def _bar_chart_options(chart_id: str, name: str, data: list, y_title: str, title_text: str) -> dict:
        return {
            "chart": {
                "type": "bar",
                "backgroundColor": "#FFFFFF",
                "borderColor": "#DFE8E3",
                "borderWidth": 1,
                "borderRadius": 12,
                "style": {"fontFamily": "inherit"},
                "height": height,
                # left/right handled by explicit margins below; keep a little
                # breathing room top and bottom
                "spacing": [16, 12, 12, 8],
                "marginLeft": _margin_left,
                "marginRight": 64,
            },
            "title": {"text": title_text, "align": "center", "margin": 3, "style": {"color": "#14231D", "fontSize": "17px", "fontWeight": "700"}},
            "subtitle": {"text": subtitle_text, "align": "center", "style": {"color": "#66776E", "fontSize": "12px"}},
            "xAxis": {
                "categories": categories,
                "labels": {
                    "align": "right",
                    "x": -10,
                    "style": {
                        **AXIS_LABEL_STYLE,
                        "fontSize": "13px",
                        "width": f"{_label_width}px",
                        "textOverflow": "ellipsis",
                        "whiteSpace": "nowrap",
                        "lineHeight": "15px",
                    },
                },
                "lineColor": "rgba(128,128,128,0.3)",
            },
            "yAxis": {
                "title": {"text": y_title, "style": {**AXIS_TITLE_STYLE, "fontSize": "13px"}},
                "labels": {"style": {**AXIS_LABEL_STYLE, "fontSize": "13px"}},
                "gridLineColor": "#E8EFEB",
                "plotLines": [{"value": 0, "color": "#999999", "width": 1, "zIndex": 3}],
            },
            "legend": {"enabled": False},
            "credits": {"enabled": False},
            "plotOptions": {
                "series": {
                    "borderWidth": 0,
                    "cursor": "pointer",
                    # Selection is synchronized across both charts by the
                    # click handler below, rather than Highcharts toggling
                    # only the individual bar that received the click.
                    "allowPointSelect": False,
                    "states": {
                        "inactive": {"opacity": 0.22},
                        "hover": {"brightness": 0.06},
                        "select": {"borderColor": PBS_GREEN_DARK, "borderWidth": 2, "brightness": -0.04},
                    },
                },
                "bar": {
                    "groupPadding": 0.08,
                    "pointPadding": 0.12,
                    "borderRadius": 5,
                    "maxPointWidth": 22,
                    "dataLabels": {
                        "enabled": True,
                        "format": "{point.custom.label}",
                        # never clip a value label that overhangs the plot edge
                        "crop": False,
                        "overflow": "allow",
                        "style": {"fontSize": "13px", "fontWeight": "600", "color": "#333333", "textOutline": "none"},
                    },
                    "animation": {"duration": 500},
                }
            },
            "responsive": {
                "rules": [
                    {
                        "condition": {"maxWidth": 460},
                        "chartOptions": {
                            "chart": {"marginLeft": _margin_left_narrow, "marginRight": 44},
                            "xAxis": {
                                "labels": {
                                    "x": -6,
                                    "style": {
                                        "color": AXIS_LABEL_STYLE["color"],
                                        "fontSize": "11px",
                                        "width": f"{_label_width_narrow}px",
                                        "textOverflow": "ellipsis",
                                        "whiteSpace": "nowrap",
                                        "lineHeight": "13px",
                                    },
                                }
                            },
                        },
                    }
                ]
            },
            "tooltip": {
                "backgroundColor": "rgba(255,255,255,0.97)",
                "borderColor": "#BFD2C8",
                "borderRadius": 8,
                "shadow": True,
                "headerFormat": "",
                "pointFormat": f"<b>{{point.custom.fullCategory}}</b><br/>{name}: " + "{point.custom.label}",
            },
            "series": [{"name": name, "data": data}],
        }

    left_config = _bar_chart_options(left_id, "MoM", left_pct_pts, "Month-to-month change (%)", left_title)
    right_config = _bar_chart_options(right_id, "YoY", right_pct_pts, "Year-to-year change (%)", right_title)

    components.html(
        f"""
        <div class="hc-group-grid">
            <div class="hc-group-panel">
                <div class="hc-chart-actions">
                    <button type="button" onclick="__downloadChartPng(__leftChart, 'monthly-cpi-movement.png')" title="Capture chart image (PNG)" aria-label="Capture monthly chart image as PNG"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.4-2h7.2L17 7h3v12H4V7Z"/><circle cx="12" cy="13" r="3.5"/></svg></button>
                    <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{left_xlsx}" download="monthly-cpi-movement.xlsx" title="Download chart data (Excel)" aria-label="Download monthly chart data as Excel"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 11h7M9 15h7M9 19h7M12 9v10"/></svg></a>
                </div>
                <div id="{left_id}" style="width:100%;"></div>
            </div>
            <div class="hc-group-panel">
                <div class="hc-chart-actions">
                    <button type="button" onclick="__downloadChartPng(__rightChart, 'annual-cpi-movement.png')" title="Capture chart image (PNG)" aria-label="Capture annual chart image as PNG"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.4-2h7.2L17 7h3v12H4V7Z"/><circle cx="12" cy="13" r="3.5"/></svg></button>
                    <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{right_xlsx}" download="annual-cpi-movement.xlsx" title="Download chart data (Excel)" aria-label="Download annual chart data as Excel"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 11h7M9 15h7M9 19h7M12 9v10"/></svg></a>
                </div>
                <div id="{right_id}" style="width:100%;"></div>
            </div>
        </div>
        <section class="hc-group-heat" aria-live="polite">
            <div class="hc-heat-heading">
                <div>
                    <div class="hc-heat-eyebrow">12 groups · 12 months</div>
                    <h3 id="hc-heat-title">CPI Group Inflation Heat Table</h3>
                    <p id="hc-heat-subtitle"></p>
                </div>
                <div class="hc-heat-controls">
                    <div class="hc-mini-segment" role="group" aria-label="Heat table measure">
                        <button id="hc-heat-mom" class="active" onclick="__setHeatMeasure('mom')" title="Month-over-month change">ΔM&nbsp; MoM</button>
                        <button id="hc-heat-yoy" onclick="__setHeatMeasure('yoy')" title="Year-over-year change">ΔY&nbsp; YoY</button>
                    </div>
                    <label class="hc-scale-control" title="Choose how color intensity is normalized">
                        <span aria-hidden="true">◐</span>
                        <select id="hc-heat-scale" onchange="__setHeatScale(this.value)" aria-label="Heat table color scale">
                            <option value="row">Row-wise</option>
                            <option value="column">Column-wise</option>
                        </select>
                    </label>
                </div>
            </div>
            <div class="hc-heat-table-wrap">
                <table class="hc-heat-table">
                    <thead id="hc-heat-head"></thead>
                    <tbody id="hc-heat-body"></tbody>
                </table>
            </div>
            <div class="hc-heat-legend"><span class="cool"></span>Negative change <i></i><span class="warm"></span>Positive change <small>Shade intensity reflects magnitude across the displayed matrix</small></div>
            <div class="hc-item-drilldown" id="hc-item-drilldown">
                <div class="hc-drill-head">
                    <div class="hc-drill-identity"><h3 id="hc-drill-title"></h3><p id="hc-drill-subtitle"></p></div>
                    <div class="hc-item-controls">
                        <label title="Selected CPI weight"><span>W</span><select id="hc-item-weight" onchange="__setItemWeight(this.value)"><option value="0">Overall</option><option value="1">Q1</option><option value="2">Q2</option><option value="3">Q3</option><option value="4">Q4</option><option value="5">Q5</option></select></label>
                        <div class="hc-mini-segment" role="group" aria-label="Item price change measure"><button id="hc-item-mom" class="active" onclick="__setItemMeasure('mom')">MoM</button><button id="hc-item-yoy" onclick="__setItemMeasure('yoy')">YoY</button></div>
                        <label title="Price-change color scaling"><span>◐</span><select id="hc-item-scale" onchange="__setItemScale(this.value)"><option value="row">Row scale</option><option value="column">Column scale</option></select></label>
                        <button class="hc-sort-btn" id="hc-item-sort" onclick="__toggleItemSort()" title="Sort by selected weight">↓ W</button>
                        <a class="hc-mini-icon" href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{drilldown_xlsx}" download="cpi-item-drilldown-12-months.xlsx" title="Download item data (Excel)" aria-label="Download item drilldown data as Excel"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 11h7M9 15h7M9 19h7M12 9v10"/></svg></a>
                    </div>
                </div>
                <div class="hc-group-summary" id="hc-group-summary"></div>
                <div class="hc-weight-table-wrap"><table class="hc-weight-table"><thead id="hc-weight-head"></thead><tbody id="hc-weight-body"></tbody></table></div>
                <section class="hc-city-map" id="hc-city-map" aria-live="polite">
                    <div class="hc-map-head">
                        <div class="hc-map-heading">
                            <div class="hc-map-eyebrow">Spatial price intelligence</div>
                            <h3 id="hc-map-title">City Price Distribution</h3>
                            <p id="hc-map-subtitle">Select an item-month cell to compare prices across CPI cities.</p>
                        </div>
                        <div class="hc-map-controls">
                            <label class="hc-map-metric" title="Choose the mapped price measure">
                                <span>Metric</span>
                                <select id="hc-map-metric" onchange="__setMapMetric(this.value)" aria-label="Map price metric">
                                    <option value="price">Price</option>
                                    <option value="mom">MoM change</option>
                                    <option value="yoy">YoY change</option>
                                </select>
                            </label>
                            <div class="hc-map-levels" role="group" aria-label="Map geography level">
                                <button id="hc-map-province" class="active" onclick="__setMapLevel('province')">Province</button>
                                <button id="hc-map-division" onclick="__setMapLevel('division')">Division</button>
                                <button id="hc-map-district" onclick="__setMapLevel('district')">District</button>
                            </div>
                            <div class="hc-map-actions">
                                <button id="hc-map-label-toggle" type="button" onclick="__toggleMapLabels()" title="Hide map value labels" aria-label="Toggle map value labels" aria-pressed="true"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14M12 6v12M8.5 18h7"/></svg></button>
                                <button type="button" onclick="__downloadMapPng()" title="Capture map image (PNG)" aria-label="Capture price map as PNG"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.4-2h7.2L17 7h3v12H4V7Z"/><circle cx="12" cy="13" r="3.5"/></svg></button>
                                <button type="button" onclick="__downloadMapExcel()" title="Download mapped price data (Excel)" aria-label="Download mapped price data as Excel"><svg class="hc-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 11h7M9 15h7M12 9v10"/></svg></button>
                            </div>
                        </div>
                    </div>
                    <p class="hc-map-extremes" id="hc-map-extremes"></p>
                    <div class="hc-map-layout">
                        <div class="hc-map-visual">
                            <div class="hc-map-stage" id="hc-map-stage">
                                <svg id="hc-price-map-svg" viewBox="0 0 1000 530" role="img" aria-labelledby="hc-map-title hc-map-subtitle"></svg>
                                <div class="hc-map-tooltip" id="hc-map-tooltip"></div>
                                <div class="hc-map-compass" aria-hidden="true"><b>N</b><i></i></div>
                                <div class="hc-map-zoom" role="group" aria-label="Map zoom controls">
                                    <button id="hc-map-zoom-in" type="button" onclick="__zoomMap(1)" title="Zoom in" aria-label="Zoom map in">+</button>
                                    <button id="hc-map-zoom-out" type="button" onclick="__zoomMap(-1)" title="Zoom out" aria-label="Zoom map out" disabled>−</button>
                                </div>
                                <div class="hc-map-hint">Click an area to focus its reporting cities</div>
                            </div>
                            <div class="hc-map-legend">
                                <span id="hc-map-legend-low">Low</span>
                                <div class="hc-map-gradient" aria-hidden="true"></div>
                                <span id="hc-map-legend-mid"></span>
                                <span id="hc-map-legend-high">High</span>
                                <small id="hc-map-legend-note">Dynamic average-price scale</small>
                            </div>
                        </div>
                        <aside class="hc-city-panel">
                            <div class="hc-city-panel-head"><div><span id="hc-city-scope">Reporting centres</span><strong id="hc-city-panel-title">City-wise prices</strong></div><div class="hc-city-panel-tools"><button id="hc-map-clear-area" type="button" onclick="__clearMapAreaFocus()" title="Show all reporting cities">All areas ×</button><b id="hc-city-count">0</b></div></div>
                            <div class="hc-city-table-wrap"><table class="hc-city-table"><thead><tr><th>#</th><th>City</th><th id="hc-city-value-head">Price</th></tr></thead><tbody id="hc-city-price-body"></tbody></table></div>
                        </aside>
                    </div>
                    <div class="hc-map-note">Price uses the equal-city arithmetic mean. MoM and YoY use a matched-city method: current and comparison-period means are calculated from the same reporting cities, then change = (current mean ÷ comparison mean − 1) × 100. Percentages are never averaged. Geography is linked through IMIS.dbo.PVD; Karachi retains dv code 18 in district view.</div>
                </section>
            </div>
        </section>
        <style>
            .hc-group-grid {{ display:flex; flex-wrap:wrap; gap:12px; }}
            .hc-group-panel {{ position:relative; flex:1 1 380px; min-width:280px; }}
            .hc-chart-actions {{ position:absolute; z-index:8; top:12px; right:13px; display:flex; gap:5px; }}
            .hc-chart-actions button, .hc-chart-actions a {{
                width:30px; height:30px; padding:0; box-sizing:border-box;
                display:inline-flex; align-items:center; justify-content:center;
                border:1px solid #c8d8d0; border-radius:7px; background:#fff;
                color:#21382e; text-decoration:none; cursor:pointer;
                box-shadow:0 1px 2px rgba(18,49,37,.04);
            }}
            .hc-action-icon {{ width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
            .hc-chart-actions button:hover, .hc-chart-actions a:hover {{ border-color:#0b6e4f; color:#07533c; background:#f3faf7; }}
            .hc-group-heat {{
                margin-top:12px; padding:13px 15px 12px; background:#fff;
                border:1px solid #dfe8e3; border-radius:12px;
                box-shadow:0 4px 14px rgba(18,49,37,.055);
            }}
            .hc-heat-heading {{ display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-bottom:10px; }}
            .hc-heat-eyebrow {{ color:#0b6e4f; font:750 9px -apple-system,sans-serif; letter-spacing:.13em; text-transform:uppercase; }}
            .hc-heat-heading h3 {{ margin:2px 0 0; color:#14231d; font:720 15px -apple-system,sans-serif; }}
            .hc-heat-heading p {{ margin:2px 0 0; color:#718078; font:500 10px -apple-system,sans-serif; }}
            .hc-heat-hint {{ color:#607269; background:#f1f6f3; border:1px solid #dce8e2; border-radius:999px; padding:4px 8px; font:650 9px -apple-system,sans-serif; white-space:nowrap; }}
            .hc-heat-controls {{ display:flex; align-items:center; gap:6px; white-space:nowrap; }}
            .hc-mini-segment {{ display:inline-flex; height:28px; padding:2px; border:1px solid #c8d8d0; border-radius:8px; background:#eef4f1; box-sizing:border-box; }}
            .hc-mini-segment button {{ height:22px; padding:0 8px; border:0; border-radius:5px; background:transparent; color:#52665c; cursor:pointer; font:650 9px -apple-system,sans-serif; }}
            .hc-mini-segment button:hover {{ color:#07533c; }}
            .hc-mini-segment button.active {{ color:#07533c; background:#fff; box-shadow:0 1px 3px rgba(18,49,37,.13); }}
            .hc-scale-control {{ height:28px; display:inline-flex; align-items:center; gap:3px; padding:0 4px 0 7px; border:1px solid #c8d8d0; border-radius:8px; background:#fff; color:#315044; box-sizing:border-box; }}
            .hc-scale-control select {{ height:24px; max-width:105px; border:0; outline:0; background:transparent; color:#315044; cursor:pointer; font:650 9px -apple-system,sans-serif; }}
            .hc-heat-table-wrap {{ overflow-x:auto; }}
            .hc-heat-table {{ width:100%; min-width:1120px; border-collapse:separate; border-spacing:3px; table-layout:fixed; font:600 10px -apple-system,sans-serif; }}
            .hc-heat-table th {{ padding:2px 7px 5px; color:#607269; text-align:center; font-size:9px; letter-spacing:.08em; text-transform:uppercase; }}
            .hc-heat-table th:first-child, .hc-heat-table td:first-child {{ width:68px; text-align:left; }}
            .hc-heat-table td {{ padding:7px 9px; border-radius:6px; text-align:center; color:#243c32; font-variant-numeric:tabular-nums; }}
            .hc-heat-table td:not(:first-child) {{ cursor:pointer; transition:transform .12s ease,outline-color .12s ease; }}
            .hc-heat-table td:not(:first-child):hover {{ transform:translateY(-1px); outline:2px solid #07533c; outline-offset:-1px; }}
            .hc-heat-table td.hc-selected-cell {{ outline:2px solid #054a34; outline-offset:-2px; box-shadow:0 0 0 2px rgba(5,74,52,.12); }}
            .hc-heat-table td:first-child {{ background:#f5f8f6; color:#52665c; }}
            .hc-heat-legend {{ display:flex; align-items:center; gap:5px; margin-top:7px; color:#607269; font:500 9px -apple-system,sans-serif; }}
            .hc-heat-legend span {{ width:9px; height:9px; border-radius:3px; }}
            .hc-heat-legend .cool {{ background:rgba(0,158,115,.58); }} .hc-heat-legend .warm {{ background:rgba(213,94,0,.58); }}
            .hc-heat-legend i {{ width:8px; }} .hc-heat-legend small {{ margin-left:auto; font-size:9px; }}
            .hc-item-drilldown {{ margin-top:14px; padding-top:13px; border-top:1px solid #dfe8e3; }}
            .hc-drill-head {{ display:flex; justify-content:space-between; align-items:center; gap:14px; padding:10px 11px 10px 13px; border:1px solid #d8e5de; border-left:4px solid #0b6e4f; border-radius:10px; background:linear-gradient(135deg,#f7fbf9,#eef6f2); box-shadow:0 2px 8px rgba(18,49,37,.045); }}
            .hc-drill-identity {{ min-width:0; }}
            .hc-drill-head h3 {{ margin:0; color:#10291f; font:750 17px/1.08 -apple-system,sans-serif; letter-spacing:-.015em; }}
            .hc-drill-head p {{ margin:4px 0 0; color:#607269; font:580 10px/1.2 -apple-system,sans-serif; white-space:nowrap; }}
            .hc-item-controls {{ display:flex; align-items:center; justify-content:flex-end; gap:5px; flex-wrap:wrap; }}
            .hc-item-controls label {{ height:28px; display:inline-flex; align-items:center; gap:3px; padding:0 4px 0 7px; border:1px solid #c8d8d0; border-radius:8px; background:#fff; color:#315044; box-sizing:border-box; }}
            .hc-item-controls select {{ height:24px; border:0; outline:0; background:transparent; color:#315044; cursor:pointer; font:650 9px -apple-system,sans-serif; }}
            .hc-sort-btn {{ height:28px; padding:0 8px; border:1px solid #c8d8d0; border-radius:8px; background:#fff; color:#315044; cursor:pointer; font:700 9px -apple-system,sans-serif; }}
            .hc-mini-icon {{ width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; box-sizing:border-box; border:1px solid #c8d8d0; border-radius:8px; background:#fff; color:#315044; text-decoration:none; }}
            .hc-sort-btn:hover,.hc-item-controls label:hover,.hc-mini-icon:hover {{ border-color:#0b6e4f; background:#f3faf7; }}
            .hc-group-summary {{ display:flex; align-items:center; flex-wrap:wrap; gap:0; margin:10px 1px 9px; padding:2px 0; color:#53675d; font:550 10px/1.45 -apple-system,sans-serif; }}
            .hc-summary-part {{ display:inline-flex; align-items:baseline; gap:4px; padding:0 12px; border-right:1px solid #d7e3dd; }}
            .hc-summary-part:first-child {{ padding-left:0; }}
            .hc-summary-part:last-child {{ border-right:0; }}
            .hc-summary-part strong {{ color:#123c2d; font-size:12px; font-weight:750; font-variant-numeric:tabular-nums; }}
            .hc-summary-leader {{ color:#263f35; }}
            .hc-summary-leader strong {{ color:#07533c; }}
            .hc-weight-table-wrap {{ max-height:390px; overflow:auto; margin-top:9px; border:1px solid #dfe8e3; border-radius:9px; }}
            .hc-weight-table {{ width:100%; min-width:1450px; border-collapse:separate; border-spacing:0; table-layout:fixed; font:550 9px -apple-system,sans-serif; }}
            .hc-weight-table th {{ position:sticky; top:0; z-index:2; padding:7px 6px; background:#edf4f0; color:#52665c; border-bottom:1px solid #d7e3dd; font-size:8px; letter-spacing:.06em; text-transform:uppercase; }}
            .hc-weight-table th:first-child {{ width:220px; text-align:left; }}
            .hc-weight-table td {{ padding:9px 7px; border-bottom:1px solid #edf2ef; text-align:center; color:#2e453b; font-variant-numeric:tabular-nums; line-height:1.32; }}
            .hc-weight-table th:first-child {{ position:sticky; left:0; z-index:4; background:#e8f1ec; box-shadow:2px 0 4px rgba(18,49,37,.08); }}
            .hc-weight-table td:first-child {{ position:sticky; left:0; z-index:1; text-align:left; font-weight:650; background:#fff; box-shadow:2px 0 4px rgba(18,49,37,.06); }}
            .hc-weight-table tr:hover td {{ box-shadow:inset 0 0 0 999px rgba(11,110,79,.035); }}
            .hc-weight-table td.hc-map-trigger {{ cursor:pointer; transition:box-shadow .12s ease, transform .12s ease; }}
            .hc-weight-table td.hc-map-trigger:hover {{ outline:2px solid #0b6e4f; outline-offset:-2px; transform:translateY(-1px); }}
            .hc-weight-table td.hc-map-selected {{ outline:2px solid #07533c; outline-offset:-2px; box-shadow:inset 0 0 0 999px rgba(11,110,79,.08); }}
            .hc-city-map {{ margin-top:16px; padding:15px 14px 12px; overflow:hidden; border:1px solid #d8e5de; border-radius:14px; background:linear-gradient(155deg,#ffffff 0%,#fbfdfc 52%,#f7faf8 100%); box-shadow:0 8px 26px rgba(21,56,43,.06); }}
            .hc-map-head {{ min-height:54px; display:grid; grid-template-columns:1fr auto 1fr; align-items:start; gap:14px; padding:0 0 8px; }}
            .hc-map-heading {{ text-align:center; min-width:0; }}
            .hc-map-heading {{ grid-column:2; }}
            .hc-map-eyebrow {{ color:#0b6e4f; font:760 9px -apple-system,sans-serif; letter-spacing:.13em; text-transform:uppercase; }}
            .hc-map-heading h3 {{ margin:3px 0 0; color:#14231d; font:750 17px/1.1 -apple-system,sans-serif; letter-spacing:-.012em; }}
            .hc-map-heading p {{ margin:4px 0 0; color:#687a71; font:540 10px/1.3 -apple-system,sans-serif; }}
            .hc-map-controls {{ grid-column:3; justify-self:end; display:flex; align-items:center; gap:6px; }}
            .hc-map-metric {{ height:30px; display:inline-flex; align-items:center; overflow:hidden; border:1px solid #c8d8d0; border-radius:8px; background:#fff; color:#607269; box-sizing:border-box; }}
            .hc-map-metric span {{ padding:0 6px 0 8px; font:720 8px -apple-system,sans-serif; letter-spacing:.06em; text-transform:uppercase; }}
            .hc-map-metric select {{ height:28px; padding:0 23px 0 7px; border:0; border-left:1px solid #dce6e1; outline:0; background:#f7fbf9; color:#15382b; cursor:pointer; font:700 9px -apple-system,sans-serif; }}
            .hc-map-levels {{ display:inline-flex; height:30px; padding:2px; border:1px solid #c8d8d0; border-radius:8px; background:#eef6f2; box-sizing:border-box; }}
            .hc-map-levels button {{ height:24px; padding:0 8px; border:0; border-radius:5px; background:transparent; color:#46685a; cursor:pointer; font:680 9px -apple-system,sans-serif; }}
            .hc-map-levels button:hover {{ color:#07533c; }}
            .hc-map-levels button.active {{ color:#fff; background:#0b6e4f; box-shadow:0 1px 3px rgba(7,83,60,.2); }}
            .hc-map-actions {{ display:flex; gap:5px; }}
            .hc-map-actions button {{ width:30px; height:30px; padding:0; display:inline-flex; align-items:center; justify-content:center; border:1px solid #c8d8d0; border-radius:7px; background:#fff; color:#21382e; cursor:pointer; box-shadow:0 1px 2px rgba(18,49,37,.04); }}
            .hc-map-actions button:hover,.hc-map-actions button.active {{ border-color:#0b6e4f; color:#07533c; background:#eef8f3; }}
            .hc-map-extremes {{ margin:4px 0 9px; color:#607269; font:560 10px/1.35 -apple-system,sans-serif; }}
            .hc-map-extremes strong {{ color:#15382b; font-weight:760; font-variant-numeric:tabular-nums; }}
            .hc-map-extremes .hc-map-divider {{ margin:0 8px; color:#c9d5cf; }}
            .hc-map-layout {{ display:grid; grid-template-columns:minmax(0,2fr) minmax(245px,1fr); gap:10px; height:520px; align-items:stretch; }}
            .hc-map-visual {{ min-width:0; min-height:0; display:grid; grid-template-rows:minmax(0,1fr) auto; gap:7px; }}
            .hc-map-stage {{ position:relative; min-height:0; overflow:hidden; border:1px solid #dce7e1; border-radius:12px; background:radial-gradient(circle at 50% 43%,#ffffff 0,#f7fbf9 66%,#edf5f1 100%); box-shadow:inset 0 0 0 1px rgba(255,255,255,.7),0 3px 12px rgba(21,56,43,.05); }}
            .hc-map-stage::before {{ content:""; position:absolute; inset:0; pointer-events:none; background-image:linear-gradient(rgba(11,110,79,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(11,110,79,.025) 1px,transparent 1px); background-size:28px 28px; }}
            #hc-price-map-svg {{ position:relative; z-index:1; display:block; width:100%; height:100%; min-height:0; }}
            .hc-map-district {{ vector-effect:non-scaling-stroke; stroke:#fff; stroke-width:.75; cursor:pointer; transition:opacity .18s ease,fill .18s ease,stroke .12s ease,filter .12s ease; }}
            .hc-map-district:hover {{ stroke:#5d1713; stroke-width:1.45; filter:drop-shadow(0 1px 2px rgba(91,20,16,.26)); }}
            .hc-map-district.hc-area-muted {{ opacity:.2; filter:saturate(.35); }}
            .hc-map-district.hc-area-focused {{ stroke:#123f30; stroke-width:2.2; filter:drop-shadow(0 2px 4px rgba(7,83,60,.3)); }}
            .hc-map-city-dot {{ fill:#fff; stroke:#8f201b; stroke-width:1.25; vector-effect:non-scaling-stroke; }}
            .hc-map-city-label {{ fill:#681713; paint-order:stroke; stroke:rgba(255,255,255,.95); stroke-width:3px; stroke-linejoin:round; font:750 9px -apple-system,sans-serif; text-anchor:middle; pointer-events:none; }}
            .hc-map-stage.hc-labels-hidden .hc-map-city-label {{ display:none; }}
            .hc-map-tooltip {{ position:absolute; z-index:5; display:none; min-width:145px; max-width:220px; padding:8px 9px; border:1px solid #dfb9b5; border-radius:8px; background:rgba(255,255,255,.98); color:#4e312e; box-shadow:0 5px 18px rgba(77,20,16,.17); pointer-events:none; font:520 10px/1.35 -apple-system,sans-serif; }}
            .hc-map-tooltip strong {{ display:block; color:#531713; font-size:11px; }}
            .hc-map-tooltip b {{ color:#9c241e; font-size:12px; font-variant-numeric:tabular-nums; }}
            .hc-map-empty {{ fill:#718078; font:600 14px -apple-system,sans-serif; text-anchor:middle; }}
            .hc-map-compass {{ position:absolute; z-index:2; top:11px; left:12px; display:grid; justify-items:center; color:#315b4a; font:760 8px -apple-system,sans-serif; opacity:.72; }}
            .hc-map-compass i {{ width:0; height:0; margin-top:2px; border-right:4px solid transparent; border-bottom:13px solid #0b6e4f; border-left:4px solid transparent; }}
            .hc-map-zoom {{ position:absolute; z-index:3; top:10px; right:10px; display:grid; overflow:hidden; border:1px solid #bfd3c9; border-radius:8px; background:rgba(255,255,255,.94); box-shadow:0 3px 10px rgba(21,56,43,.12); backdrop-filter:blur(4px); }}
            .hc-map-zoom button {{ width:29px; height:28px; padding:0; border:0; background:transparent; color:#174c39; cursor:pointer; font:500 19px/1 -apple-system,sans-serif; }}
            .hc-map-zoom button+button {{ border-top:1px solid #dce7e1; }}
            .hc-map-zoom button:hover:not(:disabled) {{ background:#eaf5ef; color:#07533c; }}
            .hc-map-zoom button:disabled {{ color:#a9b8b1; cursor:default; }}
            .hc-map-hint {{ position:absolute; z-index:2; right:10px; bottom:9px; padding:4px 7px; border:1px solid rgba(200,216,208,.9); border-radius:6px; background:rgba(255,255,255,.88); color:#607269; pointer-events:none; font:620 8px -apple-system,sans-serif; backdrop-filter:blur(3px); }}
            .hc-map-legend {{ display:grid; grid-template-columns:auto minmax(140px,1fr) auto auto minmax(110px,auto); align-items:center; gap:7px; color:#6b4a47; font:650 9px -apple-system,sans-serif; font-variant-numeric:tabular-nums; }}
            .hc-map-gradient {{ height:9px; border-radius:999px; background:linear-gradient(90deg,#fff4ef 0%,#fdc9bd 20%,#fb806c 42%,#e43f32 64%,#a71918 82%,#65000d 100%); box-shadow:inset 0 0 0 1px rgba(101,0,13,.16); }}
            .hc-map-legend small {{ justify-self:end; color:#718078; font-size:9px; font-weight:500; }}
            .hc-city-panel {{ min-width:0; min-height:0; height:100%; display:flex; flex-direction:column; overflow:hidden; border:1px solid #dce7e1; border-radius:12px; background:#fff; box-shadow:0 3px 12px rgba(21,56,43,.045); }}
            .hc-city-panel-head {{ flex:none; display:flex; align-items:center; justify-content:space-between; gap:8px; padding:11px 12px 9px; border-bottom:1px solid #dce8e2; background:linear-gradient(145deg,#f9fcfa,#edf6f1); }}
            .hc-city-panel-head span {{ display:block; overflow:hidden; color:#527064; font:740 8px/1.1 -apple-system,sans-serif; letter-spacing:.09em; text-overflow:ellipsis; text-transform:uppercase; white-space:nowrap; }}
            .hc-city-panel-head strong {{ display:block; margin-top:3px; color:#173a2d; font:750 13px/1.1 -apple-system,sans-serif; }}
            .hc-city-panel-tools {{ display:flex; align-items:center; gap:5px; }}
            .hc-city-panel-tools button {{ display:none; height:24px; padding:0 7px; border:1px solid #bcd3c8; border-radius:6px; background:#fff; color:#315b4a; cursor:pointer; font:680 8px -apple-system,sans-serif; }}
            .hc-city-panel-tools button.visible {{ display:inline-flex; align-items:center; }}
            .hc-city-panel-head b {{ min-width:25px; padding:4px 7px; border-radius:999px; background:#0b6e4f; color:#fff; text-align:center; font:750 10px -apple-system,sans-serif; }}
            .hc-city-table-wrap {{ flex:1; min-height:0; overflow-y:auto; scrollbar-width:thin; scrollbar-color:#d69b95 #f7eeee; }}
            .hc-city-table {{ width:100%; border-collapse:separate; border-spacing:0; table-layout:fixed; font:560 10px -apple-system,sans-serif; }}
            .hc-city-table th {{ position:sticky; top:0; z-index:2; padding:7px 8px; border-bottom:1px solid #dce8e2; background:#f2f8f5; color:#527064; text-align:left; font-size:8px; letter-spacing:.07em; text-transform:uppercase; }}
            .hc-city-table th:first-child,.hc-city-table td:first-child {{ width:25px; text-align:center; }}
            .hc-city-table th:last-child,.hc-city-table td:last-child {{ width:76px; text-align:right; }}
            .hc-city-table td {{ padding:7px 8px; border-bottom:1px solid #f3e8e6; color:#523c39; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-variant-numeric:tabular-nums; }}
            .hc-city-table tr:hover td {{ background:#f4faf7; }}
            .hc-city-price {{ display:inline-flex; align-items:center; justify-content:flex-end; gap:6px; color:#23483a; font-weight:720; }}
            .hc-city-swatch {{ width:7px; height:18px; flex:none; border-radius:3px; }}
            .hc-map-note {{ margin-top:6px; color:#718078; font:500 9px/1.35 -apple-system,sans-serif; }}
            @media(max-width:560px) {{ .hc-heat-hint,.hc-heat-legend small {{ display:none; }} .hc-heat-heading {{ align-items:flex-start; flex-direction:column; }} }}
            @media(max-width:900px) {{ .hc-map-head {{ grid-template-columns:1fr; }} .hc-map-heading,.hc-map-controls {{ grid-column:1; justify-self:center; }} .hc-map-layout {{ grid-template-columns:1fr; height:auto; }} .hc-map-visual {{ height:500px; }} .hc-city-panel {{ height:340px; }} }}
            @media(max-width:650px) {{ .hc-drill-head {{ align-items:flex-start; flex-direction:column; }} .hc-drill-head p {{ white-space:normal; }} .hc-summary-part {{ padding:2px 8px; }} .hc-map-extremes {{ line-height:1.55; }} .hc-map-divider {{ display:none; }} .hc-map-extremes span {{ display:block; }} .hc-map-legend {{ grid-template-columns:auto 1fr auto; }} .hc-map-legend #hc-map-legend-mid,.hc-map-legend small {{ display:none; }} .hc-map-controls {{ flex-wrap:wrap; }} }}
        </style>
        <script>{_highstock_js()}</script>
        <script>
            var __leftPct = {json.dumps(left_pct_pts)};
            var __rightPct = {json.dumps(right_pct_pts)};
            var __heatMatrix = {json.dumps(heat_matrix)};
            var __heatGroups = {json.dumps(heat_groups)};
            var __heatItems = {json.dumps(heat_items)};
            var __cityPrices = {json.dumps(city_prices)};
            var __districtCityMap = {json.dumps(district_city_map)};
            var __geoJSONLevels = {json.dumps(geojson_levels, separators=(',', ':'))};
            var __selectedHeatMeasure = 'mom';
            var __heatScaleMode = 'row';
            var __selectedHeatPeriod = null;
            var __selectedHeatGroup = null;
            var __itemWeightIndex = 0;
            var __itemMeasure = 'mom';
            var __itemScaleMode = 'row';
            var __itemSortDescending = true;
            var __selectedMapItem = null;
            var __selectedMapPeriod = null;
            var __selectedMapLevel = 'province';
            var __selectedMapMetric = 'price';
            var __mapLabelsVisible = true;
            var __mapZoomLevels = [1,1.25,1.6,2,2.5,3.2];
            var __mapZoomIndex = 0;
            var __mapZoomAnimation = null;
            var __selectedMapAreaCode = null;
            var __selectedMapAreaName = '';
            var __allCityRows = [];
            var __cityValueMinimum = 0;
            var __cityValueMaximum = 0;
            var __activeItemMeta = {{}};
            var __currentMapRows = [];
            var __currentCityRows = [];

            var __leftChart = Highcharts.chart('{left_id}', {json.dumps(left_config)});
            var __rightChart = Highcharts.chart('{right_id}', {json.dumps(right_config)});

            function __heatCell(value, scale, period, groupCode, measure) {{
                if (value === null || value === undefined) return '<td style="background:#f4f7f5;color:#8a9690">—</td>';
                var directionalScale = value < 0 ? scale.negative : scale.positive;
                var intensity = Math.min(Math.abs(value) / Math.max(directionalScale, .01), 1);
                var alpha = (.10 + intensity * .48).toFixed(2);
                var rgb = value < 0 ? '0,158,115' : '213,94,0';
                var ink = value < 0 ? '#07533c' : '#7f2e12';
                var text = (value > 0 ? '+' : '') + Number(value).toFixed(2) + '%';
                var extreme = (value > 0 && Math.abs(value-scale.positive)<.000001)
                    || (value < 0 && Math.abs(Math.abs(value)-scale.negative)<.000001);
                return '<td data-period="' + period + '" data-group="' + groupCode + '" data-measure="' + measure + '" style="background:rgba(' + rgb + ',' + alpha + ');color:' + ink + ';font-weight:' + (extreme?'750':'500') + '">' + text + '</td>';
            }}
            function __esc(value) {{
                return String(value === null || value === undefined ? '' : value)
                    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
            }}
            function __num(value, digits) {{
                return value === null || value === undefined || !isFinite(value)
                    ? '—' : Number(value).toLocaleString(undefined, {{minimumFractionDigits:digits, maximumFractionDigits:digits}});
            }}
            function __median(values) {{
                if (!values.length) return null;
                values = values.slice().sort(function(a,b) {{ return a-b; }});
                var mid = Math.floor(values.length / 2);
                return values.length % 2 ? values[mid] : (values[mid-1] + values[mid]) / 2;
            }}
            function __shiftPeriod(period, delta) {{
                var parts=period.split('-'), date=new Date(Date.UTC(Number(parts[0]),Number(parts[1])-1+delta,1));
                return date.getUTCFullYear()+'-'+String(date.getUTCMonth()+1).padStart(2,'0');
            }}
            function __periodLabel(period) {{ var d=new Date(period+'-01T00:00:00Z'); return d.toLocaleString('en',{{month:'short',year:'numeric',timeZone:'UTC'}}); }}
            function __priceFormat(value) {{ return Number(value).toLocaleString(undefined, {{minimumFractionDigits:2,maximumFractionDigits:2}}); }}
            function __walkCoordinates(value, callback) {{
                if (Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number') {{ callback(value); return; }}
                if (Array.isArray(value)) value.forEach(function(part) {{ __walkCoordinates(part, callback); }});
            }}
            function __featureCenter(feature) {{
                var minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
                __walkCoordinates(feature.geometry.coordinates,function(point){{minX=Math.min(minX,point[0]);maxX=Math.max(maxX,point[0]);minY=Math.min(minY,point[1]);maxY=Math.max(maxY,point[1]);}});
                return [(minX+maxX)/2,(minY+maxY)/2];
            }}
            function __mapProjection(geoJSON) {{
                var minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
                geoJSON.features.forEach(function(feature){{
                    __walkCoordinates(feature.geometry.coordinates,function(point){{minX=Math.min(minX,point[0]);maxX=Math.max(maxX,point[0]);minY=Math.min(minY,point[1]);maxY=Math.max(maxY,point[1]);}});
                }});
                var width=1000,height=530,pad=18,lonFactor=Math.cos(((minY+maxY)/2)*Math.PI/180);
                var spanX=(maxX-minX)*lonFactor,spanY=maxY-minY,scale=Math.min((width-pad*2)/spanX,(height-pad*2)/spanY);
                var offsetX=(width-spanX*scale)/2,offsetY=(height-spanY*scale)/2;
                return function(point){{return [offsetX+(point[0]-minX)*lonFactor*scale,offsetY+(maxY-point[1])*scale];}};
            }}
            function __geometryPath(geometry, project) {{
                function ringPath(ring){{return ring.map(function(point,index){{var p=project(point);return (index?'L':'M')+p[0].toFixed(2)+' '+p[1].toFixed(2);}}).join('')+'Z';}}
                if (geometry.type==='Polygon') return geometry.coordinates.map(ringPath).join('');
                if (geometry.type==='MultiPolygon') return geometry.coordinates.map(function(polygon){{return polygon.map(ringPath).join('');}}).join('');
                return '';
            }}
            function __interpolateColor(low,high,t) {{
                var a=low.match(/\\w\\w/g).map(function(x){{return parseInt(x,16);}}),b=high.match(/\\w\\w/g).map(function(x){{return parseInt(x,16);}});
                return '#'+a.map(function(value,index){{return Math.round(value+(b[index]-value)*t).toString(16).padStart(2,'0');}}).join('');
            }}
            function __mapColor(value,minimum,maximum) {{
                var t=maximum===minimum?.58:Math.pow(Math.max(0,Math.min(1,(value-minimum)/(maximum-minimum))),.72);
                var colors=['fff4ef','fdc9bd','fb806c','e43f32','a71918','65000d'];
                var position=t*(colors.length-1),index=Math.min(colors.length-2,Math.floor(position));
                return __interpolateColor(colors[index],colors[index+1],position-index);
            }}
            function __mapChangeColor(value,minimum,maximum) {{
                var limit=Math.max(Math.abs(minimum),Math.abs(maximum),.01),strength=Math.pow(Math.min(Math.abs(value)/limit,1),.68);
                if(Math.abs(value)<.000001)return '#f6f2ef';
                return value<0?__interpolateColor('e8f6f0','006747',strength):__interpolateColor('fff0ec','8f1011',strength);
            }}
            function __mapValueColor(value,minimum,maximum) {{
                return __selectedMapMetric==='price'?__mapColor(value,minimum,maximum):__mapChangeColor(value,minimum,maximum);
            }}
            function __mapValueFormat(value) {{
                return __selectedMapMetric==='price'?__priceFormat(value):(value>0?'+':'')+__num(value,2)+'%';
            }}
            function __mapMetricMeta() {{
                if(__selectedMapMetric==='mom')return {{label:'MoM Price Change',short:'MoM change',delta:-1}};
                if(__selectedMapMetric==='yoy')return {{label:'YoY Price Change',short:'YoY change',delta:-12}};
                return {{label:'Average Price',short:'Price',delta:0}};
            }}
            function __showMapTooltip(event, html) {{
                var tooltip=document.getElementById('hc-map-tooltip'),stage=document.getElementById('hc-map-stage'),rect=stage.getBoundingClientRect();
                tooltip.innerHTML=html;tooltip.style.display='block';
                var left=Math.min(event.clientX-rect.left+12,rect.width-tooltip.offsetWidth-8),top=Math.min(event.clientY-rect.top+12,rect.height-tooltip.offsetHeight-8);
                tooltip.style.left=Math.max(8,left)+'px';tooltip.style.top=Math.max(8,top)+'px';
            }}
            function __mapLevelLabel(level) {{ return level==='province'?'Province':level==='division'?'Division':'District'; }}
            function __mapAreaIdentity(mapping,level) {{
                if(level==='province')return {{code:String(mapping.provinceCode),name:mapping.provinceName}};
                if(level==='division')return {{code:String(mapping.divisionCode),name:mapping.divisionName}};
                if(Number(mapping.cityCode)===18)return {{code:'18',name:'KARACHI DIVISION'}};
                return {{code:String(mapping.districtCode),name:mapping.districtName}};
            }}
            function __aggregateMapAreas(currentByCity, previousByCity, level, metric) {{
                var grouped={{}};
                __districtCityMap.forEach(function(mapping){{
                    var cityCode=String(mapping.cityCode),current=currentByCity[cityCode],previous=previousByCity[cityCode];
                    if(current===undefined||(metric!=='price'&&previous===undefined))return;
                    var identity=__mapAreaIdentity(mapping,level),code=identity.code,name=identity.name;
                    if(!grouped[code])grouped[code]={{code:code,name:name,current:{{}},previous:{{}}}};
                    grouped[code].current[cityCode]=current;
                    if(metric!=='price')grouped[code].previous[cityCode]=previous;
                }});
                var result={{}};
                Object.keys(grouped).forEach(function(code){{
                    var group=grouped[code],cityCodes=Object.keys(group.current),currentValues=cityCodes.map(function(cityCode){{return group.current[cityCode];}});
                    var currentAverage=currentValues.reduce(function(total,value){{return total+value;}},0)/currentValues.length,previousAverage=null,value=currentAverage;
                    if(metric!=='price'){{
                        var previousValues=cityCodes.map(function(cityCode){{return group.previous[cityCode];}});
                        previousAverage=previousValues.reduce(function(total,item){{return total+item;}},0)/previousValues.length;
                        value=previousAverage>0?(currentAverage/previousAverage-1)*100:null;
                    }}
                    if(value!==null&&isFinite(value))result[code]={{code:code,name:group.name,value:value,currentAverage:currentAverage,previousAverage:previousAverage,cityCount:cityCodes.length}};
                }});
                return result;
            }}
            function __setMapMetric(metric) {{
                if(['price','mom','yoy'].indexOf(metric)<0)return;
                __selectedMapMetric=metric;
                document.getElementById('hc-map-metric').value=metric;
                if(__selectedMapItem&&__selectedMapPeriod)__renderCityMap(__selectedMapItem,__selectedMapPeriod,null);
            }}
            function __setMapLevel(level) {{
                if(!__geoJSONLevels[level])return;
                __selectedMapLevel=level;
                __selectedMapAreaCode=null;__selectedMapAreaName='';
                __resetMapZoom();
                ['province','division','district'].forEach(function(name){{document.getElementById('hc-map-'+name).classList.toggle('active',name===level);}});
                if(__selectedMapItem&&__selectedMapPeriod)__renderCityMap(__selectedMapItem,__selectedMapPeriod,null);
            }}
            function __applyMapZoom(animate) {{
                var svg=document.getElementById('hc-price-map-svg'),zoom=__mapZoomLevels[__mapZoomIndex],targetWidth=1000/zoom,targetHeight=530/zoom,target=[(1000-targetWidth)/2,(530-targetHeight)/2,targetWidth,targetHeight];
                document.getElementById('hc-map-zoom-in').disabled=__mapZoomIndex===__mapZoomLevels.length-1;
                document.getElementById('hc-map-zoom-out').disabled=__mapZoomIndex===0;
                if(__mapZoomAnimation)cancelAnimationFrame(__mapZoomAnimation);
                if(!animate){{svg.setAttribute('viewBox',target.join(' '));return;}}
                var start=(svg.getAttribute('viewBox')||'0 0 1000 530').split(/\\s+/).map(Number),started=performance.now();
                function frame(now){{
                    var progress=Math.min((now-started)/180,1),eased=1-Math.pow(1-progress,3),current=start.map(function(value,index){{return value+(target[index]-value)*eased;}});
                    svg.setAttribute('viewBox',current.join(' '));
                    if(progress<1)__mapZoomAnimation=requestAnimationFrame(frame);else __mapZoomAnimation=null;
                }}
                __mapZoomAnimation=requestAnimationFrame(frame);
            }}
            function __zoomMap(direction) {{
                __mapZoomIndex=Math.max(0,Math.min(__mapZoomLevels.length-1,__mapZoomIndex+direction));
                __applyMapZoom(true);
            }}
            function __resetMapZoom() {{__mapZoomIndex=0;__applyMapZoom(false);}}
            function __toggleMapLabels() {{
                __mapLabelsVisible=!__mapLabelsVisible;
                document.getElementById('hc-map-stage').classList.toggle('hc-labels-hidden',!__mapLabelsVisible);
                var button=document.getElementById('hc-map-label-toggle');button.classList.toggle('active',!__mapLabelsVisible);button.setAttribute('aria-pressed',String(__mapLabelsVisible));button.title=__mapLabelsVisible?'Hide map value labels':'Show map value labels';
            }}
            function __cityMatchesArea(cityCode,areaCode) {{
                return __districtCityMap.some(function(mapping){{return String(mapping.cityCode)===String(cityCode)&&__mapAreaIdentity(mapping,__selectedMapLevel).code===String(areaCode);}});
            }}
            function __renderMapCityTable() {{
                var rows=__selectedMapAreaCode?__allCityRows.filter(function(row){{return __cityMatchesArea(row.code,__selectedMapAreaCode);}}):__allCityRows.slice();
                document.getElementById('hc-city-scope').textContent=__selectedMapAreaCode?__selectedMapAreaName+' · reporting centres':'Reporting centres';
                document.getElementById('hc-map-clear-area').classList.toggle('visible',Boolean(__selectedMapAreaCode));
                document.getElementById('hc-city-count').textContent=String(rows.length);
                document.getElementById('hc-city-price-body').innerHTML=rows.length?rows.map(function(row,index){{return '<tr title="CityCode '+String(row.code).padStart(2,'0')+'"><td>'+(index+1)+'</td><td>'+__esc(row.city)+'</td><td><span class="hc-city-price"><i class="hc-city-swatch" style="background:'+__mapValueColor(row.value,__cityValueMinimum,__cityValueMaximum)+'"></i>'+__mapValueFormat(row.value)+'</span></td></tr>';}}).join(''):'<tr><td colspan="3">No reporting city is mapped to this area</td></tr>';
                __currentCityRows=rows;
            }}
            function __applyMapAreaFocus() {{
                document.querySelectorAll('.hc-map-district').forEach(function(path){{
                    var selected=__selectedMapAreaCode&&path.dataset.areaCode===String(__selectedMapAreaCode);
                    path.classList.toggle('hc-area-focused',Boolean(selected));
                    path.classList.toggle('hc-area-muted',Boolean(__selectedMapAreaCode&&!selected));
                }});
                __renderMapCityTable();
            }}
            function __focusMapArea(areaCode,areaName) {{
                if(__selectedMapAreaCode===String(areaCode)){{__selectedMapAreaCode=null;__selectedMapAreaName='';}}
                else{{__selectedMapAreaCode=String(areaCode);__selectedMapAreaName=areaName;}}
                __applyMapAreaFocus();
            }}
            function __clearMapAreaFocus() {{__selectedMapAreaCode=null;__selectedMapAreaName='';__applyMapAreaFocus();}}
            function __renderCityMap(itemCode, period, cell) {{
                if(cell){{document.querySelectorAll('.hc-map-selected').forEach(function(el){{el.classList.remove('hc-map-selected');}});cell.classList.add('hc-map-selected');__selectedMapAreaCode=null;__selectedMapAreaName='';__resetMapZoom();}}
                __selectedMapItem=itemCode;__selectedMapPeriod=period;
                var meta=__activeItemMeta[itemCode]||{{description:itemCode,unit:''}},metric=__mapMetricMeta(),comparisonPeriod=metric.delta?__shiftPeriod(period,metric.delta):null;
                var raw=__cityPrices[period+'|'+itemCode]||[],comparisonRaw=comparisonPeriod?(__cityPrices[comparisonPeriod+'|'+itemCode]||[]):[];
                var cityMeta={{}},currentByCity={{}},previousByCity={{}};
                __districtCityMap.forEach(function(row){{cityMeta[String(row.cityCode)]=row.cityName;}});
                raw.forEach(function(row){{currentByCity[String(row[0])]=Number(row[1]);}});
                comparisonRaw.forEach(function(row){{previousByCity[String(row[0])]=Number(row[1]);}});
                var cityRows=Object.keys(currentByCity).filter(function(code){{return __selectedMapMetric==='price'||previousByCity[code]!==undefined;}}).map(function(code){{
                    var current=currentByCity[code],previous=__selectedMapMetric==='price'?null:previousByCity[code];
                    return {{code:code,city:cityMeta[code]||('City '+code),currentPrice:current,comparisonPrice:previous,value:__selectedMapMetric==='price'?current:(previous>0?(current/previous-1)*100:null)}};
                }}).filter(function(row){{return row.value!==null&&isFinite(row.value);}});
                var svg=document.getElementById('hc-price-map-svg');while(svg.firstChild)svg.removeChild(svg.firstChild);
                var levelLabel=__mapLevelLabel(__selectedMapLevel),geoJSON=__geoJSONLevels[__selectedMapLevel];
                document.getElementById('hc-map-title').textContent=metric.label+' by '+levelLabel;
                document.getElementById('hc-map-subtitle').textContent=meta.description+' · '+__periodLabel(period)+(comparisonPeriod?' vs '+__periodLabel(comparisonPeriod):'')+(meta.unit?' · '+meta.unit:'')+' · '+(__selectedMapMetric==='price'?'equal-city arithmetic mean':'matched-city change of arithmetic means');
                document.getElementById('hc-city-panel-title').textContent='City-wise '+metric.short.toLowerCase();
                document.getElementById('hc-city-value-head').textContent=__selectedMapMetric==='price'?'Price':(__selectedMapMetric==='mom'?'MoM':'YoY');
                if(!cityRows.length){{
                    document.getElementById('hc-map-extremes').innerHTML='<span><strong>No comparable mapped prices</strong> for '+__esc(__periodLabel(period))+(comparisonPeriod?' and '+__esc(__periodLabel(comparisonPeriod)):'')+'.</span>';
                    document.getElementById('hc-city-price-body').innerHTML='<tr><td colspan="3">No comparable city prices available</td></tr>';document.getElementById('hc-city-count').textContent='0';
                    var empty=document.createElementNS('http://www.w3.org/2000/svg','text');empty.setAttribute('x','500');empty.setAttribute('y','265');empty.setAttribute('class','hc-map-empty');empty.textContent='No comparable mapped city prices are available for this measure.';svg.appendChild(empty);
                    __allCityRows=[];__currentMapRows=[];__currentCityRows=[];__selectedMapAreaCode=null;__selectedMapAreaName='';document.getElementById('hc-city-scope').textContent='Reporting centres';document.getElementById('hc-map-clear-area').classList.remove('visible');setTimeout(__resizeGroupBarsFrame,40);return;
                }}
                var areas=__aggregateMapAreas(currentByCity,previousByCity,__selectedMapLevel,__selectedMapMetric),areaRows=Object.keys(areas).map(function(code){{return areas[code];}}),areaValues=areaRows.map(function(area){{return area.value;}});
                var minimum=Math.min.apply(null,areaValues),maximum=Math.max.apply(null,areaValues),midpoint=__selectedMapMetric==='price'?(minimum+maximum)/2:0;
                var rankedAreas=areaRows.slice().sort(function(a,b){{return a.value-b.value;}}),low=rankedAreas[0],high=rankedAreas[rankedAreas.length-1];
                document.getElementById('hc-map-extremes').innerHTML=
                    '<span>Lowest '+levelLabel+' '+metric.short.toLowerCase()+': <strong>'+__mapValueFormat(low.value)+'</strong> · '+__esc(low.name)+'</span>'+
                    '<i class="hc-map-divider">|</i>'+ 
                    '<span>Highest '+levelLabel+' '+metric.short.toLowerCase()+': <strong>'+__mapValueFormat(high.value)+'</strong> · '+__esc(high.name)+'</span>';
                var legendLimit=Math.max(Math.abs(minimum),Math.abs(maximum));
                document.getElementById('hc-map-legend-low').textContent=__selectedMapMetric==='price'?__priceFormat(minimum):__mapValueFormat(-legendLimit);
                document.getElementById('hc-map-legend-mid').textContent=__selectedMapMetric==='price'?__priceFormat(midpoint):'0.00%';
                document.getElementById('hc-map-legend-high').textContent=__selectedMapMetric==='price'?__priceFormat(maximum):__mapValueFormat(legendLimit);
                document.querySelector('.hc-map-gradient').style.background=__selectedMapMetric==='price'?'linear-gradient(90deg,#fff4ef 0%,#fdc9bd 20%,#fb806c 42%,#e43f32 64%,#a71918 82%,#65000d 100%)':'linear-gradient(90deg,#006747 0%,#88c9b2 32%,#f6f2ef 50%,#ef9b8f 70%,#8f1011 100%)';
                document.getElementById('hc-map-legend-note').textContent=__selectedMapMetric==='price'?'Dynamic average-price scale':'Green = decrease · red = increase';
                var project=__mapProjection(geoJSON);
                geoJSON.features.forEach(function(feature){{
                    var areaCode=String(feature.properties.code),area=areas[areaCode],value=area?area.value:undefined;
                    var path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',__geometryPath(feature.geometry,project));path.setAttribute('class','hc-map-district');path.setAttribute('fill',value===undefined?'#eee9e8':__mapValueColor(value,minimum,maximum));path.setAttribute('stroke','#ffffff');path.setAttribute('stroke-width','.75');
                    path.dataset.areaCode=areaCode;path.setAttribute('role','button');path.setAttribute('tabindex',area?'0':'-1');path.setAttribute('aria-label',feature.properties.name+(area?' · '+metric.short+' '+__mapValueFormat(value):' · no data'));
                    var detail=area&&__selectedMapMetric!=='price'?'<br>Current avg: '+__priceFormat(area.currentAverage)+' · Prior avg: '+__priceFormat(area.previousAverage):'';
                    path.addEventListener('mousemove',function(event){{__showMapTooltip(event,'<strong>'+__esc(feature.properties.name)+'</strong>'+(area?metric.short+': <b>'+__mapValueFormat(value)+'</b>'+detail+'<br>'+area.cityCount+' matched reporting '+(area.cityCount===1?'city':'cities')+'<br><em>Click to focus the city table</em>':'No comparable CPI city'));}});
                    path.addEventListener('mouseleave',function(){{document.getElementById('hc-map-tooltip').style.display='none';}});svg.appendChild(path);
                    if(area){{path.addEventListener('click',function(){{__focusMapArea(areaCode,feature.properties.name);}});path.addEventListener('keydown',function(event){{if(event.key==='Enter'||event.key===' '){{event.preventDefault();__focusMapArea(areaCode,feature.properties.name);}}}});}}
                    if(value!==undefined){{var xy=project(__featureCenter(feature)),dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx',xy[0]);dot.setAttribute('cy',xy[1]);dot.setAttribute('r','2.5');dot.setAttribute('class','hc-map-city-dot');dot.setAttribute('fill','#fff');dot.setAttribute('stroke','#8f201b');svg.appendChild(dot);var label=document.createElementNS('http://www.w3.org/2000/svg','text');label.setAttribute('x',xy[0]);label.setAttribute('y',xy[1]-5);label.setAttribute('class','hc-map-city-label');label.setAttribute('fill','#681713');label.setAttribute('stroke','#fff');label.setAttribute('stroke-width','3');label.setAttribute('paint-order','stroke');label.textContent=__mapValueFormat(value);svg.appendChild(label);}}
                }});
                var cityValues=cityRows.map(function(row){{return row.value;}}),cityMinimum=Math.min.apply(null,cityValues),cityMaximum=Math.max.apply(null,cityValues);
                var rankedCities=cityRows.slice().sort(function(a,b){{return b.value-a.value;}});
                __cityValueMinimum=cityMinimum;__cityValueMaximum=cityMaximum;
                __allCityRows=rankedCities.map(function(row){{
                    var districts=__districtCityMap.filter(function(mapping){{return String(mapping.cityCode)===row.code;}}).map(function(mapping){{return mapping.districtName;}}).join(', ');
                    return {{itemCode:itemCode,item:meta.description,period:period,comparisonPeriod:comparisonPeriod||'',metric:metric.short,code:row.code,cityCode:row.code.padStart(2,'0'),city:row.city,districts:districts,currentPrice:row.currentPrice,comparisonPrice:row.comparisonPrice,value:row.value}};
                }});
                __currentMapRows=rankedAreas.map(function(area){{return {{itemCode:itemCode,item:meta.description,period:period,comparisonPeriod:comparisonPeriod||'',metric:metric.short,level:levelLabel,areaCode:area.code,area:area.name,currentAverage:area.currentAverage,comparisonAverage:area.previousAverage,value:area.value,reportingCities:area.cityCount}};}});
                __applyMapAreaFocus();
                document.getElementById('hc-map-stage').classList.toggle('hc-labels-hidden',!__mapLabelsVisible);
                setTimeout(__resizeGroupBarsFrame,80);
            }}
            function __downloadMapExcel() {{
                if(!__currentMapRows.length)return;
                function table(headers,rows){{return '<table border="1"><thead><tr>'+headers.map(function(v){{return '<th>'+__esc(v)+'</th>';}}).join('')+'</tr></thead><tbody>'+rows.map(function(row){{return '<tr>'+row.map(function(v){{return '<td>'+__esc(v)+'</td>';}}).join('')+'</tr>';}}).join('')+'</tbody></table>';}}
                var exportMapRows=__selectedMapAreaCode?__currentMapRows.filter(function(row){{return String(row.areaCode)===String(__selectedMapAreaCode);}}):__currentMapRows;
                var areaRows=exportMapRows.map(function(row){{return [row.itemCode,row.item,row.period,row.comparisonPeriod,row.metric,row.level,row.areaCode,row.area,row.currentAverage,row.comparisonAverage,row.value,row.reportingCities];}});
                var cityRows=__currentCityRows.map(function(row){{return [row.itemCode,row.item,row.period,row.comparisonPeriod,row.metric,row.cityCode,row.city,row.districts,row.currentPrice,row.comparisonPrice,row.value];}});
                var workbook='<h2>'+__esc(__selectedMapLevel)+' '+__esc(__mapMetricMeta().short)+'</h2>'+table(['Item Code','Item','Current Period','Comparison Period','Metric','Level','Area Code','Area','Current Average Price','Comparison Average Price','Metric Value','Matched Reporting Cities'],areaRows)+'<br><h2>City-wise '+__esc(__mapMetricMeta().short)+'</h2>'+table(['Item Code','Item','Current Period','Comparison Period','Metric','City Code','City','Mapped Districts','Current Price','Comparison Price','Metric Value'],cityRows);
                var blob=new Blob(['\ufeff<html><head><meta charset="UTF-8"></head><body>'+workbook+'</body></html>'],{{type:'application/vnd.ms-excel'}}),url=URL.createObjectURL(blob),link=document.createElement('a');
                link.href=url;link.download=__selectedMapLevel+'-'+__selectedMapMetric+'-map-'+__selectedMapPeriod+'-'+__selectedMapItem.replace(/[^a-z0-9.-]/gi,'-')+'.xls';document.body.appendChild(link);link.click();link.remove();setTimeout(function(){{URL.revokeObjectURL(url);}},1000);
            }}
            function __downloadMapPng() {{
                var svg=document.getElementById('hc-price-map-svg');if(!svg||!__currentMapRows.length)return;
                var clone=svg.cloneNode(true);if(!__mapLabelsVisible)clone.querySelectorAll('.hc-map-city-label').forEach(function(label){{label.remove();}});var style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent='.hc-map-district{{stroke:#fff;stroke-width:.75}} .hc-area-muted{{opacity:.2}} .hc-area-focused{{stroke:#123f30;stroke-width:2.2}} .hc-map-city-dot{{fill:#fff;stroke:#8f201b;stroke-width:1.25}} .hc-map-city-label{{fill:#681713;paint-order:stroke;stroke:#fff;stroke-width:3px;font:750 9px sans-serif;text-anchor:middle}}';clone.insertBefore(style,clone.firstChild);
                var source=new XMLSerializer().serializeToString(clone),url=URL.createObjectURL(new Blob([source],{{type:'image/svg+xml;charset=utf-8'}})),image=new Image();
                image.onload=function(){{var canvas=document.createElement('canvas');canvas.width=2000;canvas.height=1060;var ctx=canvas.getContext('2d');ctx.scale(2,2);ctx.fillStyle='#fbf5f4';ctx.fillRect(0,0,1000,530);ctx.drawImage(image,0,0,1000,530);URL.revokeObjectURL(url);canvas.toBlob(function(png){{var pngUrl=URL.createObjectURL(png),link=document.createElement('a');link.href=pngUrl;link.download=__selectedMapLevel+'-'+__selectedMapMetric+'-map-'+__selectedMapPeriod+'-'+__selectedMapItem.replace(/[^a-z0-9.-]/gi,'-')+'.png';document.body.appendChild(link);link.click();link.remove();setTimeout(function(){{URL.revokeObjectURL(pngUrl);}},1000);}},'image/png');}};image.src=url;
            }}
            function __setItemWeight(value) {{ __itemWeightIndex=Number(value); __renderItemAnalysis(); }}
            function __setItemMeasure(value) {{ __itemMeasure=value; __renderItemAnalysis(); }}
            function __setItemScale(value) {{ __itemScaleMode=value; __renderItemAnalysis(); }}
            function __toggleItemSort() {{ __itemSortDescending=!__itemSortDescending; __renderItemAnalysis(); }}
            function __renderItemDrilldown(period, groupCode, measure, cell) {{
                document.querySelectorAll('.hc-selected-cell').forEach(function(el) {{ el.classList.remove('hc-selected-cell'); }});
                if (cell) cell.classList.add('hc-selected-cell');
                __selectedHeatPeriod=period; __selectedHeatGroup=groupCode; __itemMeasure=measure;
                __selectedMapItem=null; __selectedMapPeriod=null;
                __renderItemAnalysis();
            }}
            function __renderItemAnalysis() {{
                var period=__selectedHeatPeriod, groupCode=__selectedHeatGroup;
                if (!period || !groupCode) return;
                var items=(__heatItems[period+'|'+groupCode]||[]).slice();
                var group=__heatGroups.find(function(item){{return item.code===groupCode;}})||{{full:'Group '+groupCode}};
                var weightKey='w'+__itemWeightIndex, weightName=__itemWeightIndex===0?'Overall':'Q'+__itemWeightIndex;
                var periods=[]; for(var offset=-11;offset<=0;offset++) periods.push(__shiftPeriod(period,offset));
                function recordAt(code,p){{return (__heatItems[p+'|'+groupCode]||[]).find(function(item){{return item.code===code;}});}}
                items.forEach(function(item){{
                    item.weight=item[weightKey]; item.changes=periods.map(function(p){{
                        var current=recordAt(item.code,p), previous=recordAt(item.code,__shiftPeriod(p,__itemMeasure==='mom'?-1:-12));
                        return current&&previous&&current.gm>0&&previous.gm>0 ? (current.gm/previous.gm-1)*100 : null;
                    }});
                }});
                items.sort(function(a,b){{var av=a.weight||0,bv=b.weight||0;return __itemSortDescending?bv-av:av-bv;}});
                var ranked=items.slice().sort(function(a,b){{return (b.weight||0)-(a.weight||0);}});
                __activeItemMeta={{}};items.forEach(function(item){{__activeItemMeta[item.code]=item;}});
                document.getElementById('hc-item-weight').value=String(__itemWeightIndex);
                document.getElementById('hc-item-scale').value=__itemScaleMode;
                document.getElementById('hc-item-mom').classList.toggle('active',__itemMeasure==='mom');
                document.getElementById('hc-item-yoy').classList.toggle('active',__itemMeasure==='yoy');
                document.getElementById('hc-item-sort').textContent=(__itemSortDescending?'↓':'↑')+' W';
                document.getElementById('hc-drill-title').textContent=group.full;
                var measureLabel=__itemMeasure==='mom'?'MoM':'YoY';
                var weightLabel=weightName==='Overall'?'Overall basket weight':weightName+' weight';
                document.getElementById('hc-drill-subtitle').textContent=__periodLabel(period)+' · '+weightLabel+' · '+measureLabel+' price change · city GM';
                if(!items.length){{document.getElementById('hc-group-summary').textContent='No joined item records are available for this cell.';return;}}
                var total=items.reduce(function(s,i){{return s+(i.weight||0);}},0);
                var topShare=total?(ranked[0].weight||0)/total*100:0;
                document.getElementById('hc-group-summary').innerHTML=
                    '<span class="hc-summary-part"><strong>'+items.length+'</strong> items in this group</span>'+
                    '<span class="hc-summary-part"><strong>'+__num(total,2)+'</strong> '+weightName+' group-weight sum</span>'+
                    '<span class="hc-summary-part hc-summary-leader">Highest weight: <strong>'+__esc(ranked[0].description)+'</strong> at '+__num(ranked[0].weight,4)+' ('+__num(topShare,1)+'%)</span>';
                function directionalScale(values){{return values.reduce(function(scale,value){{if(value===null)return scale;if(value<0)scale.negative=Math.max(scale.negative,Math.abs(value));else scale.positive=Math.max(scale.positive,value);return scale;}},{{negative:.01,positive:.01}});}}
                var columnScales=periods.map(function(_,idx){{return directionalScale(items.map(function(i){{return i.changes[idx];}}));}});
                function priceCell(value,scale,itemCode,pricePeriod){{if(value===null)return '<td class="hc-map-trigger" data-item="'+__esc(itemCode)+'" data-price-period="'+pricePeriod+'" title="View city prices on map">—</td>';var denominator=value<0?scale.negative:scale.positive,a=(.08+Math.min(Math.abs(value)/Math.max(denominator,.01),1)*.58).toFixed(2),rgb=value<0?'0,158,115':'213,94,0',ink=Number(a)>.4?'#fff':(value<0?'#07533c':'#7f2e12'),extreme=(value>0&&Math.abs(value-scale.positive)<.000001)||(value<0&&Math.abs(Math.abs(value)-scale.negative)<.000001);return '<td class="hc-map-trigger" data-item="'+__esc(itemCode)+'" data-price-period="'+pricePeriod+'" title="View '+__esc(__periodLabel(pricePeriod))+' city prices on map" style="background:rgba('+rgb+','+a+');color:'+ink+';font-weight:'+(extreme?'750':'500')+'">'+(value>0?'+':'')+__num(value,2)+'%</td>';}}
                document.getElementById('hc-weight-head').innerHTML='<tr><th>Item</th><th>'+weightName+' weight</th><th>Price</th>'+periods.map(function(p){{return '<th>'+__periodLabel(p).replace(' ','<br>')+'</th>';}}).join('')+'</tr>';
                document.getElementById('hc-weight-body').innerHTML=items.map(function(item){{var rowScale=directionalScale(item.changes);return '<tr><td title="'+__esc(item.description)+'">'+__esc(item.short)+'</td><td>'+__num(item.weight,4)+'</td><td class="hc-map-trigger" data-item="'+__esc(item.code)+'" data-price-period="'+period+'" title="View '+__esc(__periodLabel(period))+' city prices on map">'+__num(item.gm,2)+'</td>'+item.changes.map(function(v,idx){{return priceCell(v,__itemScaleMode==='row'?rowScale:columnScales[idx],item.code,periods[idx]);}}).join('')+'</tr>';}}).join('');
                document.querySelectorAll('#hc-weight-body .hc-map-trigger').forEach(function(cell){{cell.addEventListener('click',function(){{__renderCityMap(cell.dataset.item,cell.dataset.pricePeriod,cell);}});}});
                var mapItem=__selectedMapItem&&__activeItemMeta[__selectedMapItem]?__selectedMapItem:ranked[0].code;
                var mapPeriod=__selectedMapPeriod&&periods.indexOf(__selectedMapPeriod)>=0?__selectedMapPeriod:period;
                var mapCell=Array.from(document.querySelectorAll('#hc-weight-body .hc-map-trigger')).find(function(cell){{return cell.dataset.item===mapItem&&cell.dataset.pricePeriod===mapPeriod;}});
                __renderCityMap(mapItem,mapPeriod,mapCell||null);
                setTimeout(__resizeGroupBarsFrame,80);
            }}
            function __renderPeriodHeat(measure) {{
                __selectedHeatMeasure = measure;
                var groupScales = {{}}, monthScales = {{}};
                function updateScale(scales,key,value) {{
                    if (!scales[key]) scales[key] = {{negative:.01,positive:.01}};
                    if (value < 0) scales[key].negative = Math.max(scales[key].negative, Math.abs(value));
                    else scales[key].positive = Math.max(scales[key].positive, value);
                }}
                __heatMatrix.forEach(function(row) {{
                    __heatGroups.forEach(function(group) {{
                        var value = row.values[group.full] ? row.values[group.full][measure] : null;
                        if (value !== null && value !== undefined) {{
                            updateScale(groupScales, group.code, value);
                            updateScale(monthScales, row.period, value);
                        }}
                    }});
                }});
                document.getElementById('hc-heat-mom').classList.toggle('active', measure === 'mom');
                document.getElementById('hc-heat-yoy').classList.toggle('active', measure === 'yoy');
                var first = __heatMatrix.length ? __heatMatrix[0].month : '';
                var last = __heatMatrix.length ? __heatMatrix[__heatMatrix.length - 1].month : '';
                document.getElementById('hc-heat-subtitle').textContent =
                    (measure === 'mom' ? 'Month-over-month' : 'Year-over-year') + ' change (%) · ' + first + ' to ' + last;
                document.getElementById('hc-heat-head').innerHTML = '<tr><th>Month</th>' + __heatGroups.map(function(group) {{
                    return '<th title="' + group.full.replace(/"/g, '&quot;') + '">' + group.short + '</th>';
                }}).join('') + '</tr>';
                document.getElementById('hc-heat-body').innerHTML = __heatMatrix.map(function(row) {{
                    return '<tr><td>' + row.month + '</td>' + __heatGroups.map(function(group) {{
                        var cell = row.values[group.full] || {{}};
                        var cellScale = __heatScaleMode === 'row'
                            ? monthScales[row.period] : groupScales[group.code];
                        return __heatCell(cell[measure], cellScale || {{negative:1,positive:1}}, row.period, group.code, measure);
                    }}).join('') + '</tr>';
                }}).join('');
                document.querySelectorAll('#hc-heat-body td[data-period]').forEach(function(cell) {{
                    cell.addEventListener('click', function() {{
                        __renderItemDrilldown(cell.dataset.period, cell.dataset.group, cell.dataset.measure, cell);
                    }});
                }});
                if (__selectedHeatPeriod && __selectedHeatGroup) {{
                    var selected = document.querySelector('#hc-heat-body td[data-period="' + __selectedHeatPeriod + '"][data-group="' + __selectedHeatGroup + '"]');
                    if (selected) selected.classList.add('hc-selected-cell');
                }}
                setTimeout(__resizeGroupBarsFrame, 20);
            }}
            function __setHeatMeasure(measure) {{ __renderPeriodHeat(measure); }}
            function __setHeatScale(mode) {{ __heatScaleMode = mode; __renderPeriodHeat(__selectedHeatMeasure); }}
            Highcharts.addEvent(Highcharts.Point, 'click', function() {{
                if (this.series && this.series.chart === __leftChart) __renderPeriodHeat('mom');
                if (this.series && this.series.chart === __rightChart) __renderPeriodHeat('yoy');
            }});
            __renderPeriodHeat('mom');
            if (__heatMatrix.length && __heatGroups.length) {{
                var __defaultRow = __heatMatrix[__heatMatrix.length - 1];
                var __defaultIndex = __heatGroups.findIndex(function(group) {{ return group.code === '01'; }});
                if (__defaultIndex < 0) __defaultIndex = 0;
                var __defaultCell = document.querySelector('#hc-heat-body tr:last-child td:nth-child(' + (__defaultIndex + 2) + ')');
                __renderItemDrilldown(__defaultRow.period, __heatGroups[__defaultIndex].code, 'mom', __defaultCell);
            }}

            function __downloadChartPng(chart, filename) {{
                if (!chart) return;
                var svgNode = chart.container.querySelector('svg');
                if (!svgNode) return;
                var url = URL.createObjectURL(new Blob([
                    new XMLSerializer().serializeToString(svgNode)
                ], {{type:'image/svg+xml;charset=utf-8'}}));
                var image = new Image();
                image.onload = function() {{
                    var scale = 2, canvas = document.createElement('canvas');
                    canvas.width = chart.chartWidth * scale; canvas.height = chart.chartHeight * scale;
                    var ctx = canvas.getContext('2d');
                    ctx.scale(scale, scale); ctx.fillStyle = '#ffffff';
                    ctx.fillRect(0, 0, chart.chartWidth, chart.chartHeight); ctx.drawImage(image, 0, 0);
                    URL.revokeObjectURL(url);
                    canvas.toBlob(function(png) {{
                        var pngUrl = URL.createObjectURL(png), link = document.createElement('a');
                        link.href = pngUrl; link.download = filename;
                        document.body.appendChild(link); link.click(); link.remove();
                        setTimeout(function() {{ URL.revokeObjectURL(pngUrl); }}, 1000);
                    }}, 'image/png');
                }};
                image.src = url;
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
        height=height,
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

_pbs_header_html = f"""
    <style>
    .pbs-header {{
        position:relative; isolation:isolate; overflow:hidden;
        background:linear-gradient(112deg,#043e2d 0%,{PBS_GREEN_DARK} 46%,#0b7655 100%);
        color:white; padding:12px 18px; border-radius:0 0 16px 16px;
        display:flex; align-items:center; gap:15px; margin-bottom:13px;
        border:1px solid rgba(255,255,255,.13); border-top:0;
        box-shadow:0 9px 28px rgba(6,72,51,.2);
    }}
    .pbs-header::before {{
        content:""; position:absolute; z-index:-1; width:260px; height:260px;
        right:-82px; top:-142px; border-radius:50%;
        border:38px solid rgba(255,255,255,.045);
    }}
    .pbs-header::after {{
        content:""; position:absolute; z-index:-1; inset:auto 0 0 0; height:2px;
        background:linear-gradient(90deg,#8ee0bf,rgba(142,224,191,0));
    }}
    .pbs-header .logo {{
        height:56px; flex-shrink:0; background:white; border-radius:10px;
        padding:5px 10px; box-shadow:0 4px 14px rgba(0,0,0,.15);
    }}
    .pbs-header .badge {{
        background: white; color: {PBS_GREEN_DARK}; font-weight: 700;
        border-radius: 50%; width: 44px; height: 44px; flex-shrink: 0;
        display: flex; align-items: center; justify-content: center; font-size: 13px;
    }}
    .pbs-header .title-block {{ min-width:0; flex:1; }}
    .pbs-header .eyebrow {{
        display:flex; align-items:center; gap:7px; margin:0 0 2px;
        color:#c9eddf; font-size:.64rem; font-weight:760;
        letter-spacing:.145em; text-transform:uppercase;
    }}
    .pbs-header .eyebrow::before {{
        content:""; width:6px; height:6px; flex:none; border-radius:50%;
        background:#93e3c3; box-shadow:0 0 0 4px rgba(147,227,195,.14);
    }}
    .pbs-header h1 {{
        font-size: clamp(1.28rem, 2vw, 1.58rem); line-height: 1;
        margin:0; padding:0; color:white; letter-spacing:-0.028em; font-weight:760;
        text-shadow: 0 1px 2px rgba(0,0,0,.12);
    }}
    .pbs-header .subtitle {{
        margin:4px 0 0; color:#d9eee6; font-size:.76rem; line-height:1.2;
        letter-spacing:.012em;
    }}
    .pbs-header .title-accent {{
        display: inline-block; width: 34px; height: 2px; margin-left: 8px;
        vertical-align: middle; border-radius: 2px; background: #8ee0bf;
    }}
    .pbs-header .header-context {{
        flex:none; display:flex; align-items:center; gap:14px;
        padding:7px 11px; border:1px solid rgba(255,255,255,.17);
        border-radius:11px; background:rgba(255,255,255,.075);
        box-shadow:inset 0 1px 0 rgba(255,255,255,.06);
        backdrop-filter:blur(5px);
    }}
    .pbs-header .context-item {{ min-width:76px; }}
    .pbs-header .context-item + .context-item {{
        padding-left:14px; border-left:1px solid rgba(255,255,255,.16);
    }}
    .pbs-header .context-label {{
        display:block; color:#bfe5d6; font-size:.56rem; line-height:1.2;
        font-weight:700; letter-spacing:.11em; text-transform:uppercase;
    }}
    .pbs-header .context-value {{
        display:block; margin-top:2px; color:#fff; font-size:.72rem;
        line-height:1.2; font-weight:680; white-space:nowrap;
    }}
    .pbs-header .db-status {{ display:inline-flex; align-items:center; gap:5px; }}
    .pbs-header .db-status::before {{
        content:""; width:6px; height:6px; border-radius:50%; background:#93e3c3;
        box-shadow:0 0 0 3px rgba(147,227,195,.12);
    }}
    @media(max-width:760px) {{
        .pbs-header .header-context {{ display:none; }}
    }}
    @media(max-width:480px) {{
        .pbs-header {{ padding:10px 12px; gap:10px; }}
        .pbs-header .logo {{ height:48px; padding:4px 7px; }}
        .pbs-header .subtitle {{ font-size:.68rem; }}
        .pbs-header .title-accent {{ display:none; }}
    }}
    div[data-testid="stColumn"]:has(.period-filter-marker) {{
        background: linear-gradient(145deg, #ffffff, #f7fbf9);
        border: 1px solid #d9e6df; border-left: 4px solid {PBS_GREEN};
        border-radius: 12px; padding: 7px 11px 9px;
        box-shadow: 0 4px 14px rgba(18,49,37,.065);
    }}
    .period-filter-marker {{
        display:flex; align-items:baseline; justify-content:space-between;
        gap:10px; margin:0 0 4px;
    }}
    .period-filter-marker strong {{
        color:#17382b; font-size:.82rem; letter-spacing:.015em;
    }}
    .period-filter-marker span {{
        color:#74827b; font-size:.68rem; white-space:nowrap;
    }}
    div[data-testid="stColumn"]:has(.period-filter-marker) [data-baseweb="select"] > div {{
        background:#fff; border-color:#bfd2c8; box-shadow:none;
    }}
    .kpi-grid {{
        display:grid; grid-template-columns:repeat(5,minmax(0,1fr));
        gap:10px; margin:1px 0 15px;
    }}
    .kpi-card {{
        --accent:#0b6e4f; position:relative; overflow:hidden;
        min-height:112px; padding:12px 13px 11px;
        background:linear-gradient(155deg,#ffffff 20%,#f7faf8 100%);
        border:1px solid #dce7e1; border-radius:14px;
        box-shadow:0 5px 16px rgba(18,49,37,.075);
        transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease;
    }}
    .kpi-card::before {{
        content:""; position:absolute; left:0; top:0; bottom:0; width:4px;
        background:var(--accent);
    }}
    .kpi-card:hover {{
        transform:translateY(-2px); border-color:#c5d8ce;
        box-shadow:0 10px 24px rgba(18,49,37,.12);
    }}
    .kpi-card__top {{
        display:flex; align-items:flex-start; justify-content:space-between;
        gap:8px; padding-left:2px;
    }}
    .kpi-card__title {{
        color:#31483e; font-size:.76rem; line-height:1.2; font-weight:720;
        letter-spacing:.015em;
    }}
    .kpi-card__period {{
        flex:none; color:#607269; background:#edf4f0; border:1px solid #dce8e2;
        border-radius:999px; padding:2px 7px; font-size:.62rem;
        line-height:1.35; font-weight:650; white-space:nowrap;
    }}
    .kpi-card__value {{
        margin:10px 48px 2px 2px; color:#10291f;
        font-size:1.68rem; line-height:1; font-weight:760;
        letter-spacing:-.035em; font-variant-numeric:tabular-nums;
    }}
    .kpi-card__context {{
        margin-left:2px; color:#718078; font-size:.64rem; line-height:1.2;
    }}
    .kpi-card__icon {{
        position:absolute; right:12px; bottom:11px; width:36px; height:36px;
        display:flex; align-items:center; justify-content:center;
        color:var(--accent); background:color-mix(in srgb,var(--accent) 10%,white);
        border:1px solid color-mix(in srgb,var(--accent) 20%,white);
        border-radius:11px; font-size:1.35rem; line-height:1;
    }}
    @media(max-width:1050px) {{ .kpi-grid {{ grid-template-columns:repeat(3,1fr); }} }}
    @media(max-width:680px) {{ .kpi-grid {{ grid-template-columns:1fr 1fr; }} }}
    @media(max-width:430px) {{ .kpi-grid {{ grid-template-columns:1fr; }} }}
    </style>
    <div class="pbs-header">
        {_logo_html}
        <div class="title-block">
            <div class="eyebrow">Pakistan Bureau of Statistics · IMIS</div>
            <h1>Pakistan Inflation Intelligence<span class="title-accent"></span></h1>
            <p class="subtitle">Official Consumer Price Index monitoring, movements and group-level insights</p>
        </div>
        <div class="header-context" aria-label="Dashboard context">
            <div class="context-item">
                <span class="context-label">Coverage</span>
                <span class="context-value">National CPI</span>
            </div>
            <div class="context-item">
                <span class="context-label">Frequency</span>
                <span class="context-value">Monthly</span>
            </div>
            <div class="context-item">
                <span class="context-label">Data source</span>
                <span class="context-value db-status">PBS</span>
            </div>
        </div>
    </div>
    """

st.markdown(
    "\n".join(line.lstrip() for line in _pbs_header_html.splitlines()),
    unsafe_allow_html=True,
)

try:
    df = _load()
except ImisDataError as e:
    st.error(str(e))
    st.stop()

ct = _change_table(df)
if ct.empty:
    st.warning("No CPI data available yet.")
    st.stop()

group_long = _group_long(df)

# ------------------------------------------------ main-chart click -> period --
# The main Inflation Index chart (rendered much further down) is a custom
# component keyed "hc-main-chart"; clicking a point makes it call
# setComponentValue with the x-axis DATE under the cursor (its own axis<->value
# mapping, not a pixel guess - see hc_main_chart.py), snapped to the first of
# that month. Streamlit stashes that in st.session_state["hc-main-chart"], and
# it stays readable here on the NEXT run BEFORE the component itself is
# re-instantiated - which is the whole point of reading it up here: the
# "Selected period" picker and the period-specific KPI cards both render
# below this line, so handling the click here lets them ALL pick up the new
# month in a single run, with no st.rerun() (an st.rerun() fired from inside
# the component's own callback run was silently dropped by Streamlit's
# frontend - confirmed live - so the page never moved).
st.session_state.setdefault("selected_period", ct.index[-1])
st.session_state.setdefault("period_year", int(ct.index[-1].year))
st.session_state.setdefault("period_month", int(ct.index[-1].month))

_chart_click = st.session_state.get("hc-main-chart")
if _chart_click and _chart_click != st.session_state.get("_last_main_chart_click"):
    st.session_state["_last_main_chart_click"] = _chart_click
    try:
        _clicked_ts = pd.Timestamp(_chart_click)
        # ct.index is a first-of-month monthly grid, so an in-range click is
        # an exact hit; only fall back to `nearest` for a click that lands
        # outside the data (clamps to the endpoint).
        if _clicked_ts in ct.index:
            _target = _clicked_ts
        else:
            _target = ct.index[ct.index.get_indexer([_clicked_ts], method="nearest")[0]]
        st.session_state["selected_period"] = _target
        # Legal here: both widgets are created a few lines below, not yet.
        st.session_state["period_year"] = int(_target.year)
        st.session_state["period_month"] = int(_target.month)
        # The scroll-into-view of the group bar section is done by the chart
        # component itself right after it fires the click (see
        # hc_main_chart.py's __scrollParentToGroupBars) - not from here.
    except (ValueError, TypeError, IndexError):
        pass

# -------------------------------------------------------- period pickers --
# Required first filter: latest year/month by default, both ordered newest
# first. Every period-sensitive element below consumes the resulting
# `selected` timestamp.
year_col, month_col = st.columns(2)
_years = sorted({int(d.year) for d in ct.index}, reverse=True)
if st.session_state["period_year"] not in _years:
    st.session_state["period_year"] = _years[0]
year_col.markdown(
    '<div class="period-filter-marker"><strong>Reporting year</strong>'
    '<span>Newest first</span></div>',
    unsafe_allow_html=True,
)
selected_year = year_col.selectbox(
    "Year", _years, key="period_year", label_visibility="collapsed"
)
_months = sorted(
    {int(d.month) for d in ct.index if int(d.year) == selected_year}, reverse=True
)
if st.session_state["period_month"] not in _months:
    st.session_state["period_month"] = _months[0]
month_col.markdown(
    '<div class="period-filter-marker"><strong>Reporting month</strong>'
    '<span>Available periods</span></div>',
    unsafe_allow_html=True,
)
selected_month = month_col.selectbox(
    "Month",
    _months,
    format_func=lambda month: pd.Timestamp(2000, month, 1).strftime("%B"),
    key="period_month",
    label_visibility="collapsed",
)
selected = pd.Timestamp(selected_year, selected_month, 1)
st.session_state["selected_period"] = selected
# Compatibility alias for code/tests that previously read the combined picker.
st.session_state["period_picker"] = selected

# ------------------------------------------------------------------- KPIs --
# c1-c3 follow the picker above; c4-c5 show historical bounds as of it.
latest = ct.loc[selected]
# Historical cards and the first chart are evaluated as-of the selected
# period, so choosing an older month never leaks future values into the view.
ct_as_of = ct.loc[:selected]
high_yoy_date = ct_as_of["yoy_pct"].idxmax() if ct_as_of["yoy_pct"].notna().any() else None
high_yoy_val = ct_as_of["yoy_pct"].max() if high_yoy_date is not None else None
low_yoy_date = ct_as_of["yoy_pct"].idxmin() if ct_as_of["yoy_pct"].notna().any() else None
low_yoy_val = ct_as_of["yoy_pct"].min() if low_yoy_date is not None else None

_cards = [
    ("Current CPI index", f"{latest['cpi']:.2f}", f"{latest.name:%b %Y}", "Base 2015–16 = 100", "▥"),
    ("Monthly movement", f"{latest['mom_pct']:+.2f}%" if pd.notna(latest["mom_pct"]) else "n/a", f"{latest.name:%b %Y}", "Month over month", "↻"),
    ("Annual movement", f"{latest['yoy_pct']:+.2f}%" if pd.notna(latest["yoy_pct"]) else "n/a", f"{latest.name:%b %Y}", "Year over year", "◷"),
    ("Historical low", f"{low_yoy_val:+.2f}%" if low_yoy_val is not None else "n/a", f"{low_yoy_date:%b %Y}" if low_yoy_date is not None else "n/a", "Lowest annual movement", "↘"),
    ("Historical high", f"{high_yoy_val:+.2f}%" if high_yoy_val is not None else "n/a", f"{high_yoy_date:%b %Y}" if high_yoy_date is not None else "n/a", "Highest annual movement", "↗"),
]
_card_html = []
for _index, (_title, _value, _period, _context, _icon) in enumerate(_cards):
    _card_html.append(
        f'<article class="kpi-card" data-kpi="{_title}" style="--accent:{OKABE_ITO[_index]}">'
        f'<div class="kpi-card__top"><span class="kpi-card__title">{_title}</span>'
        f'<span class="kpi-card__period">{_period}</span></div>'
        f'<div class="kpi-card__value">{_value}</div>'
        f'<div class="kpi-card__context">{_context}</div>'
        f'<div class="kpi-card__icon" aria-hidden="true">{_icon}</div></article>'
    )
st.markdown('<section class="kpi-grid">' + ''.join(_card_html) + '</section>', unsafe_allow_html=True)
# ---------------------------------------------------------- main analysis --
# The Inflation Index & Change chart - full width (no reserved side column),
# Highcharts (see the module docstring for why), every series independently
# toggleable via the legend, drag-to-pan, and a 1x/2x/5x/10x zoom-factor
# button row + Reset. Optional overlays and visible series are controlled by
# compact dropdowns so configuration does not occupy a permanent row of
# individual switches.
show_event_bands = False
show_magnitude_bands = False

x_min, x_max = ct_as_of.index.min(), ct_as_of.index.max()
_change_values = pd.concat([ct_as_of["mom_pct"], ct_as_of["yoy_pct"]]).dropna()
y_lo = float(_change_values.min()) if not _change_values.empty else -1.0
y_hi = float(_change_values.max()) if not _change_values.empty else 1.0
pad = (y_hi - y_lo) * 0.08 or 1.0
y_lo, y_hi = y_lo - pad, y_hi + pad

_chart_series = [
    {
        "name": "CPI index (absolute)", "type": "area", "yAxis": 0,
        "color": SEQUENTIAL_HUE, "fillOpacity": 0.10, "lineWidth": 3,
        "data": [[int(ts.timestamp() * 1000), round(float(v), 2)] for ts, v in ct_as_of["cpi"].items()],
        "tooltip": {"valueDecimals": 2},
    },
    {
        "name": "Month-over-month (MoM)", "type": "line", "yAxis": 1,
        "color": MA_QUARTER_COLOR, "lineWidth": 2,
        "data": [[int(ts.timestamp() * 1000), round(float(v), 2)] for ts, v in ct_as_of["mom_pct"].dropna().items()],
        "tooltip": {"valueDecimals": 2, "valueSuffix": "%"},
    },
    {
        "name": "Year-over-year (YoY)", "type": "line", "yAxis": 1,
        "color": HIGHLIGHT_HUE, "lineWidth": 3,
        "data": [[int(ts.timestamp() * 1000), round(float(v), 2)] for ts, v in ct_as_of["yoy_pct"].dropna().items()],
        "tooltip": {"valueDecimals": 2, "valueSuffix": "%"},
    },
]

_headline_export = pd.DataFrame({
    "Reporting Month": ct_as_of.index.strftime("%Y-%m"),
    "CPI Index": ct_as_of["cpi"].round(2).values,
    "MoM Percentage": ct_as_of["mom_pct"].round(2).values,
    "YoY Percentage": ct_as_of["yoy_pct"].round(2).values,
})
_headline_xlsx = _xlsx_base64({"Headline CPI": _headline_export})

# The return value (last clicked month, ISO) is handled at the TOP of this
# script via st.session_state["hc-main-chart"] - see the "main-chart click
# -> period" block up there for why it's read there and not here.
hc_main_chart(
    {
        "chart": {
            "backgroundColor": "#FFFFFF",
            "borderColor": "#DFE8E3",
            "borderWidth": 1,
            "borderRadius": 12,
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
            "spacing": [18, 18, 12, 18],
            "spacingBottom": 10,
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
        "title": {
            "text": "Headline CPI Index and Inflation Change",
            "align": "center",
            "margin": 4,
            "style": {"color": "#14231D", "fontSize": "17px", "fontWeight": "700"},
        },
        "subtitle": {
            "text": f"General CPI · month-over-month and year-over-year · through {selected:%B %Y}",
            "align": "center",
            "style": {"color": "#66776E", "fontSize": "11px"},
        },
        "rangeSelector": {
            "enabled": False,
        },
        "navigator": {
            "enabled": False,
        },
        "scrollbar": {
            "enabled": False,
        },
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
            "plotLines": [{
                "value": int(selected.timestamp() * 1000),
                "color": PBS_GREEN_DARK,
                "width": 2,
                "zIndex": 6,
                "label": {"text": f"Selected: {selected:%b %Y}", "style": AXIS_LABEL_STYLE},
            }],
        },
        # Not a Highcharts option - our own data, read by the JS overlay in
        # _highcharts_main_chart to draw the 4 core events' NAMES above the
        # chart (see _event_plotbands's docstring for why they aren't drawn
        # via Highcharts's own plotBand `label` option).
        "eventLabels": _event_label_data(x_min, x_max) if show_event_bands else [],
        "availableOverlays": {
            "eventBands": _event_plotbands(x_min, x_max),
            "eventLabels": _event_label_data(x_min, x_max),
            "severityBands": _severity_plotbands(y_lo, y_hi),
        },
        "yAxis": [
            {
                "title": {"text": "CPI index", "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE},
                "opposite": False,
                "top": "0%",
                "height": "58%",
                "offset": 0,
                "gridLineColor": "#E8EFEB",
                "lineWidth": 0,
                "showLastLabel": True,
            },
            {
                "title": {"text": "Inflation rate", "style": AXIS_TITLE_STYLE},
                "labels": {"style": AXIS_LABEL_STYLE, "format": "{value:.1f}%"},
                "opposite": True,
                "top": "66%",
                "height": "28%",
                "offset": 0,
                "gridLineWidth": 1,
                "gridLineColor": "#EEF3F0",
                "lineWidth": 0,
                "plotBands": _severity_plotbands(y_lo, y_hi) if show_magnitude_bands else [],
                "plotLines": [{"value": 0, "color": "#718078", "width": 1.2, "zIndex": 3}],
            },
        ],
        "tooltip": {
            "shared": True,
            "xDateFormat": "%b %Y",
            "backgroundColor": "rgba(255,255,255,0.97)",
            "borderColor": "#BFD2C8",
            "borderRadius": 8,
            "shadow": True,
            "padding": 12,
        },
        "plotOptions": {
            "series": {
                "animation": {"duration": 450},
                "marker": {"enabled": False, "states": {"hover": {"enabled": True, "radius": 4}}},
                "states": {
                    "inactive": {"opacity": 0.2},
                    "hover": {"lineWidthPlus": 1, "halo": {"size": 5, "opacity": 0.12}},
                },
            },
            "area": {"threshold": None},
        },
        # Explicit dark, bold itemStyle - the default legend text otherwise
        # rendered noticeably lighter/thinner than the rest of the page's
        # type, reading as blurry/washed-out next to the bold KPI cards
        # above it (reported live).
        "legend": {
            "enabled": False,
            "itemStyle": {"color": "#1F2A24", "fontSize": "12.5px", "fontWeight": "600"},
            "itemHoverStyle": {"color": PBS_GREEN},
            "symbolWidth": 20,
            "symbolHeight": 3,
            "itemDistance": 22,
            "margin": 10,
            "padding": 0,
        },
        "credits": {"enabled": False},
        "excelDownload": {
            "base64": _headline_xlsx,
            "filename": "headline-cpi-index-and-change.xlsx",
        },
        "series": _chart_series,
    },
    height=480,
    key="hc-main-chart",
)

if show_event_bands:
    _legend_chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:16px;font-size:0.82rem;">'
        f'<span style="width:12px;height:12px;border-radius:3px;background:{e["color"]};'
        f'display:inline-block;"></span>{e.get("short_name", e["name"])}</span>'
        for e in CORE_EVENTS
    )
    st.markdown(f'<div style="margin:2px 0 10px;">{_legend_chips}</div>', unsafe_allow_html=True)

# ------------------------------------------------------ what caused the spike -
# Scroll target for the main chart's click-to-navigate - the chart component
# scrolls the page here itself right after a click (see hc_main_chart.py's
# __scrollParentToGroupBars); this id must stay stable.
st.markdown(f'<div id="{ANCHOR_ID}"></div>', unsafe_allow_html=True)

# `selected` is chosen by the "Selected period" picker rendered near the top
# of the page (above the KPI cards) - see that block for why it moved.
period_groups = selected_period_group_table(group_long, selected)

if not period_groups.empty:
    # Official two-digit COICOP code order for BOTH charts. Descriptions and
    # current values never affect category order, and the same verified code
    # is passed into the item-level drill-down.
    sorted_for_chart = (
        period_groups.assign(group_code=period_groups["group"].map(CPI_GROUP_CODES))
        .sort_values("group_code", ascending=True)
    )
    _heat_source = group_long.loc[
        (group_long["date"] <= selected) & group_long["group"].isin(GROUPS_12),
        ["date", "group", "mom_pct", "yoy_pct"],
    ].sort_values(["date", "group"])
    _heat_dates = list(_heat_source["date"].drop_duplicates().tail(12))
    _heat_matrix = []
    for _date in _heat_dates:
        _month_rows = _heat_source.loc[_heat_source["date"] == _date].set_index("group")
        _values = {}
        for _group in GROUPS_12:
            if _group not in _month_rows.index:
                _values[_group] = {"mom": None, "yoy": None}
                continue
            _row = _month_rows.loc[_group]
            _values[_group] = {
                "mom": None if pd.isna(_row["mom_pct"]) else round(float(_row["mom_pct"]), 2),
                "yoy": None if pd.isna(_row["yoy_pct"]) else round(float(_row["yoy_pct"]), 2),
            }
        _heat_matrix.append({
            "month": _date.strftime("%b %Y"),
            "period": _date.strftime("%Y-%m"),
            "values": _values,
        })
    _heat_groups = [
        {"full": group, "short": CPI_GROUP_SHORT_NAMES.get(group, group), "code": CPI_GROUP_CODES[group]}
        for group in sorted(GROUPS_12, key=lambda name: CPI_GROUP_CODES[name])
    ]
    _detail_start = _heat_dates[0] - pd.DateOffset(months=12) if _heat_dates else None
    _detail_end = _heat_dates[-1] if _heat_dates else None
    _item_rows = _item_drilldown(_detail_start, _detail_end) if _heat_dates else pd.DataFrame()
    _heat_items: dict[str, list[dict]] = {}
    if not _item_rows.empty:
        for (_year, _month, _group_code), _items in _item_rows.groupby(
            ["year", "month", "GroupCode"], sort=False
        ):
            _records = []
            for _item in _items.itertuples(index=False):
                _description = str(_item.ItemDescription).strip()
                _records.append({
                    "code": str(_item.ItemCode).strip(),
                    "description": _description,
                    "short": _description if len(_description) <= 34 else _description[:31].rstrip() + "…",
                    "unit": None if pd.isna(_item.Unit) else str(_item.Unit).strip(),
                    **{
                        f"w{q}": None if pd.isna(getattr(_item, f"Weight{q}")) else round(float(getattr(_item, f"Weight{q}")), 4)
                        for q in range(6)
                    },
                    "gm": None if pd.isna(_item.GMPrice) else round(float(_item.GMPrice), 2),
                    "cities": int(_item.CityCount),
                    "minPrice": None if pd.isna(_item.MinCityPrice) else round(float(_item.MinCityPrice), 2),
                    "maxPrice": None if pd.isna(_item.MaxCityPrice) else round(float(_item.MaxCityPrice), 2),
                })
            _heat_items[f"{int(_year):04d}-{int(_month):02d}|{str(_group_code).strip()}"] = _records
    _city_price_index: dict[str, list[list]] = {}
    if not _item_rows.empty:
        for _item in _item_rows.itertuples(index=False):
            _city_price_index[
                f"{int(_item.year):04d}-{int(_item.month):02d}|{str(_item.ItemCode).strip()}"
            ] = json.loads(_item.CityPricesJson or "[]")
    _district_map_rows = _cpi_district_map()
    _district_city_map = [
        {
            "provinceCode": str(row.ProvinceCode).strip(),
            "provinceName": str(row.ProvinceName).strip(),
            "divisionCode": str(row.DivisionCode).strip(),
            "divisionName": str(row.DivisionName).strip(),
            "districtCode": str(row.DistrictCode).strip(),
            "districtName": str(row.DistrictName).strip(),
            "cityCode": int(row.CityCode),
            "cityName": str(row.CityName).strip().strip('"'),
        }
        for row in _district_map_rows.itertuples(index=False)
    ]
    _drilldown_export = _item_rows.drop(columns=["CityPricesJson"], errors="ignore").rename(columns={
        "year": "Year", "month": "Month", "GroupCode": "Group Code",
        "ItemCode": "Item Code", "ItemDescription": "Item Description",
        "GMPrice": "City Price GM", "CityCount": "City Count",
        "MinCityPrice": "Minimum City Price", "MaxCityPrice": "Maximum City Price",
    })
    _drilldown_xlsx = _xlsx_base64({"Item drilldown": _drilldown_export})
    _highcharts_group_bars(
        "hc-group-mom",
        "hc-group-yoy",
        # Same icon per group as the Inflation Heatmap page's column headers
        # (pricelab.dashboard.theme.CPI_GROUP_ICONS, shared rather than a
        # separate guess) - on the category axis, so it shows on both bar
        # charts' labels and their tooltips (Highcharts pairs each point
        # with its category by position automatically).
        categories=[
            f"{CPI_GROUP_SHORT_NAMES.get(g, g)} · {CPI_GROUP_ICONS.get(g, '')}".strip(" ·")
            for g in sorted_for_chart["group"]
        ],
        full_categories=list(sorted_for_chart["group"]),
        heat_matrix=_heat_matrix,
        heat_groups=_heat_groups,
        heat_items=_heat_items,
        city_prices=_city_price_index,
        district_city_map=_district_city_map,
        geojson_levels=_price_geojson_levels(),
        drilldown_xlsx=_drilldown_xlsx,
        left_pct=sorted_for_chart["mom_pct"],
        left_title="MoM CPI Movement by Group",
        right_pct=sorted_for_chart["yoy_pct"],
        right_title="YoY CPI Movement by Group",
        # Native chart title/subtitle, not the page's shared selectbox -
        # see _highcharts_group_bars's docstring for why: so the period
        # travels with either chart if it's downloaded/exported on its own.
        period_label=f"{selected:%B %Y}",
    )

    # The click-driven heat table and its item-level analytical drill-down
    # are the terminal content of the Home page. Legacy archive/event tables
    # below remain in source temporarily for reference but are intentionally
    # not rendered.
    st.stop()

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
    height=240,
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
    height=240,
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
