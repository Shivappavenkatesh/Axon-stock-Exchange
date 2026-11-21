"""OMS wrapper with lifecycle tracking and idempotent submissions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional


ExecutorFunc = Callable[..., Dict[str, Any]]


@dataclass
class OmsResult:
    order_id: str
    lifecycle_state: str
    status: Any
    response: Dict[str, Any]
    duplicate: bool = False


class OmsService:
    """A minimal institutional OMS abstraction around broker execution."""

    def __init__(self) -> None:
        self._events: Dict[str, list[Dict[str, Any]]] = {}
        self._results: Dict[str, OmsResult] = {}

    @staticmethod
    def _ts() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_event(self, order_id: str, state: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._events.setdefault(order_id, []).append(
            {
                "timestamp": self._ts(),
                "state": state,
                "payload": payload or {},
            }
        )

    @staticmethod
    def _normalize_lifecycle_state(status: Any) -> str:
        if status is True or status in {"PAPER", "SUCCESS", "FILLED"}:
            return "FILLED"
        if status is False or status in {"ERROR", "REJECTED", "CANCELLED"}:
            return "REJECTED"
        return "PENDING"

    def submit_order(
        self,
        order_id: str,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str,
        price: Optional[float],
        use_mock: bool,
        executor: ExecutorFunc,
    ) -> OmsResult:
        if order_id in self._results:
            existing = self._results[order_id]
            self._append_event(order_id, "DUPLICATE_REQUEST", {"status": existing.status})
            return OmsResult(
                order_id=existing.order_id,
                lifecycle_state=existing.lifecycle_state,
                status=existing.status,
                response=existing.response,
                duplicate=True,
            )

        self._append_event(order_id, "NEW", {"symbol": symbol, "side": side, "quantity": quantity})
        self._append_event(order_id, "SENT")

        response = executor(
            symbol=symbol,
            quantity=quantity,
            side=side,
            order_type=order_type,
            price=price,
            use_mock=use_mock,
        )
        status = response.get("status") if isinstance(response, dict) else None
        lifecycle_state = self._normalize_lifecycle_state(status)
        self._append_event(order_id, lifecycle_state, {"status": status})

        result = OmsResult(
            order_id=order_id,
            lifecycle_state=lifecycle_state,
            status=status,
            response=response if isinstance(response, dict) else {"raw": response},
            duplicate=False,
        )
        self._results[order_id] = result
        return result

    def get_events(self, order_id: str) -> list[Dict[str, Any]]:
        return list(self._events.get(order_id, []))


_oms_service: OmsService | None = None


def get_oms_service() -> OmsService:
    global _oms_service
    if _oms_service is None:
        _oms_service = OmsService()
    return _oms_service


__all__ = ["OmsResult", "OmsService", "get_oms_service"]
