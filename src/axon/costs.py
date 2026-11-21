"""Full round-trip cost model and the cost test (spec: cost-aware sizing).

Every order's estimate is stored next to what actually happened (cost ledger). Once 50
orders exist in a book, the measured slippage replaces the assumed figure.
"""

from __future__ import annotations

from dataclasses import dataclass

from axon.config import CostSchedule
from axon.models import Product, Side


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    dp: float
    slippage: float

    @property
    def charges(self) -> float:
        """Statutory and broker charges (what the contract note shows)."""
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst + self.dp

    @property
    def total(self) -> float:
        return self.charges + self.slippage


class CostModel:
    def __init__(self, schedule: CostSchedule, slippage_pct: float | None = None):
        self.s = schedule
        self.slippage_pct = schedule.slippage_pct if slippage_pct is None else slippage_pct

    def one_side(self, side: Side, product: Product, price: float, quantity: int,
                 exchange: str = "NSE") -> CostBreakdown:
        s = self.s
        value = price * quantity
        brokerage = min(s.brokerage_cap, value * s.brokerage_pct / 100.0)
        brokerage = max(brokerage, min(s.brokerage_min, value)) if value > 0 else 0.0
        if product is Product.DELIVERY:
            stt = value * s.stt_delivery_pct / 100.0
            stamp = value * s.stamp_delivery_buy_pct / 100.0 if side is Side.BUY else 0.0
            dp = s.dp_charge * (1 + s.gst_pct / 100.0) if side is Side.SELL else 0.0
        else:
            stt = value * s.stt_intraday_sell_pct / 100.0 if side is Side.SELL else 0.0
            stamp = value * s.stamp_intraday_buy_pct / 100.0 if side is Side.BUY else 0.0
            dp = 0.0
        exch_pct = s.exchange_txn_pct_bse if exchange.upper() == "BSE" else s.exchange_txn_pct_nse
        exchange_fee = value * exch_pct / 100.0
        sebi = value * s.sebi_fee_pct / 100.0
        gst = (brokerage + exchange_fee + sebi) * s.gst_pct / 100.0
        slippage = value * self.slippage_pct / 100.0
        return CostBreakdown(brokerage, stt, exchange_fee, sebi, stamp, gst, dp, slippage)

    def round_trip(self, product: Product, price: float, quantity: int, exchange: str = "NSE") -> float:
        buy = self.one_side(Side.BUY, product, price, quantity, exchange)
        sell = self.one_side(Side.SELL, product, price, quantity, exchange)
        return buy.total + sell.total

    def passes_cost_test(self, product: Product, price: float, quantity: int, planned_risk: float,
                         exchange: str = "NSE") -> tuple[bool, float]:
        """Trade only if the full round-trip cost is at most 20% of the planned risk."""
        cost = self.round_trip(product, price, quantity, exchange)
        if planned_risk <= 0:
            return False, cost
        return cost <= self.s.max_cost_to_risk * planned_risk, cost
