"""
Configuration settings for Axon Aone - Angel One Smart API Trading System
Includes constants for risk management, trade execution, and market conditions.
"""

import datetime
import os

from axon_aone.risk_config import get_default_risk_config

# Trading configuration
TRADE_MODE = os.getenv("AXON_TRADE_MODE", os.getenv("TRADE_MODE", "PAPER")).strip().upper()  # Options: PAPER | LIVE
if TRADE_MODE not in {"PAPER", "LIVE"}:
    TRADE_MODE = "PAPER"
START_CAPITAL = 100000


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


STRATEGY_PROFILE = os.getenv("AXON_STRATEGY_PROFILE", "default").strip().lower()
_PROFILE_PRESETS = {
    "blended_titan_mode": {
        "PER_TRADE_RISK_PCT": 0.75,
        "DAILY_LOSS_LIMIT_PCT": 2.5,
        "WEEKLY_LOSS_LIMIT_PCT": 5.0,
        "MAX_POSITION_PCT": 4.0,
        "MAX_CONCURRENT_POSITIONS": 20,
        "MAX_NEW_ENTRIES_PER_CYCLE": 4,
        "MAX_CORRELATED_POSITIONS": 2,
        "CORRELATION_BLOCK_THRESHOLD": 0.88,
        "LEARNING_MIN_CLOSED_TRADES": 10,
        "EXECUTION_MAX_SLIPPAGE_PCT": 0.40,
        "FIXED_PROFIT_TARGET_PCT": 0.03,
        "AUTO_SELECT_TOP_N": 0,
        "SYMBOL_SELECTION_MIN_SCORE": 1.0,
        "SYMBOL_SELECTION_RELATIVE_TO_BEST": 0.90,
        "PROFIT_PROTECT_ACTIVATION_PCT": 0.08,
        "PROFIT_PROTECT_DROP_PCT": 0.05,
    }
}
_ACTIVE_PROFILE_DEFAULTS = _PROFILE_PRESETS.get(STRATEGY_PROFILE, {})


def _profile_default(key: str, fallback):
    return _ACTIVE_PROFILE_DEFAULTS.get(key, fallback)

# Risk management settings
#
# The canonical values live in `axon_aone.risk_config` (percent-based).
# This module exposes the commonly used limits as *fractions of capital* to
# preserve existing semantics across the codebase.
RISK_CONFIG = get_default_risk_config()

RISK_CONFIG["PER_TRADE_RISK_PCT"] = _env_float(
    "AXON_PER_TRADE_RISK_PCT",
    _profile_default("PER_TRADE_RISK_PCT", float(RISK_CONFIG.get("PER_TRADE_RISK_PCT", 1.0))),
)
RISK_CONFIG["DAILY_LOSS_LIMIT_PCT"] = _env_float(
    "AXON_DAILY_LOSS_LIMIT_PCT",
    _profile_default("DAILY_LOSS_LIMIT_PCT", float(RISK_CONFIG.get("DAILY_LOSS_LIMIT_PCT", 3.0))),
)
RISK_CONFIG["WEEKLY_LOSS_LIMIT_PCT"] = _env_float(
    "AXON_WEEKLY_LOSS_LIMIT_PCT",
    _profile_default("WEEKLY_LOSS_LIMIT_PCT", float(RISK_CONFIG.get("WEEKLY_LOSS_LIMIT_PCT", 6.0))),
)
RISK_CONFIG["MAX_POSITION_PCT"] = _env_float(
    "AXON_MAX_POSITION_PCT",
    _profile_default("MAX_POSITION_PCT", float(RISK_CONFIG.get("MAX_POSITION_PCT", 5.0))),
)
RISK_CONFIG["MAX_CONCURRENT_POSITIONS"] = max(
    1,
    _env_int(
        "AXON_MAX_CONCURRENT_POSITIONS",
        int(_profile_default("MAX_CONCURRENT_POSITIONS", int(RISK_CONFIG.get("MAX_CONCURRENT_POSITIONS", 25)))),
    ),
)

_kill_switches = dict(RISK_CONFIG.get("KILL_SWITCHES", {}))
_kill_switches["DAILY_LOSS_PCT"] = RISK_CONFIG["DAILY_LOSS_LIMIT_PCT"]
RISK_CONFIG["KILL_SWITCHES"] = _kill_switches

