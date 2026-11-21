import pytest

from axon_aone.core.allocation import AllocationEngine
from axon_aone.core.kill_switch import KillSwitch, KillSwitchConfig
from axon_aone.core.risk_engine import PortfolioSnapshot, RiskEngine


def test_risk_engine_computes_var_and_stress_loss_pct():
    engine = RiskEngine()

    returns = [0.01, -0.02, 0.015, -0.01, 0.005, -0.03]
    var_95 = engine.compute_var_95(returns=returns, exposure_notional=50_000.0, capital=100_000.0)
    stress = engine.compute_stress_loss_pct(
        open_positions=[{"quantity": 100, "entry_price": 100.0}],
        stress_drop_pct=0.10,
        capital=100_000.0,
    )

    assert var_95 > 0.0
    assert stress == pytest.approx(0.01)


def test_kill_switch_triggers_on_var_and_stress_limits():
    ks = KillSwitch(
        config=KillSwitchConfig(
            max_daily_loss_trigger=0.5,
            max_weekly_loss_trigger=0.5,
            max_drawdown_trigger=0.5,
            max_portfolio_heat=0.9,
            max_var_95_trigger=0.02,
            max_stress_loss_trigger=0.05,
        )
    )

    snapshot = PortfolioSnapshot(
        total_capital=100_000.0,
        tradable_capital=80_000.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        var_95=0.03,
        stress_loss_pct=0.08,
    )

    assert ks.check(snapshot=snapshot) is True
    assert "var_95_limit" in (ks.last_reason or "")
    assert "stress_scenario_limit" in (ks.last_reason or "")


def test_allocation_engine_builds_constraint_aware_plan():
    engine = AllocationEngine()
    candidates = [
        {"symbol": "AAA", "sector": "TECH", "opportunity_score": 10.0},
        {"symbol": "BBB", "sector": "TECH", "opportunity_score": 8.0},
        {"symbol": "CCC", "sector": "BANK", "opportunity_score": 7.0},
    ]

    plan = engine.build_allocation_plan(
        candidates=candidates,
        total_capital=100_000.0,
        current_sector_exposure={"TECH": 18_000.0},
    )

    # With default 20% sector cap, TECH has ~2k left; first symbol gets partial room,
    # second TECH symbol should usually be filtered by remaining sector budget.
    assert "AAA" in plan
    assert plan["AAA"].max_notional <= 2_000.0
    assert "BBB" not in plan
    assert "CCC" in plan
