"""Health check (finding 14): fails if the trading loop has stopped.

During market hours the last completed cycle must be under 10 minutes old. Outside market
hours the scheduler's 'alive' beat must be under 10 minutes old.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Tuple

from axon.clock import TradingCalendar
from axon.ledger import Ledger

MAX_AGE = timedelta(minutes=10)
GRACE_AFTER_OPEN = time(9, 25)


def check(ledger: Ledger, calendar: TradingCalendar, now: datetime) -> Tuple[bool, str]:
    alive = ledger.last_beat("alive")
    if alive is None or now - alive > MAX_AGE:
        return False, f"scheduler not alive (last beat: {alive})"
    if calendar.in_session(now) and now.time() >= GRACE_AFTER_OPEN:
        cycle = ledger.last_beat("cycle")
        if cycle is None or now - cycle > MAX_AGE:
            return False, f"no trading cycle finished in the last 10 minutes (last: {cycle})"
    return True, "ok"
