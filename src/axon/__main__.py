"""Command line.

  python -m axon run                     trading scheduler (the only process that trades)
  python -m axon web                     dashboard on 127.0.0.1:8080 (login required)
  python -m axon health                  exit 1 if the trading loop has stopped
  python -m axon status                  modes, money, brakes
  python -m axon cycle                   run one trading cycle now (testing)
  python -m axon deposit BOOK AMOUNT     record money in (BOOK = test, paper or live)
  python -m axon withdraw BOOK AMOUNT    record money out
  python -m axon mode PART MODE [--confirm "LIVE intraday"]
  python -m axon kill-switch on|off
  python -m axon report [YYYY-MM-DD]
  python -m axon income BOOK YYYY-MM [--record]
  python -m axon hash-password           make AXON_WEB_PASSWORD_HASH
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from datetime import date

from axon.clock import now_ist


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="axon")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("web")
    sub.add_parser("health")
    sub.add_parser("status")
    sub.add_parser("cycle")
    sub.add_parser("hash-password")
    for name in ("deposit", "withdraw"):
        sp = sub.add_parser(name)
        sp.add_argument("book", choices=["test", "paper", "live"])
        sp.add_argument("amount", type=float)
    sp = sub.add_parser("mode")
    sp.add_argument("part", choices=["core", "swing", "intraday"])
    sp.add_argument("mode", choices=["off", "test", "paper", "live"])
    sp.add_argument("--confirm", default="")
    sp = sub.add_parser("kill-switch")
    sp.add_argument("state", choices=["on", "off"])
    sp = sub.add_parser("report")
    sp.add_argument("day", nargs="?")
    sp = sub.add_parser("income")
    sp.add_argument("book", choices=["test", "paper", "live"])
    sp.add_argument("month")
    sp.add_argument("--record", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "hash-password":
        from werkzeug.security import generate_password_hash

        print(generate_password_hash(getpass.getpass("New dashboard password: ")))
        return 0
    if args.cmd == "web":
        from axon.web.app import main as web_main

        web_main()
        return 0

    from axon.context import build

    axon = build()
    now = now_ist()
    if args.cmd == "run":
        from axon.scheduler import Scheduler

        Scheduler(axon).run_forever()
        return 0
    if args.cmd == "health":
        from axon.health import check

        ok, msg = check(axon.ledger, axon.calendar, now)
        print(msg)
        return 0 if ok else 1
    if args.cmd == "status":
        from axon.risk import RiskEngine

        risk = RiskEngine(axon.settings, axon.ledger)
        out = {"modes": {k.value: v.value for k, v in axon.ledger.modes().items()},
               "kill_switch": bool(axon.ledger.kill_switch().get("active")),
               "books": {b: {"value": round(axon.ledger.nav(b), 2), "brakes": risk.current_brakes(b).describe()}
                         for b in ("test", "paper", "live")}}
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "cycle":
        result = axon.engine.run_cycle(now)
        print(json.dumps(result, default=lambda o: o.__dict__, indent=2))
        return 0
    if args.cmd in {"deposit", "withdraw"}:
        kind = "deposit" if args.cmd == "deposit" else "withdrawal"
        r = axon.ledger.record_cash_flow(args.book, kind, args.amount, now, note="cli")
        print(f"{kind} of {args.amount:,.2f} recorded in {args.book} at {r['nav_per_unit']:.4f} per unit")
        return 0
    if args.cmd == "mode":
        from axon.models import Mode, Part
        from axon.modes import ModeChangeRefused, change_mode

        try:
            old = change_mode(ledger=axon.ledger, alerter=axon.alerter, settings=axon.settings,
                              part=Part(args.part), new_mode=Mode(args.mode), actor=f"cli:{getpass.getuser()}",
                              now=now, confirm=args.confirm)
        except ModeChangeRefused as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
        print(f"{args.part}: {old.value} -> {args.mode}")
        return 0
    if args.cmd == "kill-switch":
        axon.ledger.set_kill_switch(args.state == "on", now, f"cli:{getpass.getuser()}")
        axon.alerter.send(f"Kill switch {args.state.upper()} (cli)", now)
        print(f"kill switch {args.state}")
        return 0
    if args.cmd == "report":
        from axon.report import write_daily_report

        day = date.fromisoformat(args.day) if args.day else now.date()
        print(write_daily_report(axon.ledger, day, axon.settings.reports_dir))
        return 0
    if args.cmd == "income":
        from axon.income import month_end_income

        d = month_end_income(axon.ledger, args.book, args.month)
        print(json.dumps(d.__dict__, indent=2))
        if args.record and d.payout > 0:
            axon.ledger.record_cash_flow(args.book, "payout", d.payout, now, note=f"income {args.month}")
            print(f"payout of {d.payout:,.2f} recorded")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
