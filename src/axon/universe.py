"""Universe and liquidity tiers (spec: design principle 1)."""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Iterable, List, Optional, Set

from axon.config import LiquidityTiers
from axon.models import Candle, Instrument, Part

TIER_PARTS = {
    "A": {Part.CORE, Part.SWING, Part.INTRADAY},
    "B": {Part.CORE, Part.SWING},
    "C": {Part.CORE},
    "X": set(),
}


def load_universe(path: Path) -> List[Instrument]:
    with open(path, encoding="utf-8") as fh:
        rows = (line for line in fh if line.strip() and not line.lstrip().startswith("#"))
        return [
            Instrument(symbol=r["symbol"].strip().upper(), token=r["token"].strip(),
                       exchange=(r.get("exchange") or "NSE").strip().upper(), sector=(r.get("sector") or "").strip())
            for r in csv.DictReader(rows)
        ]


def load_symbol_set(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as fh:
        return {line.strip().upper() for line in fh if line.strip() and not line.lstrip().startswith("#")}


def adtv_from_daily(candles: Iterable[Candle], days: int = 20) -> Optional[float]:
    """20-day median daily traded value (close x volume)."""
    values = [c.close * c.volume for c in candles][-days:]
    if len(values) < min(days, 10):
        return None
    return float(statistics.median(values))


def tier_for(adtv: Optional[float], tiers: LiquidityTiers, under_surveillance: bool = False) -> str:
    if under_surveillance or adtv is None:
        return "X"
    if adtv >= tiers.tier_a_min:
        return "A"
    if adtv >= tiers.tier_b_min:
        return "B"
    if adtv >= tiers.tier_c_min:
        return "C"
    return "X"


def eligible(part: Part, tier: str) -> bool:
    return part in TIER_PARTS.get(tier, set())
