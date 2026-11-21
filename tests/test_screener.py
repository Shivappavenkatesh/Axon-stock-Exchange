"""Fundamentals screener (research tool, not part of the trading path)."""

from research.screener.screener import score_universe, top_n

FUNDAMENTALS = {
    "QUALITY": {"revenue_growth": 0.20, "roe": 25, "debt_to_equity": 0.1, "market_cap": 5e11},
    "LEVERED": {"revenue_growth": 0.20, "roe": 25, "debt_to_equity": 8.0, "market_cap": 5e11},
    "SHRINKING": {"revenue_growth": -0.30, "roe": 2, "debt_to_equity": 1.0, "market_cap": 1e9},
    "BROKEN": {"revenue_growth": "n/a"},
}


def test_score_universe_ranks_quality_above_leverage():
    scores = score_universe(FUNDAMENTALS)
    assert scores["QUALITY"] > scores["LEVERED"] > scores["SHRINKING"]
    assert scores["BROKEN"] == 0.0


def test_top_n_returns_sorted_pairs():
    assert [s for s, _ in top_n(FUNDAMENTALS, n=2)] == ["QUALITY", "LEVERED"]
