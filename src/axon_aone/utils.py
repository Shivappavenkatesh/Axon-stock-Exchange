"""
Utility functions for Axon Aone trading system.
"""

import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def format_date(date):
    """Format date to ISO format string."""
    return date.strftime("%Y-%m-%d")


def log_trade_action(action, symbol, qty, price):
    """Log trade action."""
    logging.info(f"{action} {qty} shares of {symbol} at {price}")


def validate_stock_data(stock):
    """Validate required fields in stock data."""
    required_keys = ["symbol", "price", "high", "low", "vwap", "volume", "avg_volume", "daily_trend_ok"]
    for key in required_keys:
        if key not in stock:
            raise ValueError(f"Missing required stock data: {key}")
    return True
