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
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    # Top-of-page KPIs only - the "What caused the inflation spike?" heading
    # and its own 4-metric KPI row/active-event caption were removed; the
    # period picker and 12-group breakdown (bar chart + table) stayed.
    assert len(at.metric) == 4
    # Spike-section breakdown + month-by-month + year-by-year + Global Events.
    assert len(at.dataframe) == 4
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


def test_inflation_heatmap_page_loads_with_group_columns_and_period_rows():
    at = AppTest.from_file(str(HEATMAP_PATH), default_timeout=60).run()
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
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    page_text = " ".join(md.value for md in at.markdown) + " ".join(h.value for h in at.subheader)
    assert "What caused the inflation spike" not in page_text
    assert "Selected period:" not in page_text  # the bold "**Selected period: ...**" line
    # The period picker and 12-group breakdown below it are still present.
    assert "period_picker" in at.session_state
    assert "selected_period" in at.session_state


def test_main_chart_full_width_with_pan_and_zoom_controls():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]

    # Regression check: the chart used to sit in st.columns([9, 3]) with an
    # empty reserved column beside it. Column count across the WHOLE page
    # should now be exactly 6 (4 top KPIs + 2 band checkboxes - the M/M-YoY
    # comparison section's own 2 columns were removed along with it) - if
    # the 9:3 split were still there, it'd be higher.
    assert len(at.columns) == 6

    cfg = _main_chart_config(at)

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

    # 1x/2x/5x/10x + Reset zoom-factor buttons and the click->setComponentValue
    # wiring live in the component's static frontend file, not per-render
    # JSON args - written as a side effect of app.py running (see
    # _write_hc_main_chart_component), so it's a real file on disk by now.
    component_html = MAIN_CHART_COMPONENT_HTML.read_text(encoding="utf-8")
    for needle in ("function __zoom(", "function __reset(", "setValue(ymd)"):
        assert needle in component_html
    assert "Highcharts.stockChart" in component_html
    assert "code.highcharts.com" not in component_html  # bundled locally, not loaded from a CDN


def test_event_and_severity_bands_toggle_into_the_chart_config():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    cfg = _main_chart_config(at)
    assert cfg["xAxis"]["plotBands"] == []  # off by default
    assert cfg["yAxis"][1]["plotBands"] == []
    assert cfg["eventLabels"] == []

    event_cb = next(c for c in at.checkbox if "major-event" in c.label.lower())
    severity_cb = next(c for c in at.checkbox if "severity" in c.label.lower())
    event_cb.set_value(True)
    severity_cb.set_value(True)
    at = at.run()
    assert not at.exception, [e.message for e in at.exception]

    cfg = _main_chart_config(at)
    assert len(cfg["xAxis"]["plotBands"]) == 4  # shaded regions only, no Highcharts `label`
    assert all("label" not in b for b in cfg["xAxis"]["plotBands"])
    # Event NAMES are a plain HTML/CSS overlay (see _event_label_data /
    # _write_hc_main_chart_component's JS), not a Highcharts plotBand
    # `label` - several attempts at the native option all broke in
    # different ways (overlap, truncation, or clipping) - stored as our
    # own `eventLabels` config key instead.
    event_names = {item["text"] for item in cfg["eventLabels"]}
    assert "COVID-19" in event_names

    severity_labels = {b["label"]["text"] for b in cfg["yAxis"][1]["plotBands"]}
    # Label text is a useHTML span (background box, for readability against
    # the chart lines behind it) - substring match, not exact equality.
    assert any("Very high inflation" in t for t in severity_labels)


def test_group_bars_share_one_category_order_and_a_synced_mode_toggle():
    """The MoM and Y/Y group bar charts (_highcharts_group_bars) must use
    the exact same groups in the exact same order (not independently
    re-sorted), matching colors/styling, and one Percentage/Absolute Value
    toggle driving both charts together."""
    from pricelab.dashboard.theme import CPI_GROUP_ORDER, DECREASE_COLOR, INCREASE_COLOR

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    srcdoc = _group_bars_srcdoc(at)

    left_pct = _json_after(srcdoc, "var __leftPct = ")
    left_abs = _json_after(srcdoc, "var __leftAbs = ")
    right_pct = _json_after(srcdoc, "var __rightPct = ")
    right_abs = _json_after(srcdoc, "var __rightAbs = ")

    left_config = _json_after(srcdoc, "Highcharts.chart('hc-group-mom', ")
    right_config = _json_after(srcdoc, "Highcharts.chart('hc-group-yoy', ")
    left_categories = left_config["xAxis"]["categories"]
    right_categories = right_config["xAxis"]["categories"]

    # Same groups, same order, in both charts - and it's the real 12
    # COICOP groups, not a separately hand-built list.
    assert left_categories == right_categories
    assert set(left_categories) == set(CPI_GROUP_ORDER[1:])
    assert len(left_categories) == 12

    # The Percentage dataset's own point order must match that category
    # order too (paired by position, not re-sorted per series) - and all
    # four datasets (both charts x both modes) are the same length as the
    # category list.
    for dataset in (left_pct, left_abs, right_pct, right_abs):
        assert len(dataset) == len(left_categories)

    # Colors follow the same increase/decrease pair used everywhere else on
    # this page, by the value's own sign - not a separate, ad-hoc palette.
    for point in left_pct + right_pct:
        if point is None:
            continue
        assert point["color"] == (INCREASE_COLOR if point["y"] >= 0 else DECREASE_COLOR)

    # Titles per the spec: the original chart keeps its identity, the new
    # one is clearly labeled "Year-to-Year Inflation".
    assert "Inflation Groups" in srcdoc
    assert "Year-to-Year Inflation" in srcdoc

    # One shared toggle drives both charts' setData together, with a
    # smooth Highcharts-native animated transition (not a Streamlit rerun
    # that would tear down and recreate this iframe on every click).
    assert "function __setGroupBarMode(mode)" in srcdoc
    assert "__leftChart.series[0].setData(pct ? __leftPct : __leftAbs, true" in srcdoc
    assert "__rightChart.series[0].setData(pct ? __rightPct : __rightAbs, true" in srcdoc
    assert "Percentage" in srcdoc and "Absolute Value" in srcdoc


def test_archive_tables_show_all_12_real_groups():
    from pricelab.dashboard.theme import CPI_GROUP_ORDER

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    spike, monthly, yearly, ge = (d.value for d in at.dataframe)
    assert set(monthly["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])
    assert set(yearly["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])
    assert set(spike["Inflation Group"]) <= set(CPI_GROUP_ORDER[1:])
    assert len(ge) > 0
