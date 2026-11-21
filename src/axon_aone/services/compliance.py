"""Pre-trade compliance gate for institutional-style hard checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from axon_aone.config import (
    COMPLIANCE_MAX_ORDER_NOTIONAL_PCT,
    COMPLIANCE_MAX_ORDER_QUANTITY,
    MAX_CONCURRENT_TRADES,
    RESTRICTED_SYMBOLS,
)
from axon_aone.db import is_manual_kill_switch_active


@dataclass
class OrderRequest:
    symbol: str
    side: str
    quantity: int
    price: float
    total_capital: float
    tradable_capital: float


@dataclass
class ComplianceDecision:
    allowed: bool
    reasons: List[str] = field(default_factory=list)


class ComplianceGate:
    """Evaluate hard pre-trade policy checks before order submission."""

    def __init__(
        self,
        max_order_notional_pct: float = COMPLIANCE_MAX_ORDER_NOTIONAL_PCT,
        max_order_quantity: int = COMPLIANCE_MAX_ORDER_QUANTITY,
        restricted_symbols: set[str] | None = None,
        max_concurrent_trades: int = MAX_CONCURRENT_TRADES,
    ) -> None:
        self.max_order_notional_pct = float(max_order_notional_pct)
        self.max_order_quantity = int(max_order_quantity)
        self.restricted_symbols = {s.upper() for s in (restricted_symbols or RESTRICTED_SYMBOLS)}
        self.max_concurrent_trades = int(max_concurrent_trades)

    def evaluate(self, request: OrderRequest, open_trade_count: int) -> ComplianceDecision:
        reasons: List[str] = []
        symbol = (request.symbol or "").upper()
        side = (request.side or "").upper()

        if is_manual_kill_switch_active():
            reasons.append("manual_kill_switch_active")

        if symbol in self.restricted_symbols:
            reasons.append("restricted_symbol")

        if side not in {"BUY", "SELL"}:
            reasons.append("invalid_side")

        qty = max(0, int(request.quantity))
        price = max(0.0, float(request.price or 0.0))
        notional = qty * price

        if qty <= 0:
            reasons.append("invalid_quantity")
        if qty > self.max_order_quantity:
            reasons.append("max_order_quantity_exceeded")

        if request.total_capital <= 0:
            reasons.append("invalid_total_capital")
        else:
            max_notional = request.total_capital * (self.max_order_notional_pct / 100.0)
            if notional > max_notional:
                reasons.append("max_order_notional_exceeded")

        if side == "BUY" and request.tradable_capital > 0 and notional > request.tradable_capital:
            reasons.append("insufficient_tradable_capital")

        if side == "BUY" and open_trade_count >= self.max_concurrent_trades:
            reasons.append("max_concurrent_trades_reached")

        return ComplianceDecision(allowed=len(reasons) == 0, reasons=reasons)


def compliance_reason_counts(decisions: List[ComplianceDecision]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for decision in decisions:
        for reason in decision.reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


__all__ = [
    "ComplianceDecision",
    "ComplianceGate",
    "OrderRequest",
    "compliance_reason_counts",
]
