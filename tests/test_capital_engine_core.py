import datetime
import math
from unittest.mock import patch

import pytest

from axon_aone.core.regime import RegimeState, RegimeMode, calculate_regime
from axon_aone.core.risk_engine import PortfolioSnapshot, RiskEngine
from axon_aone.core.kill_switch import KillSwitch, KillSwitchConfig
from axon_aone.core.correlation import compute_correlation_from_universe
from axon_aone.core.allocation import AllocationEngine
from axon_aone.core.sandbox import SandboxEngine
from axon_aone.features.trade import (
    calculate_atr,
    calculate_profit_target_price,
    calculate_position_size,
    calculate_stop_loss_price,
    run_day,
    should_sell,
    state,
)


def test_calculate_regime_components_and_mode():
    state = calculate_regime(index_trend_ok=True, volatility_ok=True)
    assert isinstance(state, RegimeState)
    assert 0 <= state.score <= 100
    # With both flags true, regime should be at least neutral-to-bullish
    assert state.mode in {RegimeMode.BULL, RegimeMode.SIDEWAYS}
    # Component scores should be populated
    assert state.trend_score >= 0
    assert state.vix_score >= 0


def test_risk_engine_daily_and_weekly_limits():
    engine = RiskEngine()
    snapshot = PortfolioSnapshot(
        total_capital=100_000,
        tradable_capital=80_000,
        daily_pnl=-3_000,  # -3%
        weekly_pnl=-7_000,  # -7%
    )
    assert engine.daily_loss_breached(snapshot) is True
    assert engine.weekly_drawdown_breached(snapshot) is True


def test_risk_engine_portfolio_heat():
    engine = RiskEngine()
    snapshot = PortfolioSnapshot(
        total_capital=100_000,
        tradable_capital=80_000,
        daily_pnl=0,
        weekly_pnl=0,
    )
    heat = engine.compute_portfolio_heat(open_risk=5_000, snapshot=snapshot)
    assert math.isclose(heat, 0.05, rel_tol=1e-6)


def test_kill_switch_triggers_on_daily_weekly_and_regime():
    cfg = KillSwitchConfig(
        max_daily_loss_trigger=0.02,  # 2%
        max_weekly_loss_trigger=0.03,  # 3%
        max_drawdown_trigger=0.25,
        max_portfolio_heat=0.10,
    )
    ks = KillSwitch(config=cfg)

    snapshot = PortfolioSnapshot(
        total_capital=100_000,
        tradable_capital=80_000,
        daily_pnl=-3_000,  # -3%
        weekly_pnl=-4_000,  # -4%
    )
    # Use a strongly bearish regime to also exercise regime-based path
    regime = RegimeState(score=20, mode=RegimeMode.BEAR, trend_score=0, breadth_score=0, vix_score=0, liquidity_score=0)

    snapshot.portfolio_heat = 0.15
    active = ks.check(snapshot=snapshot, regime=regime)
    assert active is True
    assert ks.last_reason is not None
    # All three reasons should be present in the reason string
    assert "daily_loss_limit" in ks.last_reason
    assert "weekly_loss_limit" in ks.last_reason
    assert "regime_collapse" in ks.last_reason
    assert "portfolio_heat_limit" in ks.last_reason


def test_correlation_from_universe_basic():
    universe = [
        {
            "symbol": "AAA",
            "candles": [
                {"close": 100.0},
                {"close": 101.0},
                {"close": 102.0},
                {"close": 103.0},
            ],
        },
        {
            "symbol": "BBB",
            "candles": [
                {"close": 50.0},
                {"close": 50.5},
                {"close": 51.0},
                {"close": 51.5},
            ],
        },
    ]

    result = compute_correlation_from_universe(universe, window=4)
    assert result is not None
    assert set(result.symbols) == {"AAA", "BBB"}
    assert "AAA" in result.matrix and "BBB" in result.matrix


def test_allocation_engine_default_engine():
    alloc_engine = AllocationEngine()
    allocs = alloc_engine.get_allocations()
    assert len(allocs) == 1
    assert allocs[0].name == "trend_engine"
    assert allocs[0].allocation == 1.0


def test_sandbox_engine_enriches_order_with_fill_and_notional():
    engine = SandboxEngine()
    order = {"symbol": "AAA", "quantity": 10, "side": "BUY", "price": 100.0}
    result = engine.simulate(order)
    assert result.status == "PAPER"
    payload = result.payload
    assert "fill_price" in payload
    assert "notional" in payload
    assert payload["notional"] == pytest.approx(payload["fill_price"] * 10)


def test_calculate_position_size_respects_risk_and_position_caps():
    qty = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=99.0,
        tradable_capital=100_000,
    )

    assert qty == 50


def test_calculate_stop_loss_price_uses_atr_multiplier():
    candles = [
        {"high": 100.0, "low": 98.0, "close": 99.0},
        {"high": 102.0, "low": 99.0, "close": 101.0},
        {"high": 103.0, "low": 100.0, "close": 102.0},
    ]

    atr = calculate_atr(candles)
    stop_price = calculate_stop_loss_price(entry_price=100.0, candles=candles)

    assert atr == pytest.approx(8.0 / 3.0)
    assert stop_price == pytest.approx(100.0 - (2.0 * atr))


