"""Order execution engine that routes between sandbox and live broker paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from axon_aone.config import TRADE_MODE
from axon_aone.db import get_global_trade_mode
from axon_aone.execution.broker import execute_trade
from axon_aone.execution.sandbox import SandboxEngine


@dataclass
class ExecutionResult:
    status: Any
    raw: Dict[str, Any]


class ExecutionEngine:
    def __init__(self) -> None:
        self.sandbox = SandboxEngine()

    def execute(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        price: Optional[float] = None,
        trade_mode: Optional[str] = None,
    ) -> ExecutionResult:
        if trade_mode:
            effective_mode = trade_mode
        else:
            try:
                effective_mode = get_global_trade_mode()
            except Exception:
                effective_mode = "mock" if TRADE_MODE == "PAPER" else "live"

        if effective_mode == "mock":
            sandbox_result = self.sandbox.simulate(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "side": side,
                    "order_type": order_type,
                    "price": price,
                    "trade_mode": effective_mode,
                }
            )
            return ExecutionResult(status=sandbox_result.status, raw={"sandbox": sandbox_result.payload})

        raw_result = execute_trade(
            symbol=symbol,
            quantity=quantity,
            side=side,
            order_type=order_type,
            price=price,
            use_mock=False,
        )
        return ExecutionResult(status=raw_result.get("status"), raw=raw_result)
