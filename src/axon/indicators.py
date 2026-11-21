"""Price indicators used by the strategies and market filter."""

from __future__ import annotations

from typing import List, Optional, Sequence

from axon.models import Candle


def vwap_series(candles: Sequence[Candle]) -> List[float]:
    """Running VWAP for the day, one value per candle (typical price x volume)."""
    out, pv, vol = [], 0.0, 0.0
    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        pv += typical * c.volume
        vol += c.volume
        out.append(pv / vol if vol > 0 else c.close)
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    """Average true range over the last `period` candles (simple average)."""
    if len(candles) < 2:
        return None
    trs = []
    for prev, cur in zip(candles[:-1], candles[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    window = trs[-period:]
    return sum(window) / len(window) if window else None


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period
