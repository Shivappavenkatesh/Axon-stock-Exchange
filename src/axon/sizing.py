"""Position sizing (finding 8): the smallest of the risk rule, the liquidity cap and the
capital cap, then the brake multiplier."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SizeResult:
    quantity: int
    by_risk: int
    by_liquidity: Optional[int]
    by_capital: int
    planned_risk: float
    limited_by: str


def size_position(*, capital: float, price: float, stop: float, risk_pct: float,
                  capital_cap_pct: float, adtv: Optional[float], adtv_cap_pct: float,
                  risk_multiplier: float = 1.0) -> SizeResult:
    """Return whole shares. Quantity 0 means the trade cannot be sized safely.

    capital          total portfolio value (risk and caps are % of total capital)
    risk_pct         % of capital to lose if the stop is hit (e.g. 0.25)
    capital_cap_pct  largest position as % of capital (e.g. 5)
    adtv             20-day median daily traded value in rupees (None = unknown -> no trade)
    adtv_cap_pct     largest position as % of ADTV (e.g. 0.25)
    risk_multiplier  0.5 when the -8% brake is on
    """
    stop_distance = price - stop
    if capital <= 0 or price <= 0 or stop_distance <= 0:
        return SizeResult(0, 0, None, 0, 0.0, "invalid inputs")
    risk_budget = capital * risk_pct / 100.0 * risk_multiplier
    by_risk = math.floor(risk_budget / stop_distance)
    by_capital = math.floor(capital * capital_cap_pct / 100.0 / price)
    if adtv is None or adtv <= 0:
        return SizeResult(0, by_risk, None, by_capital, 0.0, "liquidity unknown")
    by_liquidity = math.floor(adtv * adtv_cap_pct / 100.0 / price)
    options = {"risk": by_risk, "liquidity": by_liquidity, "capital": by_capital}
    limited_by = min(options, key=options.get)
    qty = max(0, options[limited_by])
    return SizeResult(qty, by_risk, by_liquidity, by_capital, qty * stop_distance, limited_by)
