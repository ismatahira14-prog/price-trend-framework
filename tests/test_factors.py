import pandas as pd

from pricelab.dashboard.factors import (
    EVENTS,
    classify_relative_magnitude,
    events_covering,
    global_events,
    load_inflation_bands,
)


def test_events_are_dated_and_tagged():
    assert len(EVENTS) >= 8  # a real, thorough list - not just 2-3 examples
    for e in EVENTS:
        assert e["start"] < e["end"]
        assert e["color"]
        assert e["scope"] in {"global", "domestic"}
        assert isinstance(e["channels"], list) and e["channels"]
        assert isinstance(e.get("labeled_on_chart"), bool)


def test_events_covering_finds_known_event():
    covid = pd.Timestamp("2020-06-01")
    names = [e["name"] for e in events_covering(covid)]
    assert "COVID-19 Pandemic" in names


def test_global_events_excludes_domestic():
    names = {e["name"] for e in global_events()}
    assert "Russia-Ukraine War" in names
    assert "2022 Pakistan Floods" not in names  # domestic, not global
    assert "Currency Devaluation & Energy Price Reform" not in names


def test_ongoing_events_have_a_true_flag():
    ongoing = [e for e in EVENTS if e["is_ongoing"]]
    assert any(e["name"] == "Russia-Ukraine War" for e in ongoing)


def test_classify_relative_magnitude_tiers_by_rank_fraction():
    assert classify_relative_magnitude(1, 12) == "High"
    assert classify_relative_magnitude(4, 12) == "High"
    assert classify_relative_magnitude(5, 12) == "Medium"
    assert classify_relative_magnitude(8, 12) == "Medium"
    assert classify_relative_magnitude(9, 12) == "Low"
    assert classify_relative_magnitude(12, 12) == "Low"


def test_inflation_bands_are_config_driven_not_hardcoded():
    bands = load_inflation_bands()
    labels = [b["label"] for b in bands]
    assert "Deflation" in labels
    assert "Very high inflation" in labels
    deflation = next(b for b in bands if b["label"] == "Deflation")
    assert deflation["max"] == 0
    assert deflation["min"] is None  # unbounded on the low end
