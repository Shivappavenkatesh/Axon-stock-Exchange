"""Telegram alerts. Every alert is also stored in the ledger; a dedupe key stops repeats."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

log = logging.getLogger(__name__)


class Alerter:
    def __init__(self, ledger, token: str = "", chat_id: str = "",
                 sender: Optional[Callable[[str], None]] = None):
        self.ledger = ledger
        self.token = token
        self.chat_id = chat_id
        self._sender = sender

    def send(self, message: str, now: datetime, key: Optional[str] = None) -> bool:
        """Store and send. Returns False if the same key was already sent."""
        if not self.ledger.record_alert(now, message, key):
            return False
        log.warning("ALERT: %s", message)
        try:
            if self._sender is not None:
                self._sender(message)
            elif self.token and self.chat_id:
                import requests

                requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                              json={"chat_id": self.chat_id, "text": message}, timeout=10)
        except Exception as exc:  # noqa: BLE001 - alerts must never stop trading logic
            log.error("Telegram send failed: %s", exc)
        return True
