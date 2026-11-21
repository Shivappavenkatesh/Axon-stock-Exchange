"""The one ledger: every fill, position, cost, tax estimate, cash flow, brake, mode change,
alert and heartbeat lives here, so state survives restarts (findings 2, 6, 10, 11, 14).

Uses SQLite (standard library) in WAL mode so the trading loop and the web app can share
it on one machine. Money is tracked per *book* (test / paper / live) so practice results
never mix with real money.

Drawdown is measured on value per unit, like a mutual fund NAV (review fix): deposits buy
units and payouts redeem them, so moving money in or out never looks like profit or loss.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from axon.models import Mode, Part, Position

START_NAV_PER_UNIT = 100.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL, part TEXT NOT NULL, symbol TEXT NOT NULL, token TEXT NOT NULL,
    exchange TEXT NOT NULL, quantity INTEGER NOT NULL, entry_price REAL NOT NULL,
    entry_ts TEXT NOT NULL, stop REAL, target REAL, entry_costs REAL NOT NULL DEFAULT 0,
    last_price REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open',
    exit_price REAL, exit_ts TEXT, exit_reason TEXT, exit_costs REAL, realized_pnl REAL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_positions_open ON positions(book, status);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, book TEXT NOT NULL, part TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, quantity INTEGER NOT NULL, order_type TEXT NOT NULL,
    reference_price REAL NOT NULL, status TEXT NOT NULL, broker_order_id TEXT,
    fill_price REAL, filled_quantity INTEGER, expected_cost REAL, actual_cost REAL,
    slippage_pct REAL, reason TEXT, position_id INTEGER, message TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_day ON orders(book, ts);
CREATE TABLE IF NOT EXISTS books (
    book TEXT PRIMARY KEY, cash REAL NOT NULL DEFAULT 0, units REAL NOT NULL DEFAULT 0,
    peak_nav_per_unit REAL NOT NULL DEFAULT 0, brake_level REAL NOT NULL DEFAULT 0,
    brake_locked INTEGER NOT NULL DEFAULT 0, updated_ts TEXT
);
CREATE TABLE IF NOT EXISTS cash_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, book TEXT NOT NULL,
    kind TEXT NOT NULL, amount REAL NOT NULL, nav_per_unit REAL NOT NULL, units REAL NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS nav_history (
    ts TEXT NOT NULL, book TEXT NOT NULL, nav REAL NOT NULL, units REAL NOT NULL,
    nav_per_unit REAL NOT NULL, drawdown_pct REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS part_modes (
    part TEXT PRIMARY KEY, mode TEXT NOT NULL, updated_ts TEXT
);
CREATE TABLE IF NOT EXISTS mode_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, part TEXT NOT NULL,
    old_mode TEXT NOT NULL, new_mode TEXT NOT NULL, actor TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS kill_switch (
    id INTEGER PRIMARY KEY CHECK (id = 1), active INTEGER NOT NULL, ts TEXT, actor TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS brake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, book TEXT NOT NULL,
    level REAL NOT NULL, drawdown_pct REAL NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS day_halts (
    book TEXT NOT NULL, part TEXT NOT NULL, day TEXT NOT NULL, ts TEXT NOT NULL, reason TEXT,
    PRIMARY KEY (book, part, day)
);
CREATE TABLE IF NOT EXISTS tax_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, book TEXT NOT NULL,
    part TEXT NOT NULL, symbol TEXT NOT NULL, gain REAL NOT NULL, category TEXT NOT NULL,
    est_tax REAL NOT NULL, position_id INTEGER
);
CREATE TABLE IF NOT EXISTS data_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, book TEXT NOT NULL,
    symbol TEXT NOT NULL, check_name TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, dedupe_key TEXT, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS heartbeat (
    name TEXT PRIMARY KEY, ts TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS adtv (
    symbol TEXT NOT NULL, day TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (symbol, day)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT
);
"""

DEFAULT_MODES = {Part.CORE: Mode.OFF, Part.SWING: Mode.OFF, Part.INTRADAY: Mode.PAPER}


def _iso(ts: datetime) -> str:
    return ts.isoformat()


