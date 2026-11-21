"""
Execution module for trade execution via Angel One.
"""

import logging
import threading
from typing import Dict, Any
from axon_aone.brokers import get_broker
from axon_aone.config import BROKER_CREDENTIALS
from axon_aone.services import metrics

logger = logging.getLogger(__name__)

# Reuse a single authenticated broker instance across trade executions within
# the same process to avoid hammering the Angel One auth endpoint (which itself
# is rate-limited and returns "Access denied" on rapid re-logins).
_exec_broker = None
_exec_broker_lock = threading.Lock()


def _get_authenticated_broker():
    """Return a cached, authenticated broker (thread-safe)."""
    global _exec_broker
    with _exec_broker_lock:
        if _exec_broker is not None and _exec_broker.authenticated:
            return _exec_broker

        credentials = BROKER_CREDENTIALS.get("angel_one", {})
        broker = get_broker(
            "angel_one",
            api_key=credentials.get("api_key", ""),
            client_id=credentials.get("client_id", ""),
            pin=credentials.get("pin", ""),
            totp_secret=credentials.get("totp_secret", ""),
        )
        if not broker.authenticate():
            logger.error("Failed to authenticate with Angel One for order execution")
            return None
        _exec_broker = broker
        return _exec_broker


def _execution_status_label(result: Any) -> str:
    if not isinstance(result, dict):
        return "error"
    status = result.get("status")
    if status == "PAPER":
        return "paper"
    if status is True or status == "SUCCESS":
        return "success"
    if result.get("message") == "Authentication failed":
        return "auth_fail"
    return "error"


def execute_trade(symbol: str, quantity: int, side: str = "BUY", order_type: str = "MARKET",
                  price: float = None, use_mock: bool = False) -> Dict[str, Any]:
    """Execute a trade and record Prometheus metrics (see `_execute_trade`)."""
    with metrics.timed_execution():
        result = _execute_trade(symbol, quantity, side=side, order_type=order_type,
                                price=price, use_mock=use_mock)
    metrics.record_execution(side, _execution_status_label(result))
    return result


def _execute_trade(symbol: str, quantity: int, side: str = "BUY", order_type: str = "MARKET",
                   price: float = None, use_mock: bool = False) -> Dict[str, Any]:
    """
    Execute a trade via Angel One or mock execution.
    
    Args:
        symbol: Trading symbol
        quantity: Order quantity
        side: "BUY" or "SELL"
        order_type: "MARKET" or "LIMIT"
        price: Price for LIMIT orders
        use_mock: If True, simulate execution without placing real order
    
    Returns:
        Order result dict
    """
    if use_mock:
        # Paper trading simulation
        return {
            "status": "PAPER",
            "order_id": f"PAPER_{hash((symbol, quantity, side)) % 1000000}",
            "symbol": symbol,
            "qty": quantity,
            "side": side,
            "order_type": order_type,
        }
    
    try:
        broker = _get_authenticated_broker()
        if broker is None:
            return {"status": "ERROR", "message": "Authentication failed"}
        
        result = broker.place_order(symbol, quantity, order_type, side=side, price=price)
        logger.info(f"Order executed: {side} {quantity} {symbol}. Result: {result}")

        # SmartAPI placeOrder() may return a raw order-ID string instead of a
        # dict.  Normalise so callers can always do result.get("status").
        if isinstance(result, str):
            return {
                "status": True,
                "order_id": result,
                "symbol": symbol,
                "qty": quantity,
                "side": side,
                "order_type": order_type,
            }
        if not isinstance(result, dict):
            return {"status": "ERROR", "message": f"Unexpected response: {result}"}
        return result
        
    except Exception as e:
        logger.error(f"Error executing trade for {symbol}: {e}")
        return {"status": "ERROR", "message": str(e)}


def get_available_funds(use_mock: bool = False) -> float:
    """Fetch currently available broker funds for new entries."""
    if use_mock:
        return None

    try:
        broker = _get_authenticated_broker()
        if broker is None:
            return None

        return broker.get_available_funds()
    except Exception as e:
        logger.error(f"Error fetching available funds: {e}")
        return None


def get_open_positions(use_mock: bool = False) -> list:
    """
    Fetch all open positions.
    
    Args:
        use_mock: If True, return empty list (no positions in mock mode)
    
    Returns:
        List of position dicts
    """
    if use_mock:
        metrics.record_positions("mock")
        return []

    try:
        broker = _get_authenticated_broker()
        if broker is None:
            metrics.record_positions("auth_fail")
            return []

        positions = broker.get_positions()
        logger.debug(f"Positions fetched: {len(positions)} open positions")
        metrics.record_positions("success")
        return positions

    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        metrics.record_positions("error")
        return []


def close_position(symbol: str, use_mock: bool = False) -> bool:
    """
    Close a position for a symbol.
    
    Args:
        symbol: Symbol to close
        use_mock: If True, simulate close without placing real order
    
    Returns:
        True if successful, False otherwise
    """
    if use_mock:
        metrics.record_execution("CLOSE", "paper")
        return True

    try:
        with metrics.timed_execution():
            broker = _get_authenticated_broker()
            if broker is None:
                metrics.record_execution("CLOSE", "auth_fail")
                return False

            result = broker.close_position(symbol)
        logger.info(f"Position closed for {symbol}")
        metrics.record_execution("CLOSE", "success" if result else "error")
        return result

    except Exception as e:
        logger.error(f"Error closing position for {symbol}: {e}")
        metrics.record_execution("CLOSE", "error")
        return False