# Per-trade risk fraction (e.g. 1.0% -> 0.01)
MAX_RISK_PER_TRADE = float(RISK_CONFIG.get("PER_TRADE_RISK_PCT", 1.0)) / 100.0

# Loss limits as fractions of total capital
MAX_DAILY_LOSS = float(RISK_CONFIG.get("DAILY_LOSS_LIMIT_PCT", 3.0)) / 100.0
MAX_WEEKLY_DRAWDOWN = float(RISK_CONFIG.get("WEEKLY_LOSS_LIMIT_PCT", 6.0)) / 100.0

# Position / concurrency constraints
MAX_CONCURRENT_TRADES = int(RISK_CONFIG.get("MAX_CONCURRENT_POSITIONS", 25))
MAX_NEW_ENTRIES_PER_CYCLE = max(
    1,
    _env_int(
        "AXON_MAX_NEW_ENTRIES_PER_CYCLE",
        int(_profile_default("MAX_NEW_ENTRIES_PER_CYCLE", 6)),
    ),
)
MAX_CORRELATED_POSITIONS = max(
    1,
    _env_int(
        "AXON_MAX_CORRELATED_POSITIONS",
        int(_profile_default("MAX_CORRELATED_POSITIONS", 3)),
    ),
)
CORRELATION_BLOCK_THRESHOLD = min(
    0.99,
    max(
        0.50,
        _env_float(
            "AXON_CORRELATION_BLOCK_THRESHOLD",
            float(_profile_default("CORRELATION_BLOCK_THRESHOLD", 0.90)),
        ),
    ),
)
LEARNING_MIN_CLOSED_TRADES = max(
    1,
    _env_int(
        "AXON_LEARNING_MIN_CLOSED_TRADES",
        int(_profile_default("LEARNING_MIN_CLOSED_TRADES", 10)),
    ),
)
EXECUTION_MAX_SLIPPAGE_PCT = max(
    0.0,
    _env_float(
        "AXON_EXECUTION_MAX_SLIPPAGE_PCT",
        float(_profile_default("EXECUTION_MAX_SLIPPAGE_PCT", 0.50)),
    ),
)
RISK_CONFIG["VAR_DAILY_95_PCT"] = _env_float(
    "AXON_VAR_DAILY_95_PCT",
    float(RISK_CONFIG.get("VAR_DAILY_95_PCT", 3.0)),
)
RISK_CONFIG["STRESS_SCENARIO_LOSS_PCT"] = _env_float(
    "AXON_STRESS_SCENARIO_LOSS_PCT",
    float(RISK_CONFIG.get("TAIL_RISK_BUDGET_PCT", 2.0)) * 2.0,
)
RISK_CONFIG["MAX_SECTOR_PCT"] = _env_float(
    "AXON_MAX_SECTOR_PCT",
    float(RISK_CONFIG.get("MAX_SECTOR_PCT", 20.0)),
)
RISK_CONFIG["MAX_NEW_EXPOSURE_PCT"] = _env_float(
    "AXON_MAX_NEW_EXPOSURE_PCT",
    _profile_default("MAX_NEW_EXPOSURE_PCT", 25.0),
)

VAR_DAILY_95_LIMIT = max(0.0, float(RISK_CONFIG.get("VAR_DAILY_95_PCT", 3.0)) / 100.0)
STRESS_SCENARIO_LOSS_LIMIT = max(0.0, float(RISK_CONFIG.get("STRESS_SCENARIO_LOSS_PCT", 5.0)) / 100.0)
MAX_SECTOR_EXPOSURE = max(0.0, float(RISK_CONFIG.get("MAX_SECTOR_PCT", 20.0)) / 100.0)
MAX_NEW_EXPOSURE_PCT = max(0.0, float(RISK_CONFIG.get("MAX_NEW_EXPOSURE_PCT", 25.0)) / 100.0)
COMPLIANCE_MAX_ORDER_NOTIONAL_PCT = max(
    0.10,
    _env_float("AXON_COMPLIANCE_MAX_ORDER_NOTIONAL_PCT", 10.0),
)
COMPLIANCE_MAX_ORDER_QUANTITY = max(
    1,
    _env_int("AXON_COMPLIANCE_MAX_ORDER_QUANTITY", 50000),
)
RESTRICTED_SYMBOLS = {
    symbol.strip().upper()
    for symbol in os.getenv("AXON_RESTRICTED_SYMBOLS", "").split(",")
    if symbol.strip()
}

