"""Market data sources and the data guard (finding 5 and review fix 1).

- TEST mode uses RandomMarketData: random prices, for development only.
- PAPER and LIVE use BrokerMarketData: real prices from the broker. Paper trading on
  real prices is what makes probation results meaningful.
- There is no fallback from real to random data. If real data fails, the cycle is skipped.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Protocol, Sequence

from axon.clock import IST, MARKET_OPEN
from axon.models import Candle, Instrument, Quote


class DataUnavailable(Exception):
    """Raised when real prices cannot be fetched. Never answered with made-up prices."""


class MarketData(Protocol):
    def quote(self, instrument: Instrument, now: datetime) -> Quote: ...

    def intraday_candles(self, instrument: Instrument, now: datetime) -> List[Candle]: ...

    def daily_candles(self, instrument: Instrument, now: datetime, days: int) -> List[Candle]: ...


def closed_candles(candles: Sequence[Candle], now: datetime, minutes: int = 5) -> List[Candle]:
    """Drop the candle that is still forming."""
    return [c for c in candles if c.start + timedelta(minutes=minutes) <= now]


class RandomMarketData:
    """Deterministic random walk per symbol and day. TEST mode only."""

    is_real = False

    def __init__(self, seed: int = 7, drift: float = 0.0):
        self.seed = seed
        self.drift = drift

    def _rng(self, key: str) -> random.Random:
        digest = hashlib.sha256(f"{self.seed}:{key}".encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    def _day_path(self, instrument: Instrument, day: date) -> List[Candle]:
        rng = self._rng(f"{instrument.symbol}:{day.isoformat()}")
        price = 200 + rng.random() * 2800
        start = datetime.combine(day, MARKET_OPEN, IST)
        candles = []
        for i in range(75):
            o = price
            c = max(1.0, o * (1 + self.drift + rng.gauss(0, 0.002)))
            h = max(o, c) * (1 + abs(rng.gauss(0, 0.001)))
            low = min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
            candles.append(Candle(start + timedelta(minutes=5 * i), o, h, low, c, 1000 + rng.random() * 50000))
            price = c
        return candles

    def intraday_candles(self, instrument: Instrument, now: datetime) -> List[Candle]:
        return [c for c in self._day_path(instrument, now.date()) if c.start <= now]

    def quote(self, instrument: Instrument, now: datetime) -> Quote:
        candles = self.intraday_candles(instrument, now)
        price = candles[-1].close if candles else self._day_path(instrument, now.date())[0].open
        return Quote(instrument.symbol, price, now)

    def daily_candles(self, instrument: Instrument, now: datetime, days: int) -> List[Candle]:
        out = []
        for back in range(days, 0, -1):
            d = now.date() - timedelta(days=back)
            path = self._day_path(instrument, d)
            vol = sum(c.volume for c in path) * 40  # scale so tier A is reachable in tests
            out.append(Candle(datetime.combine(d, time(9, 15), IST), path[0].open,
                              max(c.high for c in path), min(c.low for c in path), path[-1].close, vol))
        return out


class BrokerMarketData:
    """Real prices through the broker adapter (Angel One). Used by PAPER and LIVE."""

    is_real = True

    def __init__(self, client):
        self.client = client

    def quote(self, instrument: Instrument, now: datetime) -> Quote:
        try:
            q = self.client.get_quote(instrument)
        except Exception as exc:  # noqa: BLE001 - any broker failure means no data
            raise DataUnavailable(f"quote failed for {instrument.symbol}: {exc}") from exc
        if q is None or q.price <= 0:
            raise DataUnavailable(f"no price for {instrument.symbol}")
        return q

    def intraday_candles(self, instrument: Instrument, now: datetime) -> List[Candle]:
        try:
            return self.client.get_candles(instrument, "FIVE_MINUTE", now.replace(hour=9, minute=15, second=0,
                                                                                  microsecond=0), now)
        except Exception as exc:  # noqa: BLE001
            raise DataUnavailable(f"candles failed for {instrument.symbol}: {exc}") from exc

    def daily_candles(self, instrument: Instrument, now: datetime, days: int) -> List[Candle]:
        try:
            return self.client.get_candles(instrument, "ONE_DAY", now - timedelta(days=int(days * 1.6) + 5), now)[-days:]
        except Exception as exc:  # noqa: BLE001
            raise DataUnavailable(f"daily candles failed for {instrument.symbol}: {exc}") from exc


class DataGuard:
    """Checks every load for staleness, gaps and jumps before strategies see it."""

    def __init__(self, stale_after_seconds: int = 600, max_jump_pct: float = 10.0, interval_minutes: int = 5):
        self.stale_after = timedelta(seconds=stale_after_seconds)
        self.max_jump_pct = max_jump_pct
        self.interval = timedelta(minutes=interval_minutes)

    def check_candles(self, candles: Sequence[Candle], now: datetime) -> Optional[str]:
        """Return a problem description, or None if the candles are fine."""
        if not candles:
            return "no candles"
        last_end = candles[-1].start + self.interval
        if now - last_end > self.stale_after:
            return f"stale: last candle ended {int((now - last_end).total_seconds() // 60)} min ago"
        for prev, cur in zip(candles[:-1], candles[1:]):
            if cur.start - prev.start > self.interval * 3:
                return f"gap before {cur.start.time()}"
            if prev.close > 0 and abs(cur.close - prev.close) / prev.close * 100 > self.max_jump_pct:
                return f"jump of more than {self.max_jump_pct:.0f}% at {cur.start.time()}"
        return None


def snapshot_quotes(source: MarketData, instruments: Sequence[Instrument], now: datetime) -> Dict[str, Quote]:
    return {i.symbol: source.quote(i, now) for i in instruments}
