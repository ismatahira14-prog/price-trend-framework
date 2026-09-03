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


@pytest.fixture(scope="module", autouse=True)
def _require_snapshot():
    if not snapshot_path().is_file():
        pytest.skip("no duckdb snapshot yet - run `python -m pricelab.ingest --all` first")


def _chart_config(srcdoc: str, chart_id: str) -> dict:
    """Pull the JSON config back out of an embedded Highcharts <script> block.

    Neither "first ');'" nor "last ');'" is safe here: band labels embed CSS
    (e.g. "rgba(255,255,255,0.85);") containing a literal "');"-like
    substring (breaks non-greedy), and the main chart's script also defines
    zoom/reset functions *after* the stockChart(...) call (breaks greedy).
    A real brace-depth scan from the opening "{" is the only robust way to
    find the matching close, respecting quoted/escaped JSON strings.
    """
    prefix = f"Highcharts.stockChart('{chart_id}', "
    start = srcdoc.index(prefix) + len(prefix)
    assert srcdoc[start] == "{", f"expected a JSON object right after {prefix!r}"
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
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(srcdoc[start : i + 1])
    raise AssertionError(f"never found the matching close brace for {chart_id!r}")


def test_home_page_loads_without_exceptions():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    # 4 top-of-page KPIs + 4 in "What caused the inflation spike?".
    assert len(at.metric) == 8
    # Spike-section breakdown + month-by-month + year-by-year + Global Events.
    assert len(at.dataframe) == 4
    # The 12-group breakdown bar chart is the one Plotly chart left on this
    # page; the Inflation Index & Change and M/M/Y/Y comparison charts are
    # Highcharts (embedded via st.components.v1.html -> `iframe` in AppTest).
    assert len(at.get("plotly_chart")) == 1
    assert len(at.get("iframe")) == 3


def test_spike_analysis_section_present():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    page_text = " ".join(md.value for md in at.markdown) + " ".join(h.value for h in at.subheader)
    assert "What caused the inflation spike" in page_text
    assert "period_picker" in at.session_state
    assert "selected_period" in at.session_state


def test_main_chart_full_width_with_pan_and_zoom_controls():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]

    # Regression check: the chart used to sit in st.columns([9, 3]) with an
    # empty reserved column beside it. Column count across the WHOLE page
    # should now be exactly 12 (4 top KPIs + 2 band checkboxes + 4 spike-
    # section KPIs + 2 M/M-YoY) - if the 9:3 split were still there, it'd be
    # 2 higher.
    assert len(at.columns) == 12

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
    # Label text is a useHTML span (background box, for readability against
    # the chart lines behind it) - substring match, not exact equality.
    assert any("COVID-19" in t for t in event_labels)
    assert any("Very high inflation" in t for t in severity_labels)


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


def test_archive_tables_show_all_12_real_groups():
    from pricelab.dashboard.theme import CPI_GROUP_ORDER

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    spike, monthly, yearly, ge = (d.value for d in at.dataframe)
    assert set(monthly["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])
    assert set(yearly["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])
    assert set(spike["Inflation Group"]) <= set(CPI_GROUP_ORDER[1:])
    assert len(ge) > 0
