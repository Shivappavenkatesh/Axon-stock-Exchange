"""Daily deep-dive reporting for strategy behavior and outcomes.

Captures per-iteration diagnostics (good and bad signals), persists daily JSON,
and writes a human-readable markdown summary at end of day.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytz

from axon_aone.db import SessionLocal, Trade
from axon_aone.services.reconciliation import generate_reconciliation_report, persist_reconciliation_report
from axon_aone.services.telegram_notify import send_telegram_message


IST = pytz.timezone("Asia/Kolkata")


def _now_ist() -> datetime:
    return datetime.now(IST)


def _day_key() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@dataclass
class DayStats:
    date: str
    mode: str
    iterations: int = 0
    buy_signals: int = 0
    entry_attempts: int = 0
    entry_filled: int = 0
    entry_rejected: int = 0
    exit_attempts: int = 0
    exit_filled: int = 0
    exit_rejected: int = 0
    kill_switch_triggers: int = 0
    skip_reasons: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reject_reasons: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    exception_count: int = 0
    slippage_alerts: int = 0
    slippage_bps_sum: float = 0.0
    slippage_bps_count: int = 0
    realized_pnl: float = 0.0
    vaulted_profit: float = 0.0
    max_open_trades: int = 0
    min_tradable_capital: float | None = None
    max_tradable_capital: float | None = None
    min_portfolio_heat: float | None = None
    max_portfolio_heat: float | None = None
    last_state: Dict[str, Any] = field(default_factory=dict)

    def update(self, metrics: Dict[str, Any], state: Dict[str, Any]) -> None:
        self.iterations += 1
        self.buy_signals += int(metrics.get("buy_signals", 0) or 0)
        self.entry_attempts += int(metrics.get("entry_attempts", 0) or 0)
        self.entry_filled += int(metrics.get("entry_filled", 0) or 0)
        self.entry_rejected += int(metrics.get("entry_rejected", 0) or 0)
        self.exit_attempts += int(metrics.get("exit_attempts", 0) or 0)
        self.exit_filled += int(metrics.get("exit_filled", 0) or 0)
        self.exit_rejected += int(metrics.get("exit_rejected", 0) or 0)
        self.kill_switch_triggers += int(metrics.get("kill_switch_triggers", 0) or 0)
        self.exception_count += int(metrics.get("exception_count", 0) or 0)

        skip_reasons = metrics.get("skip_reasons") or {}
        for reason, count in skip_reasons.items():
            self.skip_reasons[str(reason)] += int(count or 0)

        reject_reasons = metrics.get("reject_reasons") or {}
        for reason, count in reject_reasons.items():
            self.reject_reasons[str(reason)] += int(count or 0)

        self.slippage_alerts += int(metrics.get("slippage_alerts", 0) or 0)
        avg_slippage_bps = float(metrics.get("avg_slippage_bps", 0.0) or 0.0)
        if avg_slippage_bps > 0:
            self.slippage_bps_sum += avg_slippage_bps
            self.slippage_bps_count += 1

        self.realized_pnl += float(metrics.get("realized_pnl", 0.0) or 0.0)
        self.vaulted_profit += float(metrics.get("vaulted_profit", 0.0) or 0.0)

        open_trades = len(state.get("open_trades") or [])
        self.max_open_trades = max(self.max_open_trades, open_trades)

        tradable = float(state.get("tradable_capital") or 0.0)
        if self.min_tradable_capital is None or tradable < self.min_tradable_capital:
            self.min_tradable_capital = tradable
        if self.max_tradable_capital is None or tradable > self.max_tradable_capital:
            self.max_tradable_capital = tradable

        heat = metrics.get("portfolio_heat")
        if heat is not None:
            heat_val = float(heat)
            if self.min_portfolio_heat is None or heat_val < self.min_portfolio_heat:
                self.min_portfolio_heat = heat_val
            if self.max_portfolio_heat is None or heat_val > self.max_portfolio_heat:
                self.max_portfolio_heat = heat_val

        self.last_state = {
            "total_capital": float(state.get("total_capital") or 0.0),
            "tradable_capital": tradable,
            "daily_pnl": float(state.get("daily_pnl") or 0.0),
            "weekly_pnl": float(state.get("weekly_pnl") or 0.0),
            "open_trades": open_trades,
            "investment_bucket": float(state.get("investment_bucket") or 0.0),
            "vault_capital": float(state.get("vault_capital") or 0.0),
            "updated_at": _now_ist().isoformat(),
        }


class DailyDeepDiveLogger:
    def __init__(self, report_dir: str | None = None) -> None:
        root = report_dir or os.getenv("AXON_DAILY_REPORT_DIR", "logs/daily_deepdive")
        self.report_dir = Path(root)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._days: Dict[str, DayStats] = {}

    def _get_day(self, mode: str) -> DayStats:
        key = _day_key()
        if key not in self._days:
            self._days[key] = DayStats(date=key, mode=mode)
        return self._days[key]

    def record_iteration(self, metrics: Dict[str, Any], state: Dict[str, Any], mode: str) -> Path:
        day = self._get_day(mode)
        day.update(metrics=metrics, state=state)
        return self._write_json(day)

    def finalize_day(self, mode: str) -> Dict[str, Path]:
        day = self._get_day(mode)
        learning = self._build_learning_snapshot()
        reconciliation = None
        reconciliation_path = None
        try:
            reconciliation = generate_reconciliation_report()
            reconciliation_path = persist_reconciliation_report(reconciliation)
        except Exception:
            reconciliation = None
            reconciliation_path = None

        data = {
            "date": day.date,
            "mode": day.mode,
            "summary": {
                "iterations": day.iterations,
                "buy_signals": day.buy_signals,
                "entry_attempts": day.entry_attempts,
                "entry_filled": day.entry_filled,
                "entry_rejected": day.entry_rejected,
                "exit_attempts": day.exit_attempts,
                "exit_filled": day.exit_filled,
                "exit_rejected": day.exit_rejected,
                "kill_switch_triggers": day.kill_switch_triggers,
                "exception_count": day.exception_count,
                "max_open_trades": day.max_open_trades,
                "realized_pnl": day.realized_pnl,
                "vaulted_profit": day.vaulted_profit,
            },
            "execution_quality": {
                "slippage_alerts": day.slippage_alerts,
                "avg_slippage_bps": (day.slippage_bps_sum / day.slippage_bps_count) if day.slippage_bps_count > 0 else 0.0,
                "reject_reasons": dict(day.reject_reasons),
            },
            "risk_envelope": {
                "min_tradable_capital": day.min_tradable_capital,
                "max_tradable_capital": day.max_tradable_capital,
                "min_portfolio_heat": day.min_portfolio_heat,
                "max_portfolio_heat": day.max_portfolio_heat,
            },
            "skip_reasons": dict(day.skip_reasons),
            "last_state": day.last_state,
            "learning": learning,
            "reconciliation": {
                "break_count": reconciliation.break_count if reconciliation else 0,
                "scheduler_count": reconciliation.scheduler_count if reconciliation else 0,
                "trade_count": reconciliation.trade_count if reconciliation else 0,
                "missing_in_db": reconciliation.missing_in_db if reconciliation else [],
                "status_mismatches": reconciliation.status_mismatches if reconciliation else [],
                "report_path": str(reconciliation_path) if reconciliation_path else None,
            },
            "deepdive": {
                "what_went_good": self._what_went_good(day),
                "what_went_bad": self._what_went_bad(day),
                "why": self._why(day),
                "next_actions": self._next_actions(day),
            },
            "generated_at": _now_ist().isoformat(),
        }

        json_path = self.report_dir / f"{day.date}.json"
        md_path = self.report_dir / f"{day.date}.md"
        json_path.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
        md_path.write_text(self._to_markdown(data), encoding="utf-8")
        self._send_telegram_summary(data=data, json_path=json_path, md_path=md_path)
        return {"json": json_path, "md": md_path}

    def _write_json(self, day: DayStats) -> Path:
        payload = {
            "date": day.date,
            "mode": day.mode,
            "iterations": day.iterations,
            "entry_filled": day.entry_filled,
            "entry_rejected": day.entry_rejected,
            "exit_filled": day.exit_filled,
            "exit_rejected": day.exit_rejected,
            "kill_switch_triggers": day.kill_switch_triggers,
            "skip_reasons": dict(day.skip_reasons),
            "reject_reasons": dict(day.reject_reasons),
            "avg_slippage_bps": (day.slippage_bps_sum / day.slippage_bps_count) if day.slippage_bps_count > 0 else 0.0,
            "slippage_alerts": day.slippage_alerts,
            "realized_pnl": day.realized_pnl,
            "vaulted_profit": day.vaulted_profit,
            "last_state": day.last_state,
            "updated_at": _now_ist().isoformat(),
        }
        path = self.report_dir / f"{day.date}.json"
        path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
        return path

    @staticmethod
    def _what_went_good(day: DayStats) -> List[str]:
        notes: List[str] = []
        if day.entry_filled > 0:
            notes.append(f"Filled entries: {day.entry_filled}")
        if day.exit_filled > 0:
            notes.append(f"Filled exits: {day.exit_filled}")
        if day.kill_switch_triggers == 0:
            notes.append("Kill switch stayed inactive")
        if not notes:
            notes.append("No strong positive execution signals were recorded")
        return notes

    @staticmethod
    def _what_went_bad(day: DayStats) -> List[str]:
        notes: List[str] = []
        if day.entry_rejected > 0:
            notes.append(f"Rejected entries: {day.entry_rejected}")
        if day.exit_rejected > 0:
            notes.append(f"Rejected exits: {day.exit_rejected}")
        if day.exception_count > 0:
            notes.append(f"Exceptions: {day.exception_count}")
        if day.kill_switch_triggers > 0:
            notes.append(f"Kill-switch activations: {day.kill_switch_triggers}")
        if day.slippage_alerts > 0:
            notes.append(f"Slippage alerts: {day.slippage_alerts}")
        for reason, count in sorted(day.skip_reasons.items(), key=lambda item: item[1], reverse=True)[:5]:
            notes.append(f"Skip reason '{reason}': {count}")
        for reason, count in sorted(day.reject_reasons.items(), key=lambda item: item[1], reverse=True)[:5]:
            notes.append(f"Reject reason '{reason}': {count}")
        if not notes:
            notes.append("No major negatives recorded")
        return notes

    @staticmethod
    def _why(day: DayStats) -> List[str]:
        analysis: List[str] = []
        if day.buy_signals > 0 and day.entry_filled == 0:
            analysis.append("Signals existed but no entries filled; risk gates or broker rejections likely dominated")
        if day.entry_attempts > 0 and day.entry_rejected / max(1, day.entry_attempts) > 0.4:
            analysis.append("High entry rejection ratio suggests execution or sizing mismatch")
        if day.kill_switch_triggers > 0:
            analysis.append("Portfolio protections were triggered; review pnl path and heat progression")
        if day.slippage_bps_count > 0 and (day.slippage_bps_sum / day.slippage_bps_count) > 25.0:
            analysis.append("Execution quality degraded; average slippage is above the control band")
        if not analysis:
            analysis.append("Execution/risk path looked stable for the sampled iterations")
        return analysis

    @staticmethod
    def _next_actions(day: DayStats) -> List[str]:
        actions: List[str] = []
        if day.entry_rejected > day.entry_filled:
            actions.append("Inspect broker responses for rejected entry orders and tune retry/validation")
        if day.skip_reasons.get("stop_loss_unavailable", 0) > 0:
            actions.append("Improve candle quality so ATR-based stop-loss can be derived more often")
        if day.kill_switch_triggers > 0:
            actions.append("Audit daily and weekly pnl updates and tighten pre-entry risk throttles")
        if day.slippage_alerts > 0:
            actions.append("Reduce market-order aggression or broaden liquidity filters for high-slippage names")
        if not actions:
            actions.append("Keep the current configuration and continue collecting behavior history")
        return actions

    @staticmethod
    def _to_markdown(payload: Dict[str, Any]) -> str:
        summary = payload["summary"]
        lines = [
            f"# Axon Daily DeepDive - {payload['date']}",
            "",
            f"Mode: {payload['mode']}",
            "",
            "## Summary",
            f"- Iterations: {summary['iterations']}",
            f"- Buy signals: {summary['buy_signals']}",
            f"- Entry filled/rejected: {summary['entry_filled']} / {summary['entry_rejected']}",
            f"- Exit filled/rejected: {summary['exit_filled']} / {summary['exit_rejected']}",
            f"- Kill switch triggers: {summary['kill_switch_triggers']}",
            f"- Exceptions: {summary['exception_count']}",
            f"- Realized PnL: {summary['realized_pnl']:.2f}",
            f"- Vaulted Profit: {summary['vaulted_profit']:.2f}",
            f"- Reconciliation breaks: {payload.get('reconciliation', {}).get('break_count', 0)}",
            "",
            "## What Went Good",
        ]
        lines.extend([f"- {item}" for item in payload["deepdive"]["what_went_good"]])
        lines.append("")
        lines.append("## What Went Bad")
        lines.extend([f"- {item}" for item in payload["deepdive"]["what_went_bad"]])
        lines.append("")
        lines.append("## Why")
        lines.extend([f"- {item}" for item in payload["deepdive"]["why"]])
        lines.append("")
        lines.append("## Next Actions")
        lines.extend([f"- {item}" for item in payload["deepdive"]["next_actions"]])
        lines.append("")
        lines.append("## Learning Snapshot")
        for item in payload["learning"].get("top_symbols", []):
            lines.append(f"- Top symbol: {item['symbol']} | wins={item['wins']} losses={item['losses']} pnl={item['realized_pnl']:.2f}")
        for item in payload["learning"].get("bottom_symbols", []):
            lines.append(f"- Bottom symbol: {item['symbol']} | wins={item['wins']} losses={item['losses']} pnl={item['realized_pnl']:.2f}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _build_learning_snapshot() -> Dict[str, Any]:
        """Build a lightweight behavior-learning snapshot from filled trades.

        The strategy already uses this pattern for symbol scoring. This report
        exposes the learned winners/losers explicitly for operator review.
        """
        session = SessionLocal()
        try:
            rows = (
                session.query(Trade)
                .filter(Trade.status == "FILLED")
                .order_by(Trade.created_at.asc(), Trade.id.asc())
                .all()
            )
        except Exception:
            return {"top_symbols": [], "bottom_symbols": []}
        finally:
            try:
                session.close()
            except Exception:
                pass

        open_lots: Dict[str, List[Dict[str, float]]] = defaultdict(list)
        perf: Dict[str, Dict[str, float]] = defaultdict(lambda: {"realized_pnl": 0.0, "wins": 0.0, "losses": 0.0})

        for row in rows:
            symbol = row.symbol
            side = (row.side or "").upper()
            qty = int(row.quantity or 0)
            price = float(row.price or 0.0)
            if qty <= 0 or price <= 0:
                continue

            if side == "BUY":
                open_lots[symbol].append({"qty": float(qty), "price": price})
                continue

            if side != "SELL":
                continue

            remaining = float(qty)
            pnl = 0.0
            while remaining > 0 and open_lots[symbol]:
                lot = open_lots[symbol][0]
                matched = min(remaining, lot["qty"])
                pnl += (price - lot["price"]) * matched
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 0:
                    open_lots[symbol].pop(0)

            if pnl > 0:
                perf[symbol]["wins"] += 1.0
            elif pnl < 0:
                perf[symbol]["losses"] += 1.0
            perf[symbol]["realized_pnl"] += pnl

        ranked = [
            {"symbol": symbol, **stats}
            for symbol, stats in perf.items()
        ]
        ranked.sort(key=lambda item: item["realized_pnl"], reverse=True)
        return {
            "top_symbols": ranked[:5],
            "bottom_symbols": list(reversed(ranked[-5:])),
        }

    @staticmethod
    def _send_telegram_summary(data: Dict[str, Any], json_path: Path, md_path: Path) -> None:
        summary = data.get("summary", {})
        deepdive = data.get("deepdive", {})
        skip_reasons = data.get("skip_reasons", {})

        top_skips = sorted(skip_reasons.items(), key=lambda item: item[1], reverse=True)[:3]
        skip_text = ", ".join(f"{k}:{v}" for k, v in top_skips) if top_skips else "none"

        msg_lines = [
            f"[Axon][Daily DeepDive] {data.get('date')} ({data.get('mode')})",
            f"Iterations: {summary.get('iterations', 0)}",
            f"Entries F/R: {summary.get('entry_filled', 0)}/{summary.get('entry_rejected', 0)}",
            f"Exits F/R: {summary.get('exit_filled', 0)}/{summary.get('exit_rejected', 0)}",
            f"Realized/Vaulted: {summary.get('realized_pnl', 0.0):.2f}/{summary.get('vaulted_profit', 0.0):.2f}",
            f"Kill-switch: {summary.get('kill_switch_triggers', 0)} | Exceptions: {summary.get('exception_count', 0)}",
            f"Recon breaks: {data.get('reconciliation', {}).get('break_count', 0)}",
            f"Top skip reasons: {skip_text}",
        ]

        good = (deepdive.get("what_went_good") or ["-"])[0]
        bad = (deepdive.get("what_went_bad") or ["-"])[0]
        why = (deepdive.get("why") or ["-"])[0]
        msg_lines.extend(
            [
                f"Good: {good}",
                f"Bad: {bad}",
                f"Why: {why}",
                f"Reports: {json_path.name}, {md_path.name}",
            ]
        )

        try:
            send_telegram_message("\n".join(msg_lines))
        except Exception:
            pass


_daily_deepdive_logger: DailyDeepDiveLogger | None = None


def get_daily_deepdive_logger() -> DailyDeepDiveLogger:
    global _daily_deepdive_logger
    if _daily_deepdive_logger is None:
        _daily_deepdive_logger = DailyDeepDiveLogger()
    return _daily_deepdive_logger


__all__ = ["DailyDeepDiveLogger", "get_daily_deepdive_logger"]
