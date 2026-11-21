"""
Abstract base class for broker implementations.
All brokers must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any


class BaseBroker(ABC):
    """
    Abstract base class defining the interface for all broker implementations.
    """

    def __init__(self, client_id: str = "", access_token: str = ""):
        """
        Initialize broker with credentials.
        
        Args:
            client_id: Broker client ID
            access_token: Broker access token
        """
        self.client_id = client_id
        self.access_token = access_token
        self.authenticated = False

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the broker.
        
        Returns:
            True if authentication successful, False otherwise.
        """
        pass

    @abstractmethod
    def get_quote(self, symbol: str, exchange_token: str) -> Dict[str, Any]:
        """
        Fetch a single quote for a symbol.
        
        Args:
            symbol: Symbol name (e.g., "RELIANCE")
            exchange_token: Broker-specific exchange token
        
        Returns:
            Quote dict with price, high, low, volume, vwap, etc.
        """
        pass

    @abstractmethod
    def get_intraday_minute_data(self, symbol: str, exchange_token: str, interval: int = 1) -> List[Dict]:
        """
        Fetch intraday minute candlestick data.
        
        Args:
            symbol: Symbol name
            exchange_token: Broker-specific exchange token
            interval: Minute interval (1, 5, 15, 30, 60)
        
        Returns:
            List of candle dicts: [{"close": float, "open": float, "high": float, "low": float, "volume": int}, ...]
        """
        pass

    @abstractmethod
    def place_order(self, symbol: str, quantity: int, order_type: str, side: str = "BUY", price: float = None) -> Dict[str, Any]:
        """
        Place a buy or sell order.
        
        Args:
            symbol: Symbol to trade
            quantity: Number of shares
            order_type: "MARKET" or "LIMIT"
            side: "BUY" or "SELL"
            price: Price for LIMIT orders
        
        Returns:
            Order dict with order_id, status, etc.
        """
        pass

    @abstractmethod
    def get_available_funds(self) -> float:
        """
        Fetch currently available cash/margin for opening new positions.

        Returns:
            Available funds as a float, or None if unavailable.
        """
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """
        Fetch all open positions.
        
        Returns:
            List of position dicts with symbol, quantity, ltp, pl, etc.
        """
        pass

    @abstractmethod
    def close_position(self, symbol: str) -> bool:
        """
        Close a position for a symbol.
        
        Args:
            symbol: Symbol to close
        
        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if successful, False otherwise.
        """
        pass
