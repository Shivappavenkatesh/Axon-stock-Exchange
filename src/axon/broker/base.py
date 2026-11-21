"""Broker interface and the order-rate limiter."""

from __future__ import annotations

import threading
import time
from typing import Callable, Protocol

from axon.config import MAX_ORDERS_PER_SECOND_CEILING
from axon.models import OrderIntent, OrderResult, Quote


class Broker(Protocol):
    def place(self, intent: OrderIntent, quote: Quote) -> OrderResult: ...

    def logout(self) -> None: ...


class RateLimiter:
    """At most `per_second` orders per second, never above the compliance ceiling of 2."""

    def __init__(self, per_second: float = MAX_ORDERS_PER_SECOND_CEILING,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.per_second = min(per_second, MAX_ORDERS_PER_SECOND_CEILING)
        self.min_interval = 1.0 / self.per_second
        self._clock = clock
        self._sleep = sleep
        self._last = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                gap = now - self._last
                if gap < self.min_interval:
                    self._sleep(self.min_interval - gap)
                    now = self._clock()
            self._last = now
