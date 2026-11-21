"""Shared test setup. Everything is built through axon.context.build, the same wiring the
scheduler uses, so the tests cover the code that trades (finding 4)."""

from __future__ import annotations

import dataclasses
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from axon.clock import IST  # noqa: E402
from axon.config import load_settings  # noqa: E402
from axon.context import build  # noqa: E402
from axon.ledger import Ledger  # noqa: E402
from axon.market_data import DataUnavailable  # noqa: E402
from axon.market_filter import FilterState  # noqa: E402
from axon.models import Candle, Instrument, Mode, OrderResult, Part, Quote  # noqa: E402

MONDAY = datetime(2026, 11, 23, 10, 20, tzinfo=IST)   # a normal trading day
HOLIDAY = datetime(2026, 11, 24, 10, 20, tzinfo=IST)  # Guru Nanak Jayanti
SYMBOLS = ["AAA-EQ", "BBB-EQ", "CCC-EQ", "DDD-EQ"]


def at(hh: int, mm: int, day: datetime = MONDAY) -> datetime:
    return day.replace(hour=hh, minute=mm, second=0, microsecond=0)


def climb(day: datetime, start: float = 1000.0, step: float = 2.0, until: datetime | None = None,
          spread: float = 5.0) -> List[Candle]:
    """Rising 5-minute candles from 9:15 that trigger the steady-climb entry."""
    out, price = [], start
    t = day.replace(hour=9, minute=15, second=0, microsecond=0)
    end = until or day.replace(hour=15, minute=30)
    while t < end:
        o, c = price, price + step
        out.append(Candle(t, o, max(o, c) + spread, min(o, c) - spread, c, 10000))
        price = c
        t += timedelta(minutes=5)
    return out


class FakeData:
    """Real-looking market data (is_real=True) that tests can steer."""

    is_real = True

    def __init__(self):
        self.candles: Dict[str, List[Candle]] = {}
        self.price_override: Dict[str, float] = {}
        self.fail = False
        self.daily: Dict[str, List[Candle]] = {}

    def set_climb(self, symbol: str, day: datetime = MONDAY, start: float = 1000.0, step: float = 2.0):
        self.candles[symbol] = climb(day, start, step)

    def intraday_candles(self, inst: Instrument, now: datetime):
        if self.fail:
            raise DataUnavailable("simulated data login failure")
        return [c for c in self.candles.get(inst.symbol, []) if c.start <= now]

    def quote(self, inst: Instrument, now: datetime) -> Quote:
        if self.fail:
            raise DataUnavailable("simulated data login failure")
        if inst.symbol in {"NIFTY 50", "INDIA VIX"}:
            return Quote(inst.symbol, 24000.0 if inst.symbol == "NIFTY 50" else 14.0, now)
        if inst.symbol in self.price_override:
            return Quote(inst.symbol, self.price_override[inst.symbol], now)
        closed = [c for c in self.candles.get(inst.symbol, []) if c.start + timedelta(minutes=5) <= now]
        if not closed:
            raise DataUnavailable(f"no data for {inst.symbol}")
        return Quote(inst.symbol, closed[-1].close + 1.0, now)

    def daily_candles(self, inst: Instrument, now: datetime, days: int):
        if self.fail:
            raise DataUnavailable("simulated")
        return self.daily.get(inst.symbol, [])


class RecordingBroker:
    """Stands in for Angel One in LIVE tests; records every order it is asked to place."""

    def __init__(self):
        self.calls = []

    def place(self, intent, quote):
        self.calls.append(intent)
        return OrderResult(True, "FILLED", broker_order_id=f"LIVE-{len(self.calls)}", fill_price=quote.price,
                           filled_quantity=intent.quantity, charges=20.0)

    def logout(self):
        pass


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("AXON_RESTRICTED_SYMBOLS", raising=False)
    universe = tmp_path / "universe.csv"
    universe.write_text("symbol,token,exchange,sector\n" + "".join(f"{s},{i + 1},NSE,\n" for i, s in enumerate(SYMBOLS)))
    surveillance = tmp_path / "surveillance.txt"
    surveillance.write_text("")
    s = load_settings()
    return dataclasses.replace(s, db_path=tmp_path / "axon.sqlite3", reports_dir=tmp_path / "reports",
                               universe_file=universe, surveillance_file=surveillance, static_ip="203.0.113.10")


@pytest.fixture
def system(tmp_settings):
    """A full Axon system on paper with ₹10,00,000, fake real-time data and an open market filter."""
    data = FakeData()
    live = RecordingBroker()
    sent: list = []
    ax = build(tmp_settings, alert_sender=sent.append, real_data=data, live_broker=live)
    ax.engine._filter_override = lambda part, now: FilterState(True, "test: filter open")
    ax.ledger.record_cash_flow("paper", "deposit", 1_000_000, MONDAY.replace(hour=8))
    for sym in SYMBOLS:
        ax.ledger.save_adtv(sym, MONDAY.date(), 1e10)  # tier A
    ax.data = data
    ax.live = live
    ax.sent = sent
    return ax


def reopen(ledger: Ledger) -> Ledger:
    """Simulate a restart: a new ledger object on the same file."""
    path = ledger.path
    ledger.close()
    return Ledger(path)


__all__ = ["MONDAY", "HOLIDAY", "SYMBOLS", "at", "climb", "FakeData", "RecordingBroker", "reopen", "Mode", "Part"]
