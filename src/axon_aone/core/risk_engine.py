"""Global risk engine wrapper.

Provides a thin object-oriented layer over the existing risk utilities
so that other components (scheduler, web API, strategies) can make
consistent risk/kill decisions via a single interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist
from typing import Optional

from axon_aone.config import RISK_CONFIG


@dataclass
class PortfolioSnapshot:
    total_capital: float
    tradable_capital: float
    daily_pnl: float
    weekly_pnl: float
    max_drawdown: float = 0.0
    portfolio_heat: float = 0.0
    var_95: float = 0.0
    stress_loss_pct: float = 0.0


class RiskEngine:
    """Aggregate risk checks for trades and portfolio.

    This currently delegates to the existing functions in axon_aone.risk
    but centralises the interface so future enhancements (portfolio heat,
    dynamic throttles, etc.) can live here.
    """

    def __init__(self, risk_config: Optional[dict] = None) -> None:
        cfg = risk_config or RISK_CONFIG
        # Percent-based config is converted into fractions of capital.
        self.max_risk_per_trade = float(cfg.get("PER_TRADE_RISK_PCT", 1.0)) / 100.0
        self.max_daily_loss = float(cfg.get("DAILY_LOSS_LIMIT_PCT", 3.0)) / 100.0
        self.max_weekly_drawdown = float(cfg.get("WEEKLY_LOSS_LIMIT_PCT", 6.0)) / 100.0
        self.var_daily_95_limit = float(cfg.get("VAR_DAILY_95_PCT", 3.0)) / 100.0
        self.stress_scenario_loss_limit = float(cfg.get("STRESS_SCENARIO_LOSS_PCT", 5.0)) / 100.0

    def can_open_trade(
        self,
        entry_price: float,
        stop_loss_price: float,
        quantity: int,
        snapshot: PortfolioSnapshot,
    ) -> bool:
        """Return True if a new trade is allowed under risk rules.

        This replicates the logic from ``axon_aone.risk.can_open_new_trade``
        so that the engine does not depend on that module at import time.
        """
        trade_risk = abs(entry_price - stop_loss_price) * quantity
        max_risk = snapshot.tradable_capital * self.max_risk_per_trade
        return trade_risk <= max_risk

    def daily_loss_breached(self, snapshot: PortfolioSnapshot) -> bool:
        if snapshot.total_capital <= 0:
            return False
        max_daily_loss = self.max_daily_loss * snapshot.total_capital
        return snapshot.daily_pnl <= -max_daily_loss

    def weekly_drawdown_breached(self, snapshot: PortfolioSnapshot) -> bool:
        if snapshot.total_capital <= 0:
            return False
        max_weekly_drawdown = self.max_weekly_drawdown * snapshot.total_capital
        return snapshot.weekly_pnl <= -max_weekly_drawdown

    def compute_portfolio_heat(self, open_risk: float, snapshot: PortfolioSnapshot) -> float:
        """Compute simple portfolio heat as open risk divided by capital.

        This is a placeholder for a richer implementation that would
        aggregate risk across all open positions.
        """
        if snapshot.total_capital <= 0:
            return 0.0
        return max(0.0, open_risk) / snapshot.total_capital

    @staticmethod
    def compute_var_95(returns: list[float], exposure_notional: float, capital: float) -> float:
        """Compute 1-day historical-normal VaR95 as fraction of capital."""
        if not returns or exposure_notional <= 0 or capital <= 0:
            return 0.0

        mu = sum(returns) / len(returns)
        if len(returns) > 1:
            variance = sum((value - mu) ** 2 for value in returns) / (len(returns) - 1)
        else:
            variance = 0.0
        sigma = variance ** 0.5
        z_95 = NormalDist().inv_cdf(0.95)
        loss_fraction = max(0.0, z_95 * sigma - mu)
        var_notional = exposure_notional * loss_fraction
        return max(0.0, var_notional / capital)

    @staticmethod
    def compute_stress_loss_pct(open_positions: list[dict], stress_drop_pct: float, capital: float) -> float:
        """Compute stressed one-day loss as fraction of capital."""
        if not open_positions or capital <= 0:
            return 0.0

        drop = max(0.0, float(stress_drop_pct))
        stress_loss = 0.0
        for position in open_positions:
            qty = max(0, int(position.get("quantity", 0)))
            entry = float(position.get("entry_price", 0.0) or 0.0)
            if qty <= 0 or entry <= 0:
                continue
            stress_loss += qty * entry * drop
        return max(0.0, stress_loss / capital)
