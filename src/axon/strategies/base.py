"""The one strategy interface. Strategies only propose; the engine and risk engine decide."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Protocol, Sequence

from axon.models import Candle, ExitRequest, Instrument, Part, Position, Quote, Signal


@dataclass
class MarketView:
    """What a strategy may see in one cycle: checked quotes and closed candles only."""

    now: datetime
    quotes: Dict[str, Quote]
    intraday: Dict[str, List[Candle]]


class Strategy(Protocol):
    part: Part

    def exits(self, positions: Sequence[Position], view: MarketView) -> List[ExitRequest]:
        """Positions to close this cycle. Called before any new entry."""
        ...

    def entries(self, candidates: Sequence[Instrument], view: MarketView) -> List[Signal]:
        """Ranked entry signals. Ranking must not use a stock's past trade results."""
        ...

    def entry_window_open(self, now: datetime) -> bool: ...
