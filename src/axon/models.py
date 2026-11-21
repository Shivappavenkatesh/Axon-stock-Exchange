"""Shared data types. Plain dataclasses so every layer speaks the same language."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Part(str, Enum):
    CORE = "core"
    SWING = "swing"
    INTRADAY = "intraday"


# Parts that are built and allowed to trade. Core and swing come in the next phase.
IMPLEMENTED_PARTS = {Part.INTRADAY}


class Mode(str, Enum):
    """How a part trades.

    OFF     - does nothing.
    TEST    - random prices, simulated orders. Development only; can never go live.
    PAPER   - real prices from the broker, simulated orders with the full cost model.
              This is what probation and pass tests are measured on.
    LIVE    - real prices, real orders.
    """

    OFF = "off"
    TEST = "test"
    PAPER = "paper"
    LIVE = "live"

    @property
    def book(self) -> str:
        """Each mode keeps its own money book, so paper results never mix with real money."""
        return self.value


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Product(str, Enum):
    INTRADAY = "INTRADAY"  # Angel One MIS
    DELIVERY = "DELIVERY"  # Angel One CNC


PRODUCT_FOR_PART = {
    Part.INTRADAY: Product.INTRADAY,
    Part.SWING: Product.DELIVERY,
    Part.CORE: Product.DELIVERY,
}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    token: str
    exchange: str = "NSE"
    sector: str = ""


@dataclass(frozen=True)
class Candle:
    start: datetime  # candle start time (IST, timezone-aware)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    ts: datetime  # when the price was observed (IST, timezone-aware)
    upper_circuit: Optional[float] = None
    lower_circuit: Optional[float] = None


@dataclass
class Signal:
    """A strategy's wish to enter. Sizing and approval happen later in the risk engine."""

    part: Part
    instrument: Instrument
    price: float
    stop: float
    target: Optional[float]
    score: float
    reason: str


@dataclass
class ExitRequest:
    position_id: int
    reason: str


@dataclass
class OrderIntent:
    part: Part
    mode: Mode
    instrument: Instrument
    side: Side
    quantity: int
    reference_price: float  # price used for sizing / slippage measurement
    order_type: str = "MARKET"
    limit_price: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    reason: str = ""
    position_id: Optional[int] = None  # set for exits

    @property
    def product(self) -> Product:
        return PRODUCT_FOR_PART[self.part]


@dataclass
class OrderResult:
    ok: bool
    status: str  # FILLED, REJECTED, PENDING, ERROR
    broker_order_id: str = ""
    fill_price: float = 0.0
    filled_quantity: int = 0
    message: str = ""
    charges: float = 0.0


@dataclass
class Position:
    id: int
    book: str
    part: Part
    symbol: str
    token: str
    exchange: str
    quantity: int
    entry_price: float
    entry_ts: datetime
    stop: Optional[float]
    target: Optional[float]
    entry_costs: float = 0.0
    last_price: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def market_value(self) -> float:
        return self.quantity * (self.last_price or self.entry_price)

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * ((self.last_price or self.entry_price) - self.entry_price)
