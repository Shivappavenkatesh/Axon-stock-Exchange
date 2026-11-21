"""Central kill-switch logic for the capital engine.

The kill switch aggregates risk signals (daily loss, drawdown, regime,
correlation in future) and exposes a simple `active` flag and `check`
method used by schedulers and order entry paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from axon_aone.config import RISK_CONFIG
from axon_aone.core.regime import RegimeState, RegimeMode
from axon_aone.core.risk_engine import PortfolioSnapshot


_KS_DEFAULTS = RISK_CONFIG.get("KILL_SWITCHES", {}) if isinstance(RISK_CONFIG, dict) else {}
_DEFAULT_DAILY_LOSS_TRIGGER = float(
    _KS_DEFAULTS.get("DAILY_LOSS_PCT", RISK_CONFIG.get("DAILY_LOSS_LIMIT_PCT", 3.0))
) / 100.0
_DEFAULT_WEEKLY_LOSS_TRIGGER = float(RISK_CONFIG.get("WEEKLY_LOSS_LIMIT_PCT", 6.0)) / 100.0
_DEFAULT_DRAWDOWN_TRIGGER = float(
    _KS_DEFAULTS.get("GLOBAL_DRAWDOWN_PCT", RISK_CONFIG.get("MAX_DRAWDOWN_PCT", 20.0))
) / 100.0
_DEFAULT_VAR_95_TRIGGER = float(RISK_CONFIG.get("VAR_DAILY_95_PCT", 3.0)) / 100.0
_DEFAULT_STRESS_TRIGGER = float(RISK_CONFIG.get("STRESS_SCENARIO_LOSS_PCT", 5.0)) / 100.0


@dataclass
class KillSwitchConfig:
    max_daily_loss_trigger: float = _DEFAULT_DAILY_LOSS_TRIGGER  # fraction of capital
    max_weekly_loss_trigger: float = _DEFAULT_WEEKLY_LOSS_TRIGGER  # fraction of capital
    max_drawdown_trigger: float = _DEFAULT_DRAWDOWN_TRIGGER
    max_portfolio_heat: float = 0.10  # not yet wired to snapshot
    max_var_95_trigger: float = _DEFAULT_VAR_95_TRIGGER
    max_stress_loss_trigger: float = _DEFAULT_STRESS_TRIGGER


class KillSwitch:
    def __init__(self, config: Optional[KillSwitchConfig] = None) -> None:
        self.config = config or KillSwitchConfig()
        self.active: bool = False
        self.last_reason: Optional[str] = None

    def check(self, snapshot: PortfolioSnapshot, regime: Optional[RegimeState] = None) -> bool:
        """Evaluate kill conditions and update `active`.

        For now we only look at daily loss vs capital, mirroring existing
        behaviour. Regime and other signals can be folded in later.
        """
        # Manual override via database-backed flag
        try:
            from axon_aone.db import is_manual_kill_switch_active

            if is_manual_kill_switch_active():
                self.active = True
                if not self.last_reason:
                    self.last_reason = "manual"
                return True
        except Exception:
            # If DB is unavailable, fall back to automatic logic
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

        # Simple regime-based brake: if regime score collapses in a bear mode,
        # treat it as an additional trigger.
        if regime is not None and regime.mode == RegimeMode.BEAR and regime.score <= 30:
            reasons.append("regime_collapse")

        # Optional portfolio-heat brake: if portfolio heat is too high
        # (requires caller to populate snapshot.portfolio_heat).
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
