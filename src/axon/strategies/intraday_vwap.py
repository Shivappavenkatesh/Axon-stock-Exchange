"""Part 3: intraday VWAP momentum (spec rules, after the review's fixes).

Entry (9:30 AM - 1:00 PM, tier A only):
  price above VWAP, and either
  - steady climb: the last 3 closed 5-minute candles each closed above their VWAP, or
  - bounce: the previous candle closed at or below VWAP and the latest closed higher
    without making a lower low.
Stop 1.5 x ATR (5-minute) below entry. Target 2 x ATR above entry.
Trail: exit when a closed candle finishes below VWAP.
Forced exit: everything closed by 2:45 PM.

Ranking uses only today's prices (finding 9: no bonus for past results).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from axon.clock import IST, parse_hhmm
from axon.config import IntradayRules
from axon.indicators import atr, vwap_series
from axon.models import Candle, ExitRequest, Instrument, Part, Position, Signal
from axon.strategies.base import MarketView


class IntradayVwapStrategy:
    part = Part.INTRADAY

    def __init__(self, rules: IntradayRules):
        self.r = rules
        self.entry_start = parse_hhmm(rules.entry_start)
        self.entry_end = parse_hhmm(rules.entry_end)
        self.forced_exit = parse_hhmm(rules.forced_exit)

    def entry_window_open(self, now: datetime) -> bool:
        t = now.astimezone(IST).time()
        return self.entry_start <= t < self.entry_end

    def forced_exit_due(self, now: datetime) -> bool:
        return now.astimezone(IST).time() >= self.forced_exit

    # ------------------------------------------------------------------ exits
    def exits(self, positions: Sequence[Position], view: MarketView) -> List[ExitRequest]:
        out: List[ExitRequest] = []
        forced = self.forced_exit_due(view.now)
        for pos in positions:
            if pos.part is not Part.INTRADAY:
                continue
            if forced:
                out.append(ExitRequest(pos.id, "forced exit 2:45 PM"))
                continue
            quote = view.quotes.get(pos.symbol)
            if quote is None:
                continue
            price = quote.price
            if pos.stop is not None and price <= pos.stop:
                out.append(ExitRequest(pos.id, f"stop-loss hit ({price:.2f} <= {pos.stop:.2f})"))
            elif pos.target is not None and price >= pos.target:
                out.append(ExitRequest(pos.id, f"target hit ({price:.2f} >= {pos.target:.2f})"))
            else:
                candles = view.intraday.get(pos.symbol) or []
                after_entry = [c for c in candles if c.start >= pos.entry_ts]
                if after_entry:
                    vwap = vwap_series(candles)[-1]
                    if candles[-1].close < vwap:
                        out.append(ExitRequest(pos.id, f"closed below VWAP ({candles[-1].close:.2f} < {vwap:.2f})"))
        return out

    # ------------------------------------------------------------------ entries
    def entries(self, candidates: Sequence[Instrument], view: MarketView) -> List[Signal]:
        if not self.entry_window_open(view.now):
            return []
        signals = []
        for inst in candidates:
            candles = view.intraday.get(inst.symbol) or []
            quote = view.quotes.get(inst.symbol)
            if quote is None:
                continue
            sig = self.evaluate(inst, candles, quote.price)
            if sig is not None:
                signals.append(sig)
        return sorted(signals, key=lambda s: s.score, reverse=True)

    def evaluate(self, inst: Instrument, candles: Sequence[Candle], price: float) -> Optional[Signal]:
        if len(candles) < max(4, self.r.atr_period // 2):
            return None
        vwaps = vwap_series(candles)
        if price <= vwaps[-1]:
            return None
        last3 = list(zip(candles[-3:], vwaps[-3:]))
        steady = all(c.close > v for c, v in last3)
        prev, cur = candles[-2], candles[-1]
        bounce = prev.close <= vwaps[-2] and cur.close > prev.close and cur.low >= prev.low
        if not (steady or bounce):
            return None
        a = atr(candles, self.r.atr_period)
        if a is None or a <= 0:
            return None
        stop = price - self.r.stop_atr * a
        target = price + self.r.target_atr * a
        momentum = (cur.close - candles[-4].close) / candles[-4].close
        above = (price - vwaps[-1]) / vwaps[-1]
        avg_vol = sum(c.volume for c in candles[:-1]) / max(1, len(candles) - 1)
        surge = min(cur.volume / avg_vol, 3.0) if avg_vol > 0 else 1.0
        score = momentum * 100 + above * 100 + surge * 0.1
        return Signal(Part.INTRADAY, inst, price, round(stop, 2), round(target, 2), score,
                      "steady climb above VWAP" if steady else "VWAP bounce")
