"""Per-part mode changes (finding 11). The only way to change a mode: logged, announced,
and stored in the ledger so a restart keeps it. There is no startup flag."""

from __future__ import annotations

from datetime import datetime

from axon.alerts import Alerter
from axon.config import Settings
from axon.evaluation import pass_test
from axon.ledger import Ledger
from axon.models import IMPLEMENTED_PARTS, Mode, Part


class ModeChangeRefused(Exception):
    pass


def live_confirmation_text(part: Part) -> str:
    return f"LIVE {part.value}"


def change_mode(*, ledger: Ledger, alerter: Alerter, settings: Settings, part: Part, new_mode: Mode,
                actor: str, now: datetime, confirm: str = "") -> Mode:
    old = ledger.get_mode(part)
    if new_mode == old:
        return old
    if new_mode is not Mode.OFF and part not in IMPLEMENTED_PARTS:
        raise ModeChangeRefused(f"{part.value} is not built yet; it can only be OFF")
    open_in_old_book = ledger.open_positions(old.book, part) if old is not Mode.OFF else []
    if open_in_old_book:
        raise ModeChangeRefused(
            f"{part.value} has {len(open_in_old_book)} open position(s) in {old.value} mode; close them first")
    if new_mode is Mode.LIVE:
        if old is Mode.TEST:
            raise ModeChangeRefused("TEST mode uses random prices and can never go straight to LIVE; use PAPER first")
        if confirm.strip() != live_confirmation_text(part):
            raise ModeChangeRefused(f"type '{live_confirmation_text(part)}' to confirm")
        if not settings.static_ip:
            raise ModeChangeRefused("set AXON_STATIC_IP (the IP registered with Angel One) before going live")
        result = pass_test(ledger, part, Mode.PAPER.book)
        if not result.passed:
            raise ModeChangeRefused(f"{part.value} has not passed its paper test: {result.reason}")
    ledger.set_mode(part, new_mode, now, actor)
    alerter.send(f"Mode change: {part.value} {old.value.upper()} -> {new_mode.value.upper()} (by {actor})", now)
    return old
