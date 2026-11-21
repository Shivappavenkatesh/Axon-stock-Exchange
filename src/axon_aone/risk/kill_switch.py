"""Kill-switch controls for portfolio safety and emergency stops."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from axon_aone.risk.engine import PortfolioSnapshot
from axon_aone.strategy.regime import RegimeMode, RegimeState
from axon_aone.config import RISK_CONFIG


@dataclass
class KillSwitchConfig:
    max_daily_loss_trigger: float = 0.03
    max_weekly_loss_trigger: float = 0.06
    max_drawdown_trigger: float = 0.25
    max_portfolio_heat: float = 0.10
    max_var_95_trigger: float = float(RISK_CONFIG.get("VAR_DAILY_95_PCT", 3.0)) / 100.0
    max_stress_loss_trigger: float = float(RISK_CONFIG.get("STRESS_SCENARIO_LOSS_PCT", 5.0)) / 100.0


class KillSwitch:
    def __init__(self, config: Optional[KillSwitchConfig] = None) -> None:
        self.config = config or KillSwitchConfig()
        self.active: bool = False
        self.last_reason: Optional[str] = None

    def check(self, snapshot: PortfolioSnapshot, regime: Optional[RegimeState] = None) -> bool:
        try:
            from axon_aone.db import is_manual_kill_switch_active

            if is_manual_kill_switch_active():
                self.active = True
                if not self.last_reason:
                    self.last_reason = "manual"
                return True
        except Exception:
            pass

        reasons = []
        daily_loss_fraction = 0.0
        if snapshot.total_capital > 0:
            daily_loss_fraction = max(0.0, -snapshot.daily_pnl) / snapshot.total_capital
        if daily_loss_fraction >= self.config.max_daily_loss_trigger:
            reasons.append("daily_loss_limit")

        weekly_loss_fraction = 0.0
        if snapshot.total_capital > 0:
            weekly_loss_fraction = max(0.0, -snapshot.weekly_pnl) / snapshot.total_capital
        if weekly_loss_fraction >= self.config.max_weekly_loss_trigger:
            reasons.append("weekly_loss_limit")

        if regime is not None and regime.mode == RegimeMode.BEAR and regime.score <= 30:
            reasons.append("regime_collapse")

        if snapshot.portfolio_heat >= self.config.max_portfolio_heat > 0:
            reasons.append("portfolio_heat_limit")

        if snapshot.var_95 >= self.config.max_var_95_trigger > 0:
            reasons.append("var_95_limit")

        if snapshot.stress_loss_pct >= self.config.max_stress_loss_trigger > 0:
            reasons.append("stress_scenario_limit")

        if reasons:
            self.active = True
            self.last_reason = ",".join(reasons)
        return self.active
