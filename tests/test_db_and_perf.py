import math
from sqlalchemy import inspect, text

import pandas as pd
import pytest

try:
    from axon_aone.db import (  # type: ignore
        Base,
        engine,
        SessionLocal,
        init_db,
        PortfolioSnapshot as DbPortfolioSnapshot,
        Engine as DbEngine,
        SymbolSelection as DbSymbolSelection,
    )
    _DB_AVAILABLE = True
except Exception:  # pragma: no cover - if DB deps missing, tests will be skipped
    _DB_AVAILABLE = False


def test_init_db_seeds_default_engine(tmp_path, monkeypatch):
    if not _DB_AVAILABLE:
        pytest.skip("Database dependencies not available; skipping init_db test")
    # Point SQLAlchemy to a temporary SQLite DB for this test
    test_db = tmp_path / "test.db"
    monkeypatch.setenv("AXON_DATABASE_URL", f"sqlite:///{test_db}")

    # Recreate engine and session bound to the new URL
    from importlib import reload
    import axon_aone.db as db_mod

    reload(db_mod)

    db_mod.init_db()

    session = db_mod.SessionLocal()
    try:
        engines = session.query(db_mod.Engine).all()
        assert len(engines) == 1
        eng = engines[0]
        assert eng.name == "trend_engine"
        assert eng.allocation_target == 1.0
        assert eng.enabled is True
    finally:
        session.close()


def test_init_db_backfills_trade_debug_columns(tmp_path, monkeypatch):
    if not _DB_AVAILABLE:
        pytest.skip("Database dependencies not available; skipping init_db test")

    test_db = tmp_path / "legacy.db"
    monkeypatch.setenv("AXON_DATABASE_URL", f"sqlite:///{test_db}")

    from importlib import reload
    import axon_aone.db as db_mod

    reload(db_mod)

    with db_mod.engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id VARCHAR(128) NOT NULL,
                symbol VARCHAR(64) NOT NULL,
                side VARCHAR(8) NOT NULL,
                quantity INTEGER NOT NULL,
                order_type VARCHAR(16) NOT NULL,
                price FLOAT,
                status VARCHAR(32) NOT NULL,
                trade_mode VARCHAR(16) NOT NULL,
                broker VARCHAR(32) NOT NULL,
                broker_response JSON,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))

    db_mod.init_db()

    columns = {column["name"] for column in inspect(db_mod.engine).get_columns("trades")}
    assert "atr" in columns
    assert "reserved_capital" in columns


def test_init_db_creates_symbol_selections_table(tmp_path, monkeypatch):
    if not _DB_AVAILABLE:
        pytest.skip("Database dependencies not available; skipping init_db test")

    test_db = tmp_path / "selection.db"
    monkeypatch.setenv("AXON_DATABASE_URL", f"sqlite:///{test_db}")

    from importlib import reload
    import axon_aone.db as db_mod

    reload(db_mod)
    db_mod.init_db()

    tables = set(inspect(db_mod.engine).get_table_names())
    assert "symbol_selections" in tables


def test_performance_metrics_computable_from_snapshots():
    # Build a simple equity curve DataFrame similar to what the dashboard uses
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    current_values = [100_000, 101_000, 100_500, 102_000, 101_500]
    snaps_df = pd.DataFrame(
        {
            "created_at": dates,
            "total_capital": [100_000] * 5,
            "current_value": current_values,
            "cash_available": [50_000] * 5,
            "daily_pnl": [0, 1_000, -500, 1_500, -500],
        }
    )

    snaps_sorted = snaps_df.sort_values("created_at").copy()
    snaps_sorted["date"] = snaps_sorted["created_at"].dt.date
    daily = snaps_sorted.groupby("date").tail(1).set_index("created_at")

    equity = daily["current_value"].astype(float)
    returns = equity.pct_change().dropna()

    assert not returns.empty
    assert returns.std() > 0

    sharpe = float((returns.mean() / returns.std()) * math.sqrt(252))
    running_max = equity.cummax()
    drawdown_series = equity / running_max - 1.0
    max_drawdown = float(drawdown_series.min())

    # Basic sanity checks on results
    assert math.isfinite(sharpe)
    assert max_drawdown <= 0
