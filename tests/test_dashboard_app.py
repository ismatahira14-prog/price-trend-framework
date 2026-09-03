"""Headless smoke test for the Home dashboard page.

Runs the actual Streamlit script via AppTest - this is what caught the
_highlight_month() column-name bug during development, so it stays as a
permanent regression test rather than a one-off check.
"""

import json
import re
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1", reason="requires the [dashboard] extra")
AppTest = st_testing.AppTest

from pricelab.integration.duckdb_export import snapshot_path  # noqa: E402

APP_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


@pytest.fixture(scope="module", autouse=True)
def _require_snapshot():
    if not snapshot_path().is_file():
        pytest.skip("no duckdb snapshot yet - run `python -m pricelab.ingest --all` first")


def _chart_config(srcdoc: str, chart_id: str) -> dict:
    """Pull the JSON config back out of an embedded Highcharts <script> block."""
    m = re.search(rf"Highcharts\.stockChart\('{re.escape(chart_id)}', (.*?)\);", srcdoc, re.S)
    assert m, f"couldn't find the stockChart(...) call for {chart_id!r}"
    return json.loads(m.group(1))


def test_home_page_loads_without_exceptions():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.metric) == 4  # top-of-page KPIs only - the spike-analysis KPIs were removed
    # Month-by-month + year-by-year + Global Events (the 12-group breakdown
    # table was removed along with "What caused the inflation spike?")
    assert len(at.dataframe) == 3
    # Every chart on this page is Highcharts now (embedded via
    # st.components.v1.html -> an `iframe` element in AppTest): the main
    # Inflation Index & Change chart, plus M/M and Y/Y comparison charts.
    assert len(at.get("plotly_chart")) == 0
    assert len(at.get("iframe")) == 3


def test_spike_analysis_section_is_gone():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    page_text = " ".join(md.value for md in at.markdown)
    assert "What caused the inflation spike" not in page_text
    assert "period_picker" not in at.session_state
    assert "selected_period" not in at.session_state


def test_main_chart_full_width_with_pan_and_zoom_controls():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]

    # Regression check: the chart used to sit in st.columns([9, 3]) with an
    # empty reserved column beside it. Column count across the WHOLE page
    # should now be exactly 8 (4 KPIs + 2 band checkboxes + 2 M/M-YoY) - if
    # the 9:3 split were still there, it'd be 10.
    assert len(at.columns) == 8

    main = next(f for f in at.get("iframe") if "hc-main-chart" in f.proto.srcdoc)
    srcdoc = main.proto.srcdoc
    cfg = _chart_config(srcdoc, "hc-main-chart")

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

    # 1x/2x/5x/10x + Reset zoom-factor buttons, wired to this chart's own instance.
    for call in (
        "__zoom_hc_main_chart(1)", "__zoom_hc_main_chart(2)",
        "__zoom_hc_main_chart(5)", "__zoom_hc_main_chart(10)",
        "__reset_hc_main_chart()",
    ):
        assert call in srcdoc

    assert "Highcharts.stockChart" in srcdoc
    assert "code.highcharts.com" not in srcdoc  # bundled locally, not loaded from a CDN


def test_event_and_severity_bands_toggle_into_the_chart_config():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    main = next(f for f in at.get("iframe") if "hc-main-chart" in f.proto.srcdoc)
    cfg = _chart_config(main.proto.srcdoc, "hc-main-chart")
    assert cfg["xAxis"]["plotBands"] == []  # off by default
    assert cfg["yAxis"][1]["plotBands"] == []

    event_cb = next(c for c in at.checkbox if "major-event" in c.label.lower())
    severity_cb = next(c for c in at.checkbox if "severity" in c.label.lower())
    event_cb.set_value(True)
    severity_cb.set_value(True)
    at = at.run()
    assert not at.exception, [e.message for e in at.exception]

    main = next(f for f in at.get("iframe") if "hc-main-chart" in f.proto.srcdoc)
    cfg = _chart_config(main.proto.srcdoc, "hc-main-chart")
    event_labels = {b["label"]["text"] for b in cfg["xAxis"]["plotBands"]}
    severity_labels = {b["label"]["text"] for b in cfg["yAxis"][1]["plotBands"]}
    assert any("COVID-19" in t for t in event_labels)
    assert "Very high inflation" in severity_labels


def test_highcharts_mom_yoy_comparison_charts_still_render():
    """The M/M and Y/Y comparison charts are unchanged by this pass - still
    Highcharts, embedded via st.components.v1.html."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    iframes = [f for f in at.get("iframe") if "hc-main-chart" not in f.proto.srcdoc]
    assert len(iframes) == 2
    srcdocs = [f.proto.srcdoc for f in iframes]
    assert any("hc-mom-chart" in s and "Month-over-month" in s for s in srcdocs)
    assert any("hc-yoy-chart" in s and "Year-over-year" in s for s in srcdocs)
    assert all("Highcharts.stockChart" in s for s in srcdocs)
    assert all("code.highcharts.com" not in s for s in srcdocs)
    assert all(len(s) > 300_000 for s in srcdocs)  # the ~370KB library is actually inlined


def test_archive_tables_show_all_12_real_groups_without_a_selected_period():
    from pricelab.dashboard.theme import CPI_GROUP_ORDER

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    monthly, yearly, ge = (d.value for d in at.dataframe)
    assert set(monthly["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])
    assert set(yearly["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])
    assert len(ge) > 0
