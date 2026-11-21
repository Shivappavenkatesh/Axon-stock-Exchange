"""Time and the NSE trading calendar (finding 12)."""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    return datetime.now(IST)


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class TradingCalendar:
    """Weekends plus the NSE holiday list. Special weekend sessions (Budget day, Muhurat)
    are not traded automatically: Axon stays off unless a session date is added below."""

    def __init__(self, holidays: Dict[date, str], special_sessions: Optional[Dict[date, str]] = None):
        self.holidays = holidays
        self.special_sessions = special_sessions or {}

    @classmethod
    def from_file(cls, path: Path) -> "TradingCalendar":
        holidays: Dict[date, str] = {}
        with open(path, encoding="utf-8") as fh:
            rows = (line for line in fh if line.strip() and not line.lstrip().startswith("#"))
            for row in csv.DictReader(rows):
                holidays[date.fromisoformat(row["date"].strip())] = row["name"].strip()
        return cls(holidays)

    def years_covered(self) -> set:
        return {d.year for d in self.holidays}

    def has_year(self, year: int) -> bool:
        return year in self.years_covered()

    def closed_reason(self, day: date) -> Optional[str]:
        if day in self.special_sessions:
            return None
        if day.weekday() >= 5:
            return "weekend"
        if day in self.holidays:
            return f"NSE holiday: {self.holidays[day]}"
        return None

    def is_trading_day(self, day: date) -> bool:
        return self.closed_reason(day) is None

    def in_session(self, ts: datetime) -> bool:
        ts = ts.astimezone(IST)
        return self.is_trading_day(ts.date()) and MARKET_OPEN <= ts.time() < MARKET_CLOSE

    def trading_days_between(self, start: date, end: date) -> int:
        """Trading days after `start` up to and including `end` (used by time stops)."""
        days, cursor = 0, start
        while cursor < end:
            cursor += timedelta(days=1)
            if self.is_trading_day(cursor):
                days += 1
        return days


Clock = Callable[[], datetime]
