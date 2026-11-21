import pytest

import axon_aone.execution.engine as execution_engine_module
import axon_aone.orchestration.scheduler as scheduler_module
from axon_aone.execution.engine import ExecutionEngine
from axon_aone.execution.sandbox import SandboxEngine
from axon_aone.orchestration.scheduler import TradingScheduler
from axon_aone.portfolio.correlation import compute_correlation_from_universe
from axon_aone.risk.engine import PortfolioSnapshot, RiskEngine
from axon_aone.risk.kill_switch import KillSwitch, KillSwitchConfig
from axon_aone.strategy.regime import RegimeMode, RegimeState, calculate_regime


@pytest.mark.parametrize(
    "index_ok,vol_ok,expected_mode",
    [
        (True, True, RegimeMode.BULL),
        (True, False, RegimeMode.BULL),
        (False, True, RegimeMode.BULL),
        (False, False, RegimeMode.SIDEWAYS),
    ],
)
def test_regime_mode_matrix(index_ok, vol_ok, expected_mode):
    state = calculate_regime(index_trend_ok=index_ok, volatility_ok=vol_ok)
    assert state.mode == expected_mode


def test_risk_engine_can_open_trade_boundary_and_breach():
    engine = RiskEngine(user_overrides={"PER_TRADE_RISK_PCT": 1.0})
    snapshot = PortfolioSnapshot(total_capital=100_000, tradable_capital=50_000, daily_pnl=0, weekly_pnl=0)

    # max risk = 500
    assert engine.can_open_trade(entry_price=100.0, stop_loss_price=99.0, quantity=500, snapshot=snapshot) is True
    assert engine.can_open_trade(entry_price=100.0, stop_loss_price=99.0, quantity=501, snapshot=snapshot) is False


def test_risk_engine_loss_breaches_do_not_trigger_with_zero_capital():
    engine = RiskEngine()
    snapshot = PortfolioSnapshot(total_capital=0, tradable_capital=0, daily_pnl=-999, weekly_pnl=-999)
    assert engine.daily_loss_breached(snapshot) is False
    assert engine.weekly_drawdown_breached(snapshot) is False


@pytest.mark.parametrize(
    "side,price,expected",
    [
        ("BUY", 100.0, 100.1),
        ("SELL", 100.0, 99.9),
    ],
)
def test_sandbox_slippage_direction(side, price, expected):
    result = SandboxEngine().simulate({"symbol": "ABC", "quantity": 2, "side": side, "price": price})
    assert result.payload["fill_price"] == pytest.approx(expected)


def test_sandbox_preserves_preexisting_enriched_fields():
    result = SandboxEngine().simulate(
        {
            "id": "ORD_1",
            "symbol": "ABC",
            "quantity": 2,
            "side": "BUY",
            "price": 100.0,
            "fill_price": 777.0,
            "notional": 1554.0,
        }
    )
    assert result.order_id == "ORD_1"
    assert result.payload["fill_price"] == 777.0
    assert result.payload["notional"] == 1554.0


def test_execution_engine_explicit_mock_path(monkeypatch):
    engine = ExecutionEngine()

    called = {"live": False}

    def fake_execute_trade(**kwargs):
        called["live"] = True
        return {"status": True}

    monkeypatch.setattr(execution_engine_module, "execute_trade", fake_execute_trade)

    result = engine.execute(symbol="ABC", quantity=1, trade_mode="mock")
    assert result.status == "PAPER"
    assert "sandbox" in result.raw
    assert called["live"] is False


def test_execution_engine_explicit_live_path(monkeypatch):
    engine = ExecutionEngine()

    def fake_execute_trade(**kwargs):
        return {"status": True, "order_id": "L1", "kwargs": kwargs}

    monkeypatch.setattr(execution_engine_module, "execute_trade", fake_execute_trade)

    result = engine.execute(symbol="ABC", quantity=3, side="SELL", trade_mode="live")
    assert result.status is True
    assert result.raw["order_id"] == "L1"
    assert result.raw["kwargs"]["use_mock"] is False


def test_execution_engine_uses_db_trade_mode_when_not_provided(monkeypatch):
    engine = ExecutionEngine()

    monkeypatch.setattr(execution_engine_module, "get_global_trade_mode", lambda: "mock")
    monkeypatch.setattr(
        execution_engine_module,
        "execute_trade",
        lambda **kwargs: {"status": False, "path": "live"},
    )

    result = engine.execute(symbol="ABC", quantity=1, trade_mode=None)
    assert result.status == "PAPER"