MODEL_PROMOTION_MIN_PAPER_DAYS = max(1, _env_int("AXON_MODEL_PROMOTION_MIN_PAPER_DAYS", 20))
MODEL_PROMOTION_MIN_SHARPE = _env_float("AXON_MODEL_PROMOTION_MIN_SHARPE", 1.2)
MODEL_PROMOTION_MIN_WIN_RATE = _env_float("AXON_MODEL_PROMOTION_MIN_WIN_RATE", 0.52)
MODEL_PROMOTION_MAX_DRAWDOWN_PCT = max(0.0, _env_float("AXON_MODEL_PROMOTION_MAX_DRAWDOWN_PCT", 8.0)) / 100.0
RISK_COMMITTEE_REPORT_DIR = os.getenv("AXON_RISK_COMMITTEE_REPORT_DIR", "logs/risk_committee")

# Time settings - Market hours (IST - Indian Standard Time)
MARKET_OPEN_TIME = datetime.time(hour=9, minute=15)  # 9:15 AM IST
MARKET_CLOSE_TIME = datetime.time(hour=15, minute=30)  # 3:30 PM IST

# Force exit time and promotion check time
FORCE_EXIT_TIME = datetime.time(hour=14, minute=0)
ENTRY_CUTOFF_TIME = datetime.time(hour=14, minute=30)
PROMOTION_CHECK_TIME = datetime.time(hour=13, minute=45)

# Scheduling interval (in seconds) - run algorithm every 5 minutes during market hours
ALGO_RUN_INTERVAL = 300  # 5 minutes

# Profit vaulting settings
INTRADAY_PROFIT_VAULT = 0.60
OVERNIGHT_PROFIT_VAULT = 0.70

# Fixed live profit target as a fraction of entry price.
# Example: 0.02 means exit at +2%.
FIXED_PROFIT_TARGET_PCT = _env_float(
    "AXON_FIXED_PROFIT_TARGET_PCT",
    float(_profile_default("FIXED_PROFIT_TARGET_PCT", 0.02)),
)

# Swing trading settings
MAX_SWING_POSITIONS = 3
MAX_SWING_DAYS = 3

# Broker configuration - ANGEL ONE ONLY
ACTIVE_BROKER = "angel_one"

# Angel One API configuration
# API Key: Get from SmartAPI Developer Portal (https://smartapi.angelbroking.com/)
ANGEL_ONE_API_KEY = os.getenv("ANGEL_ONE_API_KEY", "")
# Client ID: Your Angel One User ID (format: D12345 or similar)
ANGEL_ONE_CLIENT_ID = os.getenv("ANGEL_ONE_CLIENT_ID", "")
# PIN: Your 4-digit MPIN or trading PIN
ANGEL_ONE_PIN = os.getenv("ANGEL_ONE_PIN", "")
# TOTP Secret: From Angel One app's TOTP setup (scan QR or manual entry)
# To get this: Angel One App > Profile > Settings > TOTP > Enable/Reset > Copy the secret key
ANGEL_ONE_TOTP_SECRET = os.getenv("ANGEL_ONE_TOTP_SECRET", "")

# Broker credentials mapping
BROKER_CREDENTIALS = {
    "angel_one": {
        "api_key": ANGEL_ONE_API_KEY,
        "client_id": ANGEL_ONE_CLIENT_ID,
        "pin": ANGEL_ONE_PIN,
        "totp_secret": ANGEL_ONE_TOTP_SECRET,
    },
}

# Market data symbols to track (exchange_token format or symbol names)
TRACKED_SYMBOLS = [
    "TATAPOWER-EQ",
    "IDFCFIRSTB-EQ",
    "IOC-EQ",
    "WIPRO-EQ",
    "ONGC-EQ",
    "SUZLON-EQ"
]

