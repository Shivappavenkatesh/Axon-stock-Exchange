"""
Angel One Smart API broker implementation.
Provides integration with Angel One's SmartConnect API for automated trading.
"""

import collections
import logging
import json
import random
import threading
import time
from typing import Dict, List, Any, Optional, Callable, Union
from datetime import datetime, timedelta

from .base_broker import BaseBroker
from axon_aone.config import (
    get_exchange_token as config_get_exchange_token,
    ANGEL_ONE_LTP_MIN_INTERVAL_SEC,
    ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC,
    ANGEL_ONE_ORDER_MIN_INTERVAL_SEC,
    ANGEL_ONE_ORDER_MAX_REQUESTS_PER_MIN,
    ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES,
    ANGEL_ONE_ORDER_TOO_MANY_REQUESTS_MAX_RETRIES,
    ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES,
    ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC,
    ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC,
    ANGEL_ONE_CANDLE_CACHE_TTL_SEC,
    ANGEL_ONE_INTRADAY_LOOKBACK_DAYS,
)

# Global sliding-window rate limiter.
# Angel One allows ~180 candle requests/minute; we enforce a slightly lower
# ceiling across ALL broker instances in this process.
_GLOBAL_RATE_WINDOW_SEC = 60
_GLOBAL_RATE_MAX_REQUESTS: Dict[str, int] = {
    "getCandleData": 170,   # stay under 180/min hard limit
    "ltpData": 170,
    "placeOrder": max(1, int(ANGEL_ONE_ORDER_MAX_REQUESTS_PER_MIN)),
}
_global_request_timestamps: Dict[str, collections.deque] = {}
_global_rate_lock = threading.Lock()

logger = logging.getLogger(__name__)

# Module-level candle cache shared across all AngelOneBroker instances.
# This survives broker re-instantiation (e.g. when fetch_market_data()
# creates a fresh MarketDataFeed each scheduler cycle).
_candle_cache: Dict[str, tuple] = {}          # {cache_key: (mono_ts, candles_list)}
_candle_cache_lock = threading.Lock()


