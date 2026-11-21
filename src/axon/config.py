"""All settings in one place. Rules are percentages, R-multiples or shares of liquidity,
never rupee amounts (spec: design principles for scale).

Every value can be overridden with an AXON_* environment variable. Safety ceilings
(order rate, brake levels) can only be made stricter, never looser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from axon.models import Part

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


def _f(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _i(name: str, default: int) -> int:
    return int(_f(name, default))


def _s(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else raw.strip()


def _b(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Hard ceiling from the compliance checklist: never more than 2 orders a second.
# An environment variable may lower this, never raise it.
MAX_ORDERS_PER_SECOND_CEILING = 2.0


@dataclass(frozen=True)
class LiquidityTiers:
    # 20-day median daily traded value, in rupees (spec starting values)
    tier_a_min: float = 50e7   # ₹50 crore
    tier_b_min: float = 5e7    # ₹5 crore
    tier_c_min: float = 50e5   # ₹50 lakh


@dataclass(frozen=True)
class IntradayRules:
    entry_start: str = "09:30"
    entry_end: str = "13:00"
    forced_exit: str = "14:45"
    stop_atr: float = 1.5
    target_atr: float = 2.0
    atr_period: int = 14
    risk_pct: float = 0.25          # % of total capital per trade
    adtv_cap_pct: float = 0.25      # % of the stock's ADTV
    capital_cap_pct: float = 5.0    # % of total capital per position
    max_trades_per_day: int = 3
    daily_loss_stop_pct: float = 1.0  # % of total capital
    max_vix: float = 20.0           # review fix: the spec names India VIX but no level
    pass_test_trades: int = 60
    lucky_days_excluded: int = 3    # result must survive removing the best 3 days


@dataclass(frozen=True)
class Brakes:
    halve_risk_at: float = 8.0
    no_new_entries_at: float = 12.0
    close_satellites_at: float = 15.0


@dataclass(frozen=True)
class CostSchedule:
    """Angel One equity charges. Defaults as understood on 21 Nov 2026; verify against
    Angel One's charges page. The cost ledger replaces estimates with measured figures."""

    brokerage_pct: float = 0.1          # % of order value ...
    brokerage_cap: float = 20.0         # ... capped at ₹20 per executed order ...
    brokerage_min: float = 5.0          # ... with a ₹5 minimum (spec source)
    stt_delivery_pct: float = 0.1       # buy and sell
    stt_intraday_sell_pct: float = 0.025
    exchange_txn_pct_nse: float = 0.00297
    exchange_txn_pct_bse: float = 0.00375
    sebi_fee_pct: float = 0.0001        # ₹10 per crore
    stamp_delivery_buy_pct: float = 0.015
    stamp_intraday_buy_pct: float = 0.003
    gst_pct: float = 18.0               # on brokerage + exchange + SEBI fees
    dp_charge: float = 20.0             # per scrip sold from demat, plus GST
    slippage_pct: float = 0.05          # per side, until 50 measured orders exist
    max_cost_to_risk: float = 0.20      # cost test: round trip <= 20% of planned risk
    measured_after_orders: int = 50


@dataclass(frozen=True)
class TaxRates:
    """Estimated tax counted as a cost in pass tests. Confirm treatment with a CA."""

    intraday_pct: float = 30.0   # speculative income at slab rate; set your own slab
    stcg_pct: float = 20.0
    ltcg_pct: float = 12.5


@dataclass(frozen=True)
class Settings:
    db_path: Path
    capital_split: Dict[Part, float]
    tiers: LiquidityTiers
    intraday: IntradayRules
    brakes: Brakes
    costs: CostSchedule
    tax: TaxRates
    cycle_minutes: int
    stale_after_seconds: int
    max_orders_per_second: float
    one_position_per_stock_across_parts: bool
    restricted_symbols: frozenset
    nifty_token: str
    vix_token: str
    algo_id: str
    static_ip: str
    telegram_token: str
    telegram_chat_id: str
    reports_dir: Path
    universe_file: Path
    holidays_file: Path
    surveillance_file: Path
    extra: dict = field(default_factory=dict)


def load_settings() -> Settings:
    rate = min(_f("AXON_MAX_ORDERS_PER_SECOND", MAX_ORDERS_PER_SECOND_CEILING), MAX_ORDERS_PER_SECOND_CEILING)
    brakes = Brakes(
        halve_risk_at=min(_f("AXON_BRAKE_HALVE_RISK_PCT", 8.0), 8.0),
        no_new_entries_at=min(_f("AXON_BRAKE_NO_ENTRIES_PCT", 12.0), 12.0),
        close_satellites_at=min(_f("AXON_BRAKE_CLOSE_PCT", 15.0), 15.0),
    )
    intraday = IntradayRules(
        max_vix=_f("AXON_INTRADAY_MAX_VIX", 20.0),
        risk_pct=_f("AXON_INTRADAY_RISK_PCT", 0.25),
    )
    restricted = frozenset(
        s.strip().upper() for s in os.getenv("AXON_RESTRICTED_SYMBOLS", "").split(",") if s.strip()
    )
    return Settings(
        db_path=Path(_s("AXON_DB_PATH", "data/axon.sqlite3")),
        capital_split={Part.CORE: 60.0, Part.SWING: 30.0, Part.INTRADAY: 10.0},
        tiers=LiquidityTiers(
            tier_a_min=_f("AXON_TIER_A_MIN", 50e7),
            tier_b_min=_f("AXON_TIER_B_MIN", 5e7),
            tier_c_min=_f("AXON_TIER_C_MIN", 50e5),
        ),
        intraday=intraday,
        brakes=brakes,
        costs=CostSchedule(slippage_pct=_f("AXON_SLIPPAGE_PCT", 0.05)),
        tax=TaxRates(intraday_pct=_f("AXON_TAX_INTRADAY_PCT", 30.0)),
        cycle_minutes=_i("AXON_CYCLE_MINUTES", 5),
        stale_after_seconds=_i("AXON_STALE_AFTER_SECONDS", 600),
        max_orders_per_second=rate,
        one_position_per_stock_across_parts=_b("AXON_ONE_POSITION_ACROSS_PARTS", True),
        restricted_symbols=restricted,
        nifty_token=_s("AXON_NIFTY_TOKEN", "99926000"),
        vix_token=_s("AXON_VIX_TOKEN", "99926017"),
        algo_id=_s("AXON_ALGO_ID", ""),
        static_ip=_s("AXON_STATIC_IP", ""),
        telegram_token=_s("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=_s("TELEGRAM_CHAT_ID", ""),
        reports_dir=Path(_s("AXON_REPORTS_DIR", "reports")),
        universe_file=Path(_s("AXON_UNIVERSE_FILE", str(DATA_DIR / "universe.csv"))),
        holidays_file=Path(_s("AXON_HOLIDAYS_FILE", str(DATA_DIR / "nse_holidays.csv"))),
        surveillance_file=Path(_s("AXON_SURVEILLANCE_FILE", str(DATA_DIR / "surveillance.txt"))),
    )