def test_calculate_profit_target_price_uses_fixed_two_percent_target():
    assert calculate_profit_target_price(100.0) == pytest.approx(102.0)


def test_run_day_uses_risk_based_position_size_for_orders():
    universe = [
        {
            "symbol": "AAA",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 100_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = []

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=11, minute=0)), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            mock_execute.return_value = {"status": "PAPER"}

            run_day(universe, use_mock=True)

        assert mock_execute.called
        assert mock_execute.call_args.kwargs["quantity"] == 50
        assert state["open_trades"][0]["target"] == pytest.approx(102.0)
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_reduces_tradable_capital_after_filled_orders():
    universe = [
        {
            "symbol": "AAA",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        },
        {
            "symbol": "BBB",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        },
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 100_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = []

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=11, minute=0)), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            mock_execute.return_value = {"status": "PAPER"}

            run_day(universe, use_mock=True)

        quantities = [call.kwargs["quantity"] for call in mock_execute.call_args_list]
        assert quantities == [50, 47]
        assert state["tradable_capital"] == pytest.approx(90_300.0)
        assert len(state["open_trades"]) == 2
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_releases_reserved_capital_on_exit():
    universe = [
        {
            "symbol": "AAA",
            "price": 98.0,
            "vwap": 100.0,
            "candles": [
                {"high": 100.0, "close": 100.0, "vwap": 100.0, "low": 99.5},
                {"high": 99.5, "close": 99.0, "vwap": 99.5, "low": 98.5},
                {"high": 99.0, "close": 98.0, "vwap": 99.0, "low": 97.5},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 95_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = [
            {
                "symbol": "AAA",
                "quantity": 50,
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "allocated_capital": 5_000.0,
                "atr": 1.0,
            }
        ]

        with patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade") as mock_persist_trade, \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            mock_execute.return_value = {"status": "PAPER"}

            run_day(universe, use_mock=False)

        assert mock_execute.call_count == 1
        assert mock_execute.call_args.kwargs["side"] == "SELL"
        assert state["tradable_capital"] == pytest.approx(99_900.0)
        assert state["total_capital"] == pytest.approx(99_900.0)
        assert state["open_trades"] == []
        persisted_order = mock_persist_trade.call_args.args[0]
        assert persisted_order["reserved_capital"] == pytest.approx(-5_000.0)
        assert persisted_order["atr"] == pytest.approx(1.0)
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_vaults_portion_of_realized_profit_on_exit():
    universe = [
        {
            "symbol": "AAA",
            "price": 110.0,
            "vwap": 112.0,
            "candles": [
                {"high": 109.0, "close": 108.0, "vwap": 111.5, "low": 107.0},
                {"high": 110.0, "close": 109.0, "vwap": 111.5, "low": 108.0},
                {"high": 111.0, "close": 110.0, "vwap": 111.5, "low": 109.0},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 95_000
        state["investment_bucket"] = 0.0
        state["vault_capital"] = 0.0
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["daily_realized_pnl"] = 0.0
        state["open_trades"] = [
            {
                "symbol": "AAA",
                "quantity": 50,
                "entry_price": 100.0,
                "stop_loss": 95.0,
                "target": 105.0,
                "allocated_capital": 5_000.0,
                "atr": 5.0,
            }
        ]

        with patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            mock_execute.return_value = {"status": "PAPER"}

            run_day(universe, use_mock=False)

        assert state["open_trades"] == []
        assert state["daily_realized_pnl"] == pytest.approx(500.0)
        assert state["investment_bucket"] == pytest.approx(300.0)
        assert state["vault_capital"] == pytest.approx(300.0)
        assert state["tradable_capital"] == pytest.approx(100_200.0)
        assert state["total_capital"] == pytest.approx(100_500.0)
    finally:
        state.clear()
        state.update(original_state)


def test_should_sell_profit_protection_on_peak_drawdown_in_weak_regime():
    position = {
        "entry_price": 200.0,
        "peak_price": 220.0,
        "stop_loss": 180.0,
        "target": 260.0,
    }
    regime = RegimeState(score=35, mode=RegimeMode.SIDEWAYS, trend_score=0, breadth_score=0, vix_score=0, liquidity_score=0)

    # Price dropped more than 5% from 220 after >10% gain from entry.
    assert should_sell(position, current_price=208.0, use_mock=False, regime_state=regime) is True


def test_run_day_does_not_rebuy_existing_open_symbol_when_tracking_exit_prices():
    universe = [
        {
            "symbol": "AAA",
            "price": 101.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 102.0, "close": 101.0, "vwap": 99.5, "low": 99.0},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 95_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = [
            {
                "symbol": "AAA",
                "quantity": 50,
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "target": 102.0,
                "allocated_capital": 5_000.0,
                "atr": 1.0,
            }
        ]

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=11, minute=0)), \
             patch("axon_aone.features.trade.get_available_funds", return_value=None), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            run_day(universe, use_mock=False)

        mock_execute.assert_not_called()
        assert len(state["open_trades"]) == 1
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_closes_position_at_fixed_profit_target():
    universe = [
        {
            "symbol": "AAA",
            "price": 102.0,
            "vwap": 100.0,
            "candles": [
                {"high": 100.0, "close": 100.0, "vwap": 100.0, "low": 99.5},
                {"high": 101.0, "close": 101.0, "vwap": 100.5, "low": 100.0},
                {"high": 102.5, "close": 102.0, "vwap": 101.0, "low": 101.0},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 95_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = [
            {
                "symbol": "AAA",
                "quantity": 50,
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "target": 102.0,
                "allocated_capital": 5_000.0,
                "atr": 1.0,
            }
        ]

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=11, minute=0)), \
             patch("axon_aone.features.trade.get_available_funds", return_value=None), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            mock_execute.return_value = {"status": True}
            run_day(universe, use_mock=False)

        assert mock_execute.call_count == 1
        assert mock_execute.call_args.kwargs["side"] == "SELL"
        assert state["open_trades"] == []
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_skips_new_buys_after_entry_cutoff():
    universe = [
        {
            "symbol": "AAA",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 100_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = []

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=14, minute=31)), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            run_day(universe, use_mock=True)

        mock_execute.assert_not_called()
        assert state["open_trades"] == []
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_skips_buy_when_broker_funds_cannot_cover_one_share():
    universe = [
        {
            "symbol": "AAA",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        }
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 100_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = []

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=11, minute=0)), \
             patch("axon_aone.features.trade.get_available_funds", return_value=50.0), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            run_day(universe, use_mock=False)

        mock_execute.assert_not_called()
        assert state["open_trades"] == []
    finally:
        state.clear()
        state.update(original_state)


def test_run_day_refreshes_broker_funds_after_insufficient_funds_rejection():
    universe = [
        {
            "symbol": "AAA",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        },
        {
            "symbol": "BBB",
            "price": 100.0,
            "vwap": 99.0,
            "candles": [
                {"high": 99.0, "close": 98.0, "vwap": 97.5, "low": 97.0},
                {"high": 100.0, "close": 99.0, "vwap": 98.5, "low": 98.0},
                {"high": 101.0, "close": 100.0, "vwap": 99.5, "low": 99.0},
            ],
        },
    ]

    original_state = {
        key: list(value) if isinstance(value, list) else value
        for key, value in state.items()
    }

    try:
        state["total_capital"] = 100_000
        state["tradable_capital"] = 100_000
        state["daily_pnl"] = 0.0
        state["weekly_pnl"] = 0.0
        state["open_trades"] = []

        with patch("axon_aone.features.trade.now", return_value=datetime.time(hour=11, minute=0)), \
             patch("axon_aone.features.trade.get_available_funds", side_effect=[100_000.0, 0.0]), \
             patch("axon_aone.features.trade.execute_trade") as mock_execute, \
             patch("axon_aone.features.trade.append_scheduler_order"), \
             patch("axon_aone.features.trade.send_telegram_message"), \
             patch("axon_aone.features.trade._persist_scheduler_trade"), \
             patch("axon_aone.features.trade._persist_regime"), \
             patch("axon_aone.features.trade._persist_correlation_matrix"), \
             patch("axon_aone.features.trade.compute_correlation_from_universe", return_value=None):
            mock_execute.return_value = {"status": "ERROR", "message": "Insufficient funds"}
            run_day(universe, use_mock=False)

        assert mock_execute.call_count == 1
        assert mock_execute.call_args.kwargs["symbol"] == "AAA"
        assert state["open_trades"] == []
    finally:
        state.clear()
        state.update(original_state)


def test_angel_one_broker_retries_place_order_when_rate_limited():
    class DummyClient:
        def __init__(self):
            self.calls = 0

        def placeOrder(self, order_data):
            self.calls += 1
            if self.calls == 1:
                return {"status": False, "message": "TooManyRequests", "status_code": 429}
            return "OID123"

    from axon_aone.brokers.angel_one_broker import AngelOneBroker

    broker = AngelOneBroker(api_key="key", client_id="client", pin="1234", totp_secret="secret")
    broker.authenticated = True
    broker.angel_client = DummyClient()

    with patch("axon_aone.brokers.angel_one_broker.time.sleep") as mock_sleep:
        response = broker.place_order("TATAPOWER-EQ", 1, "MARKET", side="BUY")

    assert response == "OID123"
    assert broker.angel_client.calls == 2
    assert mock_sleep.called


def test_angel_one_broker_extracts_available_funds_from_rms_response():
    class DummyClient:
        def rmsLimit(self):
            return {"status": True, "data": {"availablecash": "12345.67"}}

    from axon_aone.brokers.angel_one_broker import AngelOneBroker

    broker = AngelOneBroker(api_key="key", client_id="client", pin="1234", totp_secret="secret")
    broker.authenticated = True
    broker.angel_client = DummyClient()

    assert broker.get_available_funds() == pytest.approx(12345.67)
