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
    assert len(at.dataframe) == 2  # month-by-month + year-by-year tables


def test_selecting_a_period_updates_metrics_and_tables():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.selectbox(key="period_picker").select("May 2023")
    at = at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert any("Selected period: May 2023" in md.value for md in at.markdown)
    assert all(len(d.value) > 0 for d in at.dataframe)