# Exchange token mapping for Angel One
# Angel One uses token format from NSE master data
EXCHANGE_TOKEN_MAP = {
    "ABB-EQ": "13",
    "ADANIENT-EQ": "25",
    "ADANIPORTS-EQ": "15083",
    "AMBUJACEM-EQ": "1270",
    "APOLLOHOSP-EQ": "157",
    "ASIANPAINT-EQ": "236",
    "AXISBANK-EQ": "5900",
    "BAJAJ-AUTO-EQ": "16669",
    "BAJAJFINSV-EQ": "16675",
    "BAJFINANCE-EQ": "317",
    "BANKBARODA-EQ": "4668",
    "BEL-EQ": "383",
    "BHARTIARTL-EQ": "10604",
    "BPCL-EQ": "526",
    "BRITANNIA-EQ": "547",
    "CANBK-EQ": "10794",
    "CIPLA-EQ": "694",
    "TATAPOWER-EQ": "3426",
    "COALINDIA-EQ": "20374",
    "DIVISLAB-EQ": "10940",
    "DLF-EQ": "14732",
    "DMART-EQ": "19913",
    "DRREDDY-EQ": "881",
    "EICHERMOT-EQ": "910",
    "GRASIM-EQ": "1232",
    "HAL-EQ": "2303",
    "HCLTECH-EQ": "7229",
    "HDFCBANK-EQ": "1333",
    "HDFCLIFE-EQ": "467",
    "HEROMOTOCO-EQ": "1348",
    "HINDALCO-EQ": "1363",
    "HINDUNILVR-EQ": "1394",
    "IDFCFIRSTB-EQ": "11184",
    "ICICIBANK-EQ": "4963",
    "ICICIPRULI-EQ": "18652",
    "INDIGO-EQ": "11195",
    "INDUSINDBK-EQ": "5258",
    "INFY-EQ": "1594",
    "IOC-EQ": "1624",
    "IRCTC-EQ": "13611",
    "WIPRO-EQ": "3787",
    "ITC-EQ": "1660",
    "JIOFIN-EQ": "18143",
    "JSWSTEEL-EQ": "11723",
    "KOTAKBANK-EQ": "1922",
    "LICI-EQ": "9480",
    "LT-EQ": "11483",
    "M&M-EQ": "2031",
    "MARUTI-EQ": "10999",
    "NESTLEIND-EQ": "17963",
    "NTPC-EQ": "11630",
    "ONGC-EQ": "2475",
    "PFC-EQ": "14299",
    "PIDILITIND-EQ": "2664",
    "POWERGRID-EQ": "14977",
    "RECLTD-EQ": "15355",
    "RELIANCE-EQ": "2885",
    "SBILIFE-EQ": "21808",
    "SBIN-EQ": "3045",
    "SHREECEM-EQ": "3103",
    "SIEMENS-EQ": "3150",
    "SUZLON-EQ": "12018"   
    ,"SUNPHARMA-EQ": "3351"
    ,"TATASTEEL-EQ": "3499"
    ,"TATACONSUM-EQ": "3432"
    ,"TCS-EQ": "11536"
    ,"TECHM-EQ": "13538"
    ,"TITAN-EQ": "3506"
    ,"TRENT-EQ": "1964"
    ,"TVSMOTOR-EQ": "8479"
    ,"ULTRACEMCO-EQ": "11532"
    ,"ZOMATO-EQ": "5097"
}

