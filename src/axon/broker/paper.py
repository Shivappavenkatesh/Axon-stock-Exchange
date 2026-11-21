"""Simulated broker for TEST and PAPER modes: fills at the quote plus slippage, with the
full Angel One cost schedule, so paper results are honest (spec: intraday paper costs)."""

from __future__ import annotations

from axon.costs import CostModel
from axon.models import OrderIntent, OrderResult, Quote, Side


class PaperBroker:
    def __init__(self, costs: CostModel):
        self.costs = costs
        self._seq = 0

    def place(self, intent: OrderIntent, quote: Quote) -> OrderResult:
        if intent.quantity <= 0:
            return OrderResult(False, "REJECTED", message="quantity must be positive")
        if quote.price <= 0:
            return OrderResult(False, "REJECTED", message="no price")
        slip = self.costs.slippage_pct / 100.0
        price = quote.price * (1 + slip) if intent.side is Side.BUY else quote.price * (1 - slip)
        if intent.order_type == "LIMIT" and intent.limit_price is not None:
            if (intent.side is Side.BUY and price > intent.limit_price) or (
                    intent.side is Side.SELL and price < intent.limit_price):
                return OrderResult(False, "REJECTED", message="limit not reachable at current price")
        breakdown = self.costs.one_side(intent.side, intent.product, price, intent.quantity,
                                        intent.instrument.exchange)
        self._seq += 1
        return OrderResult(True, "FILLED", broker_order_id=f"PAPER-{self._seq}", fill_price=round(price, 2),
                           filled_quantity=intent.quantity, charges=breakdown.charges)

    def logout(self) -> None:
        return None
