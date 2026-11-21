"""Monthly income rule (replaces the profit vault).

At month end: realised net profit of swing + intraday. Pay out 50% if it is positive and
the portfolio is no more than 5% below its peak value per unit. Losing months are not
made up from the core. The payout is recorded only when you confirm it (`axon payout`).
"""

from __future__ import annotations

from dataclasses import dataclass

from axon.ledger import Ledger
from axon.models import Part

PAYOUT_SHARE = 0.5
MAX_DRAWDOWN_FOR_PAYOUT = 5.0


@dataclass(frozen=True)
class IncomeDecision:
    month: str
    book: str
    net_profit: float
    payout: float
    reinvest: float
    reason: str


def month_end_income(ledger: Ledger, book: str, month: str) -> IncomeDecision:
    """month as 'YYYY-MM'. Net profit is after costs and estimated tax."""
    net = 0.0
    for part in (Part.SWING, Part.INTRADAY):
        for p in ledger.closed_positions(book, part):
            if (p["exit_ts"] or "")[:7] == month:
                net += (p["realized_pnl"] or 0.0) - ledger.tax_for_position(p["id"])
    state = ledger.book_state(book)
    npu = ledger.nav_per_unit(book)
    peak = state["peak_nav_per_unit"] or npu
    drawdown = max(0.0, (peak - npu) / peak * 100.0) if peak else 0.0
    if net <= 0:
        return IncomeDecision(month, book, net, 0.0, 0.0, "no payout: month's net profit is zero or negative")
    if drawdown > MAX_DRAWDOWN_FOR_PAYOUT:
        return IncomeDecision(month, book, net, 0.0, net,
                              f"no payout: portfolio is {drawdown:.1f}% below its peak (limit {MAX_DRAWDOWN_FOR_PAYOUT}%)")
    payout = round(net * PAYOUT_SHARE, 2)
    return IncomeDecision(month, book, net, payout, round(net - payout, 2), "payout due")
