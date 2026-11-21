"""
Deterministic backtester for Axon Aone.

Usage:
  - Prepare historical candles per symbol as lists of dicts with keys:
    `timestamp` (ISO string or unix ts), `open`, `high`, `low`, `close`, `volume`.
  - Create Backtester(universe_candles) and call `run()` to simulate.

This is intentionally lightweight: it replays time-ordered candles, calls
the strategy signal functions (`should_buy`, `should_sell`) and simulates
market fills at candle `close` prices. It produces a trade log and
basic performance metrics.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from axon_aone.features.trade import should_buy, should_sell
from axon_aone.risk.manager import can_open_new_trade
from axon_aone.config import START_CAPITAL, MAX_RISK_PER_TRADE


def _parse_ts(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts)
        except Exception:
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            try:
                return datetime.fromtimestamp(float(ts))
            except Exception:
                return None
    return None


class Backtester:
    """Simple event-driven backtester.

    universe_candles: Dict[symbol, List[candle_dict]]
    """

    def __init__(
        self,
        universe_candles: Dict[str, List[Dict[str, Any]]],
        start_capital: float = START_CAPITAL,
        fill_at: str = "close",  # 'close' or 'next_open'
        slippage_pct: float = 0.0005,  # 0.05% default
        commission_pct: float = 0.000,  # commission as fraction of trade value
        use_atr_stop: bool = False,
        atr_period: int = 14,
        atr_mult: float = 1.5,
    ):
        self.universe = deepcopy(universe_candles)
        # Normalize timestamps
        for sym, candles in self.universe.items():
            for c in candles:
                c["_ts"] = _parse_ts(c.get("timestamp") or c.get("time") or c.get("t"))

        self.start_capital = float(start_capital)
        self.cash = float(start_capital)
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.trade_log: List[Dict[str, Any]] = []
        # execution params
        self.fill_at = fill_at
        self.slippage_pct = float(slippage_pct)
        self.commission_pct = float(commission_pct)
        self.use_atr_stop = bool(use_atr_stop)
        self.atr_period = int(atr_period)
        self.atr_mult = float(atr_mult)

    def _all_timestamps(self) -> List[datetime]:
        ts_set = set()
        for candles in self.universe.values():
            for c in candles:
                if c.get("_ts"):
                    ts_set.add(c["_ts"])
        return sorted(list(ts_set))

    def _snapshot(self, ts: datetime) -> Dict[str, Dict[str, Any]]:
        """Get latest candle <= ts for each symbol."""
        snap = {}
        for sym, candles in self.universe.items():
            latest = None
            for c in candles:
                if not c.get("_ts"):
                    continue
                if c["_ts"] <= ts:
                    latest = c
                else:
                    break
            if latest:
                snap[sym] = latest
        return snap

    def _get_next_candle(self, sym: str, ts: datetime) -> Optional[Dict[str, Any]]:
        candles = self.universe.get(sym, [])
        for c in candles:
            if not c.get("_ts"):
                continue
            if c["_ts"] > ts:
                return c
        return None

    def _compute_atr(self, sym: str, ts: datetime, period: int) -> Optional[float]:
        candles = self.universe.get(sym, [])
        # find index of last candle <= ts
        idx = None
        for i, c in enumerate(candles):
            if not c.get("_ts"):
                continue
            if c["_ts"] <= ts:
                idx = i
            else:
                break
        if idx is None or idx - period < 0:
            return None
        trs = []
        for j in range(idx - period + 1, idx + 1):
            cur = candles[j]
            prev = candles[j - 1] if j - 1 >= 0 else cur
            high = float(cur.get("high", cur.get("close", 0)))
            low = float(cur.get("low", cur.get("close", 0)))
            prev_close = float(prev.get("close", cur.get("close", 0)))
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        if not trs:
            return None
        return sum(trs) / len(trs)

    def _mark_equity(self, ts: Optional[datetime]):
        total = self.cash
        for sym, pos in self.positions.items():
            price = pos.get("market_price", pos.get("entry_price", 0))
            total += pos["quantity"] * price
        self.equity_curve.append((ts or datetime.now(), total))

    def _close_position(self, sym: str, price: float, ts: datetime):
        pos = self.positions.pop(sym, None)
        if not pos:
            return
        qty = pos["quantity"]
        entry = pos["entry_price"]
        proceeds = qty * price
        self.cash += proceeds
        pnl = (price - entry) * qty * (1 if pos.get("side", "BUY") == "BUY" else -1)
        trade = {
            "symbol": sym,
            "action": "SELL",
            "quantity": qty,
            "price": price,
            "entry_price": entry,
            "pnl": pnl,
            "timestamp": ts.isoformat(),
        }
        self.trade_log.append(trade)

    def _open_position(self, sym: str, qty: int, price: float, stop_loss: float, target: float, ts: datetime):
        cost = qty * price
        if cost > self.cash:
            qty = int(self.cash // price)
            if qty <= 0:
                return False
            cost = qty * price
        self.cash -= cost
        self.positions[sym] = {
            "quantity": qty,
            "entry_price": price,
            "stop_loss": stop_loss,
            "target": target,
            "side": "BUY",
            "market_price": price,
        }
        trade = {
            "symbol": sym,
            "action": "BUY",
            "quantity": qty,
            "price": price,
            "timestamp": ts.isoformat(),
        }
        self.trade_log.append(trade)
        return True

    def run(self) -> Dict[str, Any]:
        timestamps = self._all_timestamps()
        if not timestamps:
            return {"error": "no timestamps in data"}

        for ts in timestamps:
            snap = self._snapshot(ts)

            # Update market_price for positions
            for sym, pos in list(self.positions.items()):
                c = snap.get(sym)
                if c:
                    pos["market_price"] = float(c.get("close", pos.get("market_price", pos.get("entry_price", 0))))

            # SELL checks first (reduce risk)
            for sym, pos in list(self.positions.items()):
                price = pos.get("market_price", pos.get("entry_price", 0))
                # apply slippage and commission on exit
                exit_price = price * (1 - self.slippage_pct)
                if should_sell(pos, price, use_mock=True):
                    # subtract commission
                    comm = exit_price * pos["quantity"] * self.commission_pct
                    self._close_position(sym, exit_price, ts)

            # BUY checks
            for sym, c in snap.items():
                price = float(c.get("close", 0))
                stock = {
                    "symbol": sym,
                    "price": price,
                    "candles": [c],
                    "vwap": c.get("vwap", price),
                }
                if should_buy(stock, use_mock=True):
                    # determine fill price based on fill_at
                    fill_price = price
                    if self.fill_at == "next_open":
                        nxt = self._get_next_candle(sym, ts)
                        if nxt and nxt.get("open") is not None:
                            fill_price = float(nxt.get("open"))

                    # apply slippage for BUY
                    fill_price = fill_price * (1 + self.slippage_pct)

                    entry_price = fill_price

                    # determine stop-loss (ATR-based optional)
                    if self.use_atr_stop:
                        atr = self._compute_atr(sym, ts, self.atr_period)
                        if atr:
                            stop_loss = max(entry_price - atr * self.atr_mult, entry_price * 0.995)
                        else:
                            stop_loss = entry_price * 0.99
                    else:
                        stop_loss = entry_price * 0.99

                    risk_per_share = abs(entry_price - stop_loss)
                    max_risk_amount = self.start_capital * MAX_RISK_PER_TRADE
                    qty = 1
                    if risk_per_share > 0:
                        qty = int(max(1, max_risk_amount // risk_per_share))

                    if qty <= 0:
                        continue

                    if not can_open_new_trade(entry_price, stop_loss, qty, {"total_capital": self.start_capital, "tradable_capital": self.cash}):
                        continue

                    target = entry_price * 1.02
                    # Only open if not already in position for symbol
                    if sym not in self.positions:
                        self._open_position(sym, qty, entry_price, stop_loss, target, ts)

            # Record equity at this timestamp
            self._mark_equity(ts)

        # Close remaining positions at last known price
        last_ts = timestamps[-1]
        snap = self._snapshot(last_ts)
        for sym in list(self.positions.keys()):
            price = float(snap.get(sym, {}).get("close", self.positions[sym]["entry_price"]))
            self._close_position(sym, price, last_ts)
        self._mark_equity(last_ts)

        # Compute metrics
        start = self.start_capital
        end = self.equity_curve[-1][1] if self.equity_curve else self.cash
        ret = (end - start) / start

        # max drawdown
        peak = -math.inf
        max_dd = 0.0
        for _, eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        results = {
            "start_capital": start,
            "end_capital": end,
            "return": ret,
            "max_drawdown": max_dd,
            "trades": self.trade_log,
            "equity_curve": [(t.isoformat(), v) for t, v in self.equity_curve],
        }

        return results


if __name__ == "__main__":
    # Simple example usage (reads example JSON file `backtest_input.json` if present)
    try:
        with open("backtest_input.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        print("No backtest_input.json found in cwd. Create a JSON mapping symbol->candles to run.")
        data = {}

    bt = Backtester(data)
    res = bt.run()
    print(json.dumps({k: (v if k != "trades" else list(v)) for k, v in res.items()}, indent=2, default=str))
