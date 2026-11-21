"""The daily routine. One loop, no external scheduler library.

08:45  liquidity refresh (20-day ADTV) for every part that is switched on
09:00  morning brief on Telegram
09:15-15:30  a trading cycle every 5 minutes
15:35  daily report, API logout, month-end income check
Weekends and NSE holidays: one log line, nothing else.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, time, timedelta
from typing import Callable, Optional

from axon.clock import MARKET_CLOSE, MARKET_OPEN, now_ist
from axon.context import Axon
from axon.income import month_end_income
from axon.models import Mode
from axon.report import write_daily_report
from axon.risk import RiskEngine

log = logging.getLogger(__name__)

LIQUIDITY_AT = time(8, 45)
BRIEF_AT = time(9, 0)
POST_CLOSE_AT = time(15, 35)


class Scheduler:
    def __init__(self, axon: Axon, clock: Callable[[], datetime] = now_ist,
                 sleep: Callable[[float], None] = _time.sleep):
        self.axon = axon
        self.clock = clock
        self.sleep = sleep
        self._done: set = set()
        self._last_cycle_slot: Optional[datetime] = None

    def _once(self, key: str) -> bool:
        if key in self._done:
            return False
        self._done.add(key)
        return True

    def tick(self, now: datetime) -> None:
        a = self.axon
        a.ledger.beat("alive", now)
        day = now.date()
        if not a.calendar.has_year(day.year) and self._once(f"nocal:{day}"):
            a.alerter.send(f"NSE holiday list for {day.year} is missing. Add it to the holidays file.", now,
                           key=f"nocal:{day}")
        if not a.calendar.is_trading_day(day):
            a.engine.run_cycle(now)  # logs the skip once a day
            return
        t = now.time()
        active = {m for m in a.ledger.modes().values() if m is not Mode.OFF}
        if t >= LIQUIDITY_AT and self._once(f"adtv:{day}"):
            for mode in active:
                try:
                    n = a.engine.refresh_liquidity(mode, now)
                    log.info("liquidity refreshed for %d stocks (%s)", n, mode.value)
                except Exception as exc:  # noqa: BLE001
                    a.alerter.send(f"Liquidity refresh failed ({mode.value}): {exc}", now, key=f"adtv:{day}:{mode}")
        if t >= BRIEF_AT and self._once(f"brief:{day}"):
            a.alerter.send(self.morning_brief(now), now, key=f"brief:{day}")
        if MARKET_OPEN <= t < MARKET_CLOSE:
            slot = now.replace(minute=now.minute - now.minute % a.settings.cycle_minutes, second=0, microsecond=0)
            if slot != self._last_cycle_slot:
                self._last_cycle_slot = slot
                a.engine.run_cycle(now)
        if t >= POST_CLOSE_AT and self._once(f"close:{day}"):
            self.post_close(now)

    def morning_brief(self, now: datetime) -> str:
        a = self.axon
        risk = RiskEngine(a.settings, a.ledger)
        lines = [f"Axon morning brief {now:%d %b %Y}"]
        for part, mode in a.ledger.modes().items():
            lines.append(f"- {part.value}: {mode.value.upper()}")
        for book in sorted({m.book for m in a.ledger.modes().values() if m is not Mode.OFF}):
            lines.append(f"- {book} book: value {a.ledger.nav(book):,.0f}; {risk.current_brakes(book).describe()}")
            lines.append(f"  open positions: {len(a.ledger.open_positions(book))}")
        if a.ledger.kill_switch().get("active"):
            lines.append("- KILL SWITCH IS ON")
        return "\n".join(lines)

    def post_close(self, now: datetime) -> None:
        a = self.axon
        path = write_daily_report(a.ledger, now.date(), a.settings.reports_dir)
        a.alerter.send(f"Daily report written: {path.name}", now, key=f"report:{now.date()}")
        try:
            a.logout()
        except Exception as exc:  # noqa: BLE001
            a.alerter.send(f"API logout failed: {exc}", now, key=f"logout:{now.date()}")
        nxt = now.date() + timedelta(days=1)
        while not a.calendar.is_trading_day(nxt):
            nxt += timedelta(days=1)
        if nxt.month != now.month:
            month = now.strftime("%Y-%m")
            for book in sorted({m.book for m in a.ledger.modes().values() if m is not Mode.OFF}):
                d = month_end_income(a.ledger, book, month)
                a.alerter.send(f"Income {month} ({book}): net {d.net_profit:+.2f}, payout {d.payout:.2f} — {d.reason}",
                               now, key=f"income:{book}:{month}")

    def run_forever(self, poll_seconds: float = 20.0) -> None:
        log.info("Axon scheduler started")
        while True:
            now = self.clock()
            try:
                self.tick(now)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; health check watches it
                log.exception("scheduler tick failed")
                self.axon.alerter.send(f"Scheduler error: {exc}", now, key=f"tick:{now:%Y-%m-%d %H}")
            self.sleep(poll_seconds)
