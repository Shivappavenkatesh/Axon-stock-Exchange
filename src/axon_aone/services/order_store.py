"""Shared storage utilities for scheduler-placed orders.

This module provides simple JSONL-based persistence for orders generated
by the automated trading scheduler so that they can be displayed in the
web interface regardless of which process created them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_LOG_DIR_NAME = "logs"
DEFAULT_FILE_NAME = "scheduler_orders.jsonl"


def _project_root() -> Path:
    """Return the project root directory (one level above src)."""
    # This file lives in src/axon_aone/services/order_store.py
    # Go up three levels to reach the project root.
    return Path(__file__).resolve().parents[3]


def _log_dir(for_date: Optional[date] = None) -> Path:
    """Return the directory where scheduler order logs are stored."""
    base = Path(os.getenv("AXON_LOG_DIR", _project_root() / DEFAULT_LOG_DIR_NAME))
    day = (for_date or datetime.now().date()).strftime("%Y-%m-%d")
    return base / day


def _log_path(for_date: Optional[date] = None) -> Path:
    """Return the JSONL file path for scheduler orders for a given date."""
    return _log_dir(for_date) / DEFAULT_FILE_NAME


@dataclass
class SchedulerOrder:
    """Representation of an order placed by the scheduler.

    The structure is intentionally similar to the web_server order schema
    so the UI can render both manual and scheduler orders consistently.
    """

    id: str
    symbol: str
    quantity: int
    side: str
    order_type: str = "MARKET"
    price: Optional[float] = None
    trade_mode: str = "mock"  # "mock" or "live"
    status: str = "PENDING"
    timestamp: str = ""
    filled_quantity: int = 0
    average_price: float = 0.0
    execution_time: Optional[str] = None
    broker_response: Optional[Dict[str, Any]] = None
    source: str = "scheduler"  # Distinguish from manual web orders
    atr: Optional[float] = None
    reserved_capital: Optional[float] = None
    opportunity_score: Optional[float] = None


def append_scheduler_order(order: Dict[str, Any]) -> None:
    """Append a scheduler order to the JSONL log file.

    Args:
        order: Order dict; will be JSON-serialised. The caller is
               responsible for providing a reasonably complete object.
    """
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure minimally required fields
    if "timestamp" not in order:
        order["timestamp"] = datetime.now().isoformat()
    order.setdefault("source", "scheduler")

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(order, default=str) + "\n")


def read_scheduler_orders(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read scheduler orders from today's JSONL log.

    Args:
        limit: Optional maximum number of most recent orders to return.

    Returns:
        List of order dicts sorted by timestamp descending.
    """
    path = _log_path()
    if not path.exists():
        return []

    orders: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                orders.append(obj)
            except json.JSONDecodeError:
                # Skip malformed lines instead of failing the endpoint
                continue

    # Sort by timestamp descending when available
    def _ts(o: Dict[str, Any]) -> str:
        return o.get("timestamp", "")

    orders.sort(key=_ts, reverse=True)

    if limit is not None and limit > 0:
        return orders[:limit]
    return orders


__all__ = [
    "SchedulerOrder",
    "append_scheduler_order",
    "read_scheduler_orders",
]
