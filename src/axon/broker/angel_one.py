"""Angel One SmartAPI adapter (live orders and real market data for PAPER and LIVE).

Compliance items handled here (spec: go-live checklist):
- one API key, read from ANGEL_ONE_API_KEY
- daily login (session is renewed when the date changes) and logout after close
- hard order-rate limit of at most 2 orders per second
- orders carry AXON_ALGO_ID in the order tag
- live orders are refused if this machine's public IP is not AXON_STATIC_IP
- delivery (CNC) orders for core and swing, intraday (MIS) for intraday
- no consent flag for surveillance stocks: those are excluded, not traded

Requires `smartapi-python` and `pyotp` (in requirements.txt). Nothing here runs in tests;
the payload builders are tested with a fake client.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from typing import Callable, List, Optional

from axon.broker.base import RateLimiter
from axon.clock import IST
from axon.models import Candle, Instrument, OrderIntent, OrderResult, Quote

log = logging.getLogger(__name__)


class AngelOneError(Exception):
    pass


def build_order_payload(intent: OrderIntent, algo_id: str) -> dict:
    """The exact SmartAPI placeOrder payload for an order intent."""
    is_limit = intent.order_type == "LIMIT"
    if is_limit and not intent.limit_price:
        raise AngelOneError("LIMIT order without a limit price")
    return {
        "variety": "NORMAL",
        "tradingsymbol": intent.instrument.symbol,
        "symboltoken": intent.instrument.token,
        "transactiontype": intent.side.value,
        "exchange": intent.instrument.exchange,
        "ordertype": "LIMIT" if is_limit else "MARKET",
        "producttype": intent.product.value,  # INTRADAY or DELIVERY (CNC)
        "duration": "DAY",
        "price": f"{intent.limit_price:.2f}" if is_limit else "0",
        "squareoff": "0",
        "stoploss": "0",
        "quantity": str(intent.quantity),
        "ordertag": (algo_id or "AXON")[:20],
    }


def parse_candles(rows: list) -> List[Candle]:
    out = []
    for row in rows or []:
        if len(row) < 6:
            continue
        start = datetime.fromisoformat(str(row[0]))
        if start.tzinfo is None:
            start = start.replace(tzinfo=IST)
        out.append(Candle(start.astimezone(IST), float(row[1]), float(row[2]), float(row[3]), float(row[4]),
                          float(row[5])))
    return out


class AngelOneClient:
    def __init__(self, *, api_key: str, client_id: str, pin: str, totp_secret: str, algo_id: str = "",
                 static_ip: str = "", rate_limiter: Optional[RateLimiter] = None,
                 connect_factory: Optional[Callable] = None, public_ip_lookup: Optional[Callable[[], str]] = None):
        self.api_key = api_key
        self.client_id = client_id
        self.pin = pin
        self.totp_secret = totp_secret
        self.algo_id = algo_id
        self.static_ip = static_ip
        self.rate = rate_limiter or RateLimiter()
        self._connect_factory = connect_factory
        self._public_ip_lookup = public_ip_lookup or _lookup_public_ip
        self._api = None
        self._session_day: Optional[date] = None

    @classmethod
    def from_env(cls, algo_id: str = "", static_ip: str = "") -> "AngelOneClient":
        missing = [k for k in ("ANGEL_ONE_API_KEY", "ANGEL_ONE_CLIENT_ID", "ANGEL_ONE_PIN", "ANGEL_ONE_TOTP_SECRET")
                   if not os.getenv(k)]
        if missing:
            raise AngelOneError(f"missing environment variables: {', '.join(missing)}")
        return cls(api_key=os.environ["ANGEL_ONE_API_KEY"], client_id=os.environ["ANGEL_ONE_CLIENT_ID"],
                   pin=os.environ["ANGEL_ONE_PIN"], totp_secret=os.environ["ANGEL_ONE_TOTP_SECRET"],
                   algo_id=algo_id, static_ip=static_ip)

    # ------------------------------------------------------------------ session
    def _login(self) -> None:
        if self._connect_factory is None:
            from SmartApi import SmartConnect  # type: ignore
            import pyotp  # type: ignore

            api = SmartConnect(api_key=self.api_key)
            otp = pyotp.TOTP(self.totp_secret).now()
        else:
            api = self._connect_factory()
            otp = "000000"
        resp = api.generateSession(self.client_id, self.pin, otp)
        if not (isinstance(resp, dict) and resp.get("status")):
            raise AngelOneError(f"login failed: {resp.get('message') if isinstance(resp, dict) else resp}")
        self._api = api
        self._session_day = datetime.now(IST).date()
        log.info("Angel One session started")

    def api(self):
        """A logged-in session; renewed every day (daily login authentication)."""
        if self._api is None or self._session_day != datetime.now(IST).date():
            self._login()
        return self._api

    def logout(self) -> None:
        """End the API session after market close every day."""
        if self._api is None:
            return
        try:
            self._api.terminateSession(self.client_id)
            log.info("Angel One session ended")
        finally:
            self._api = None
            self._session_day = None

    def verify_static_ip(self) -> None:
        if not self.static_ip:
            raise AngelOneError("AXON_STATIC_IP is not set; live orders need the IP registered with Angel One")
        actual = self._public_ip_lookup()
        if actual != self.static_ip:
            raise AngelOneError(f"public IP {actual} is not the registered static IP {self.static_ip}")

    # ------------------------------------------------------------------ data
    def get_quote(self, instrument: Instrument) -> Quote:
        api = self.api()
        now = datetime.now(IST)
        resp = api.getMarketData("FULL", {instrument.exchange: [instrument.token]})
        fetched = (resp or {}).get("data", {}).get("fetched", []) if isinstance(resp, dict) else []
        if fetched:
            row = fetched[0]
            ts = now
            feed = row.get("exchFeedTime")
            if feed:
                try:
                    ts = datetime.strptime(feed, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
                except ValueError:
                    pass
            return Quote(instrument.symbol, float(row.get("ltp") or 0), ts,
                         upper_circuit=_num(row.get("upperCircuit")), lower_circuit=_num(row.get("lowerCircuit")))
        resp = api.ltpData(instrument.exchange, instrument.symbol, instrument.token)
        if isinstance(resp, dict) and resp.get("status"):
            return Quote(instrument.symbol, float(resp["data"]["ltp"]), now)
        raise AngelOneError(f"no quote for {instrument.symbol}: {resp}")

    def get_candles(self, instrument: Instrument, interval: str, start: datetime, end: datetime) -> List[Candle]:
        params = {
            "exchange": instrument.exchange,
            "symboltoken": instrument.token,
            "interval": interval,
            "fromdate": start.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            "todate": end.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
        }
        resp = self.api().getCandleData(params)
        if not (isinstance(resp, dict) and resp.get("status")):
            raise AngelOneError(f"candles failed for {instrument.symbol}: {resp}")
        return parse_candles(resp.get("data") or [])

    # ------------------------------------------------------------------ orders
    def place(self, intent: OrderIntent, quote: Quote) -> OrderResult:
        try:
            self.verify_static_ip()
        except AngelOneError as exc:
            return OrderResult(False, "REJECTED", message=str(exc))
        if intent.side.value == "BUY" and quote.upper_circuit and quote.price >= quote.upper_circuit * 0.999:
            return OrderResult(False, "REJECTED", message="stock is at its upper price limit")
        if intent.side.value == "SELL" and quote.lower_circuit and quote.price <= quote.lower_circuit * 1.001:
            return OrderResult(False, "REJECTED", message="stock is at its lower price limit")
        payload = build_order_payload(intent, self.algo_id)
        self.rate.wait()
        try:
            order_id = self.api().placeOrder(payload)
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, "ERROR", message=f"placeOrder failed: {exc}")
        if not order_id:
            return OrderResult(False, "ERROR", message="placeOrder returned no order id")
        return self._await_fill(str(order_id))

    def _await_fill(self, order_id: str, timeout_s: float = 15.0) -> OrderResult:
        deadline = time.monotonic() + timeout_s
        last_status = "PENDING"
        while time.monotonic() < deadline:
            book = self.api().orderBook()
            for row in (book or {}).get("data") or []:
                if str(row.get("orderid")) != order_id:
                    continue
                status = str(row.get("orderstatus") or row.get("status") or "").lower()
                last_status = status or last_status
                if status == "complete":
                    return OrderResult(True, "FILLED", broker_order_id=order_id,
                                       fill_price=float(row.get("averageprice") or 0),
                                       filled_quantity=int(float(row.get("filledshares") or row.get("quantity") or 0)))
                if status in {"rejected", "cancelled"}:
                    return OrderResult(False, "REJECTED", broker_order_id=order_id,
                                       message=str(row.get("text") or status))
            time.sleep(1.0)
        return OrderResult(False, "PENDING", broker_order_id=order_id, message=f"not filled yet ({last_status})")


def _num(value) -> Optional[float]:
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _lookup_public_ip() -> str:
    import requests

    return requests.get("https://api.ipify.org", timeout=5).text.strip()