class Ledger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _q(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, args))

    # ------------------------------------------------------------------ books & NAV
    def _ensure_book(self, conn: sqlite3.Connection, book: str) -> sqlite3.Row:
        conn.execute("INSERT OR IGNORE INTO books(book) VALUES (?)", (book,))
        return conn.execute("SELECT * FROM books WHERE book=?", (book,)).fetchone()

    def book_state(self, book: str) -> dict:
        with self.tx() as conn:
            return dict(self._ensure_book(conn, book))

    def nav(self, book: str) -> float:
        """Cash plus open positions at their latest prices."""
        state = self.book_state(book)
        mtm = sum(p.market_value for p in self.open_positions(book))
        return state["cash"] + mtm

    def nav_per_unit(self, book: str) -> float:
        state = self.book_state(book)
        if state["units"] <= 0:
            return START_NAV_PER_UNIT
        return self.nav(book) / state["units"]

    def record_cash_flow(self, book: str, kind: str, amount: float, ts: datetime, note: str = "") -> dict:
        """Deposits buy units at today's value per unit; withdrawals and payouts redeem them."""
        if kind not in {"deposit", "withdrawal", "payout"}:
            raise ValueError(f"unknown cash flow kind: {kind}")
        if amount <= 0:
            raise ValueError("amount must be positive")
        npu = self.nav_per_unit(book)
        units = amount / npu
        with self.tx() as conn:
            state = self._ensure_book(conn, book)
            sign = 1 if kind == "deposit" else -1
            if sign < 0 and amount > state["cash"] + 1e-6:
                raise ValueError("not enough cash in the book for this withdrawal")
            new_units = state["units"] + sign * units
            peak = state["peak_nav_per_unit"] or npu
            conn.execute(
                "UPDATE books SET cash=cash+?, units=?, peak_nav_per_unit=?, updated_ts=? WHERE book=?",
                (sign * amount, new_units, max(peak, npu), _iso(ts), book),
            )
            conn.execute(
                "INSERT INTO cash_flows(ts, book, kind, amount, nav_per_unit, units, note) VALUES (?,?,?,?,?,?,?)",
                (_iso(ts), book, kind, amount, npu, sign * units, note),
            )
        return {"nav_per_unit": npu, "units": sign * units}

    def snapshot_nav(self, book: str, ts: datetime) -> dict:
        """Save value per unit and update the high-water mark. The peak is never reset."""
        state = self.book_state(book)
        nav = self.nav(book)
        units = state["units"]
        npu = nav / units if units > 0 else START_NAV_PER_UNIT
        peak = max(state["peak_nav_per_unit"] or npu, npu)
        drawdown = 0.0 if peak <= 0 else max(0.0, (peak - npu) / peak * 100.0)
        with self.tx() as conn:
            conn.execute("UPDATE books SET peak_nav_per_unit=?, updated_ts=? WHERE book=?", (peak, _iso(ts), book))
            conn.execute(
                "INSERT INTO nav_history(ts, book, nav, units, nav_per_unit, drawdown_pct) VALUES (?,?,?,?,?,?)",
                (_iso(ts), book, nav, units, npu, drawdown),
            )
        return {"nav": nav, "units": units, "nav_per_unit": npu, "peak": peak, "drawdown_pct": drawdown}

    def set_brake(self, book: str, level: float, drawdown: float, ts: datetime, lock: bool, note: str = "") -> None:
        with self.tx() as conn:
            self._ensure_book(conn, book)
            conn.execute(
                "UPDATE books SET brake_level=?, brake_locked=CASE WHEN ? THEN 1 ELSE brake_locked END, updated_ts=? WHERE book=?",
                (level, 1 if lock else 0, _iso(ts), book),
            )
            conn.execute(
                "INSERT INTO brake_events(ts, book, level, drawdown_pct, note) VALUES (?,?,?,?,?)",
                (_iso(ts), book, level, drawdown, note),
            )

    def unlock_brakes(self, book: str, ts: datetime, actor: str) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE books SET brake_locked=0, brake_level=0, updated_ts=? WHERE book=?", (_iso(ts), book))
            conn.execute(
                "INSERT INTO brake_events(ts, book, level, drawdown_pct, note) VALUES (?,?,?,?,?)",
                (_iso(ts), book, 0, 0, f"unlocked by {actor} after review"),
            )

    def brake_events(self, book: Optional[str] = None, day: Optional[date] = None) -> List[dict]:
        sql, args = "SELECT * FROM brake_events WHERE 1=1", []
        if book:
            sql += " AND book=?"
            args.append(book)
        if day:
            sql += " AND substr(ts,1,10)=?"
            args.append(day.isoformat())
        return [dict(r) for r in self._q(sql + " ORDER BY id", tuple(args))]

    # ------------------------------------------------------------------ positions & orders
    def open_positions(self, book: Optional[str] = None, part: Optional[Part] = None) -> List[Position]:
        sql, args = "SELECT * FROM positions WHERE status='open'", []
        if book:
            sql += " AND book=?"
            args.append(book)
        if part:
            sql += " AND part=?"
            args.append(part.value)
        return [self._to_position(r) for r in self._q(sql + " ORDER BY id", tuple(args))]

    def all_open_symbols(self) -> Dict[str, List[str]]:
        """symbol -> list of 'book:part' holding it (for the one-position-per-stock rule)."""
        out: Dict[str, List[str]] = {}
        for r in self._q("SELECT symbol, book, part FROM positions WHERE status='open'"):
            out.setdefault(r["symbol"], []).append(f"{r['book']}:{r['part']}")
        return out

    @staticmethod
    def _to_position(r: sqlite3.Row) -> Position:
        return Position(
            id=r["id"], book=r["book"], part=Part(r["part"]), symbol=r["symbol"], token=r["token"],
            exchange=r["exchange"], quantity=r["quantity"], entry_price=r["entry_price"],
            entry_ts=datetime.fromisoformat(r["entry_ts"]), stop=r["stop"], target=r["target"],
            entry_costs=r["entry_costs"], last_price=r["last_price"], meta=json.loads(r["meta"] or "{}"),
        )

    def record_order(self, *, ts: datetime, book: str, part: Part, symbol: str, side: str, quantity: int,
                     order_type: str, reference_price: float, status: str, broker_order_id: str = "",
                     fill_price: float = 0.0, filled_quantity: int = 0, expected_cost: float = 0.0,
                     actual_cost: float = 0.0, reason: str = "", position_id: Optional[int] = None,
                     message: str = "") -> int:
        slippage = None
        if fill_price and reference_price:
            direction = 1 if side == "BUY" else -1
            slippage = direction * (fill_price - reference_price) / reference_price * 100.0
        with self.tx() as conn:
            cur = conn.execute(
                """INSERT INTO orders(ts, book, part, symbol, side, quantity, order_type, reference_price, status,
                   broker_order_id, fill_price, filled_quantity, expected_cost, actual_cost, slippage_pct, reason,
                   position_id, message) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_iso(ts), book, part.value, symbol, side, quantity, order_type, reference_price, status,
                 broker_order_id, fill_price, filled_quantity, expected_cost, actual_cost, slippage, reason,
                 position_id, message),
            )
            return int(cur.lastrowid)

    def open_position(self, *, ts: datetime, book: str, part: Part, symbol: str, token: str, exchange: str,
                      quantity: int, price: float, costs: float, stop: Optional[float], target: Optional[float],
                      meta: Optional[dict] = None) -> int:
        with self.tx() as conn:
            self._ensure_book(conn, book)
            cur = conn.execute(
                """INSERT INTO positions(book, part, symbol, token, exchange, quantity, entry_price, entry_ts, stop,
                   target, entry_costs, last_price, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (book, part.value, symbol, token, exchange, quantity, price, _iso(ts), stop, target, costs, price,
                 json.dumps(meta or {})),
            )
            conn.execute("UPDATE books SET cash=cash-?, updated_ts=? WHERE book=?",
                         (quantity * price + costs, _iso(ts), book))
            return int(cur.lastrowid)

    def close_position(self, position_id: int, *, ts: datetime, price: float, costs: float, reason: str) -> float:
        with self.tx() as conn:
            r = conn.execute("SELECT * FROM positions WHERE id=? AND status='open'", (position_id,)).fetchone()
            if r is None:
                raise ValueError(f"position {position_id} is not open")
            pnl = r["quantity"] * (price - r["entry_price"]) - r["entry_costs"] - costs
            conn.execute(
                """UPDATE positions SET status='closed', exit_price=?, exit_ts=?, exit_reason=?, exit_costs=?,
                   realized_pnl=?, last_price=? WHERE id=?""",
                (price, _iso(ts), reason, costs, pnl, price, position_id),
            )
            conn.execute("UPDATE books SET cash=cash+?, updated_ts=? WHERE book=?",
                         (r["quantity"] * price - costs, _iso(ts), r["book"]))
            return pnl

    def update_marks(self, prices: Dict[str, float], book: Optional[str] = None) -> None:
        with self.tx() as conn:
            for symbol, price in prices.items():
                if book:
                    conn.execute("UPDATE positions SET last_price=? WHERE status='open' AND symbol=? AND book=?",
                                 (price, symbol, book))
                else:
                    conn.execute("UPDATE positions SET last_price=? WHERE status='open' AND symbol=?", (price, symbol))

    def update_position_meta(self, position_id: int, **changes) -> None:
        with self.tx() as conn:
            r = conn.execute("SELECT meta FROM positions WHERE id=?", (position_id,)).fetchone()
            meta = json.loads(r["meta"] or "{}")
            meta.update(changes)
            conn.execute("UPDATE positions SET meta=? WHERE id=?", (json.dumps(meta), position_id))

    def closed_positions(self, book: Optional[str] = None, part: Optional[Part] = None,
                         day: Optional[date] = None) -> List[dict]:
        sql, args = "SELECT * FROM positions WHERE status='closed'", []
        if book:
            sql += " AND book=?"
            args.append(book)
        if part:
            sql += " AND part=?"
            args.append(part.value)
        if day:
            sql += " AND substr(exit_ts,1,10)=?"
            args.append(day.isoformat())
        return [dict(r) for r in self._q(sql + " ORDER BY id", tuple(args))]

    def orders(self, book: Optional[str] = None, day: Optional[date] = None, part: Optional[Part] = None) -> List[dict]:
        sql, args = "SELECT * FROM orders WHERE 1=1", []
        if book:
            sql += " AND book=?"
            args.append(book)
        if day:
            sql += " AND substr(ts,1,10)=?"
            args.append(day.isoformat())
        if part:
            sql += " AND part=?"
            args.append(part.value)
        return [dict(r) for r in self._q(sql + " ORDER BY id", tuple(args))]

    def entries_today(self, book: str, part: Part, day: date) -> int:
        rows = self._q(
            "SELECT COUNT(*) AS n FROM orders WHERE book=? AND part=? AND side='BUY' AND status='FILLED' AND substr(ts,1,10)=?",
            (book, part.value, day.isoformat()),
        )
        return int(rows[0]["n"])

    def measured_slippage_pct(self, book: str, min_orders: int) -> Optional[float]:
        rows = self._q(
            "SELECT AVG(ABS(slippage_pct)) AS s, COUNT(*) AS n FROM orders WHERE book=? AND status='FILLED' AND slippage_pct IS NOT NULL",
            (book,),
        )
        if rows and rows[0]["n"] >= min_orders:
            return float(rows[0]["s"])
        return None

    # ------------------------------------------------------------------ tax
    def record_tax(self, *, ts: datetime, book: str, part: Part, symbol: str, gain: float, category: str,
                   est_tax: float, position_id: int) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO tax_events(ts, book, part, symbol, gain, category, est_tax, position_id) VALUES (?,?,?,?,?,?,?,?)",
                (_iso(ts), book, part.value, symbol, gain, category, est_tax, position_id),
            )

    def tax_for_position(self, position_id: int) -> float:
        rows = self._q("SELECT COALESCE(SUM(est_tax),0) AS t FROM tax_events WHERE position_id=?", (position_id,))
        return float(rows[0]["t"])

    # ------------------------------------------------------------------ modes, kill switch, halts
    def get_mode(self, part: Part) -> Mode:
        rows = self._q("SELECT mode FROM part_modes WHERE part=?", (part.value,))
        return Mode(rows[0]["mode"]) if rows else DEFAULT_MODES[part]

    def modes(self) -> Dict[Part, Mode]:
        return {p: self.get_mode(p) for p in Part}

    def set_mode(self, part: Part, mode: Mode, ts: datetime, actor: str, note: str = "") -> Mode:
        old = self.get_mode(part)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO part_modes(part, mode, updated_ts) VALUES (?,?,?) "
                "ON CONFLICT(part) DO UPDATE SET mode=excluded.mode, updated_ts=excluded.updated_ts",
                (part.value, mode.value, _iso(ts)),
            )
            conn.execute(
                "INSERT INTO mode_changes(ts, part, old_mode, new_mode, actor, note) VALUES (?,?,?,?,?,?)",
                (_iso(ts), part.value, old.value, mode.value, actor, note),
            )
        return old

    def mode_changes(self) -> List[dict]:
        return [dict(r) for r in self._q("SELECT * FROM mode_changes ORDER BY id")]

    def kill_switch(self) -> dict:
        rows = self._q("SELECT * FROM kill_switch WHERE id=1")
        return dict(rows[0]) if rows else {"active": 0}

    def set_kill_switch(self, active: bool, ts: datetime, actor: str, note: str = "") -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO kill_switch(id, active, ts, actor, note) VALUES (1,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET active=excluded.active, ts=excluded.ts, actor=excluded.actor, note=excluded.note",
                (1 if active else 0, _iso(ts), actor, note),
            )
        self.log_event(ts, "kill_switch", f"{'ON' if active else 'OFF'} by {actor}: {note}")

    def halt_part_for_day(self, book: str, part: Part, day: date, ts: datetime, reason: str) -> bool:
        with self.tx() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO day_halts(book, part, day, ts, reason) VALUES (?,?,?,?,?)",
                (book, part.value, day.isoformat(), _iso(ts), reason),
            )
            return cur.rowcount > 0

    def is_halted(self, book: str, part: Part, day: date) -> bool:
        return bool(self._q("SELECT 1 FROM day_halts WHERE book=? AND part=? AND day=?",
                            (book, part.value, day.isoformat())))

    # ------------------------------------------------------------------ data checks, alerts, heartbeat
    def record_data_check(self, ts: datetime, book: str, symbol: str, check: str, ok: bool, detail: str = "") -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO data_checks(ts, book, symbol, check_name, ok, detail) VALUES (?,?,?,?,?,?)",
                (_iso(ts), book, symbol, check, 1 if ok else 0, detail),
            )

    def data_checks(self, day: date, failed_only: bool = True) -> List[dict]:
        sql = "SELECT * FROM data_checks WHERE substr(ts,1,10)=?" + (" AND ok=0" if failed_only else "")
        return [dict(r) for r in self._q(sql + " ORDER BY id", (day.isoformat(),))]

    def record_alert(self, ts: datetime, message: str, dedupe_key: Optional[str] = None) -> bool:
        """Returns False if an alert with the same key was already sent (deduplicated)."""
        with self.tx() as conn:
            if dedupe_key and conn.execute("SELECT 1 FROM alerts WHERE dedupe_key=?", (dedupe_key,)).fetchone():
                return False
            conn.execute("INSERT INTO alerts(ts, dedupe_key, message) VALUES (?,?,?)", (_iso(ts), dedupe_key, message))
            return True

    def alerts(self, limit: int = 100) -> List[dict]:
        return [dict(r) for r in self._q("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]

    def beat(self, name: str, ts: datetime, detail: str = "") -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO heartbeat(name, ts, detail) VALUES (?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET ts=excluded.ts, detail=excluded.detail",
                (name, _iso(ts), detail),
            )

    def last_beat(self, name: str) -> Optional[datetime]:
        rows = self._q("SELECT ts FROM heartbeat WHERE name=?", (name,))
        return datetime.fromisoformat(rows[0]["ts"]) if rows else None

    def log_event(self, ts: datetime, kind: str, detail: str) -> None:
        with self.tx() as conn:
            conn.execute("INSERT INTO events(ts, kind, detail) VALUES (?,?,?)", (_iso(ts), kind, detail))

    def events(self, kind: Optional[str] = None) -> List[dict]:
        sql, args = "SELECT * FROM events", ()
        if kind:
            sql, args = sql + " WHERE kind=?", (kind,)
        return [dict(r) for r in self._q(sql + " ORDER BY id", args)]

    # ------------------------------------------------------------------ liquidity
    def save_adtv(self, symbol: str, day: date, value: float) -> None:
        with self.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO adtv(symbol, day, value) VALUES (?,?,?)",
                         (symbol, day.isoformat(), value))

    def latest_adtv(self, symbol: str) -> Optional[float]:
        rows = self._q("SELECT value FROM adtv WHERE symbol=? ORDER BY day DESC LIMIT 1", (symbol,))
        return float(rows[0]["value"]) if rows else None
