"""
Broker integration for Angel One Smart API.
"""

from .base_broker import BaseBroker
from .angel_one_broker import AngelOneBroker

__all__ = ["BaseBroker", "AngelOneBroker"]


def get_broker(broker_name: str, api_key: str = "", client_id: str = "", pin: str = "", totp_secret: str = "") -> BaseBroker:
    """
    Factory function to get broker instance.
    
    Args:
        broker_name: Broker name ("angel_one")
        api_key: Angel One API Key
        client_id: Angel One User ID (e.g., D12345)
        pin: Trading PIN
        totp_secret: TOTP secret for 2FA
    
    Returns:
        Broker instance (AngelOneBroker)
    
    Raises:
        ValueError: If broker_name is not "angel_one"
    """
    brokers = {
        "angel_one": AngelOneBroker,
    }
    
    broker_class = brokers.get(broker_name.lower())
    if not broker_class:
        raise ValueError(f"Unknown broker: {broker_name}. Supported: {list(brokers.keys())}")
    
    return broker_class(api_key=api_key, client_id=client_id, pin=pin, totp_secret=totp_secret)
