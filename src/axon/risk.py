"""The one risk engine. It can veto any order (spec: architecture).

Portfolio brakes (finding 6, measured on value per unit from its peak):
  -8%   halve risk per trade in swing and intraday
  -12%  no new entries in swing and intraday
  -15%  close swing and intraday; stay locked until a person unlocks after review
Intraday also stops for the day after losing 1% of capital that day.
Brakes never touch the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Set

from axon.config import Settings
from axon.ledger import Ledger
from axon.models import Part, Signal

SATELLITES = {Part.SWING, Part.INTRADAY}


@dataclass(frozen=True)
class BrakeState:
    drawdown_pct: float
    level: float          # 0, 8, 12 or 15
    risk_multiplier: float
    entries_allowed: bool
    close_satellites: bool
    locked: bool

    def describe(self) -> str:
        if self.locked:
            return f"LOCKED at -{self.level:.0f}% (drawdown {self.drawdown_pct:.1f}%): satellites closed until review"
        if self.level >= 12:
            return f"-12% brake: no new swing/intraday entries (drawdown {self.drawdown_pct:.1f}%)"
        if self.level >= 8:
            return f"-8% brake: risk per trade halved (drawdown {self.drawdown_pct:.1f}%)"
        return f"no brake (drawdown {self.drawdown_pct:.1f}%)"


@dataclass(frozen=True)
class Approval:
    ok: bool
    reason: str
    risk_multiplier: float = 1.0


class RiskEngine:
    def __init__(self, settings: Settings, ledger: Ledger, surveillance: Optional[Set[str]] = None):
        self.s = settings
        self.ledger = ledger
        self.surveillance = surveillance or set()

    # ---------------------------------------------------------------- portfolio brakes
    def level_for(self, drawdown_pct: float) -> float:
        b = self.s.brakes
        if drawdown_pct >= b.close_satellites_at:
            return b.close_satellites_at
        if drawdown_pct >= b.no_new_entries_at:
            return b.no_new_entries_at
        if drawdown_pct >= b.halve_risk_at:
            return b.halve_risk_at
        return 0.0

    def evaluate_brakes(self, book: str, now: datetime) -> BrakeState:
        """Snapshot value per unit, update the brake level and persist any change."""
        snap = self.ledger.snapshot_nav(book, now)
        state = self.ledger.book_state(book)
        drawdown = snap["drawdown_pct"]
        level = self.level_for(drawdown)
        locked = bool(state["brake_locked"])
        if locked:
            level = max(level, self.s.brakes.close_satellites_at)
        stored = float(state["brake_level"])
        if level != stored:
            lock_now = level >= self.s.brakes.close_satellites_at
            self.ledger.set_brake(book, level, drawdown, now, lock=lock_now,
                                  note="brake level changed")
            locked = locked or lock_now
        return self._state(drawdown, level, locked)

    def current_brakes(self, book: str) -> BrakeState:
        """Read-only view of the stored brake state (no snapshot)."""
        state = self.ledger.book_state(book)
        level = float(state["brake_level"])
        locked = bool(state["brake_locked"])
        npu = self.ledger.nav_per_unit(book)
        peak = state["peak_nav_per_unit"] or npu
        drawdown = max(0.0, (peak - npu) / peak * 100.0) if peak else 0.0
        return self._state(drawdown, level, locked)

    def _state(self, drawdown: float, level: float, locked: bool) -> BrakeState:
        b = self.s.brakes
        return BrakeState(
            drawdown_pct=drawdown,
            level=level,
            risk_multiplier=0.5 if level >= b.halve_risk_at else 1.0,
            entries_allowed=level < b.no_new_entries_at and not locked,
            close_satellites=locked or level >= b.close_satellites_at,
            locked=locked,
        )

    # ---------------------------------------------------------------- intraday daily stop
    def intraday_day_pnl(self, book: str, day: date) -> float:
        realized = sum(p["realized_pnl"] or 0.0 for p in self.ledger.closed_positions(book, Part.INTRADAY, day))
        unrealized = sum(p.unrealized_pnl - p.entry_costs for p in self.ledger.open_positions(book, Part.INTRADAY)
                         if p.entry_ts.date() == day)
        return realized + unrealized

    def check_intraday_daily_stop(self, book: str, now: datetime, capital: float) -> bool:
        """Halt intraday for the rest of the day after losing 1% of capital. Returns True if halted."""
        day = now.date()
        if self.ledger.is_halted(book, Part.INTRADAY, day):
            return True
        limit = -capital * self.s.intraday.daily_loss_stop_pct / 100.0
        pnl = self.intraday_day_pnl(book, day)
        if capital > 0 and pnl <= limit:
            self.ledger.halt_part_for_day(book, Part.INTRADAY, day, now,
                                          f"day loss {pnl:.0f} reached limit {limit:.0f}")
            return True
        return False

    # ---------------------------------------------------------------- entry approval
    def approve_entry(self, signal: Signal, book: str, now: datetime, brakes: BrakeState,
                      capital: float) -> Approval:
        part = signal.part
        sym = signal.instrument.symbol
        if self.ledger.kill_switch().get("active"):
            return Approval(False, "manual kill switch is on")
        if part in SATELLITES and not brakes.entries_allowed:
            return Approval(False, brakes.describe())
        if self.ledger.is_halted(book, part, now.date()):
            return Approval(False, f"{part.value} halted for the day")
        if sym in self.s.restricted_symbols:
            return Approval(False, f"{sym} is on the restricted list")
        if sym in self.surveillance:
            return Approval(False, f"{sym} is under exchange surveillance")
        holders = self.ledger.all_open_symbols().get(sym, [])
        if self.s.one_position_per_stock_across_parts:
            same_book = [h for h in holders if h.startswith(f"{book}:")]
            if same_book:
                return Approval(False, f"{sym} already held ({', '.join(same_book)})")
        elif f"{book}:{part.value}" in holders:
            return Approval(False, f"{sym} already held by {part.value}")
        if part is Part.INTRADAY:
            if self.ledger.entries_today(book, part, now.date()) >= self.s.intraday.max_trades_per_day:
                return Approval(False, f"intraday limit of {self.s.intraday.max_trades_per_day} trades a day reached")
        sleeve = capital * self.s.capital_split[part] / 100.0
        exposure = sum(p.market_value for p in self.ledger.open_positions(book, part))
        if exposure >= sleeve:
            return Approval(False, f"{part.value} already uses its {self.s.capital_split[part]:.0f}% allocation")
        multiplier = brakes.risk_multiplier if part in SATELLITES else 1.0
        return Approval(True, "approved", multiplier)

    def sleeve_room(self, book: str, part: Part, capital: float) -> float:
        sleeve = capital * self.s.capital_split[part] / 100.0
        exposure = sum(p.market_value for p in self.ledger.open_positions(book, part))
        return max(0.0, sleeve - exposure)
