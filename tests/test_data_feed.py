from axon_aone.data.feed import (
    _get_symbols_to_fetch,
    build_symbol_ranking_features,
    compute_opportunity_score,
    score_symbol_ranking_model,
    select_trade_candidates,
)


def _stock(symbol: str, price: float, vwap: float, closes: list[float], volumes: list[int]) -> dict:
    candles = []
    for close, volume in zip(closes, volumes):
        candles.append(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": volume,
                "vwap": vwap if close == closes[-1] else close - 0.3,
            }
        )
    return {
        "symbol": symbol,
        "price": price,
        "vwap": vwap,
        "candles": candles,
    }


def test_compute_opportunity_score_prefers_positive_momentum_and_vwap_edge():
    strong = _stock("STRONG", 104.0, 101.0, [100.0, 101.0, 103.0, 104.0], [1000, 1100, 1400, 1800])
    weak = _stock("WEAK", 99.0, 100.5, [101.0, 100.5, 99.5, 99.0], [1000, 950, 900, 850])

    assert compute_opportunity_score(strong) > compute_opportunity_score(weak)


def test_select_trade_candidates_returns_top_ranked_symbols():
    universe = [
        _stock("AAA", 104.0, 101.0, [100.0, 101.0, 103.0, 104.0], [1000, 1100, 1400, 1800]),
        _stock("BBB", 103.0, 101.5, [100.0, 101.0, 102.0, 103.0], [1000, 1050, 1100, 1200]),
        _stock("CCC", 99.0, 100.5, [101.0, 100.5, 99.5, 99.0], [1000, 950, 900, 850]),
    ]

    selected = select_trade_candidates(universe, top_n=2, min_score=0.0)

    assert [stock["symbol"] for stock in selected] == ["AAA", "BBB"]
    assert all("opportunity_score" in stock for stock in selected)


def test_select_trade_candidates_filters_below_threshold():
    strong = _stock("AAA", 104.0, 101.0, [100.0, 101.0, 103.0, 104.0], [1000, 1100, 1400, 1800])
    weak = _stock("CCC", 99.0, 100.5, [101.0, 100.5, 99.5, 99.0], [1000, 950, 900, 850])
    threshold = (compute_opportunity_score(strong) + compute_opportunity_score(weak)) / 2.0

    selected = select_trade_candidates([strong, weak], top_n=3, min_score=threshold)

    assert [stock["symbol"] for stock in selected] == ["AAA"]


def test_explicit_ranking_model_rewards_better_feedback():
    stock = _stock("AAA", 104.0, 101.0, [100.0, 101.0, 103.0, 104.0], [1000, 1100, 1400, 1800])

    weak_features = build_symbol_ranking_features(
        stock,
        feedback={"AAA": {"closed_trades": 8.0, "wins": 3.0, "avg_pnl_pct": -0.01, "total_pnl": -500.0}},
    )
    strong_features = build_symbol_ranking_features(
        stock,
        feedback={"AAA": {"closed_trades": 8.0, "wins": 6.0, "avg_pnl_pct": 0.02, "total_pnl": 2500.0}},
    )

    assert score_symbol_ranking_model(strong_features) > score_symbol_ranking_model(weak_features)
def test_ranking_model_dampens_feedback_when_learning_sample_is_small():
    stock = _stock("AAA", 104.0, 101.0, [100.0, 101.0, 103.0, 104.0], [1000, 1100, 1400, 1800])

    low_confidence = build_symbol_ranking_features(
        stock,
        feedback={"AAA": {"closed_trades": 1.0, "wins": 1.0, "avg_pnl_pct": 0.20, "total_pnl": 10_000.0}},
    )
    high_confidence = build_symbol_ranking_features(
        stock,
        feedback={"AAA": {"closed_trades": 20.0, "wins": 20.0, "avg_pnl_pct": 0.20, "total_pnl": 10_000.0}},
    )

    assert low_confidence["learning_confidence"] < high_confidence["learning_confidence"]
    assert score_symbol_ranking_model(high_confidence) > score_symbol_ranking_model(low_confidence)


def test_get_symbols_to_fetch_keeps_open_positions_outside_scan_batch():
    symbols = ["AAA", "BBB", "CCC", "DDD"]

    selected = _get_symbols_to_fetch(symbols, use_auto_selection=True, open_symbols={"DDD"})

    assert "DDD" in selected
    assert len(selected) >= 1
