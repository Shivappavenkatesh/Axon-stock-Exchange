"""The trading cycle. Order of work, every cycle, for every part that is switched on:

1. Skip weekends and NSE holidays (one log line a day).
2. Load real prices for the part's mode. Missing or stale prices in PAPER/LIVE: skip the
   cycle and alert. Never substitute random prices.
3. Mark positions to market and update the portfolio brakes.
4. Check exits for every open position (stop, target, VWAP trail, forced exit, -15% brake)
   before any new buy.
5. Intraday daily loss stop.
6. New entries: window, market filter, risk-engine approval, sizing, cost test, order.
Every fill is recorded as a position, with its costs and estimated tax.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Set

from axon.alerts import Alerter
from axon.clock import TradingCalendar
from axon.config import Settings
from axon.costs import CostModel
from axon.ledger import Ledger
from axon.market_data import DataGuard, DataUnavailable, MarketData, closed_candles
from axon.market_filter import FilterState, fetch_intraday_filter
from axon.models import IMPLEMENTED_PARTS, Instrument, Mode, OrderIntent, Part, Position, Quote, Side
from axon.risk import SATELLITES, RiskEngine
from axon.sizing import size_position
from axon.strategies.base import MarketView
from axon.universe import eligible, tier_for

log = logging.getLogger(__name__)


@dataclass
class PartResult:
    part: str
    mode: str
    status: str = "ok"
    exits: List[str] = field(default_factory=list)
    entries: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    brakes: str = ""
    market_filter: str = ""


@dataclass
class CycleResult:
    ts: str
    status: str
    parts: List[PartResult] = field(default_factory=list)
    reason: str = ""


class Engine:
    def __init__(self, *, settings: Settings, ledger: Ledger, calendar: TradingCalendar,
                 strategies: Dict[Part, object], data_for_mode: Callable[[Mode], MarketData],
                 broker_for_mode: Callable[[Mode], object], alerter: Alerter, universe: Sequence[Instrument],
                 surveillance: Optional[Set[str]] = None, filter_override: Optional[Callable] = None):
        self.s = settings
        self.ledger = ledger
        self.calendar = calendar
        self.strategies = strategies
        self.data_for_mode = data_for_mode
        self.broker_for_mode = broker_for_mode
        self.alerter = alerter
        self.universe = list(universe)
        self.surveillance = surveillance or set()
        self.risk = RiskEngine(settings, ledger, self.surveillance)
        self.guard = DataGuard(settings.stale_after_seconds)
        self._filter_override = filter_override

    # ------------------------------------------------------------------ entry point
    def run_cycle(self, now: datetime) -> CycleResult:
        self.ledger.beat("cycle_start", now)
        reason = self.calendar.closed_reason(now.date())
        if reason:
            self._log_once_per_day(now, "skip_day", f"No trading on {now.date()}: {reason}")
            return CycleResult(now.isoformat(), "skipped", reason=reason)
        if not self.calendar.in_session(now):
            return CycleResult(now.isoformat(), "outside session")
        result = CycleResult(now.isoformat(), "ok")
        for part, mode in self.ledger.modes().items():
            if mode is Mode.OFF or part not in IMPLEMENTED_PARTS or part not in self.strategies:
                continue
            try:
                result.parts.append(self._run_part(part, mode, now))
            except Exception as exc:  # noqa: BLE001 - one part failing must not stop the others
                log.exception("part %s failed", part.value)
                self.alerter.send(f"{part.value} ({mode.value}) cycle error: {exc}", now,
                                  key=f"error:{part.value}:{now:%Y-%m-%d %H}")
                result.parts.append(PartResult(part.value, mode.value, status=f"error: {exc}"))
        self.ledger.beat("cycle", now, ", ".join(f"{p.part}:{p.status}" for p in result.parts))
        return result

    def _log_once_per_day(self, now: datetime, kind: str, message: str) -> None:
        if not any(e["ts"][:10] == now.date().isoformat() for e in self.ledger.events(kind)):
            self.ledger.log_event(now, kind, message)
            log.info(message)

    # ------------------------------------------------------------------ one part
    def _run_part(self, part: Part, mode: Mode, now: datetime) -> PartResult:
        res = PartResult(part.value, mode.value)
        book = mode.book
        strategy = self.strategies[part]
        capital = self.ledger.nav(book)
        if capital <= 0:
            self.alerter.send(f"{mode.value} book has no money. Record a deposit before {part.value} can trade.",
                              now, key=f"nomoney:{book}:{now.date()}")
            res.status = "no capital"
            return res

        source = self.data_for_mode(mode)
        positions = self.ledger.open_positions(book, part)
        entry_possible = strategy.entry_window_open(now) and not self.ledger.is_halted(book, part, now.date())
        candidates = self.candidates(part) if entry_possible else []

        # 2. real prices, checked. The Nifty 50 quote doubles as the exchange-status check:
        #    no fresh index price means no trading this cycle.
        try:
            self._probe_exchange(source, now)
            held = [self._instrument_for(p) for p in positions]
            quotes, candles = self._load(source, held, now, required=True, book=book)
            c_quotes, c_candles = self._load(source, candidates, now, required=False, book=book)
        except DataUnavailable as exc:
            res.status = "skipped: no fresh data"
            self.ledger.record_data_check(now, book, "*", "fetch", False, str(exc))
            self.alerter.send(f"{part.value} ({mode.value}) skipped a cycle: prices unavailable or stale ({exc}). "
                              f"No orders placed.", now, key=f"data:{book}:{part.value}:{now:%Y-%m-%d %H}")
            return res
        quotes.update(c_quotes)
        candles.update(c_candles)
        view = MarketView(now=now, quotes=quotes, intraday=candles)

        # 3. marks and brakes
        self.ledger.update_marks({s: q.price for s, q in quotes.items()}, book=book)
        brakes = self.risk.evaluate_brakes(book, now)
        res.brakes = brakes.describe()
        if brakes.level > 0:
            self.alerter.send(f"Brake ({book}): {brakes.describe()}", now, key=f"brake:{book}:{brakes.level}:{now.date()}")

        # 4. exits first
        positions = self.ledger.open_positions(book, part)
        requests = {r.position_id: r.reason for r in strategy.exits(positions, view)}
        if brakes.close_satellites and part in SATELLITES:
            for p in positions:
                requests.setdefault(p.id, "-15% portfolio brake: closing satellites")
        for p in positions:
            if p.id in requests:
                res.exits.append(self._exit(p, requests[p.id], quotes.get(p.symbol), mode, now))

        # 5. intraday daily stop
        capital = self.ledger.nav(book)
        if part is Part.INTRADAY and self.risk.check_intraday_daily_stop(book, now, capital):
            self.alerter.send(f"Intraday ({book}) stopped for the day: loss limit of "
                              f"{self.s.intraday.daily_loss_stop_pct}% reached", now,
                              key=f"halt:{book}:{now.date()}")
            res.skipped.append("intraday halted for the day")
            return res

        # 6. entries
        if not entry_possible or not candidates:
            return res
        if not brakes.entries_allowed:
            res.skipped.append(brakes.describe())
            return res
        if self.ledger.kill_switch().get("active"):
            res.skipped.append("kill switch on")
            return res
        mfilter = self._market_filter(part, source, now)
        res.market_filter = mfilter.reason
        if not mfilter.allowed:
            res.skipped.append(f"market filter: {mfilter.reason}")
            return res
        ok_candidates = [i for i in candidates if i.symbol in c_candles]
        for signal in strategy.entries(ok_candidates, view):
            outcome = self._enter(signal, mode, now, brakes, quotes)
            (res.entries if outcome.startswith("BUY") else res.skipped).append(outcome)
        return res

    # ------------------------------------------------------------------ helpers
    def candidates(self, part: Part) -> List[Instrument]:
        out = []
        for inst in self.universe:
            tier = tier_for(self.ledger.latest_adtv(inst.symbol), self.s.tiers, inst.symbol in self.surveillance)
            if eligible(part, tier) and inst.symbol not in self.s.restricted_symbols:
                out.append(inst)
        return out

    def _instrument_for(self, p: Position) -> Instrument:
        return Instrument(p.symbol, p.token, p.exchange)

    def _load(self, source: MarketData, instruments: Sequence[Instrument], now: datetime, *, required: bool,
              book: str):
        """Quotes and closed candles. For held positions any problem skips the cycle;
        for candidates the stock is just left out (and logged)."""
        quotes: Dict[str, Quote] = {}
        candles: Dict[str, list] = {}
        real = getattr(source, "is_real", True)
        for inst in instruments:
            try:
                raw = source.intraday_candles(inst, now)
                closed = closed_candles(raw, now)
                problem = self.guard.check_candles(closed, now) if real else None
                quote = source.quote(inst, now)
                if real and quote.ts and (now - quote.ts).total_seconds() > self.s.stale_after_seconds:
                    problem = problem or "stale quote"
            except DataUnavailable:
                if required:
                    raise
                self.ledger.record_data_check(now, book, inst.symbol, "fetch", False, "unavailable")
                continue
            if problem:
                self.ledger.record_data_check(now, book, inst.symbol, "candles", False, problem)
                if required:
                    raise DataUnavailable(f"{inst.symbol}: {problem}")
                continue
            quotes[inst.symbol] = quote
            candles[inst.symbol] = closed
        return quotes, candles

    def _probe_exchange(self, source: MarketData, now: datetime) -> None:
        if not getattr(source, "is_real", True):
            return
        q = source.quote(Instrument("NIFTY 50", self.s.nifty_token, "NSE"), now)
        if q.ts and (now - q.ts).total_seconds() > self.s.stale_after_seconds:
            raise DataUnavailable(f"Nifty 50 price is stale (last at {q.ts:%H:%M})")

    def _market_filter(self, part: Part, source: MarketData, now: datetime) -> FilterState:
        if self._filter_override is not None:
            return self._filter_override(part, now)
        if part is Part.INTRADAY:
            return fetch_intraday_filter(source, self.s.vix_token, self.s.intraday.max_vix, now)
        return FilterState(False, f"no market filter defined for {part.value}")

    def _cost_model(self, book: str) -> CostModel:
        measured = self.ledger.measured_slippage_pct(book, self.s.costs.measured_after_orders)
        return CostModel(self.s.costs, measured)

    def _enter(self, signal, mode: Mode, now: datetime, brakes, quotes: Dict[str, Quote]) -> str:
        book = mode.book
        sym = signal.instrument.symbol
        capital = self.ledger.nav(book)
        approval = self.risk.approve_entry(signal, book, now, brakes, capital)
        if not approval.ok:
            return f"skip {sym}: {approval.reason}"
        rules = self.s.intraday
        size = size_position(capital=capital, price=signal.price, stop=signal.stop, risk_pct=rules.risk_pct,
                             capital_cap_pct=rules.capital_cap_pct, adtv=self.ledger.latest_adtv(sym),
                             adtv_cap_pct=rules.adtv_cap_pct, risk_multiplier=approval.risk_multiplier)
        qty = size.quantity
        room = self.risk.sleeve_room(book, signal.part, capital)
        qty = min(qty, math.floor(room / signal.price)) if signal.price > 0 else 0
        if qty < 1:
            return f"skip {sym}: size rounds to zero ({size.limited_by})"
        planned_risk = qty * (signal.price - signal.stop)
        costs = self._cost_model(book)
        intent = OrderIntent(signal.part, mode, signal.instrument, Side.BUY, qty, signal.price,
                             stop=signal.stop, target=signal.target, reason=signal.reason)
        passes, rt_cost = costs.passes_cost_test(intent.product, signal.price, qty, planned_risk,
                                                 signal.instrument.exchange)
        if not passes:
            self.ledger.log_event(now, "cost_test", f"{sym}: round trip {rt_cost:.2f} > "
                                  f"{self.s.costs.max_cost_to_risk:.0%} of risk {planned_risk:.2f}")
            return f"skip {sym}: cost test failed ({rt_cost:.0f} vs risk {planned_risk:.0f})"
        quote = quotes.get(sym) or Quote(sym, signal.price, now)
        expected = costs.one_side(Side.BUY, intent.product, signal.price, qty, signal.instrument.exchange).total
        result = self.broker_for_mode(mode).place(intent, quote)
        order_kw = dict(ts=now, book=book, part=signal.part, symbol=sym, side="BUY", quantity=qty,
                        order_type=intent.order_type, reference_price=signal.price, status=result.status,
                        broker_order_id=result.broker_order_id, fill_price=result.fill_price,
                        filled_quantity=result.filled_quantity, expected_cost=expected, reason=signal.reason,
                        message=result.message)
        if result.status != "FILLED":
            self.ledger.record_order(**order_kw)
            self.alerter.send(f"BUY {qty} {sym} ({mode.value}) not filled: {result.status} {result.message}", now)
            return f"skip {sym}: order {result.status} {result.message}"
        fill_qty = result.filled_quantity or qty
        actual = result.charges + (result.fill_price - signal.price) * fill_qty
        pid = self.ledger.open_position(ts=now, book=book, part=signal.part, symbol=sym,
                                        token=signal.instrument.token, exchange=signal.instrument.exchange,
                                        quantity=fill_qty, price=result.fill_price, costs=result.charges,
                                        stop=signal.stop, target=signal.target, meta={"reason": signal.reason})
        self.ledger.record_order(**{**order_kw, "actual_cost": actual, "position_id": pid,
                                    "filled_quantity": fill_qty})
        msg = (f"BUY {fill_qty} {sym} @ {result.fill_price:.2f} ({signal.part.value}, {mode.value}); "
               f"stop {signal.stop:.2f}, target {signal.target:.2f}")
        self.alerter.send(msg, now)
        return msg

    def _exit(self, p: Position, reason: str, quote: Optional[Quote], mode: Mode, now: datetime) -> str:
        if quote is None:
            return f"cannot exit {p.symbol}: no price"
        inst = self._instrument_for(p)
        intent = OrderIntent(p.part, mode, inst, Side.SELL, p.quantity, quote.price, reason=reason, position_id=p.id)
        costs = self._cost_model(mode.book)
        expected = costs.one_side(Side.SELL, intent.product, quote.price, p.quantity, p.exchange).total
        result = self.broker_for_mode(mode).place(intent, quote)
        order_kw = dict(ts=now, book=mode.book, part=p.part, symbol=p.symbol, side="SELL", quantity=p.quantity,
                        order_type=intent.order_type, reference_price=quote.price, status=result.status,
                        broker_order_id=result.broker_order_id, fill_price=result.fill_price,
                        filled_quantity=result.filled_quantity, expected_cost=expected, reason=reason,
                        position_id=p.id, message=result.message)
        if result.status != "FILLED":
            self.ledger.record_order(**order_kw)
            self.alerter.send(f"SELL {p.quantity} {p.symbol} ({mode.value}) not filled: {result.status} "
                              f"{result.message}. Position still open.", now)
            return f"exit failed {p.symbol}: {result.status}"
        actual = result.charges + (quote.price - result.fill_price) * p.quantity
        pnl = self.ledger.close_position(p.id, ts=now, price=result.fill_price, costs=result.charges, reason=reason)
        self.ledger.record_order(**{**order_kw, "actual_cost": actual})
        self._record_tax(p, pnl, now, mode.book)
        msg = f"SELL {p.quantity} {p.symbol} @ {result.fill_price:.2f} ({reason}); P&L {pnl:+.2f}"
        self.alerter.send(msg, now)
        return msg

    def _record_tax(self, p: Position, pnl: float, now: datetime, book: str) -> None:
        if p.part is Part.INTRADAY:
            category, rate = "intraday", self.s.tax.intraday_pct
        elif (now - p.entry_ts).days > 365:
            category, rate = "ltcg", self.s.tax.ltcg_pct
        else:
            category, rate = "stcg", self.s.tax.stcg_pct
        est = max(0.0, pnl) * rate / 100.0
        self.ledger.record_tax(ts=now, book=book, part=p.part, symbol=p.symbol, gain=pnl, category=category,
                               est_tax=est, position_id=p.id)

    # ------------------------------------------------------------------ pre-market
    def refresh_liquidity(self, mode: Mode, now: datetime) -> int:
        """Compute each stock's 20-day ADTV from daily candles (run before the open)."""
        from axon.universe import adtv_from_daily

        source = self.data_for_mode(mode)
        done = 0
        for inst in self.universe:
            try:
                value = adtv_from_daily(source.daily_candles(inst, now, 25))
            except DataUnavailable as exc:
                self.ledger.record_data_check(now, mode.book, inst.symbol, "adtv", False, str(exc))
                continue
            if value is not None:
                self.ledger.save_adtv(inst.symbol, now.date(), value)
                done += 1
        return done
