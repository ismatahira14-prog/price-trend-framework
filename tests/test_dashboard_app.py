"""Headless smoke test for the Home dashboard page.

Runs the actual Streamlit script via AppTest - this is what caught the
_highlight_month() column-name bug during development, so it stays as a
permanent regression test rather than a one-off check.
"""

import json
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1", reason="requires the [dashboard] extra")
AppTest = st_testing.AppTest

from pricelab.integration.duckdb_export import snapshot_path  # noqa: E402

APP_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
HEATMAP_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "4_Inflation_Heatmap.py"
)
# Written as a side effect of running app.py (see _write_hc_main_chart_component) -
# a real file on disk, safe to read directly once `at.run()` has executed.
MAIN_CHART_COMPONENT_HTML = APP_PATH.parent / "components" / "hc_main_chart" / "index.html"


@pytest.fixture(scope="module", autouse=True)
def _require_snapshot():
    if not snapshot_path().is_file():
        pytest.skip("no duckdb snapshot yet - run `python -m pricelab.ingest --all` first")


def _main_chart_config(at) -> dict:
    """Pull the Highcharts config out of the `hc_main_chart` custom
    component. AppTest has no dedicated wrapper for a component instance
    (it falls back to a generic `UnknownElement`, found via `at.get(
    "component_instance")`) - but the args passed to it are plain JSON
    (`proto.json_args`, `{"config": {...}, "height": ..., "key": ...}`), far
    simpler to read than the iframe-embedded-script approach the group-bars
    chart still needs (see `_json_after`).
    """
    instances = at.get("component_instance")
    # Declared in pricelab.dashboard.hc_main_chart (a normally-imported
    # module, not dashboard/app.py itself) - see that module's docstring -
    # so Streamlit names it "<module>.<name>", not "app.hc_main_chart".
    main = next(
        c for c in instances if c.proto.component_name == "pricelab.dashboard.hc_main_chart.hc_main_chart"
    )
    return json.loads(main.proto.json_args)["config"]


