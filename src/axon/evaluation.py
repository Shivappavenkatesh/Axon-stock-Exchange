"""Pass and deletion tests (spec: each part proves its edge after costs and tax)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from axon.ledger import Ledger
from axon.models import Part

REQUIRED_TRADES = {Part.INTRADAY: 60, Part.SWING: 30}
LUCKY_DAYS = {Part.INTRADAY: 3, Part.SWING: 0}


@dataclass(frozen=True)
class PassTest:
    part: Part
    book: str
    trades: int
    required: int
    avg_net: float              # average profit per trade after costs and estimated tax
    avg_net_without_best_days: float
    passed: bool
    reason: str


def pass_test(ledger: Ledger, part: Part, book: str = "paper") -> PassTest:
    closed = ledger.closed_positions(book, part)
    required = REQUIRED_TRADES.get(part, 30)
    nets, by_day = [], defaultdict(list)
    for p in closed:
        net = (p["realized_pnl"] or 0.0) - ledger.tax_for_position(p["id"])
        nets.append(net)
        by_day[(p["exit_ts"] or "")[:10]].append(net)
    n = len(nets)
    avg = sum(nets) / n if n else 0.0
    drop = LUCKY_DAYS.get(part, 0)
    best_days = sorted(by_day, key=lambda d: sum(by_day[d]), reverse=True)[:drop]
    rest = [v for d, vals in by_day.items() if d not in best_days for v in vals]
    avg_rest = sum(rest) / len(rest) if rest else 0.0
    if n < required:
        return PassTest(part, book, n, required, avg, avg_rest, False, f"{n} of {required} trades so far")
    if avg <= 0:
        return PassTest(part, book, n, required, avg, avg_rest, False, "average profit per trade after costs is not positive")
    if drop and avg_rest <= 0:
        return PassTest(part, book, n, required, avg, avg_rest, False,
                        f"profit depends on the best {drop} days")
    return PassTest(part, book, n, required, avg, avg_rest, True, "passed")
