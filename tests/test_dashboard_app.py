"""Headless smoke test for the Home dashboard page.

Runs the actual Streamlit script via AppTest - this is what caught the
_highlight_month() column-name bug during development, so it stays as a
permanent regression test rather than a one-off check.
"""

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


def test_home_page_loads_without_exceptions():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.metric) == 8  # 4 top-of-page KPIs + 4 selected-period KPIs
    # 12-group breakdown + month-by-month + year-by-year + Global Events
    assert len(at.dataframe) == 4
    # combined main chart (click-driven) + 12-group bars. The M/M and Y/Y
    # comparison charts are Highcharts (embedded via st.components.v1.html),
    # not st.plotly_chart, so they don't show up here - see test_html below.
    assert len(at.get("plotly_chart")) == 2


def test_highcharts_mom_yoy_comparison_charts_render():
    """The M/M and Y/Y comparison charts are Highcharts, embedded via
    st.components.v1.html (-> an `iframe` element in AppTest) since Streamlit
    has no first-party Highcharts support."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    iframes = at.get("iframe")
    assert len(iframes) == 2
    srcdocs = [f.proto.srcdoc for f in iframes]
    assert any("hc-mom-chart" in s and "Month-over-month" in s for s in srcdocs)
    assert any("hc-yoy-chart" in s and "Year-over-year" in s for s in srcdocs)
    # Highcharts is bundled locally (dashboard/assets/highstock.js), not loaded
    # from a CDN at runtime - verified live that a CDN <script src> silently
    # fails to render in some restricted network environments.
    assert all("Highcharts.stockChart" in s for s in srcdocs)
    assert all("code.highcharts.com" not in s for s in srcdocs)
    assert all(len(s) > 300_000 for s in srcdocs)  # the ~370KB library is actually inlined


def test_selecting_a_period_updates_metrics_and_tables():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.selectbox(key="period_picker").select("May 2023")
    at = at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Selected period: May 2023" in md.value for md in at.markdown)
    assert all(len(d.value) > 0 for d in at.dataframe)


def test_selected_period_breakdown_has_all_12_real_groups():
    from pricelab.dashboard.theme import CPI_GROUP_ORDER

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.selectbox(key="period_picker").select("May 2023")
    at = at.run()
    assert not at.exception, [e.message for e in at.exception]
    breakdown = at.dataframe[0].value  # first dataframe = the 12-group breakdown
    assert len(breakdown) == 12
    assert set(breakdown["Inflation Group"]) == set(CPI_GROUP_ORDER[1:])


def test_click_catchers_are_actually_selectable():
    """Regression test for a real bug found via live browser testing
    (Playwright): an invisible click-catcher trace with hoverinfo="skip"
    is silently excluded from Plotly's entire hover/click/selection system -
    so on_select's `points` was always empty, no matter where you clicked.
    A go.Bar catcher also didn't work even after fixing hoverinfo, because
    bar traces don't support single-click-to-select at all in Plotly - only
    marker-based scatter traces do. AppTest can't simulate a real browser
    click, so this checks the underlying figure spec is built correctly
    instead - the only way this repo can pin these two constraints down.
    """
    import json

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]

    for chart in at.get("plotly_chart")[:1]:  # the one click-driven chart (chart_main)
        spec = json.loads(chart.proto.spec)
        catchers = [
            t
            for t in spec["data"]
            if t.get("type") == "scatter"
            and t.get("mode") == "markers"
            and t.get("marker", {}).get("opacity") == 0
        ]
        assert catchers, "no invisible click-catcher scatter trace found"
        for t in catchers:
            assert t.get("hoverinfo") != "skip", (
                "hoverinfo='skip' excludes a trace from click/selection entirely"
            )
