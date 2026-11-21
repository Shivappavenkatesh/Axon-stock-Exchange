"""Daily report built from the ledger (finding 10): fills, P&L by part, costs against
expected, brakes fired, data checks, halts and alerts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List

from axon.ledger import Ledger


def build_daily_report(ledger: Ledger, day: date) -> Dict:
    orders = ledger.orders(day=day)
    fills = [o for o in orders if o["status"] == "FILLED"]
    not_filled = [o for o in orders if o["status"] != "FILLED"]
    pnl: Dict[str, float] = defaultdict(float)
    for p in ledger.closed_positions(day=day):
        pnl[f"{p['book']}:{p['part']}"] += p["realized_pnl"] or 0.0
    open_pnl: Dict[str, float] = defaultdict(float)
    for p in ledger.open_positions():
        open_pnl[f"{p.book}:{p.part.value}"] += p.unrealized_pnl
    expected = sum(o["expected_cost"] or 0.0 for o in fills)
    actual = sum(o["actual_cost"] or 0.0 for o in fills)
    halts = [e for e in ledger.events() if e["ts"][:10] == day.isoformat()]
    return {
        "day": day.isoformat(),
        "fills": fills,
        "not_filled": not_filled,
        "realized_pnl": dict(pnl),
        "unrealized_pnl": dict(open_pnl),
        "costs_expected": expected,
        "costs_actual": actual,
        "brakes": ledger.brake_events(day=day),
        "data_problems": ledger.data_checks(day),
        "events": halts,
    }


def render_markdown(report: Dict) -> str:
    lines: List[str] = [f"# Axon daily report — {report['day']}", ""]
    lines.append(f"## Fills ({len(report['fills'])})")
    if report["fills"]:
        lines.append("| Time | Book | Part | Side | Qty | Symbol | Price | Reason |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for o in report["fills"]:
            lines.append(f"| {o['ts'][11:16]} | {o['book']} | {o['part']} | {o['side']} | {o['filled_quantity']} | "
                         f"{o['symbol']} | {o['fill_price']:.2f} | {o['reason'] or ''} |")
    else:
        lines.append("No fills.")
    if report["not_filled"]:
        lines += ["", f"Orders not filled: {len(report['not_filled'])}"]
    lines += ["", "## Profit and loss by part"]
    keys = sorted(set(report["realized_pnl"]) | set(report["unrealized_pnl"]))
    if keys:
        for k in keys:
            lines.append(f"- {k}: realised {report['realized_pnl'].get(k, 0.0):+.2f}, "
                         f"open {report['unrealized_pnl'].get(k, 0.0):+.2f}")
    else:
        lines.append("No trading.")
    lines += ["", "## Costs",
              f"- Expected {report['costs_expected']:.2f}, actual {report['costs_actual']:.2f}"]
    lines += ["", f"## Brakes fired ({len(report['brakes'])})"]
    lines += [f"- {b['ts'][11:16]} {b['book']}: level {b['level']:.0f}% (drawdown {b['drawdown_pct']:.1f}%)"
              for b in report["brakes"]] or ["None."]
    lines += ["", f"## Data checks failed ({len(report['data_problems'])})"]
    lines += [f"- {d['ts'][11:16]} {d['symbol']}: {d['check_name']} — {d['detail']}"
              for d in report["data_problems"][:50]] or ["None."]
    lines += ["", "## Events"]
    lines += [f"- {e['ts'][11:16]} {e['kind']}: {e['detail']}" for e in report["events"][:50]] or ["None."]
    return "\n".join(lines) + "\n"


def write_daily_report(ledger: Ledger, day: date, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{day.isoformat()}.md"
    path.write_text(render_markdown(build_daily_report(ledger, day)), encoding="utf-8")
    return path
