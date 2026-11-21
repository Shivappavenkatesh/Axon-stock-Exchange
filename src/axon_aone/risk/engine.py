"""Aggregate risk engine for trade and portfolio checks."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

from axon_aone.config import (
    MAX_CONCURRENT_TRADES,
    MAX_DAILY_LOSS,
    MAX_RISK_PER_TRADE,
    MAX_WEEKLY_DRAWDOWN,
)


def _merge_risk_config(user_overrides: dict | None = None) -> dict:
    merged = {
        "PER_TRADE_RISK_PCT": MAX_RISK_PER_TRADE * 100.0,
        "DAILY_LOSS_LIMIT_PCT": MAX_DAILY_LOSS * 100.0,
        "WEEKLY_LOSS_LIMIT_PCT": MAX_WEEKLY_DRAWDOWN * 100.0,
        "MAX_DRAWDOWN_PCT": 20.0,
        "MAX_CONCURRENT_POSITIONS": MAX_CONCURRENT_TRADES,
    }
    merged.update(user_overrides or {})
    return merged


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
    def __init__(self, user_overrides: dict | None = None) -> None:
        merged = _merge_risk_config(user_overrides)
        self.max_risk_per_trade = float(merged.get("PER_TRADE_RISK_PCT", 1.0)) / 100.0
        self.max_daily_loss_pct = float(merged.get("DAILY_LOSS_LIMIT_PCT", 3.0)) / 100.0
        self.max_weekly_drawdown_pct = float(merged.get("WEEKLY_LOSS_LIMIT_PCT", 6.0)) / 100.0
        self.global_max_drawdown_pct = float(merged.get("MAX_DRAWDOWN_PCT", 20.0)) / 100.0
        self.max_concurrent_positions = int(merged.get("MAX_CONCURRENT_POSITIONS", 25))
        self.var_daily_95_limit = float(merged.get("VAR_DAILY_95_PCT", 3.0)) / 100.0
        self.stress_scenario_loss_limit = float(merged.get("STRESS_SCENARIO_LOSS_PCT", 5.0)) / 100.0
        self.config = merged

    def get_config(self) -> dict:
        return self.config

    def can_open_trade(
        self,
        entry_price: float,
        stop_loss_price: float,
        quantity: int,
        snapshot: PortfolioSnapshot,
    ) -> bool:
        trade_risk = abs(entry_price - stop_loss_price) * quantity
        max_risk = snapshot.tradable_capital * self.max_risk_per_trade
        return trade_risk <= max_risk

    def daily_loss_breached(self, snapshot: PortfolioSnapshot) -> bool:
        if snapshot.total_capital <= 0:
            return False
        max_daily_loss = self.max_daily_loss_pct * snapshot.total_capital
        return snapshot.daily_pnl <= -max_daily_loss

    def weekly_drawdown_breached(self, snapshot: PortfolioSnapshot) -> bool:
        if snapshot.total_capital <= 0:
            return False
        max_weekly_drawdown = self.max_weekly_drawdown_pct * snapshot.total_capital
        return snapshot.weekly_pnl <= -max_weekly_drawdown

    def compute_portfolio_heat(self, open_risk: float, snapshot: PortfolioSnapshot) -> float:
        if snapshot.total_capital <= 0:
            return 0.0
        return max(0.0, open_risk) / snapshot.total_capital

    @staticmethod
    def compute_var_95(returns: list[float], exposure_notional: float, capital: float) -> float:
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
        return max(0.0, (exposure_notional * loss_fraction) / capital)

    @staticmethod
    def compute_stress_loss_pct(open_positions: list[dict], stress_drop_pct: float, capital: float) -> float:
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
