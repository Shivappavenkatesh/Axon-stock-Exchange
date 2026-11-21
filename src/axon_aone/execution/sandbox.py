"""Sandbox execution engine for paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class SandboxResult:
    status: str
    order_id: str
    payload: Dict[str, Any]


class SandboxEngine:
    def simulate(self, order: Dict[str, Any]) -> SandboxResult:
        order_id = order.get("id") or f"SANDBOX_{hash(frozenset(order.items())) % 1_000_000}"
        quantity = int(order.get("quantity", 0)) or 0
        side = (order.get("side") or "BUY").upper()
        raw_price = float(order.get("price") or 0.0)

        slippage = 0.001
        if side == "BUY":
            fill_price = raw_price * (1.0 + slippage) if raw_price > 0 else 0.0
        else:
            fill_price = raw_price * (1.0 - slippage) if raw_price > 0 else 0.0

        notional = fill_price * quantity
        enriched_order = dict(order)
        enriched_order.setdefault("fill_price", fill_price)
        enriched_order.setdefault("notional", notional)
        return SandboxResult(status="PAPER", order_id=order_id, payload=enriched_order)