def _json_after(srcdoc: str, prefix: str) -> object:
    """Pull a JSON value (object or array) back out of `var NAME = <json>;`
    inside an embedded <script> block. A simple brace-depth scan (like
    similar to the main chart's earlier iframe-era JSON extraction) but
    tracking BOTH `{}` and `[]` together, since a top-level value here can
    be a JSON array (`_highcharts_group_bars`'s per-mode point lists), not
    just an object.
    """
    start = srcdoc.index(prefix) + len(prefix)
    assert srcdoc[start] in "{[", f"expected a JSON value right after {prefix!r}"
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(srcdoc)):
        ch = srcdoc[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return json.loads(srcdoc[start : i + 1])
    raise AssertionError(f"never found the matching close for {prefix!r}")


def _group_bars_srcdoc(at) -> str:
    iframe = next(f for f in at.get("iframe") if "hc-group-mom" in f.proto.srcdoc)
    return iframe.proto.srcdoc


def test_home_page_loads_without_exceptions():
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    # Top-of-page KPIs only - the "What caused the inflation spike?" heading
    # and its own 4-metric KPI row/active-event caption were removed; the
    # period picker and 12-group breakdown (bar chart + table) stayed. 6:
    # Inflation (CPI), MoM, YoY, Historic Low, Historic High, Snapshot.
    assert len(at.metric) == 0  # purpose-built KPI cards, not generic st.metric widgets
    # The click-driven heat table and item analytics are now the terminal
    # Home-page content. Legacy Streamlit archive/event tables were removed.
    assert len(at.dataframe) == 0
    # No Plotly left on this page at all - the 12-group breakdown is now a
    # pair of Highcharts bar charts (MoM/YoY, see _highcharts_group_bars).
    # The Inflation Index & Change chart is a real custom component
    # (`hc_main_chart`, so it can send a click back into Python) - AppTest
    # has no dedicated wrapper for that, it shows up generically via
    # `at.get("component_instance")`. The group-bars pair (one iframe,
    # doesn't need a return channel) is the only remaining
    # st.components.v1.html -> `iframe` in AppTest; the separate "Month-to-
    # Month vs Year-to-Year comparison" section (two more) was removed.
    assert len(at.get("plotly_chart")) == 0
    assert len(at.get("component_instance")) == 1
    assert len(at.get("iframe")) == 1


def test_historic_low_and_high_kpis_use_the_full_series_not_just_latest():
    """Historic Low/High Inflation must be the min/max of the WHOLE
    historical YoY series (and the exact month/year each occurred in) -
    genuinely computed, not the latest value or a hardcoded number."""
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
    from pricelab.dashboard.data import cpi_change_table, cpi_series, load_master_long

    df = load_master_long()
    ct = cpi_change_table(cpi_series(df, ["General"])["General"])
    expected_low_date = ct["yoy_pct"].idxmin()
    expected_low_val = ct["yoy_pct"].min()
    expected_high_date = ct["yoy_pct"].idxmax()
    expected_high_val = ct["yoy_pct"].max()
    latest_period = f"{ct.index[-1]:%b %Y}"
    low_period = f"{expected_low_date:%b %Y}"
    high_period = f"{expected_high_date:%b %Y}"

    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    cards = next(m.value for m in at.get("markdown") if 'class="kpi-grid"' in m.value)
    assert f"{ct['cpi'].iloc[-1]:.2f}" in cards
    assert f"{expected_low_val:+.2f}%" in cards
    assert f"{expected_high_val:+.2f}%" in cards
    assert latest_period in cards and low_period in cards and high_period in cards
    # The two are genuinely different extremes, not the same value twice.
    assert f"{expected_low_val:+.2f}%" != f"{expected_high_val:+.2f}%"


def test_inflation_heatmap_page_loads_with_group_columns_and_period_rows():
    at = AppTest.from_file(str(HEATMAP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.dataframe) == 1
    table = at.dataframe[0].value
    assert len(table.columns) == 12
    assert [column.split()[-1] for column in table.columns] == [
        "Food",
        "Tobacco",
        "Clothing",
        "Housing",
        "Furnishing",
        "Health",
        "Transport",
        "Communication",
        "Recreation",
        "Education",
        "Restaurants",
        "Miscellaneous",
    ]
    assert table.index.name == "Month"
    assert len(table) > 0


def test_spike_analysis_heading_and_kpis_are_gone():
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    page_text = " ".join(md.value for md in at.markdown) + " ".join(h.value for h in at.subheader)
    assert "What caused the inflation spike" not in page_text
    assert "Selected period:" not in page_text  # the bold "**Selected period: ...**" line
    # The period picker and 12-group breakdown below it are still present.
    assert "period_picker" in at.session_state
    assert "selected_period" in at.session_state


def test_main_chart_full_width_with_pan_and_zoom_controls():
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]

    # Regression check: the chart used to sit in st.columns([9, 3]) with an
    # empty reserved column beside it. Column count across the WHOLE page
    # should now be exactly 2 (the unified year/month reporting-period cards;
    # the click-driven heat table has no separate Streamlit button columns)
    # - if the 9:3 split were still there, it'd be higher.
    assert len(at.columns) == 2

    cfg = _main_chart_config(at)
    assert cfg["title"]["text"] == "Headline CPI Index and Inflation Change"
    assert cfg["title"]["align"] == "center"
    assert cfg["subtitle"]["text"].startswith("General CPI · month-over-month")
    assert cfg["subtitle"]["align"] == "center"
    assert cfg["excelDownload"]["filename"] == "headline-cpi-index-and-change.xlsx"
    assert len(cfg["excelDownload"]["base64"]) > 100

    # Drag pans (not the Highcharts Stock default of drag-to-zoom-a-rectangle).
    # panKey/zooming are deliberately left unset rather than set to null -
    # see the comment in app.py - so this only asserts the config is right;
    # the actual drag gesture was verified live in a real browser (Playwright),
    # including the xAxis.ordinal=False fix below - Highcharts Stock's default
    # ordinal (gap-skipping) axis registers its own chart-level "pan" handler
    # that pre-empts the normal one and threw for our non-gappy monthly data,
    # silently swallowing every drag.
    assert cfg["chart"]["panning"] == {"enabled": True, "type": "x"}
    assert cfg["xAxis"]["ordinal"] is False
    assert cfg["yAxis"][0]["height"] == "58%"
    assert cfg["yAxis"][1]["top"] == "66%"
    assert cfg["yAxis"][1]["height"] == "28%"

    # Compact period/series/overlay controls, PNG download, and
    # click->setComponentValue wiring live in the component's static frontend,
    # written as a side effect of app.py running (see
    # _write_hc_main_chart_component), so it's a real file on disk by now.
    component_html = MAIN_CHART_COMPONENT_HTML.read_text(encoding="utf-8")
    assert cfg["rangeSelector"]["enabled"] is False
    for needle in (
        "function __applyPeriod(", "function __toggleSeries(",
        "function __toggleOverlays(", "function __downloadPng(", "setValue(ymd)",
    ):
        assert needle in component_html
    for label in (
        "1Y · 12 months", "3Y · 36 months", "5Y · 60 months",
        "10Y · 120 months", "All data", "Series", "Major events",
        "Inflation severity", "Capture chart image (PNG)", "Download chart data (Excel)",
    ):
        assert label in component_html
    assert "Highcharts.stockChart" in component_html
    assert "code.highcharts.com" not in component_html  # bundled locally, not loaded from a CDN


def test_event_and_severity_bands_toggle_into_the_chart_config():
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    cfg = _main_chart_config(at)
    assert cfg["xAxis"]["plotBands"] == []  # off by default
    assert cfg["yAxis"][1]["plotBands"] == []
    assert cfg["eventLabels"] == []

    available = cfg["availableOverlays"]
    assert len(available["eventBands"]) == 4
    assert all("label" not in b for b in available["eventBands"])
    # Event NAMES are a plain HTML/CSS overlay (see _event_label_data /
    # _write_hc_main_chart_component's JS), not a Highcharts plotBand
    # `label` - several attempts at the native option all broke in
    # different ways (overlap, truncation, or clipping) - stored as our
    # own `eventLabels` config key instead.
    event_names = {item["text"] for item in available["eventLabels"]}
    assert "COVID-19" in event_names

    severity_labels = {b["label"]["text"] for b in available["severityBands"]}
    # Label text is a useHTML span (background box, for readability against
    # the chart lines behind it) - substring match, not exact equality.
    assert any("Very high inflation" in t for t in severity_labels)


def test_main_chart_series_can_be_selected_independently():
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    cfg = _main_chart_config(at)
    assert cfg["legend"]["enabled"] is False
    assert [series["name"] for series in cfg["series"]] == [
        "CPI index (absolute)",
        "Month-over-month (MoM)",
        "Year-over-year (YoY)",
    ]
    component_html = MAIN_CHART_COMPONENT_HTML.read_text(encoding="utf-8")
    assert "if (axis && axis.visible) axis.setExtremes(null, null, false)" in component_html
    assert "function __reflowAxes()" in component_html
    assert "internal navigator axes" in component_html
    assert "No series selected" in component_html


def test_group_bars_share_one_category_order_and_a_synced_mode_toggle():
    """The MoM and Y/Y group bar charts (_highcharts_group_bars) must use
    the exact same groups in the exact same order (not independently
    re-sorted), matching colors/styling, and percentage-change data only."""
    from pricelab.dashboard.theme import (
        CPI_GROUP_CODES, CPI_GROUP_ICONS, CPI_GROUP_ORDER, CPI_GROUP_SHORT_NAMES,
        DECREASE_COLOR, INCREASE_COLOR,
    )

    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    srcdoc = _group_bars_srcdoc(at)

    left_pct = _json_after(srcdoc, "var __leftPct = ")
    right_pct = _json_after(srcdoc, "var __rightPct = ")

    left_config = _json_after(srcdoc, "Highcharts.chart('hc-group-mom', ")
    right_config = _json_after(srcdoc, "Highcharts.chart('hc-group-yoy', ")
    left_categories = left_config["xAxis"]["categories"]
    right_categories = right_config["xAxis"]["categories"]

    # Same groups, same order, in both charts - and it's the real 12
    # COICOP groups (each suffixed with its shared CPI_GROUP_ICONS emoji,
    # same as the Inflation Heatmap page's column headers - not a
    # separately hand-built list or a different icon set).
    assert left_categories == right_categories
    expected = [
        f"{CPI_GROUP_SHORT_NAMES.get(g, g)} · {CPI_GROUP_ICONS.get(g, '')}".strip(" ·")
        for g in sorted(CPI_GROUP_ORDER[1:], key=lambda name: CPI_GROUP_CODES[name])
    ]
    assert left_categories == expected
    assert len(left_categories) == 12
    heat_groups = _json_after(srcdoc, "var __heatGroups = ")
    assert [group["code"] for group in heat_groups] == [f"{code:02d}" for code in range(1, 13)]
    assert all(CPI_GROUP_CODES[group["full"]] == group["code"] for group in heat_groups)

    # The Percentage dataset's own point order must match that category
    # order too (paired by position, not re-sorted per series).
    for dataset in (left_pct, right_pct):
        assert len(dataset) == len(left_categories)

    # Colors follow the same increase/decrease pair used everywhere else on
    # this page, by the value's own sign - not a separate, ad-hoc palette.
    for point in left_pct + right_pct:
        if point is None:
            continue
        assert point["color"] == (INCREASE_COLOR if point["y"] >= 0 else DECREASE_COLOR)

    # Each chart's heading and the selected period are the chart's OWN
    # native Highcharts title/subtitle (not a plain HTML heading/the page's
    # shared selectbox) so both travel with the chart if it's downloaded or
    # exported on its own.
    assert left_config["title"]["text"] == "MoM CPI Movement by Group"
    assert right_config["title"]["text"] == "YoY CPI Movement by Group"
    assert left_config["subtitle"]["text"].startswith("Selected period: ")
    assert left_config["subtitle"]["text"] == right_config["subtitle"]["text"]

    assert "function __setGroupBarMode(mode)" not in srcdoc
    assert "Display values" not in srcdoc
    assert "Index points" not in srcdoc
    assert "monthly-cpi-movement.xlsx" in srcdoc
    assert "annual-cpi-movement.xlsx" in srcdoc
    assert "function __downloadChartPng(chart, filename)" in srcdoc
    assert srcdoc.count("Download chart data (Excel)") == 2
    # Two bar-chart action pairs, the item-table Excel action, and the new
    # city-map PNG/Excel action pair all use the same icon system.
    assert srcdoc.count('class="hc-action-icon"') == 8
    assert "function __renderPeriodHeat(measure)" in srcdoc
    assert "12 groups · 12 months" in srcdoc
    assert "Highcharts.addEvent(Highcharts.Point, 'click'" in srcdoc
    assert "function __setHeatMeasure(measure)" in srcdoc
    assert "function __setHeatScale(mode)" in srcdoc
    for label in ("Row-wise", "Column-wise"):
        assert label in srcdoc
    assert '<option value="mixed">' not in srcdoc


def test_clicking_the_main_chart_syncs_the_exact_period_into_the_group_bars():
    """The main Inflation Index chart's click-to-navigate: clicking a point
    (the `hc_main_chart` component reports the x-axis DATE under the cursor,
    from the chart's own axis mapping - see hc_main_chart.py) must select
    that EXACT month everywhere below - the "Selected period" picker, the
    period-specific KPI cards, and BOTH group bar charts (MoM + YoY) - never
    a nearest / shifted month. The chart component also scrolls the page to
    that section on click. This broke once when the picker moved above the
    KPIs; keep it covered.
    """
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
    from pricelab.dashboard.data import cpi_change_table, cpi_series, load_master_long

    ct = cpi_change_table(cpi_series(load_master_long(), ["General"])["General"])

    for target in (ct.index[3], ct.index[len(ct) // 2], ct.index[-2]):
        at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
        # Simulate the component reporting a click on `target` (ISO, snapped
        # to the first of the month, exactly as the frontend sends it).
        at.session_state["hc-main-chart"] = f"{target:%Y-%m-%d}"
        at.run()
        assert not at.exception, (target, [e.message for e in at.exception])

        picked_year, picked_month = at.selectbox[0].value, at.selectbox[1].value
        assert (picked_year, picked_month) == (target.year, target.month), (
            f"pickers landed on {picked_year}-{picked_month:02d}, not the clicked {target:%b %Y}"
        )

        # Current CPI card is period-specific - exact value + period.
        cards = next(m.value for m in at.get("markdown") if 'class="kpi-grid"' in m.value)
        assert f"{target:%b %Y}" in cards
        assert f"{ct.loc[target, 'cpi']:.2f}" in cards

        # Both group bar charts carry the exact clicked month as their subtitle.
        srcdoc = _group_bars_srcdoc(at)
        left_config = _json_after(srcdoc, "Highcharts.chart('hc-group-mom', ")
        right_config = _json_after(srcdoc, "Highcharts.chart('hc-group-yoy', ")
        assert left_config["subtitle"]["text"] == f"Selected period: {target:%B %Y}"
        assert right_config["subtitle"]["text"] == f"Selected period: {target:%B %Y}"
        # MoM (left) and YoY (right) datasets are both present for that period.
        assert _json_after(srcdoc, "var __leftPct = ")
        assert _json_after(srcdoc, "var __rightPct = ")

    # The chart component carries the scroll-to-bar-graphs behaviour itself:
    # it targets the "spike-section-anchor" div and fires on every click.
    anchor_id = "spike-section-anchor"
    assert f'<div id="{anchor_id}"></div>' in at.get("markdown")[0].value or any(
        anchor_id in m.value for m in at.get("markdown")
    )
    component_html = MAIN_CHART_COMPONENT_HTML.read_text(encoding="utf-8")
    assert "__scrollParentToGroupBars" in component_html
    assert component_html.count("__scrollParentToGroupBars()") >= 1  # called from the click handler
    assert anchor_id in component_html
    # Clicks land on the plot background AND directly on a line/point: both a
    # chart-level and a per-point click handler must be wired.
    assert "Highcharts.addEvent(__chart, 'click'" in component_html
    assert "point: { events: { click:" in component_html
    # The continuous chart-level x-value is snapped to the NEAREST month so a
    # click near a boundary never selects the month before/after.
    assert "getUTCDate() >= 15" in component_html

    # A click outside the data range clamps to the nearest endpoint (the
    # latest month) rather than erroring or selecting nothing.
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    at.session_state["hc-main-chart"] = "2099-01-01"
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert (at.selectbox[0].value, at.selectbox[1].value) == (
        ct.index[-1].year,
        ct.index[-1].month,
    )


def test_item_drilldown_replaces_legacy_lower_page_content():
    at = AppTest.from_file(str(APP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.dataframe) == 0
    srcdoc = _group_bars_srcdoc(at)
    items = _json_after(srcdoc, "var __heatItems = ")
    # Up to 24 periods are requested for YoY comparison, but CPI city prices
    # currently begin in Jan 2025. Every available period must still carry
    # all 12 groups; unavailable prior-year comparisons render as gaps.
    periods = {key.split("|")[0] for key in items}
    assert len(periods) >= 12
    assert len(items) == len(periods) * 12
    assert all(records for records in items.values())
    sample = next(iter(items.values()))[0]
    assert {"code", "description", "w0", "w1", "w2", "w3", "w4", "w5", "gm", "cities"} <= set(sample)
    city_prices = _json_after(srcdoc, "var __cityPrices = ")
    district_map = _json_after(srcdoc, "var __districtCityMap = ")
    geojson_levels = _json_after(srcdoc, "var __geoJSONLevels = ")
    assert city_prices
    assert all(len(pair) == 2 for prices in city_prices.values() for pair in prices)
    assert len(district_map) == 41
    assert len({row["cityCode"] for row in district_map}) == 35
    assert all(
        {"provinceCode", "provinceName", "divisionCode", "divisionName"} <= set(row)
        for row in district_map
    )
    assert set(geojson_levels) == {"province", "division", "district"}
    assert len(geojson_levels["province"]["features"]) == 8
    assert len(geojson_levels["division"]["features"]) == 38
    assert {str(feature["properties"]["code"]) for feature in geojson_levels["province"]["features"]} >= {
        row["provinceCode"] for row in district_map
    }
    assert {str(feature["properties"]["code"]) for feature in geojson_levels["division"]["features"]} >= {
        row["divisionCode"] for row in district_map
    }
    # Seven Karachi district polygons are intentionally replaced by the one
    # Karachi Division polygon (dv code 18); every other area remains ds-level.
    district_geojson = geojson_levels["district"]
    assert len(district_geojson["features"]) == 151
    karachi = [
        feature
        for feature in district_geojson["features"]
        if feature["properties"].get("sourceBoundaryLevel") == "division"
    ]
    assert len(karachi) == 1
    assert str(karachi[0]["properties"]["code"]) == "18"
    assert karachi[0]["properties"]["mapCityCode"] == 18
    karachi_districts = {"146", "147", "148", "149", "150", "154", "166"}
    feature_codes = {str(feature["properties"]["code"]) for feature in district_geojson["features"]}
    assert feature_codes.isdisjoint(karachi_districts)
    assert feature_codes >= {
        row["districtCode"] for row in district_map if row["cityCode"] != 18
    }
    assert "function __renderItemDrilldown(period, groupCode, measure, cell)" in srcdoc
    assert "__heatMatrix[__heatMatrix.length - 1]" in srcdoc
    assert "group.code === '01'" in srcdoc
    assert "function __renderCityMap(itemCode, period, cell)" in srcdoc
    assert "function __aggregateMapAreas(currentByCity, previousByCity, level, metric)" in srcdoc
    assert 'id="hc-map-metric"' in srcdoc
    assert '<option value="price">Price</option>' in srcdoc
    assert '<option value="mom">MoM change</option>' in srcdoc
    assert '<option value="yoy">YoY change</option>' in srcdoc
    assert "(currentAverage/previousAverage-1)*100" in srcdoc
    assert "Percentages are never averaged" in srcdoc
    assert "function __setMapLevel(level)" in srcdoc
    assert "function __toggleMapLabels()" in srcdoc
    assert "function __zoomMap(direction)" in srcdoc
    assert "function __resetMapZoom()" in srcdoc
    assert 'id="hc-map-zoom-in"' in srcdoc and 'id="hc-map-zoom-out"' in srcdoc
    assert "function __focusMapArea(areaCode,areaName)" in srcdoc
    assert "function __clearMapAreaFocus()" in srcdoc
    assert "Click an area to focus its reporting cities" in srcdoc
    assert 'id="hc-price-map-svg"' in srcdoc
    assert 'id="hc-city-price-body"' in srcdoc
    assert "grid-template-columns:minmax(0,2fr) minmax(245px,1fr)" in srcdoc
    assert "data-price-period" in srcdoc
    assert 'id="hc-map-extremes"' in srcdoc
    assert "Lowest '+levelLabel+' '+metric.short.toLowerCase()" in srcdoc
    assert "Highest '+levelLabel+' '+metric.short.toLowerCase()" in srcdoc
    assert 'class="hc-map-stat"' not in srcdoc
    assert "Largest Item Weights" not in srcdoc


MEDICAL_GROUP_PATH = APP_PATH.parent / "pages" / "2_Medical_Group.py"


def test_medical_group_dashboard_renders_five_groups_and_analytics():
    """The Medical Group (Health / Group 06) dashboard renders as one HTML
    canvas: 4 KPI cards, the five groups (Medical Equipment replacing Key
    Insights) and the five bottom analytic cards - built from real Group 06
    data, no statistics jargon, no fabricated Key Insights panel."""
    at = AppTest.from_file(str(MEDICAL_GROUP_PATH), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]

    iframe = next(f for f in at.get("iframe") if "mg-root" in f.proto.srcdoc)
    doc = iframe.proto.srcdoc

    for kpi in ("Total Items", "Overall Change (MoM)", "Basket Weight", "Overall Change (YoY)"):
        assert kpi in doc
    for grp in ("Medicines", "Services", "Diagnostics", "Procedures", "Medical Equipment"):
        assert f">{grp}<" in doc or f"mg-col-title\">{grp}" in doc
    assert "Key Insights" not in doc
    for card in ("Group Price Dynamics", "Revisions Timeline", "Most Revised Items",
                 "Pakistan City Price Pressure", "Relationship Explorer"):
        assert card in doc

    # real Group 06 items are present
    assert "Septran" in doc and ("C-Section" in doc or "Cost Of Surgery" in doc)
    # no statistics vocabulary leaked in
    low = doc.lower()
    for term in ("correlation", "coefficient", "pearson", "r = ", "p-value"):
        assert term not in low, f"jargon leaked onto the page: {term}"