# Universe selection controls for scheduler-driven symbol picking.
# When enabled, the data feed scans MARKET_SCAN_SYMBOLS, assigns each symbol
# an opportunity score, and only forwards the strongest names to the strategy.
AUTO_SELECT_SYMBOLS = os.getenv("AXON_AUTO_SELECT_SYMBOLS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# 0 means "no fixed cap"; the selection model then uses score thresholds only.
AUTO_SELECT_TOP_N = max(
    0,
    _env_int(
        "AXON_AUTO_SELECT_TOP_N",
        int(_profile_default("AUTO_SELECT_TOP_N", 0)),
    ),
)
SYMBOL_SELECTION_MIN_SCORE = _env_float(
    "AXON_SYMBOL_SELECTION_MIN_SCORE",
    float(_profile_default("SYMBOL_SELECTION_MIN_SCORE", 0.0)),
)
SYMBOL_SELECTION_RELATIVE_TO_BEST = _env_float(
    "AXON_SYMBOL_SELECTION_RELATIVE_TO_BEST",
    float(_profile_default("SYMBOL_SELECTION_RELATIVE_TO_BEST", 0.85)),
)
MARKET_SCAN_BATCH_SIZE = max(
    1,
    _env_int(
        "AXON_MARKET_SCAN_BATCH_SIZE",
        int(_profile_default("MARKET_SCAN_BATCH_SIZE", 18)),
    ),
)
MARKET_SCAN_SYMBOLS = [
    symbol.strip()
    for symbol in os.getenv(
        "AXON_MARKET_SCAN_SYMBOLS",
        ",".join(EXCHANGE_TOKEN_MAP.keys()),
    ).split(",")
    if symbol.strip()
]


def get_market_scan_symbols() -> list[str]:
    """Return the candidate symbol universe used for market scanning."""
    return MARKET_SCAN_SYMBOLS or TRACKED_SYMBOLS

def get_exchange_token(symbol: str, broker_name: str = None) -> str:
    """
    Get exchange token for a symbol from the mapping.
    
    Args:
        symbol: Symbol name (e.g., "RELIANCE")
        broker_name: Broker name (for future multi-broker support)
    
    Returns:
        Exchange token for the symbol
    """
    return EXCHANGE_TOKEN_MAP.get(symbol, symbol)


# -----------------------------
# Angel One API throttling
# -----------------------------
# SmartAPI endpoints are rate-limited; these settings slow requests and retry
# politely on TooManyRequests (AB1004) responses.

# Minimum spacing between LTP requests (seconds)
ANGEL_ONE_LTP_MIN_INTERVAL_SEC = float(os.getenv("ANGEL_ONE_LTP_MIN_INTERVAL_SEC", "0.25"))

# Minimum spacing between historical candle requests (seconds)
ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC = float(os.getenv("ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC", "0.90"))

# Minimum spacing between live order placement requests (seconds)
ANGEL_ONE_ORDER_MIN_INTERVAL_SEC = float(os.getenv("ANGEL_ONE_ORDER_MIN_INTERVAL_SEC", "0.75"))

# Conservative global cap for order placement across this process.
ANGEL_ONE_ORDER_MAX_REQUESTS_PER_MIN = int(os.getenv("ANGEL_ONE_ORDER_MAX_REQUESTS_PER_MIN", "40"))

# Intraday candle request shaping
# Keep the window small to reduce API load and rate-limit errors.
ANGEL_ONE_INTRADAY_LOOKBACK_DAYS = int(os.getenv("ANGEL_ONE_INTRADAY_LOOKBACK_DAYS", "1"))
# Use coarser candles by default (5-min) to reduce request frequency/volume.
ANGEL_ONE_INTRADAY_INTERVAL_MINUTES = int(os.getenv("ANGEL_ONE_INTRADAY_INTERVAL_MINUTES", "5"))

# Retry settings when API responds with TooManyRequests
ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES = int(os.getenv("ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES", "5"))
ANGEL_ONE_ORDER_TOO_MANY_REQUESTS_MAX_RETRIES = int(
    os.getenv("ANGEL_ONE_ORDER_TOO_MANY_REQUESTS_MAX_RETRIES", "3")
)

# Candle endpoints are more aggressively rate-limited; use a moderate retry count.
ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES = int(
    os.getenv("ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES", "3")
)
ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC = float(
    os.getenv("ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC", "1.0")
)
ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC = float(
    os.getenv("ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC", "30.0")
)

# Per-symbol candle response cache TTL (seconds).
# Within this window repeated getCandleData calls for the same symbol+interval
# are served from memory instead of hitting the API again.
ANGEL_ONE_CANDLE_CACHE_TTL_SEC = float(os.getenv("ANGEL_ONE_CANDLE_CACHE_TTL_SEC", "330"))

# Profit-protection exits:
# If unrealized gain reaches activation threshold and then price falls by
# drop threshold from the observed peak, exit the position.
PROFIT_PROTECT_ACTIVATION_PCT = _env_float(
    "AXON_PROFIT_PROTECT_ACTIVATION_PCT",
    float(_profile_default("PROFIT_PROTECT_ACTIVATION_PCT", 0.10)),
)
PROFIT_PROTECT_DROP_PCT = _env_float(
    "AXON_PROFIT_PROTECT_DROP_PCT",
    float(_profile_default("PROFIT_PROTECT_DROP_PCT", 0.05)),
)