class AngelOneBroker(BaseBroker):
    """Angel One Smart API broker implementation."""

    def __init__(self, api_key: str = "", client_id: str = "", pin: str = "", totp_secret: str = ""):
        """
        Initialize Angel One broker.
        
        Args:
            api_key: Angel One API Key from SmartAPI developer portal
            client_id: Angel One User ID (e.g., D12345)
            pin: Trading PIN (4-digit MPIN)
            totp_secret: TOTP secret key for 2FA OTP generation
        """
        super().__init__(client_id, "")  # Pass client_id to base
        self.api_key = api_key
        self.client_id = client_id
        self.pin = pin
        self.totp_secret = totp_secret
        self.angel_client = None
        self.jwt_token = None
        self.refresh_token = None
        self.feed_token = None
        self.api_base_url = "https://apiconnect.angelbroking.com"
        self._market_feed = None  # SmartAPI WebSocket client (if started)

        # Simple, process-local throttling to reduce SmartAPI rate limit errors.
        self._rate_limit_lock = threading.Lock()
        self._last_request_at: Dict[str, float] = {}
        # Cooldown: after a 429 response, pause ALL requests for this endpoint.
        self._cooldown_until: Dict[str, float] = {}

    def _throttle(self, key: str, min_interval_sec: float) -> None:
        # 1. Honour any active cooldown (set after a 429 response).
        with self._rate_limit_lock:
            cooldown = self._cooldown_until.get(key, 0.0)
        cooldown_wait = cooldown - time.monotonic()
        if cooldown_wait > 0:
            logger.info(f"Rate-limit cooldown active for {key}; waiting {cooldown_wait:.1f}s")
            time.sleep(cooldown_wait)

        # 2. Per-request minimum interval.
        if min_interval_sec > 0:
            now = time.monotonic()
            with self._rate_limit_lock:
                last_at = self._last_request_at.get(key, 0.0)
                wait_for = (last_at + float(min_interval_sec)) - now
                if wait_for > 0:
                    self._last_request_at[key] = last_at + float(min_interval_sec)
                else:
                    self._last_request_at[key] = now

            if wait_for > 0:
                time.sleep(wait_for)

        # 3. Global sliding-window rate limiter (e.g. 170 req / 60s).
        max_requests = _GLOBAL_RATE_MAX_REQUESTS.get(key)
        if max_requests:
            self._enforce_global_rate_limit(key, max_requests)

    def _enforce_global_rate_limit(self, key: str, max_requests: int) -> None:
        """Block until the sliding window has room for another request."""
        with _global_rate_lock:
            if key not in _global_request_timestamps:
                _global_request_timestamps[key] = collections.deque()
            dq = _global_request_timestamps[key]

            now = time.monotonic()
            # Evict timestamps older than the window.
            while dq and (now - dq[0]) >= _GLOBAL_RATE_WINDOW_SEC:
                dq.popleft()

            if len(dq) >= max_requests:
                # Must wait until the oldest request exits the window.
                sleep_for = _GLOBAL_RATE_WINDOW_SEC - (now - dq[0]) + 0.1
                logger.warning(
                    f"Global rate limit reached for {key} ({len(dq)}/{max_requests} in last {_GLOBAL_RATE_WINDOW_SEC}s). "
                    f"Sleeping {sleep_for:.1f}s."
                )
                # Release lock while sleeping.
                _global_rate_lock_copy = _global_rate_lock  # keep reference
                # We need to release and re-acquire; use a flag instead.
            else:
                sleep_for = 0

        if sleep_for > 0:
            time.sleep(sleep_for)
            # After waking, re-check (another thread may have queued).
            return self._enforce_global_rate_limit(key, max_requests)

        # Record this request.
        with _global_rate_lock:
            _global_request_timestamps.setdefault(key, collections.deque()).append(time.monotonic())

    def _set_cooldown(self, key: str, seconds: float) -> None:
        """Activate a cooldown for *key*; all future _throttle calls will wait."""
        with self._rate_limit_lock:
            self._cooldown_until[key] = time.monotonic() + seconds

    @staticmethod
    def _is_too_many_requests_response(response: Any) -> bool:
        if not isinstance(response, dict):
            return False
        message = str(response.get("message", "") or "").strip().lower()
        errorcode = str(response.get("errorcode", "") or "").strip().upper()
        status_code = response.get("status_code") or response.get("statusCode")
        if message in ("toomanyrequests", "too many requests"):
            return True
        if errorcode == "AB1004":
            return True
        if status_code == 429:
            return True
        if "limit exceeded" in message or "access denied" in message:
            return True
        return False

    @staticmethod
    def _normalize_interval(interval: Union[str, int]) -> str:
        if isinstance(interval, int):
            mapping = {
                1: "ONE_MINUTE",
                3: "THREE_MINUTE",
                5: "FIVE_MINUTE",
                10: "TEN_MINUTE",
                15: "FIFTEEN_MINUTE",
                30: "THIRTY_MINUTE",
                60: "ONE_HOUR",
                1440: "ONE_DAY",
            }
            return mapping.get(interval, str(interval))

        # Allow callers to pass numeric strings like "1".
        try:
            as_int = int(str(interval))
            return AngelOneBroker._normalize_interval(as_int)
        except Exception:
            return str(interval)

    def _generate_totp(self) -> Optional[str]:
        """
        Generate TOTP for 2FA authentication.
        
        Returns:
            6-digit TOTP string or None if generation fails
        """
        if not self.totp_secret:
            logger.warning("TOTP secret not provided. Set ANGEL_ONE_TOTP_SECRET environment variable.")
            return None
        
        try:
            import pyotp
            totp = pyotp.TOTP(self.totp_secret)
            otp = totp.now()
            logger.debug(f"Generated TOTP: {otp}")
            return otp
        except Exception as e:
            logger.error(f"Failed to generate TOTP: {e}")
            return None

    def authenticate(self) -> bool:
        """
        Authenticate with Angel One SmartConnect API using generateSession.
        
        Requires:
        - API Key (for SmartConnect initialization)
        - Client ID (Angel One User ID)
        - PIN (Trading PIN)
        - TOTP Secret (for 2FA OTP generation)
        
        Returns:
            True if authentication successful, False otherwise.
        """
        try:
            # Import SmartAPI
            try:
                from SmartApi import SmartConnect
            except ImportError:
                logger.error("smartapi-python module not installed. Run: pip install smartapi-python")
                return False
            
            # Validate required credentials
            if not self.api_key:
                logger.error("Angel One: API Key not provided. Set ANGEL_ONE_API_KEY environment variable.")
                self.authenticated = False
                return False
            
            if not self.client_id:
                logger.error("Angel One: Client ID not provided. Set ANGEL_ONE_CLIENT_ID environment variable.")
                self.authenticated = False
                return False
            
            if not self.pin:
                logger.error("Angel One: PIN not provided. Set ANGEL_ONE_PIN environment variable.")
                self.authenticated = False
                return False
            
            # Initialize SmartConnect with API key
            try:
                self.angel_client = SmartConnect(api_key=self.api_key)
                logger.info("SmartConnect initialized with API key.")
            except Exception as init_err:
                logger.error(f"Failed to initialize SmartConnect: {init_err}")
                self.authenticated = False
                return False
            
            # Generate TOTP for 2FA
            totp = self._generate_totp()
            if not totp:
                logger.error("Angel One: TOTP generation failed. Set ANGEL_ONE_TOTP_SECRET environment variable.")
                self.authenticated = False
                return False
            
            # Authenticate using generateSession
            try:
                logger.info(f"Attempting login for client: {self.client_id}")
                data = self.angel_client.generateSession(
                    clientCode=self.client_id,
                    password=self.pin,
                    totp=totp
                )
                
                # Check response
                if data and data.get('status'):
                    session_data = data.get('data', {})
                    self.jwt_token = session_data.get('jwtToken')
                    self.refresh_token = session_data.get('refreshToken')
                    
                    # Get feed token for market data
                    try:
                        self.feed_token = self.angel_client.getfeedToken()
                    except Exception:
                        logger.warning("Could not get feed token")
                    
                    self.authenticated = True
                    logger.info(f"Angel One authentication successful for {self.client_id}")
                    return True
                else:
                    error_msg = data.get('message', 'Unknown error') if data else 'No response'
                    logger.error(f"Angel One login failed: {error_msg}")
                    self.authenticated = False
                    return False
                    
            except Exception as login_err:
                logger.error(f"Login failed: {login_err}")
                self.authenticated = False
                return False
                
        except Exception as e:
            logger.error(f"Failed to authenticate with Angel One: {e}")
            self.authenticated = False
            return False

    def get_quote(self, symbol: str, exchange_token: str, exchange: str = "NSE") -> Dict[str, Any]:
        """
        Fetch quote from Angel One SmartAPI.
        
        Args:
            symbol: Symbol name (e.g., "RELIANCE")
            exchange_token: Angel One symbol token
            exchange: Exchange name (default: "NSE")
        
        Returns:
            Quote dict with LTP, high, low, volume, etc.
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Please check credentials.")
                return {}

            def _to_float(value: Any) -> Optional[float]:
                try:
                    if value is None or value == "":
                        return None
                    return float(value)
                except Exception:
                    return None

            def _to_int(value: Any) -> Optional[int]:
                try:
                    if value is None or value == "":
                        return None
                    return int(float(value))
                except Exception:
                    return None

            def _normalize_ltp_response(resp: Dict[str, Any]) -> Dict[str, Any]:
                data = resp.get("data") if isinstance(resp, dict) else None
                if not isinstance(data, dict):
                    return resp if isinstance(resp, dict) else {}

                ltp = _to_float(data.get("ltp"))
                open_px = _to_float(data.get("open"))
                high_px = _to_float(data.get("high"))
                low_px = _to_float(data.get("low"))
                close_px = _to_float(data.get("close"))
                volume = _to_int(data.get("volume"))
                vwap = _to_float(data.get("vwap"))

                # Provide both `ltp` and `price` for downstream compatibility.
                # Keep `status/message/errorcode` from the original response.
                return {
                    "status": bool(resp.get("status")),
                    "message": resp.get("message"),
                    "errorcode": resp.get("errorcode") or resp.get("errorCode"),
                    "symbol": symbol,
                    "exchange": exchange,
                    "symboltoken": exchange_token,
                    "ltp": ltp,
                    "price": ltp,
                    "open": open_px,
                    "high": high_px,
                    "low": low_px,
                    "close": close_px,
                    "volume": volume,
                    "vwap": vwap,
                    "raw": resp,
                }

            try:
                max_retries = max(0, int(ANGEL_ONE_TOO_MANY_REQUESTS_MAX_RETRIES))
                for attempt in range(max_retries + 1):
                    self._throttle("ltpData", float(ANGEL_ONE_LTP_MIN_INTERVAL_SEC))

                    # ltpData signature: (exchange, tradingsymbol, symboltoken)
                    response = self.angel_client.ltpData(
                        exchange=exchange,
                        tradingsymbol=symbol,
                        symboltoken=exchange_token,
                    )

                    if isinstance(response, dict) and response.get("status"):
                        logger.debug(f"Quote fetched for {symbol}: {response}")
                        return _normalize_ltp_response(response)

                    if self._is_too_many_requests_response(response) and attempt < max_retries:
                        backoff = min(
                            float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC),
                            float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) * (2 ** attempt),
                        )
                        backoff += random.uniform(0.0, 0.25)
                        self._set_cooldown("ltpData", backoff)
                        logger.warning(
                            f"Rate-limited fetching quote for {symbol} (TooManyRequests). "
                            f"Retrying in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})."
                        )
                        time.sleep(backoff)
                        continue

                    error_msg = response.get("message", "Unknown error") if isinstance(response, dict) else "No response"
                    logger.warning(f"No quote data received for {symbol}: {error_msg}")
                    return {}
                
            except AttributeError as attr_err:
                logger.error(f"SmartAPI method not available: {attr_err}")
                return {}
            except Exception as quote_err:
                # SmartAPI may raise instead of returning a dict. Retry on rate-limit errors.
                msg = str(quote_err)
                if "TooManyRequests" in msg or "AB1004" in msg or "429" in msg:
                    backoff = min(
                        float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC),
                        float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) * 2,
                    )
                    backoff += random.uniform(0.0, 0.25)
                    self._set_cooldown("ltpData", backoff)
                    logger.warning(
                        f"Rate-limited fetching quote for {symbol} (exception). Sleeping {backoff:.2f}s then returning empty."
                    )
                    time.sleep(backoff)
                    return {}

                logger.error(f"Error fetching quote for {symbol}: {quote_err}")
                return {}
        except Exception as e:
            logger.error(f"Unexpected error in get_quote for {symbol}: {e}")
            return {}

    def get_intraday_minute_data(self, symbol: str, exchange_token: str, interval: Union[int, str] = 1, exchange: str = "NSE") -> List[Dict]:
        """
        Fetch intraday minute candlestick data from Angel One.
        
        Args:
            symbol: Symbol name
            exchange_token: Angel One symbol token
            interval: Candle interval (ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY)
            exchange: Exchange name (default: "NSE")
        
        Returns:
            List of candlestick dicts with OHLCV data
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Please check credentials.")
                return []

            today = datetime.now()
            # Keep intraday window small to reduce SmartAPI load/rate limiting.
            lookback_days = max(1, int(ANGEL_ONE_INTRADAY_LOOKBACK_DAYS))
            from_dt = today - timedelta(days=lookback_days)
            return self.get_historical_data(
                symbol=symbol,
                exchange_token=exchange_token,
                interval=interval,
                from_date=from_dt,
                to_date=today,
                exchange=exchange,
            )
        except Exception as e:
            logger.error(f"Unexpected error in get_intraday_minute_data for {symbol}: {e}")
            return []

    def _candle_cache_key(self, symbol: str, exchange_token: str, interval: str, exchange: str) -> str:
        """Build a deterministic cache key for candle data."""
        return f"{exchange}:{exchange_token}:{symbol}:{interval}"

    def _get_cached_candles(self, cache_key: str) -> Optional[List[Dict]]:
        """Return cached candles if still within TTL, else None."""
        ttl = float(ANGEL_ONE_CANDLE_CACHE_TTL_SEC)
        if ttl <= 0:
            return None
        with _candle_cache_lock:
            entry = _candle_cache.get(cache_key)
            if entry is not None:
                cached_at, candles = entry
                if (time.monotonic() - cached_at) < ttl:
                    return candles
                # Expired — remove stale entry
                del _candle_cache[cache_key]
        return None

    def _put_cached_candles(self, cache_key: str, candles: List[Dict]) -> None:
        """Store candle data in the cache."""
        ttl = float(ANGEL_ONE_CANDLE_CACHE_TTL_SEC)
        if ttl <= 0:
            return
        with _candle_cache_lock:
            _candle_cache[cache_key] = (time.monotonic(), candles)

    def get_historical_data(
        self,
        symbol: str,
        exchange_token: str,
        interval: Union[int, str] = "ONE_MINUTE",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        exchange: str = "NSE",
    ) -> List[Dict]:
        """Fetch historical OHLCV candlestick data from Angel One.

        Args:
            symbol: Symbol name
            exchange_token: Angel One symbol token
            interval: Candle interval (ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY)
            from_date: Start datetime (defaults to now-5 days if None)
            to_date: End datetime (defaults to now if None)
            exchange: Exchange name (default: "NSE")

        Returns:
            List of candlestick dicts with OHLCV data.
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Please check credentials.")
                return []

            now = datetime.now()
            if to_date is None:
                to_date = now
            if from_date is None:
                from_date = to_date - timedelta(days=5)

            interval_norm = self._normalize_interval(interval)

            # --- Check cache first ---
            cache_key = self._candle_cache_key(symbol, exchange_token, interval_norm, exchange)
            cached = self._get_cached_candles(cache_key)
            if cached is not None:
                logger.debug(f"Candle cache HIT for {symbol} ({interval_norm}) — {len(cached)} candles")
                return cached

            # Angel expects formatted strings
            if isinstance(from_date, datetime):
                from_str = from_date.strftime("%Y-%m-%d %H:%M")
            else:
                from_str = str(from_date)

            if isinstance(to_date, datetime):
                to_str = to_date.strftime("%Y-%m-%d %H:%M")
            else:
                to_str = str(to_date)

            try:
                historic_params = {
                    "exchange": exchange,
                    "symboltoken": exchange_token,
                    "interval": interval_norm,
                    "fromdate": from_str,
                    "todate": to_str,
                }

                candle_retries = int(ANGEL_ONE_CANDLE_TOO_MANY_REQUESTS_MAX_RETRIES)
                max_retries = max(0, candle_retries)
                for attempt in range(max_retries + 1):
                    self._throttle("getCandleData", float(ANGEL_ONE_CANDLE_MIN_INTERVAL_SEC))
                    response = self.angel_client.getCandleData(historic_params)

                    # Extract candle data from response
                    if isinstance(response, dict) and response.get("status"):
                        candles_raw = response.get("data", [])
                        if isinstance(candles_raw, list):
                            candles = []
                            for candle in candles_raw:
                                if len(candle) >= 6:
                                    candles.append(
                                        {
                                            "timestamp": candle[0],
                                            "open": candle[1],
                                            "high": candle[2],
                                            "low": candle[3],
                                            "close": candle[4],
                                            "volume": candle[5],
                                        }
                                    )
                            logger.debug(f"Historical data fetched for {symbol}: {len(candles)} candles")
                            self._put_cached_candles(cache_key, candles)
                            return candles

                    if self._is_too_many_requests_response(response) and attempt < max_retries:
                        backoff = min(
                            float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC),
                            float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) * (2 ** attempt),
                        )
                        backoff += random.uniform(0.0, 0.25)
                        self._set_cooldown("getCandleData", backoff)
                        logger.warning(
                            f"Rate-limited fetching historical data for {symbol} (TooManyRequests). "
                            f"Retrying in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})."
                        )
                        time.sleep(backoff)
                        continue

                    if isinstance(response, dict):
                        error_msg = response.get("message", "Unknown error")
                        logger.warning(f"Failed to fetch historical data for {symbol}: {error_msg}")
                        return []

                    logger.warning(f"Unexpected response type for historical data of {symbol}")
                    return []

            except Exception as data_err:
                msg = str(data_err)
                if "TooManyRequests" in msg or "AB1004" in msg or "429" in msg:
                    backoff = min(
                        float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC),
                        float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) * 2,
                    )
                    backoff += random.uniform(0.0, 0.25)
                    self._set_cooldown("getCandleData", backoff)
                    logger.warning(
                        f"Rate-limited calling getCandleData for {symbol} (exception). Sleeping {backoff:.2f}s then returning empty."
                    )
                    time.sleep(backoff)
                    return []

                logger.error(f"Error calling getCandleData for {symbol}: {data_err}")
                return []

        except Exception as e:
            logger.error(f"Unexpected error in get_historical_data for {symbol}: {e}")
            return []

    def place_order(self, symbol: str, quantity: int, order_type: str, side: str = "BUY", price: float = None) -> Dict[str, Any]:
        """
        Place order via Angel One SmartAPI.
        
        Args:
            symbol: Trading symbol
            quantity: Order quantity
            order_type: "MARKET" or "LIMIT"
            side: "BUY" or "SELL"
            price: Price for LIMIT orders
        
        Returns:
            Order confirmation dict
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Set ANGEL_ONE_API_KEY environment variable.")
                return {"status": "ERROR", "message": "Not authenticated"}

            try:
                # Resolve Angel One symbol token via config mapping.
                exchange_token = config_get_exchange_token(symbol)

                order_data = {
                    # For regular orders SmartAPI expects variety "NORMAL"
                    "variety": "NORMAL",
                    "tradingsymbol": symbol,
                    "symboltoken": exchange_token,
                    "transactiontype": side,
                    "exchange": "NSE",
                    "ordertype": order_type,
                    "producttype": "INTRADAY",
                    # Common/required order fields per SmartAPI docs
                    "duration": "DAY",
                    "price": price or 0,
                    "squareoff": 0,
                    "stoploss": 0,
                    "trailingStopLoss": 0,
                    "disclosedquantity": 0,
                    "triggerprice": 0,
                    "quantity": quantity,
                    # To execute cash orders for scrips under surveillance/cautionary listings
                    "scripconsent": "yes",
                }

                max_retries = max(0, int(ANGEL_ONE_ORDER_TOO_MANY_REQUESTS_MAX_RETRIES))
                for attempt in range(max_retries + 1):
                    self._throttle("placeOrder", float(ANGEL_ONE_ORDER_MIN_INTERVAL_SEC))
                    response = self.angel_client.placeOrder(order_data)

                    if isinstance(response, str):
                        logger.info(f"Order placed: {side} {quantity} {symbol} - order_id: {response}")
                        return response

                    if isinstance(response, dict) and response.get("status"):
                        logger.info(f"Order placed: {side} {quantity} {symbol} - response: {response}")
                        return response

                    if self._is_too_many_requests_response(response) and attempt < max_retries:
                        backoff = min(
                            float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC),
                            float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) * (2 ** attempt),
                        )
                        backoff += random.uniform(0.0, 0.25)
                        self._set_cooldown("placeOrder", backoff)
                        logger.warning(
                            f"Rate-limited placing order for {symbol} (TooManyRequests). "
                            f"Retrying in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})."
                        )
                        time.sleep(backoff)
                        continue

                    logger.info(f"Order placed: {side} {quantity} {symbol} - response: {response}")
                    return response or {"status": "ERROR", "message": "Empty response from placeOrder"}

                return {"status": "ERROR", "message": "Rate limit retries exhausted for placeOrder"}
            except Exception as order_err:
                msg = str(order_err)
                if "TooManyRequests" in msg or "AB1004" in msg or "429" in msg:
                    backoff = min(
                        float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_MAX_SEC),
                        float(ANGEL_ONE_TOO_MANY_REQUESTS_BACKOFF_BASE_SEC) * 2,
                    )
                    backoff += random.uniform(0.0, 0.25)
                    self._set_cooldown("placeOrder", backoff)
                    logger.warning(
                        f"Rate-limited placing order for {symbol} (exception). Sleeping {backoff:.2f}s before returning error."
                    )
                    time.sleep(backoff)
                logger.error(f"Error calling placeOrder for {symbol}: {order_err}")
                return {"status": "ERROR", "message": str(order_err)}
        except Exception as e:
            logger.error(f"Unexpected error in place_order for {symbol}: {e}")
            return {}

    @staticmethod
    def _extract_available_funds(payload: Any) -> Optional[float]:
        """Best-effort extraction of usable cash from SmartAPI RMS payloads."""
        preferred_keys = (
            "availablecash",
            "availableCash",
            "available_balance",
            "availableBalance",
            "net",
            "netbalance",
            "cash",
            "balance",
        )

        def _to_float(value: Any) -> Optional[float]:
            try:
                if value in (None, ""):
                    return None
                return float(value)
            except Exception:
                return None

        def _walk(node: Any) -> Optional[float]:
            if isinstance(node, dict):
                for key in preferred_keys:
                    value = _to_float(node.get(key))
                    if value is not None:
                        return max(0.0, value)

                data = node.get("data")
                if data is not None:
                    nested = _walk(data)
                    if nested is not None:
                        return nested

                for value in node.values():
                    nested = _walk(value)
                    if nested is not None:
                        return nested

            if isinstance(node, list):
                for value in node:
                    nested = _walk(value)
                    if nested is not None:
                        return nested

            return None

        return _walk(payload)

    def get_available_funds(self) -> Optional[float]:
        """Return broker-reported funds available for new entries."""
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Set ANGEL_ONE_API_KEY environment variable.")
                return None

            method_names = ("rmsLimit", "rmslimit", "getRMS")
            for method_name in method_names:
                method = getattr(self.angel_client, method_name, None)
                if not callable(method):
                    continue

                try:
                    response = method()
                except Exception as funds_err:
                    logger.warning(f"Error calling {method_name} for funds: {funds_err}")
                    continue

                available_funds = self._extract_available_funds(response)
                if available_funds is not None:
                    return available_funds

            logger.warning("Unable to determine available funds from Angel One RMS endpoints")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_available_funds: {e}")
            return None

    def get_positions(self) -> List[Dict]:
        """
        Get open positions from Angel One.
        
        Returns:
            List of open position dicts
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Set ANGEL_ONE_API_KEY environment variable.")
                return []

            try:
                response = self.angel_client.getPosition()
                
                # Extract positions from response
                if isinstance(response, dict):
                    positions = response.get("data", [])
                    if not isinstance(positions, list):
                        positions = []
                else:
                    positions = []
                
                logger.debug(f"Positions fetched: {len(positions)} open positions")
                return positions
            except Exception as pos_err:
                logger.error(f"Error calling getPosition: {pos_err}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error in get_positions: {e}")
            return []

    def close_position(self, symbol: str) -> bool:
        """
        Close a position in Angel One.
        
        Args:
            symbol: Symbol to close
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated")
                return False

            positions = self.get_positions()
            for pos in positions:
                if pos.get('tradingsymbol') == symbol:
                    qty = pos.get('quantity', 0)
                    side = "SELL" if qty > 0 else "BUY"
                    self.place_order(symbol, abs(qty), "MARKET", side=side)
                    logger.info(f"Position closed for {symbol}")
                    return True
            logger.warning(f"No position found for {symbol}")
            return False
        except Exception as e:
            logger.error(f"Error closing position for {symbol}: {e}")
            return False

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order in Angel One.
        
        Args:
            order_id: Angel One order ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.authenticated or not self.angel_client:
                logger.error("Angel One not authenticated. Set ANGEL_ONE_API_KEY environment variable.")
                return False

            try:
                params = {"orderid": order_id}
                response = self.angel_client.cancelOrder(params)
                logger.info(f"Order cancelled: {order_id}")
                return True
            except Exception as cancel_err:
                logger.error(f"Error calling cancelOrder for {order_id}: {cancel_err}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error in cancel_order for {order_id}: {e}")
            return False

    def get_exchange_token(self, symbol: str) -> str:
        """
        Get exchange token for Angel One.
        
        Args:
            symbol: Symbol name
        
        Returns:
            Exchange token
        """
        # Angel One uses token format from NSE master data
        # This would typically come from a symbol master file
        return symbol

    # ------------------------------------------------------------------
    # MarketFeed WebSocket (SmartAPI streaming)
    # ------------------------------------------------------------------

    def start_market_feed(
        self,
        channels: List[str],
        on_tick: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        """Start Angel One MarketFeed WebSocket stream.

        This uses SmartAPI's WebSocket client (SmartWebSocketV2) when available.

        Args:
            channels: List of channel strings, e.g. ["nse_cm|2885", ...]
            on_tick: Optional callback invoked with decoded tick dicts.
            on_error: Optional callback invoked with an Exception instance.
            on_close: Optional callback invoked when the feed closes.
        """
        if self._market_feed is not None:
            logger.warning("MarketFeed already running; ignoring start request.")
            return

        if not self.authenticated or not self.feed_token or not self.jwt_token:
            logger.error("Cannot start MarketFeed: broker not fully authenticated (missing jwt or feed token).")
            return

        try:
            try:
                # Newer SmartAPI client exposes SmartWebSocketV2
                from SmartApi.smartWebSocketV2 import SmartWebSocketV2
            except ImportError:
                logger.error("SmartWebSocketV2 not available from smartapi-python. Install/upgrade smartapi-python.")
                return

            sws = SmartWebSocketV2(self.api_key, self.jwt_token, self.client_id, self.feed_token)

            def _on_open(wsapp):  # type: ignore[unused-argument]
                try:
                    # Subscribe to provided channels when socket opens
                    if isinstance(channels, list) and channels:
                        try:
                            sws.subscribe(channels)  # Method name per SmartWebSocketV2 docs
                            logger.info(f"Subscribed to Angel One MarketFeed channels: {channels}")
                        except Exception as sub_err:  # pragma: no cover - depends on external lib
                            logger.error(f"Failed to subscribe to MarketFeed channels: {sub_err}")
                except Exception as e:  # pragma: no cover
                    logger.error(f"Error in MarketFeed on_open: {e}")

            def _on_data(wsapp, message: str):  # type: ignore[unused-argument]
                try:
                    payload: Any
                    try:
                        payload = json.loads(message)
                    except Exception:
                        payload = message

                    if on_tick is not None and isinstance(payload, (dict, list)):
                        try:
                            on_tick(payload)  # type: ignore[arg-type]
                        except Exception as cb_err:  # pragma: no cover
                            logger.error(f"Error in on_tick callback: {cb_err}")
                except Exception as e:  # pragma: no cover
                    logger.error(f"Error in MarketFeed on_data: {e}")

            def _on_error(wsapp, error):  # type: ignore[unused-argument]
                logger.error(f"Angel One MarketFeed error: {error}")
                if on_error is not None:
                    try:
                        # Wrap non-Exception types if needed
                        err = error if isinstance(error, Exception) else Exception(str(error))
                        on_error(err)
                    except Exception as cb_err:  # pragma: no cover
                        logger.error(f"Error in on_error callback: {cb_err}")

            def _on_close(wsapp):  # type: ignore[unused-argument]
                logger.info("Angel One MarketFeed connection closed.")
                self._market_feed = None
                if on_close is not None:
                    try:
                        on_close()
                    except Exception as cb_err:  # pragma: no cover
                        logger.error(f"Error in on_close callback: {cb_err}")

            # Assign callbacks & connect (runs internal loop in background thread)
            try:
                sws.assign_callbacks(on_open=_on_open, on_data=_on_data, on_error=_on_error, on_close=_on_close)
            except TypeError:
                # Fallback signature if assign_callbacks does not support keywords
                try:
                    sws.assign_callbacks(_on_open, _on_data, _on_error, _on_close)
                except Exception as cb_err:
                    logger.error(f"Failed to assign MarketFeed callbacks: {cb_err}")
                    return

            self._market_feed = sws
            try:
                sws.connect()
                logger.info("Angel One MarketFeed WebSocket started.")
            except Exception as conn_err:
                logger.error(f"Failed to connect Angel One MarketFeed: {conn_err}")
                self._market_feed = None

        except Exception as e:
            logger.error(f"Unexpected error starting Angel One MarketFeed: {e}")

    def stop_market_feed(self) -> None:
        """Stop the MarketFeed WebSocket stream if it is running."""
        if self._market_feed is None:
            return
        try:
            try:
                self._market_feed.close()
            except AttributeError:
                # Some SmartAPI versions expose a different close API
                try:
                    self._market_feed.disconnect()
                except Exception as e:  # pragma: no cover
                    logger.error(f"Error disconnecting MarketFeed: {e}")
            logger.info("Angel One MarketFeed WebSocket stopped.")
        except Exception as e:  # pragma: no cover
            logger.error(f"Unexpected error stopping MarketFeed: {e}")
        finally:
            self._market_feed = None
