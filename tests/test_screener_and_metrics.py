"""Tests for modules ported from Axon Aone: fundamentals screener and execution metrics."""

from axon_aone.features.screener import score_universe, top_n


FUNDAMENTALS = {
    "QUALITY": {"revenue_growth": 0.20, "roe": 25, "debt_to_equity": 0.1, "market_cap": 5e11},
    "LEVERED": {"revenue_growth": 0.20, "roe": 25, "debt_to_equity": 8.0, "market_cap": 5e11},
    "SHRINKING": {"revenue_growth": -0.30, "roe": 2, "debt_to_equity": 1.0, "market_cap": 1e9},
    "BROKEN": {"revenue_growth": "n/a"},
}


def test_score_universe_ranks_quality_above_leverage():
    scores = score_universe(FUNDAMENTALS)
    assert scores["QUALITY"] > scores["LEVERED"] > scores["SHRINKING"]


def test_score_universe_tolerates_bad_rows():
    assert score_universe(FUNDAMENTALS)["BROKEN"] == 0.0


def test_top_n_returns_sorted_symbol_score_pairs():
    top = top_n(FUNDAMENTALS, n=2)
    assert [sym for sym, _ in top] == ["QUALITY", "LEVERED"]
    assert top[0][1] >= top[1][1]


def test_metrics_helpers_never_raise():
    from axon_aone.services import metrics

    with metrics.timed_execution():
        metrics.record_execution("BUY", "paper")
    metrics.record_positions("mock")
    rendered = metrics.render_latest()
    if metrics.PROMETHEUS_AVAILABLE:
        payload, content_type = rendered
        assert b"axon_execute_total" in payload
        assert content_type.startswith("text/plain")
    else:
        assert rendered is None
