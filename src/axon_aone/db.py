"""Database setup and core models for Axon capital engine.

Uses SQLAlchemy with a DATABASE_URL environment variable.
Default is a local PostgreSQL URL; can be overridden for tests
or development (e.g. SQLite).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional


try:
    from datetime import UTC  # Python 3.11+
except ImportError:  # pragma: no cover - Python 3.10 fallback
    UTC = timezone.utc

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Boolean,
    JSON,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

from axon_aone.config import TRADE_MODE


logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv(
    "AXON_DATABASE_URL",
    # Default: local SQLite for development; override via env for PostgreSQL in production.
    "sqlite:///axon.db",
)


def _create_db_engine(database_url: str):
    engine_kwargs = {
        "echo": False,
        "future": True,
        "pool_pre_ping": True,
    }

    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    elif database_url.startswith("postgresql"):
        engine_kwargs["pool_recycle"] = 300
        engine_kwargs["connect_args"] = {"connect_timeout": 5}

    return create_engine(database_url, **engine_kwargs)


engine = _create_db_engine(DATABASE_URL)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

Base = declarative_base()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_db_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(128), index=True, nullable=False)
    symbol = Column(String(64), index=True, nullable=False)
    side = Column(String(8), nullable=False)  # BUY/SELL
    quantity = Column(Integer, nullable=False)
    order_type = Column(String(16), nullable=False)
    price = Column(Float, nullable=True)
    status = Column(String(32), nullable=False)
    trade_mode = Column(String(16), nullable=False)  # mock/live
    broker = Column(String(32), nullable=False, default="angel_one")
    atr = Column(Float, nullable=True)
    reserved_capital = Column(Float, nullable=True)
    opportunity_score = Column(Float, nullable=True)
    broker_response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class SymbolSelection(Base):
    __tablename__ = "symbol_selections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(64), index=True, nullable=False)
    opportunity_score = Column(Float, nullable=False)
    selection_rank = Column(Integer, nullable=False)
    features = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


def _ensure_trade_columns() -> None:
    """Add newly introduced nullable columns to the trades table when needed."""
    inspector = inspect(engine)
    if "trades" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("trades")}
    required_columns = {
        "atr": "ALTER TABLE trades ADD COLUMN atr FLOAT",
        "reserved_capital": "ALTER TABLE trades ADD COLUMN reserved_capital FLOAT",
        "opportunity_score": "ALTER TABLE trades ADD COLUMN opportunity_score FLOAT",
    }

    with engine.begin() as conn:
        for column_name, ddl in required_columns.items():
            if column_name not in existing_columns:
                conn.execute(text(ddl))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_capital = Column(Float, nullable=False)
    current_value = Column(Float, nullable=False)
    cash_available = Column(Float, nullable=False)
    daily_pnl = Column(Float, nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class RegimeHistory(Base):
    __tablename__ = "regime_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    score = Column(Integer, nullable=False)
    mode = Column(String(16), nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class KillSwitchLog(Base):
    __tablename__ = "kill_switch_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reason = Column(String(256), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class Engine(Base):
    __tablename__ = "engines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    description = Column(String(256), nullable=True)
    allocation_target = Column(Float, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class CorrelationMatrix(Base):
    __tablename__ = "correlation_matrix"

    id = Column(Integer, primary_key=True, autoincrement=True)
    as_of = Column(DateTime, default=_utc_now, nullable=False)
    window_minutes = Column(Integer, nullable=True)
    symbols = Column(JSON, nullable=False)
    matrix = Column(JSON, nullable=False)


class CandleBar(Base):
    __tablename__ = "candle_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "broker", "bar_time", name="uq_candle_bar_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(64), index=True, nullable=False)
    interval = Column(String(32), index=True, nullable=False)
    broker = Column(String(32), index=True, nullable=False, default="angel_one")
    bar_time = Column(DateTime, index=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=True)
    vwap = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class StructuralHunter(Base):
    __tablename__ = "structural_hunter"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(64), index=True, nullable=False)
    score = Column(Float, nullable=False)
    revenue_growth = Column(Float, nullable=True)
    allocation = Column(Float, nullable=True)
    thesis = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(128), index=True, nullable=False)
    model_version = Column(String(64), nullable=False)
    stage = Column(String(32), nullable=False, default="research")
    config_hash = Column(String(128), nullable=True)
    metrics = Column(JSON, nullable=True)
    notes = Column(String(1024), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class ModelPromotionEvent(Base):
    __tablename__ = "model_promotion_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(128), index=True, nullable=False)
    model_version = Column(String(64), nullable=False)
    from_stage = Column(String(32), nullable=False)
    to_stage = Column(String(32), nullable=False)
    approved = Column(Boolean, nullable=False, default=False)
    gate_result = Column(JSON, nullable=True)
    decided_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class RiskCommitteeReport(Base):
    __tablename__ = "risk_committee_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    summary = Column(JSON, nullable=False)
    decisions = Column(JSON, nullable=True)
    report_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=_utc_now, nullable=False)


class GlobalState(Base):
    """Single-row table for global runtime flags.

    - trade_mode: "mock" or "live" (default derived from TRADE_MODE)
    - manual_kill: when True, kill switch is forced active across the system.
    """

    __tablename__ = "global_state"

    id = Column(Integer, primary_key=True, autoincrement=False)
    trade_mode = Column(String(16), nullable=False, default="mock")
    manual_kill = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


def _get_or_create_global_state() -> GlobalState:
    """Return the singleton GlobalState row, creating a default if missing."""
    session = SessionLocal()
    try:
        state = session.get(GlobalState, 1)
        if state is None:
            default_mode = "mock" if TRADE_MODE == "PAPER" else "live"
            state = GlobalState(id=1, trade_mode=default_mode, manual_kill=False)
            session.add(state)
            session.commit()
            session.refresh(state)
        return state
    finally:
        session.close()


def is_manual_kill_switch_active() -> bool:
    """Return True if the manual kill switch flag is enabled."""
    try:
        state = _get_or_create_global_state()
        return bool(state.manual_kill)
    except Exception:
        return False


def set_manual_kill_switch(active: bool, reason: Optional[str] = None) -> None:
    """Set the manual kill switch flag and optionally log the change.

    This is used by the Streamlit dashboard to force the kill switch on/off.
    """
    session = SessionLocal()
    try:
        state = session.get(GlobalState, 1)
        if state is None:
            default_mode = "mock" if TRADE_MODE == "PAPER" else "live"
            state = GlobalState(id=1, trade_mode=default_mode, manual_kill=active)
            session.add(state)
        else:
            state.manual_kill = active

        # Best-effort log entry so history shows manual toggles
        log_reason = reason or ("manual_kill_on" if active else "manual_kill_off")
        log_row = KillSwitchLog(reason=log_reason, active=active)
        session.add(log_row)

        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def get_global_trade_mode() -> str:
    """Get the current global trade mode ("mock" or "live")."""
    try:
        state = _get_or_create_global_state()
        mode = (state.trade_mode or "mock").lower()
        return "live" if mode == "live" else "mock"
    except Exception:
        return "mock"


def set_global_trade_mode(mode: str) -> None:
    """Set the global trade mode ("mock" or "live")."""
    normalized = (mode or "").lower()
    if normalized not in {"mock", "live"}:
        return

    session = SessionLocal()
    try:
        state = session.get(GlobalState, 1)
        if state is None:
            state = GlobalState(id=1, trade_mode=normalized, manual_kill=False)
            session.add(state)
        else:
            state.trade_mode = normalized
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def init_db() -> Optional[str]:
    """Create database tables if they do not exist.

    Returns an error string when the database is unavailable so callers can
    degrade gracefully instead of crashing at import time.
    """
    session = None
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_trade_columns()

        # Seed a default engine row if none exists so that the allocation
        # dashboard and future engine logic have a baseline configuration.
        session = SessionLocal()
        existing = session.query(Engine).first()
        if existing is None:
            default_engine = Engine(
                name="trend_engine",
                description="Default single-engine allocation",
                allocation_target=1.0,
                enabled=True,
            )
            session.add(default_engine)
            session.commit()

        # Ensure a GlobalState row exists as well
        state = session.get(GlobalState, 1)
        if state is None:
            default_mode = "mock" if TRADE_MODE == "PAPER" else "live"
            state = GlobalState(id=1, trade_mode=default_mode, manual_kill=False)
            session.add(state)
            session.commit()

        return None
    except Exception as exc:
        logger.warning("Database initialization failed for %s: %s", DATABASE_URL, exc)
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        return _format_db_error(exc)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