def test_execution_engine_fallback_to_trade_mode_constant(monkeypatch):
    engine = ExecutionEngine()

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(execution_engine_module, "get_global_trade_mode", boom)
    monkeypatch.setattr(execution_engine_module, "TRADE_MODE", "LIVE")
    monkeypatch.setattr(execution_engine_module, "execute_trade", lambda **kwargs: {"status": True, "path": "live"})

    result = engine.execute(symbol="ABC", quantity=1, trade_mode=None)
    assert result.raw["path"] == "live"


def test_scheduler_prefers_db_trade_mode_over_startup_argument(monkeypatch):
    scheduler = TradingScheduler(use_mock=True)

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return type("FakeNow", (), {
                "weekday": lambda self: 4,
                "time": lambda self: scheduler_module.MARKET_OPEN_TIME,
                "strftime": lambda self, _fmt: "09:15:00",
            })()

    calls = []

    def trading_func(use_mock=False):
        calls.append(use_mock)

    monkeypatch.setattr(scheduler_module.datetime, "datetime", FakeDateTime)
    monkeypatch.setattr(scheduler_module, "get_global_trade_mode", lambda: "live")

    scheduler._run_trading_iteration(trading_func, (True,), {})

    assert calls == [False]


def test_kill_switch_manual_override(monkeypatch):
    ks = KillSwitch(config=KillSwitchConfig())
    snapshot = PortfolioSnapshot(total_capital=100_000, tradable_capital=90_000, daily_pnl=0, weekly_pnl=0)

    monkeypatch.setattr("axon_aone.db.is_manual_kill_switch_active", lambda: True)

    assert ks.check(snapshot=snapshot) is True
    assert ks.last_reason == "manual"


def test_kill_switch_no_trigger_path(monkeypatch):
    ks = KillSwitch(config=KillSwitchConfig(max_daily_loss_trigger=0.2, max_weekly_loss_trigger=0.2, max_portfolio_heat=0.5))
    snapshot = PortfolioSnapshot(total_capital=100_000, tradable_capital=90_000, daily_pnl=-100, weekly_pnl=-200)
    snapshot.portfolio_heat = 0.1

    monkeypatch.setattr("axon_aone.db.is_manual_kill_switch_active", lambda: False)

    assert ks.check(snapshot=snapshot, regime=RegimeState(score=80, mode=RegimeMode.BULL)) is False
    assert ks.active is False
    assert ks.last_reason is None


def test_kill_switch_is_sticky_after_first_trigger(monkeypatch):
    ks = KillSwitch(config=KillSwitchConfig(max_daily_loss_trigger=0.01, max_weekly_loss_trigger=0.5, max_portfolio_heat=0.9))

    monkeypatch.setattr("axon_aone.db.is_manual_kill_switch_active", lambda: False)

    bad_snapshot = PortfolioSnapshot(total_capital=100_000, tradable_capital=90_000, daily_pnl=-2_000, weekly_pnl=0)
    safe_snapshot = PortfolioSnapshot(total_capital=100_000, tradable_capital=90_000, daily_pnl=0, weekly_pnl=0)

    assert ks.check(snapshot=bad_snapshot) is True
    assert ks.check(snapshot=safe_snapshot) is True


def test_correlation_returns_none_for_empty_or_invalid_universe():
    assert compute_correlation_from_universe([]) is None
    assert compute_correlation_from_universe([{"symbol": "A", "candles": [{"close": 100.0}]}]) is None


def test_correlation_window_size_reflected_in_result():
    universe = [
        {"symbol": "AAA", "candles": [{"close": 100.0}, {"close": 101.0}, {"close": 102.0}]},
        {"symbol": "BBB", "candles": [{"close": 50.0}, {"close": 50.5}, {"close": 51.5}]},
    ]

    result = compute_correlation_from_universe(universe, window=2)
    assert result is not None
    assert result.window_size == 2
    assert set(result.symbols) == {"AAA", "BBB"}
    # With a 2-candle window there is only one return row, so correlation is NaN.
    assert "AAA" in result.matrix and "BBB" in result.matrix
    assert "AAA" in result.matrix["AAA"] and "BBB" in result.matrix["AAA"]
