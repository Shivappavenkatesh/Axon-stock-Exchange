"""Market filters with real inputs (finding 7).

- Swing and crash buying: Nifty 50 against its 200-day average.
- Intraday: India VIX at or below a set level.
If the inputs cannot be fetched, the filter is OFF (no new entries).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from axon.indicators import sma
from axon.models import Candle, Instrument


@dataclass(frozen=True)
class FilterState:
    allowed: bool
    reason: str
    value: Optional[float] = None
    threshold: Optional[float] = None


def nifty_trend(daily: Sequence[Candle], period: int = 200) -> FilterState:
    closes = [c.close for c in daily]
    average = sma(closes, period)
    if average is None:
        return FilterState(False, f"not enough Nifty history ({len(closes)}/{period} days)")
    last = closes[-1]
    if last > average:
        return FilterState(True, f"Nifty {last:.0f} above its {period}-day average {average:.0f}", last, average)
    return FilterState(False, f"Nifty {last:.0f} below its {period}-day average {average:.0f}", last, average)


def drawdown_from_peak(daily: Sequence[Candle]) -> Optional[float]:
    """Nifty % below its peak (used by core crash buying in the next phase)."""
    if not daily:
        return None
    peak = max(c.high for c in daily)
    return (peak - daily[-1].close) / peak * 100.0


def intraday_vix(vix_level: Optional[float], max_vix: float) -> FilterState:
    if vix_level is None or vix_level <= 0:
        return FilterState(False, "India VIX unavailable")
    if vix_level <= max_vix:
        return FilterState(True, f"India VIX {vix_level:.1f} at or below {max_vix:.1f}", vix_level, max_vix)
    return FilterState(False, f"India VIX {vix_level:.1f} above {max_vix:.1f}", vix_level, max_vix)


def index_instrument(token: str, symbol: str) -> Instrument:
    return Instrument(symbol=symbol, token=token, exchange="NSE")


def fetch_intraday_filter(source, vix_token: str, max_vix: float, now: datetime) -> FilterState:
    try:
        q = source.quote(index_instrument(vix_token, "INDIA VIX"), now)
    except Exception as exc:  # noqa: BLE001
        return FilterState(False, f"India VIX unavailable: {exc}")
    if not getattr(source, "is_real", True):
        return FilterState(True, "TEST mode: VIX filter bypassed (random prices)")
    return intraday_vix(q.price, max_vix)
