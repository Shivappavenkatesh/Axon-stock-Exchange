"""Axon Capital Engine Dashboard (Streamlit).

Run with:
    streamlit run dashboard/app.py

This dashboard reads from the PostgreSQL database configured via
AXON_DATABASE_URL and visualises trades, equity snapshots,
regime history, and kill-switch events.
"""

from __future__ import annotations

import logging
import os
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import streamlit as st

# Ensure src/ is on sys.path so `axon_aone` imports work
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from axon_aone.db import (
    SessionLocal,
    Trade,
    SymbolSelection,
    PortfolioSnapshot,
    RegimeHistory,
    KillSwitchLog,
    Engine,
    CorrelationMatrix,
    CandleBar,
    ModelRegistryEntry,
    ModelPromotionEvent,
    init_db,
    is_manual_kill_switch_active,
    set_manual_kill_switch,
    get_global_trade_mode,
    set_global_trade_mode,
)  # type: ignore
from axon_aone.portfolio.allocation import AllocationEngine  # type: ignore
from axon_aone.services.model_registry import register_model, review_model_promotion  # type: ignore
from axon_aone.config import ALGO_RUN_INTERVAL, MAX_DAILY_LOSS, MAX_WEEKLY_DRAWDOWN, VAR_DAILY_95_LIMIT  # type: ignore


logger = logging.getLogger(__name__)

st.set_page_config(page_title="Axon Capital Engine", layout="wide")


def apply_dashboard_theme() -> None:
    """Apply a premium dashboard theme with clear visual hierarchy."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap');
        :root {
            --bg-1: #050913;
            --bg-2: #0a1220;
            --panel: #0f1b2b;
            --panel-soft: #16263a;
            --line: #1e334a;
            --txt-1: #e6f3ff;
            --txt-2: #8ca8c2;
            --good: #1fe08f;
            --warn: #f4bf5a;
            --bad: #ff5f73;
            --accent: #3ec8ff;
        }
        html, body, [class*="css"]  {
            font-family: 'Manrope', sans-serif;
        }
        .stApp {
            background: radial-gradient(circle at top left, #16283f 0%, var(--bg-2) 34%, var(--bg-1) 100%);
            color: var(--txt-1);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0d1a2a 0%, #070f1a 100%);
            border-right: 1px solid #1a2e43;
        }
        [data-testid="stSidebar"] * {
            color: #d6e6f6;
        }
        [data-testid="stMetricValue"] {
            color: var(--txt-1);
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--line);
            border-radius: 12px;
            overflow: hidden;
        }
        .hero-wrap {
            padding: 1.1rem 1.2rem;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: linear-gradient(120deg, #112e4e 0%, #0d2237 58%, #081523 100%);
            color: var(--txt-1);
            margin-bottom: 0.8rem;
            box-shadow: 0 10px 25px rgba(3, 12, 20, 0.35);
        }
        .hero-wrap h1 {
            font-size: 1.45rem;
            margin: 0;
            font-weight: 700;
            letter-spacing: 0.2px;
        }
        .hero-wrap p {
            margin: 0.35rem 0 0 0;
            font-size: 0.92rem;
            color: var(--txt-2);
        }
        .ribbon {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin: 0.5rem 0 0.8rem 0;
        }
        .chip {
            padding: 0.35rem 0.6rem;
            border-radius: 999px;
            font-size: 0.75rem;
            border: 1px solid var(--line);
            color: var(--txt-2);
            background: rgba(10, 24, 39, 0.78);
        }
        .kpi-card {
            border-radius: 12px;
            border: 1px solid var(--line);
            background: linear-gradient(165deg, var(--panel) 0%, #102236 100%);
            padding: 0.7rem 0.85rem;
            box-shadow: 0 3px 14px rgba(2, 12, 24, 0.28);
            min-height: 95px;
        }
        .kpi-label {
            color: var(--txt-2);
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
        }
        .kpi-value {
            color: var(--txt-1);
            font-size: 1.38rem;
            font-weight: 700;
            margin-top: 0.2rem;
            line-height: 1.12;
        }
        .kpi-delta {
            color: #88b6de;
            font-size: 0.76rem;
            margin-top: 0.2rem;
        }
        .section-note {
            color: var(--txt-2);
            font-size: 0.88rem;
            margin-top: -0.35rem;
            margin-bottom: 0.45rem;
        }
        .terminal-shell {
            border: 1px solid var(--line);
            border-radius: 16px;
            background: linear-gradient(180deg, #0c1624 0%, #070f1a 100%);
            box-shadow: 0 10px 28px rgba(2, 10, 18, 0.35);
            padding: 0.55rem 0.8rem 0.95rem 0.8rem;
            margin-bottom: 0.9rem;
            animation: fadeInUp 0.45s ease-out;
        }
        .terminal-toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border: 1px solid #183046;
            border-radius: 10px;
            background: #050d18;
            padding: 0.35rem 0.6rem;
            color: #9eb5ca;
            font-size: 0.78rem;
        }
        .toolbar-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 4px;
        }
        .dot-red { background: #ff5f57; }
        .dot-yellow { background: #febc2e; }
        .dot-green { background: #2aca44; }
        .address-pill {
            border: 1px solid #1f3b54;
            border-radius: 999px;
            padding: 0.12rem 0.55rem;
            background: #0b1622;
            color: #8ea9c3;
            font-size: 0.72rem;
        }
        .terminal-nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 0.5rem;
            padding: 0.35rem 0.2rem;
            border-bottom: 1px solid #1a2a3c;
        }
        .brand {
            color: #e9f2fb;
            font-weight: 700;
            font-size: 1rem;
        }
        .menu {
            color: #92aac2;
            font-size: 0.74rem;
            letter-spacing: 0.03em;
        }
        .menu span { margin-right: 0.7rem; }
        .menu span:last-child { margin-right: 0; }
        .menu span.active {
            color: #e8f3ff;
            border-bottom: 2px solid #3ec8ff;
            padding-bottom: 0.12rem;
        }
        .terminal-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.45rem;
            margin-top: 0.65rem;
        }
        .market-tile {
            border: 1px solid #183349;
            border-radius: 10px;
            padding: 0.5rem 0.55rem;
            background: linear-gradient(180deg, #0f1c2c 0%, #091421 100%);
        }
        .tile-name { color: #89a4c0; font-size: 0.68rem; text-transform: uppercase; }
        .tile-value { color: #f1f7ff; font-size: 1.02rem; font-weight: 700; margin-top: 0.25rem; }
        .tile-delta { color: var(--good); font-size: 0.7rem; margin-top: 0.18rem; }
        .range-pills {
            margin-top: 0.45rem;
            display: flex;
            gap: 0.4rem;
            flex-wrap: wrap;
        }
        .pill {
            font-size: 0.7rem;
            color: #9bb3c9;
            border: 1px solid #234059;
            border-radius: 8px;
            background: #0f1e2f;
            padding: 0.18rem 0.45rem;
        }
        .pill.active {
            color: #e9f3ff;
            border-color: #3f83b3;
            background: #1b3044;
        }
        .ticker-row {
            margin-top: 0.45rem;
            border: 1px solid #173149;
            border-radius: 10px;
            padding: 0.35rem 0.5rem;
            color: #8eabc8;
            font-size: 0.72rem;
            white-space: nowrap;
            overflow-x: auto;
        }
        .ticker-row span { margin-right: 1.1rem; }
        .shell-panel-title {
            color: #d9e9f8;
            font-size: 0.85rem;
            font-weight: 700;
            margin: 0.35rem 0;
        }
        .watch-card {
            border: 1px solid #1d3a53;
            border-radius: 10px;
            padding: 0.45rem 0.55rem;
            background: #0d1a2a;
            margin-bottom: 0.45rem;
        }
        .watch-card .name { color: #c8daee; font-size: 0.74rem; }
        .watch-card .px { color: #f0f7ff; font-size: 0.95rem; font-weight: 700; }
        .watch-card .spark { color: #76d1ff; font-size: 0.66rem; letter-spacing: 0.05em; }
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_money(value: float) -> str:
    return f"{value:,.0f}"


def _fmt_bps(value: float) -> str:
    return f"{value:.1f} bps"


def _coerce_datetime(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df.empty or col not in df.columns:
        return df
    out = df.copy()
    out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def _date_bounds(*datasets: tuple[pd.DataFrame, str]) -> tuple[date, date] | tuple[None, None]:
    dates: list[date] = []
    for df, col in datasets:
        if df.empty or col not in df.columns:
            continue
        series = pd.to_datetime(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        dates.extend(series.dt.date.tolist())
    if not dates:
        return None, None
    return min(dates), max(dates)


def _normalize_date_range(value: object) -> tuple[date, date] | tuple[None, None]:
    if value is None:
        return None, None
    if isinstance(value, tuple):
        values = list(value)
    elif isinstance(value, list):
        values = value
    else:
        values = [value]

    cleaned: list[date] = []
    for item in values:
        if isinstance(item, datetime):
            cleaned.append(item.date())
        elif isinstance(item, date):
            cleaned.append(item)

    if not cleaned:
        return None, None
    if len(cleaned) == 1:
        return cleaned[0], cleaned[0]
    return min(cleaned[0], cleaned[-1]), max(cleaned[0], cleaned[-1])


def _filter_by_date_range(df: pd.DataFrame, ts_col: str, start_date: date | None, end_date: date | None) -> pd.DataFrame:
    if df.empty or ts_col not in df.columns or start_date is None or end_date is None:
        return df
    series = pd.to_datetime(df[ts_col], errors="coerce")
    mask = series.notna() & (series.dt.date >= start_date) & (series.dt.date <= end_date)
    return df.loc[mask].copy()


def _resolve_date_preset_range(preset: str, min_date: date, max_date: date) -> tuple[date, date]:
    anchor = max_date
    normalized = str(preset or "Today").strip().lower()

    if normalized == "yesterday":
        start = max(min_date, anchor - timedelta(days=1))
        return start, start
    if normalized == "last 7 days":
        start = max(min_date, anchor - timedelta(days=6))
        return start, anchor
    if normalized == "this month":
        month_start = anchor.replace(day=1)
        start = max(min_date, month_start)
        return start, anchor

    return anchor, anchor


def compute_dashboard_kpis(
    trades_df: pd.DataFrame,
    snaps_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    kill_df: pd.DataFrame,
    models_df: pd.DataFrame,
    promotion_events_df: pd.DataFrame,
) -> dict:
    """Compute CEO-level and analyst-level KPI snapshot."""
    kpis = {
        "total_trades": 0,
        "filled_trades": 0,
        "rejected_trades": 0,
        "buy_trades": 0,
        "sell_trades": 0,
        "buy_notional": 0.0,
        "sell_notional": 0.0,
        "turnover_notional": 0.0,
        "avg_order_qty": float("nan"),
        "avg_notional_per_trade": float("nan"),
        "net_qty": 0,
        "unique_symbols": 0,
        "top_symbol_share": float("nan"),
        "mode_live_ratio": float("nan"),
        "mode_mock_ratio": float("nan"),
        "status_success_ratio": float("nan"),
        "trades_per_day": float("nan"),
        "last_trade_age_min": float("nan"),
        "trade_interval_min": float("nan"),
        "snapshot_interval_min": float("nan"),
        "fill_ratio": 0.0,
        "rejection_ratio": 0.0,
        "realized_pnl": 0.0,
        "equity": float("nan"),
        "cash_available": float("nan"),
        "daily_pnl": float("nan"),
        "daily_loss_utilization": float("nan"),
        "sharpe": float("nan"),
        "max_drawdown": float("nan"),
        "weekly_drawdown_utilization": float("nan"),
        "daily_var_95": float("nan"),
        "regime_score": None,
        "regime_mode": None,
        "kill_events": 0,
        "active_models": 0,
        "promotion_approval_rate": float("nan"),
    }

    if not trades_df.empty:
        trades = trades_df.copy()
        trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce").fillna(0.0)
        trades["price"] = pd.to_numeric(trades["price"], errors="coerce").fillna(0.0)
        trades["notional"] = trades["quantity"] * trades["price"]

        kpis["total_trades"] = int(len(trades_df))
        filled = int((trades_df["status"] == "FILLED").sum())
        rejected = int((trades_df["status"] == "REJECTED").sum())
        kpis["filled_trades"] = filled
        kpis["rejected_trades"] = rejected
        kpis["fill_ratio"] = filled / max(1, len(trades_df))
        kpis["rejection_ratio"] = rejected / max(1, len(trades_df))
        kpis["status_success_ratio"] = filled / max(1, len(trades_df))

        buy_df = trades[trades["side"] == "BUY"]
        sell_df = trades[trades["side"] == "SELL"]
        kpis["buy_trades"] = int(len(buy_df))
        kpis["sell_trades"] = int(len(sell_df))
        kpis["buy_notional"] = float(buy_df["notional"].sum())
        kpis["sell_notional"] = float(sell_df["notional"].sum())
        kpis["turnover_notional"] = float(trades["notional"].abs().sum())
        kpis["avg_order_qty"] = float(trades["quantity"].mean()) if len(trades) else float("nan")
        kpis["avg_notional_per_trade"] = float(trades["notional"].mean()) if len(trades) else float("nan")
        kpis["net_qty"] = int(buy_df["quantity"].sum() - sell_df["quantity"].sum())

        if "symbol" in trades.columns:
            kpis["unique_symbols"] = int(trades["symbol"].nunique())
            symbol_counts = trades["symbol"].value_counts()
            if not symbol_counts.empty:
                kpis["top_symbol_share"] = float(symbol_counts.iloc[0] / max(1, len(trades)))

        if "trade_mode" in trades.columns:
            mode_counts = trades["trade_mode"].astype(str).str.lower().value_counts()
            kpis["mode_live_ratio"] = float(mode_counts.get("live", 0) / max(1, len(trades)))
            kpis["mode_mock_ratio"] = float(mode_counts.get("mock", 0) / max(1, len(trades)))

        if "created_at" in trades.columns and trades["created_at"].notna().any():
            dates = trades["created_at"].dt.date
            active_days = max(1, int(dates.nunique()))
            kpis["trades_per_day"] = float(len(trades) / active_days)

            latest_trade = trades["created_at"].max()
            now_ts = pd.Timestamp.utcnow()
            if latest_trade.tzinfo is None:
                latest_trade = latest_trade.tz_localize("UTC")
            kpis["last_trade_age_min"] = float((now_ts - latest_trade).total_seconds() / 60.0)

            sorted_ts = trades["created_at"].dropna().sort_values()
            if len(sorted_ts) >= 2:
                deltas_min = sorted_ts.diff().dropna().dt.total_seconds() / 60.0
                if not deltas_min.empty:
                    kpis["trade_interval_min"] = float(deltas_min.median())

        kpis["realized_pnl"] = float((sell_df["price"].fillna(0).sum()) - (buy_df["price"].fillna(0).sum()))

    if not snaps_df.empty:
        snaps_sorted = snaps_df.sort_values("created_at").copy()
        kpis["equity"] = float(snaps_sorted.iloc[-1]["current_value"])
        kpis["cash_available"] = float(snaps_sorted.iloc[-1]["cash_available"])
        kpis["daily_pnl"] = float(snaps_sorted.iloc[-1]["daily_pnl"])

        if kpis["equity"] and kpis["daily_pnl"] < 0:
            daily_loss_frac = abs(kpis["daily_pnl"]) / max(1.0, abs(kpis["equity"]))
            if MAX_DAILY_LOSS > 0:
                kpis["daily_loss_utilization"] = float(daily_loss_frac / MAX_DAILY_LOSS)

        snaps_sorted["date"] = snaps_sorted["created_at"].dt.date
        daily = snaps_sorted.groupby("date").tail(1).set_index("created_at")
        equity = daily["current_value"].astype(float)
        returns = equity.pct_change().dropna()
        if not returns.empty and returns.std() > 0:
            kpis["sharpe"] = float((returns.mean() / returns.std()) * np.sqrt(252))
            kpis["daily_var_95"] = float(max(0.0, -np.quantile(returns, 0.05)))
        running_max = equity.cummax()
        drawdown = equity / running_max - 1.0
        if not drawdown.empty:
            kpis["max_drawdown"] = float(drawdown.min())
            if MAX_WEEKLY_DRAWDOWN > 0:
                kpis["weekly_drawdown_utilization"] = float(abs(kpis["max_drawdown"]) / MAX_WEEKLY_DRAWDOWN)

        sorted_snap_ts = snaps_sorted["created_at"].dropna().sort_values()
        if len(sorted_snap_ts) >= 2:
            snap_deltas_min = sorted_snap_ts.diff().dropna().dt.total_seconds() / 60.0
            if not snap_deltas_min.empty:
                kpis["snapshot_interval_min"] = float(snap_deltas_min.median())

    if not regime_df.empty:
        latest = regime_df.iloc[-1]
        kpis["regime_score"] = int(latest["score"])
        kpis["regime_mode"] = str(latest["mode"])

    if not kill_df.empty:
        kpis["kill_events"] = int(len(kill_df))

    if not models_df.empty:
        kpis["active_models"] = int(models_df["active"].fillna(False).sum())

    if not promotion_events_df.empty:
        approved = int(promotion_events_df["approved"].fillna(False).sum())
        kpis["promotion_approval_rate"] = approved / max(1, len(promotion_events_df))

    return kpis


def render_kpi_card(label: str, value: str, delta: str = "") -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-delta">{delta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _latest_reference_ts(trades_df: pd.DataFrame, snaps_df: pd.DataFrame) -> datetime | None:
    candidates = []
    if not trades_df.empty and "created_at" in trades_df.columns and trades_df["created_at"].notna().any():
        candidates.append(trades_df["created_at"].max())
    if not snaps_df.empty and "created_at" in snaps_df.columns and snaps_df["created_at"].notna().any():
        candidates.append(snaps_df["created_at"].max())
    if not candidates:
        return None
    return max(candidates)


def _windowed(df: pd.DataFrame, ts_col: str, ref_ts: datetime, days: int) -> pd.DataFrame:
    if df.empty or ts_col not in df.columns:
        return df
    if days <= 1:
        return df[df[ts_col].dt.date == ref_ts.date()]
    start = ref_ts - timedelta(days=days - 1)
    return df[df[ts_col] >= start]


def build_period_kpis(
    trades_df: pd.DataFrame,
    snaps_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    kill_df: pd.DataFrame,
    models_df: pd.DataFrame,
    promotion_events_df: pd.DataFrame,
) -> dict:
    ref_ts = _latest_reference_ts(trades_df, snaps_df)
    periods = {"Today": 1, "30D": 30, "90D": 90}
    out: dict[str, dict] = {}
    if ref_ts is None:
        return out

    for label, days in periods.items():
        p_trades = _windowed(trades_df, "created_at", ref_ts, days)
        p_snaps = _windowed(snaps_df, "created_at", ref_ts, days)
        p_regime = _windowed(regime_df, "created_at", ref_ts, days)
        p_kill = _windowed(kill_df, "created_at", ref_ts, days)
        p_prom = _windowed(promotion_events_df, "created_at", ref_ts, days)
        out[label] = compute_dashboard_kpis(
            trades_df=p_trades,
            snaps_df=p_snaps,
            regime_df=p_regime,
            kill_df=p_kill,
            models_df=models_df,
            promotion_events_df=p_prom,
        )
    return out


def build_alerts(kpis: dict) -> list[tuple[str, str]]:
    alerts: list[tuple[str, str]] = []

    rej = float(kpis.get("rejection_ratio", 0.0) or 0.0)
    if rej >= 0.25:
        alerts.append(("red", f"Rejection ratio critical: {_fmt_pct(rej)} (threshold 25%)"))
    elif rej >= 0.12:
        alerts.append(("amber", f"Rejection ratio elevated: {_fmt_pct(rej)} (watch above 12%)"))

    mdd = kpis.get("max_drawdown")
    if isinstance(mdd, (int, float)) and not np.isnan(mdd):
        if mdd <= -0.12:
            alerts.append(("red", f"Drawdown critical: {_fmt_pct(mdd)} (limit -12%)"))
        elif mdd <= -0.08:
            alerts.append(("amber", f"Drawdown warning: {_fmt_pct(mdd)} (watch below -8%)"))

    sharpe = kpis.get("sharpe")
    if isinstance(sharpe, (int, float)) and not np.isnan(sharpe):
        if sharpe < 0.5:
            alerts.append(("red", f"Sharpe weak: {sharpe:.2f} (target >= 1.0)"))
        elif sharpe < 1.0:
            alerts.append(("amber", f"Sharpe soft: {sharpe:.2f} (improve risk-adjusted returns)"))

    fill = float(kpis.get("fill_ratio", 0.0) or 0.0)
    if fill < 0.60 and int(kpis.get("total_trades", 0)) >= 10:
        alerts.append(("red", f"Fill ratio low: {_fmt_pct(fill)} (target >= 60%)"))
    elif fill < 0.75 and int(kpis.get("total_trades", 0)) >= 10:
        alerts.append(("amber", f"Fill ratio below target: {_fmt_pct(fill)} (target >= 75%)"))

    kills = int(kpis.get("kill_events", 0) or 0)
    if kills >= 5:
        alerts.append(("red", f"Frequent kill-switch events: {kills}"))
    elif kills >= 1:
        alerts.append(("amber", f"Kill-switch events observed: {kills}"))

    var95 = kpis.get("daily_var_95")
    if isinstance(var95, (int, float)) and not np.isnan(var95):
        if var95 >= VAR_DAILY_95_LIMIT:
            alerts.append(("red", f"Daily VaR(95) breach risk: {_fmt_pct(var95)} vs limit {_fmt_pct(VAR_DAILY_95_LIMIT)}"))
        elif var95 >= (0.8 * VAR_DAILY_95_LIMIT):
            alerts.append(("amber", f"Daily VaR(95) near limit: {_fmt_pct(var95)} vs {_fmt_pct(VAR_DAILY_95_LIMIT)}"))

    loss_util = kpis.get("daily_loss_utilization")
    if isinstance(loss_util, (int, float)) and not np.isnan(loss_util):
        if loss_util >= 1.0:
            alerts.append(("red", f"Daily loss utilization at {loss_util * 100:.1f}% of limit"))
        elif loss_util >= 0.75:
            alerts.append(("amber", f"Daily loss utilization elevated at {loss_util * 100:.1f}% of limit"))

    if not alerts:
        alerts.append(("green", "All monitored KPI bands are within target ranges."))
    return alerts


def _interval_to_minutes(interval: str) -> float:
    normalized = str(interval or "").strip().upper()
    if not normalized:
        return float("nan")
    mapping = {
        "ONE_MINUTE": 1,
        "THREE_MINUTE": 3,
        "FIVE_MINUTE": 5,
        "TEN_MINUTE": 10,
        "FIFTEEN_MINUTE": 15,
        "THIRTY_MINUTE": 30,
        "ONE_HOUR": 60,
        "ONE_DAY": 1440,
    }
    if normalized in mapping:
        return float(mapping[normalized])
    try:
        return float(int(normalized))
    except ValueError:
        return float("nan")


def compute_candle_kpis(candles_df: pd.DataFrame) -> dict:
    out = {
        "bars": 0,
        "symbols": 0,
        "intervals": [],
        "dominant_interval": None,
        "latest_close": float("nan"),
        "latest_vwap": float("nan"),
        "vwap_distance": float("nan"),
        "median_range_pct": float("nan"),
        "median_body_pct": float("nan"),
        "bullish_ratio": float("nan"),
        "avg_volume": float("nan"),
        "realized_volatility": float("nan"),
        "freshness_min": float("nan"),
    }
    if candles_df.empty:
        return out

    df = candles_df.copy().sort_values("bar_time")
    for col in ["open", "high", "low", "close", "volume", "vwap"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    out["bars"] = int(len(df))
    if "symbol" in df.columns:
        out["symbols"] = int(df["symbol"].nunique())
    if "interval" in df.columns:
        interval_counts = df["interval"].astype(str).value_counts()
        out["intervals"] = interval_counts.index.tolist()
        if not interval_counts.empty:
            out["dominant_interval"] = str(interval_counts.index[0])

    latest = df.iloc[-1]
    out["latest_close"] = float(latest.get("close", float("nan")))
    out["latest_vwap"] = float(latest.get("vwap", float("nan")))
    if out["latest_vwap"] and not np.isnan(out["latest_close"]) and not np.isnan(out["latest_vwap"]):
        out["vwap_distance"] = float((out["latest_close"] - out["latest_vwap"]) / out["latest_vwap"])

    close = df["close"].replace(0, np.nan)
    out["median_range_pct"] = float(((df["high"] - df["low"]) / close).replace([np.inf, -np.inf], np.nan).median())
    out["median_body_pct"] = float(((df["close"] - df["open"]).abs() / close).replace([np.inf, -np.inf], np.nan).median())
    out["bullish_ratio"] = float((df["close"] > df["open"]).mean()) if len(df) else float("nan")
    out["avg_volume"] = float(df["volume"].replace([np.inf, -np.inf], np.nan).mean()) if "volume" in df.columns else float("nan")

    returns = df["close"].pct_change().dropna()
    if not returns.empty:
        out["realized_volatility"] = float(returns.std())

    latest_ts = df["bar_time"].max()
    now_ts = pd.Timestamp.utcnow()
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.tz_localize("UTC")
    out["freshness_min"] = float((now_ts - latest_ts).total_seconds() / 60.0)
    return out


def _session_bucket(ts: pd.Timestamp) -> str:
    hour = int(ts.hour)
    if 9 <= hour < 11:
        return "Open Session"
    if 11 <= hour < 14:
        return "Mid Session"
    if 14 <= hour < 16:
        return "Close Session"
    return "Off Session"


def build_position_book_and_execution_kpis(trades_df: pd.DataFrame, candles_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    position_df = pd.DataFrame()
    session_df = pd.DataFrame()
    exec_kpis = {
        "realized_lot_pnl": 0.0,
        "unrealized_lot_pnl": float("nan"),
        "total_lot_pnl": float("nan"),
        "open_positions": 0,
        "adverse_slippage_bps": float("nan"),
        "p90_adverse_slippage_bps": float("nan"),
        "timestamp_latency_sec": float("nan"),
        "p90_timestamp_latency_sec": float("nan"),
        "slippage_samples": 0,
    }

    if trades_df.empty:
        return position_df, session_df, exec_kpis

    trades = trades_df.copy()
    trades["created_at"] = pd.to_datetime(trades["created_at"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce").fillna(0.0)
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades = trades.dropna(subset=["created_at"])
    trades = trades.sort_values("created_at")

    # Session-quality segmentation.
    session_work = trades.copy()
    session_work["session"] = session_work["created_at"].apply(_session_bucket)
    session_df = (
        session_work.groupby("session")
        .agg(
            total_orders=("id", "count"),
            filled_orders=("status", lambda s: int((s == "FILLED").sum())),
            rejected_orders=("status", lambda s: int((s == "REJECTED").sum())),
            avg_order_qty=("quantity", "mean"),
        )
        .reset_index()
    )
    if not session_df.empty:
        session_df["fill_ratio"] = session_df["filled_orders"] / session_df["total_orders"].clip(lower=1)
        session_df["rejection_ratio"] = session_df["rejected_orders"] / session_df["total_orders"].clip(lower=1)
        session_df = session_df.sort_values("total_orders", ascending=False)

    # Lot-level realized/unrealized PnL (FIFO matching).
    fills = trades[(trades["status"] == "FILLED") & trades["price"].notna() & (trades["price"] > 0)].copy()
    if fills.empty:
        return position_df, session_df, exec_kpis

    latest_marks = {}
    if not candles_df.empty:
        mark = candles_df.copy()
        mark["bar_time"] = pd.to_datetime(mark["bar_time"], errors="coerce")
        mark["close"] = pd.to_numeric(mark["close"], errors="coerce")
        mark = mark.dropna(subset=["bar_time", "close"])
        if not mark.empty:
            latest_mark_rows = mark.sort_values("bar_time").groupby("symbol", as_index=False).tail(1)
            latest_marks = {str(r["symbol"]): float(r["close"]) for _, r in latest_mark_rows.iterrows()}

    position_rows = []
    realized_total = 0.0
    for symbol, grp in fills.groupby("symbol"):
        lots: list[list[float]] = []  # [qty_remaining, buy_price]
        realized_symbol = 0.0
        for _, row in grp.sort_values("created_at").iterrows():
            qty = float(row["quantity"])
            px = float(row["price"])
            side = str(row["side"] or "").upper()
            if qty <= 0:
                continue
            if side == "BUY":
                lots.append([qty, px])
                continue
            if side != "SELL":
                continue

            remaining = qty
            while remaining > 0 and lots:
                lot_qty, lot_px = lots[0]
                matched = min(remaining, lot_qty)
                realized_symbol += (px - lot_px) * matched
                remaining -= matched
                lot_qty -= matched
                if lot_qty <= 0:
                    lots.pop(0)
                else:
                    lots[0][0] = lot_qty

        open_qty = float(sum(lot[0] for lot in lots))
        open_cost = float(sum(lot[0] * lot[1] for lot in lots))
        avg_cost = (open_cost / open_qty) if open_qty > 0 else float("nan")
        mark_px = latest_marks.get(str(symbol), float("nan"))
        unrealized_symbol = float("nan")
        if open_qty > 0 and not np.isnan(mark_px):
            unrealized_symbol = (mark_px - avg_cost) * open_qty

        position_rows.append(
            {
                "symbol": symbol,
                "open_qty": open_qty,
                "avg_cost": avg_cost,
                "mark_price": mark_px,
                "realized_pnl": realized_symbol,
                "unrealized_pnl": unrealized_symbol,
                "total_pnl": realized_symbol + (0.0 if np.isnan(unrealized_symbol) else unrealized_symbol),
            }
        )
        realized_total += realized_symbol

    if position_rows:
        position_df = pd.DataFrame(position_rows).sort_values("total_pnl", ascending=False)
        exec_kpis["open_positions"] = int((position_df["open_qty"] > 0).sum())
        exec_kpis["realized_lot_pnl"] = float(realized_total)
        valid_unr = position_df["unrealized_pnl"].dropna()
        if not valid_unr.empty:
            exec_kpis["unrealized_lot_pnl"] = float(valid_unr.sum())
            exec_kpis["total_lot_pnl"] = float(realized_total + valid_unr.sum())

    # Slippage + timestamp latency proxy using nearest prior candle benchmark by symbol.
    if not candles_df.empty:
        cb = candles_df.copy()
        cb["bar_time"] = pd.to_datetime(cb["bar_time"], errors="coerce")
        cb["benchmark"] = pd.to_numeric(cb["vwap"], errors="coerce")
        cb["close"] = pd.to_numeric(cb["close"], errors="coerce")
        cb["benchmark"] = cb["benchmark"].fillna(cb["close"])
        cb = cb.dropna(subset=["bar_time", "benchmark"]).sort_values("bar_time")

        slip_samples = []
        latency_samples = []
        for symbol, grp in fills.groupby("symbol"):
            sym_cb = cb[cb["symbol"] == symbol]
            if sym_cb.empty:
                continue
            t = grp.sort_values("created_at")[["created_at", "side", "price"]].copy()
            merged = pd.merge_asof(
                t,
                sym_cb[["bar_time", "benchmark"]].sort_values("bar_time"),
                left_on="created_at",
                right_on="bar_time",
                direction="backward",
            )
            merged = merged.dropna(subset=["benchmark", "price", "bar_time"])
            if merged.empty:
                continue

            adverse_bps = np.where(
                merged["side"].astype(str).str.upper() == "BUY",
                (merged["price"] - merged["benchmark"]) / merged["benchmark"] * 10000.0,
                (merged["benchmark"] - merged["price"]) / merged["benchmark"] * 10000.0,
            )
            slip_samples.extend([float(v) for v in adverse_bps if not np.isnan(v)])

            latency_sec = (merged["created_at"] - merged["bar_time"]).dt.total_seconds().abs()
            latency_samples.extend([float(v) for v in latency_sec if not np.isnan(v)])

        if slip_samples:
            s = pd.Series(slip_samples)
            exec_kpis["adverse_slippage_bps"] = float(s.median())
            exec_kpis["p90_adverse_slippage_bps"] = float(s.quantile(0.90))
            exec_kpis["slippage_samples"] = int(len(slip_samples))
        if latency_samples:
            l = pd.Series(latency_samples)
            exec_kpis["timestamp_latency_sec"] = float(l.median())
            exec_kpis["p90_timestamp_latency_sec"] = float(l.quantile(0.90))

    return position_df, session_df, exec_kpis


def build_stress_scenario_table(position_df: pd.DataFrame) -> pd.DataFrame:
    if position_df.empty:
        return pd.DataFrame()

    work = position_df.copy()
    work["open_qty"] = pd.to_numeric(work["open_qty"], errors="coerce").fillna(0.0)
    work["mark_price"] = pd.to_numeric(work["mark_price"], errors="coerce")
    work["gross_exposure"] = (work["open_qty"].abs() * work["mark_price"].fillna(0.0)).fillna(0.0)
    gross = float(work["gross_exposure"].sum())
    if gross <= 0:
        return pd.DataFrame()

    scenarios = []
    for label, shock in [("Mild Shock", -0.01), ("Stress Shock", -0.025), ("Tail Shock", -0.05)]:
        scenarios.append(
            {
                "Scenario": label,
                "Shock": _fmt_pct(shock),
                "Estimated PnL Impact": _fmt_money(gross * shock),
                "Gross Exposure": _fmt_money(gross),
            }
        )
    return pd.DataFrame(scenarios)


def compute_drawdown_depth_duration(snaps_df: pd.DataFrame) -> tuple[float, float]:
    if snaps_df.empty:
        return float("nan"), float("nan")

    d = snaps_df.sort_values("created_at").copy()
    if "current_value" not in d.columns:
        return float("nan"), float("nan")
    equity = pd.to_numeric(d["current_value"], errors="coerce").dropna()
    if equity.empty:
        return float("nan"), float("nan")

    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    in_dd = dd < 0
    max_duration = 0
    current = 0
    for flag in in_dd.tolist():
        if flag:
            current += 1
            max_duration = max(max_duration, current)
        else:
            current = 0
    return float(dd.min()), float(max_duration)


def build_institutional_coverage_matrix(
    kpis: dict,
    candle_kpis: dict,
    execution_kpis: dict,
    session_df: pd.DataFrame,
    stress_df: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        {"Domain": "Portfolio", "Component": "PnL + Drawdown + Equity", "Status": "Ready"},
        {"Domain": "Execution", "Component": "Fill/Reject + Slippage + Latency", "Status": "Ready"},
        {"Domain": "Risk", "Component": "VaR + Drawdown Utilization + Stress Ladder", "Status": "Ready" if not stress_df.empty else "Partial"},
        {"Domain": "Market Data", "Component": "Candle Tape + VWAP + Volatility", "Status": "Ready" if int(candle_kpis.get("bars", 0)) > 0 else "Missing"},
        {"Domain": "Operations", "Component": "Kill Switch + Mode + Freshness", "Status": "Ready"},
        {"Domain": "Session Quality", "Component": "Open/Mid/Close Performance", "Status": "Ready" if not session_df.empty else "Missing"},
        {"Domain": "Model Governance", "Component": "Registry + Approval + Audit Trail", "Status": "Ready"},
    ]
    return pd.DataFrame(rows)


def render_reference_inspired_shell(
    trades_df: pd.DataFrame,
    candles_df: pd.DataFrame,
    kpis: dict,
) -> None:
    tiles = []
    if not trades_df.empty:
        grouped = (
            trades_df.groupby("symbol")
            .agg(last_price=("price", "last"), trades=("id", "count"))
            .reset_index()
            .sort_values("trades", ascending=False)
            .head(5)
        )
        for row in grouped.itertuples(index=False):
            px = 0.0 if pd.isna(row.last_price) else float(row.last_price)
            tiles.append(
                {
                    "name": str(row.symbol),
                    "value": _fmt_money(px),
                    "delta": f"Orders {int(row.trades)}",
                }
            )
    if not tiles:
        tiles = [
            {"name": "Desk A", "value": _fmt_money(0), "delta": "No data"},
            {"name": "Desk B", "value": _fmt_money(0), "delta": "No data"},
            {"name": "Desk C", "value": _fmt_money(0), "delta": "No data"},
            {"name": "Desk D", "value": _fmt_money(0), "delta": "No data"},
            {"name": "Desk E", "value": _fmt_money(0), "delta": "No data"},
        ]

    ticker_parts = [
        f"<span>Equity {_fmt_money(0.0 if np.isnan(kpis['equity']) else kpis['equity'])}</span>",
        f"<span>Cash {_fmt_money(0.0 if np.isnan(kpis['cash_available']) else kpis['cash_available'])}</span>",
        f"<span>Fill {_fmt_pct(kpis['fill_ratio'])}</span>",
        f"<span>Reject {_fmt_pct(kpis['rejection_ratio'])}</span>",
        f"<span>Turnover {_fmt_money(kpis['turnover_notional'])}</span>",
    ]

    tiles_html = "".join(
        [
            f'<div class="market-tile"><div class="tile-name">{t["name"]}</div><div class="tile-value">{t["value"]}</div><div class="tile-delta">{t["delta"]}</div></div>'
            for t in tiles
        ]
    )

    st.markdown(
        f"""
        <div class="terminal-shell">
            <div class="terminal-toolbar">
                <div>
                    <span class="toolbar-dot dot-red"></span>
                    <span class="toolbar-dot dot-yellow"></span>
                    <span class="toolbar-dot dot-green"></span>
                </div>
                <div class="address-pill">axon.terminal / desk-view</div>
                <div>Live Session</div>
            </div>
            <div class="terminal-nav">
                <div class="brand">Axon</div>
                <div class="menu"><span class="active">Markets</span><span>Analytics</span><span>Risk</span><span>Execution</span><span>Governance</span></div>
            </div>
            <div class="terminal-grid">{tiles_html}</div>
            <div class="range-pills">
                <span class="pill active">1D</span><span class="pill">5D</span><span class="pill">1M</span><span class="pill">YTD</span><span class="pill">1Y</span><span class="pill">MAX</span>
            </div>
            <div class="ticker-row">{"".join(ticker_parts)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([3.8, 1.8])
    with left_col:
        st.markdown('<div class="shell-panel-title">Market Curve Composite</div>', unsafe_allow_html=True)
        if not candles_df.empty:
            series = candles_df.sort_values("bar_time").set_index("bar_time")
            cols = [c for c in ["close", "vwap"] if c in series.columns]
            if cols:
                st.line_chart(series[cols].tail(400))
            else:
                st.info("No candle series available.")
        else:
            st.info("No candle data available for chart panel.")

    with right_col:
        st.markdown('<div class="shell-panel-title">Discover Desk</div>', unsafe_allow_html=True)
        watch = tiles[:6]
        for row in watch:
            st.markdown(
                f'<div class="watch-card"><div class="name">{row["name"]}</div><div class="px">{row["value"]}</div><div class="spark">▁▂▃▂▅▄▆▅</div></div>',
                unsafe_allow_html=True,
            )

    if not trades_df.empty:
        snap = (
            trades_df.groupby("symbol")
            .agg(
                orders=("id", "count"),
                avg_px=("price", "mean"),
                fill_ratio=("status", lambda s: float((s == "FILLED").sum() / max(1, len(s)))),
            )
            .reset_index()
            .sort_values("orders", ascending=False)
            .head(8)
        )
        if not snap.empty:
            snap["avg_px"] = snap["avg_px"].apply(lambda x: _fmt_money(0.0 if pd.isna(x) else float(x)))
            snap["fill_ratio"] = snap["fill_ratio"].apply(_fmt_pct)
            st.markdown('<div class="shell-panel-title">Instrument Snapshot</div>', unsafe_allow_html=True)
            st.dataframe(snap, width="stretch")


@st.cache_data(show_spinner=False)
def load_trades() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = session.query(Trade).order_by(Trade.created_at.desc()).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {
                "id": r.id,
                "external_id": r.external_id,
                "symbol": r.symbol,
                "side": r.side,
                "quantity": r.quantity,
                "order_type": r.order_type,
                "price": r.price,
                "status": r.status,
                "trade_mode": r.trade_mode,
                "broker": r.broker,
                "atr": r.atr,
                "reserved_capital": r.reserved_capital,
                "opportunity_score": r.opportunity_score,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return pd.DataFrame(data)
    except Exception as exc:
        logger.warning("Failed to load trades: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_symbol_selections() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(SymbolSelection)
            .order_by(SymbolSelection.created_at.desc(), SymbolSelection.selection_rank.asc())
            .limit(200)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "created_at": row.created_at,
                    "symbol": row.symbol,
                    "opportunity_score": row.opportunity_score,
                    "selection_rank": row.selection_rank,
                    "features": row.features,
                }
                for row in rows
            ]
        )
    except Exception as exc:
        logger.warning("Failed to load symbol selections: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_snapshots() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.created_at.asc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        data = [
            {
                "created_at": r.created_at,
                "total_capital": r.total_capital,
                "current_value": r.current_value,
                "cash_available": r.cash_available,
                "daily_pnl": r.daily_pnl,
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        if not df.empty:
            df["created_at"] = pd.to_datetime(df["created_at"])
        return df
    except Exception as exc:
        logger.warning("Failed to load portfolio snapshots: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_regime_history() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(RegimeHistory)
            .order_by(RegimeHistory.created_at.asc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        data = [
            {
                "created_at": r.created_at,
                "score": r.score,
                "mode": r.mode,
            }
            for r in rows
        ]
        return pd.DataFrame(data)
    except Exception as exc:
        logger.warning("Failed to load regime history: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_kill_switch_log() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(KillSwitchLog)
            .order_by(KillSwitchLog.created_at.desc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        data = [
            {
                "created_at": r.created_at,
                "reason": r.reason,
                "active": r.active,
            }
            for r in rows
        ]
        return pd.DataFrame(data)
    except Exception as exc:
        logger.warning("Failed to load kill-switch log: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_engines() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = session.query(Engine).order_by(Engine.created_at.asc()).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {
                "name": r.name,
                "description": r.description,
                "allocation_target": r.allocation_target,
                "enabled": r.enabled,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return pd.DataFrame(data)
    except Exception as exc:
        logger.warning("Failed to load engines: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_correlation_matrices() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(CorrelationMatrix)
            .order_by(CorrelationMatrix.as_of.desc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        data = [
            {
                "as_of": r.as_of,
                "window_minutes": r.window_minutes,
                "symbols": r.symbols,
                "matrix": r.matrix,
            }
            for r in rows
        ]
        return pd.DataFrame(data)
    except Exception as exc:
        logger.warning("Failed to load correlation matrices: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_model_registry() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(ModelRegistryEntry)
            .order_by(ModelRegistryEntry.created_at.desc(), ModelRegistryEntry.id.desc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "id": row.id,
                    "model_name": row.model_name,
                    "model_version": row.model_version,
                    "stage": row.stage,
                    "config_hash": row.config_hash,
                    "metrics": row.metrics,
                    "notes": row.notes,
                    "active": row.active,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]
        )
    except Exception as exc:
        logger.warning("Failed to load model registry: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_model_promotion_events() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(ModelPromotionEvent)
            .order_by(ModelPromotionEvent.created_at.desc(), ModelPromotionEvent.id.desc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "id": row.id,
                    "model_name": row.model_name,
                    "model_version": row.model_version,
                    "from_stage": row.from_stage,
                    "to_stage": row.to_stage,
                    "approved": row.approved,
                    "decided_by": row.decided_by,
                    "gate_result": row.gate_result,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        )
    except Exception as exc:
        logger.warning("Failed to load model promotion events: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def load_candle_bars(limit: int = 8000) -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = (
            session.query(CandleBar)
            .order_by(CandleBar.bar_time.desc())
            .limit(limit)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "symbol": row.symbol,
                    "interval": row.interval,
                    "broker": row.broker,
                    "bar_time": row.bar_time,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                    "vwap": row.vwap,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        )
    except Exception as exc:
        logger.warning("Failed to load candle bars: %s", exc)
        return pd.DataFrame()
    finally:
        session.close()


def main() -> None:
    apply_dashboard_theme()

    st.markdown(
        """
        <div class="hero-wrap">
            <h1>Axon Institutional Command Center</h1>
            <p>Executive and analyst views for performance, risk, execution quality, and model governance.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="ribbon">
            <div class="chip">Multi-Desk Monitoring</div>
            <div class="chip">Execution Intelligence</div>
            <div class="chip">Risk Command Layer</div>
            <div class="chip">Governance Workflow</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    db_error = init_db()
    if db_error:
        st.error("Database connection failed. The dashboard could not initialize its schema or open a session.")
        st.caption("Check the database container, hostname, and AXON_DATABASE_URL value.")
        st.code(os.getenv("AXON_DATABASE_URL", "<not set>"), language="bash")
        st.exception(Exception(db_error))
        st.stop()

    st.sidebar.header("Control Center")

    # ===== Global Controls =====
    st.sidebar.subheader("Runtime Controls")

    # Manual kill switch toggle
    current_kill = is_manual_kill_switch_active()
    manual_kill = st.sidebar.toggle(
        "Manual Kill Switch",
        value=current_kill,
        help="When enabled, all new trades are blocked by the kill switch.",
    )
    if manual_kill != current_kill:
        set_manual_kill_switch(manual_kill)
        # Invalidate cached logs so the change is reflected
        load_kill_switch_log.clear()

    # Global trade mode selector
    current_mode = get_global_trade_mode()
    selected_mode = st.sidebar.radio(
        "Default Trade Mode",
        options=["Mock", "Live"],
        index=0 if current_mode == "mock" else 1,
        help="Preferred default trade mode for engines and tools.",
    )
    new_mode = "mock" if selected_mode == "Mock" else "live"
    if new_mode != current_mode:
        set_global_trade_mode(new_mode)

    trades_df = load_trades()
    selections_df = load_symbol_selections()
    snaps_df = load_snapshots()
    regime_df = load_regime_history()
    kill_df = load_kill_switch_log()
    engines_df = load_engines()
    corr_df = load_correlation_matrices()
    candles_df = load_candle_bars()
    models_df = load_model_registry()
    promotion_events_df = load_model_promotion_events()

    trades_df = _coerce_datetime(trades_df, "created_at")
    selections_df = _coerce_datetime(selections_df, "created_at")
    snaps_df = _coerce_datetime(snaps_df, "created_at")
    regime_df = _coerce_datetime(regime_df, "created_at")
    kill_df = _coerce_datetime(kill_df, "created_at")
    models_df = _coerce_datetime(models_df, "created_at")
    models_df = _coerce_datetime(models_df, "updated_at")
    promotion_events_df = _coerce_datetime(promotion_events_df, "created_at")
    corr_df = _coerce_datetime(corr_df, "as_of")
    candles_df = _coerce_datetime(candles_df, "bar_time")
    candles_df = _coerce_datetime(candles_df, "created_at")

    symbols = sorted(trades_df["symbol"].dropna().unique().tolist()) if not trades_df.empty else []
    trade_modes = sorted(trades_df["trade_mode"].dropna().unique().tolist()) if not trades_df.empty else []
    sides = sorted(trades_df["side"].dropna().unique().tolist()) if not trades_df.empty else []

    symbol_filter = st.sidebar.selectbox("Symbol", ["All"] + symbols) if symbols else "All"
    mode_filter = st.sidebar.selectbox("Mode", ["All"] + trade_modes) if trade_modes else "All"
    side_filter = st.sidebar.selectbox("Side", ["All"] + sides) if sides else "All"

    min_date, max_date = _date_bounds(
        (trades_df, "created_at"),
        (selections_df, "created_at"),
        (snaps_df, "created_at"),
        (regime_df, "created_at"),
        (kill_df, "created_at"),
        (promotion_events_df, "created_at"),
        (corr_df, "as_of"),
        (candles_df, "bar_time"),
    )
    date_range = None
    start_date = None
    end_date = None
    if min_date is not None and max_date is not None:
        preset_options = ["Today", "Yesterday", "Last 7 Days", "This Month", "Custom"]
        preset = st.sidebar.selectbox(
            "Date Preset",
            options=preset_options,
            index=0,
            help="Quick date scopes relative to the latest available data date.",
        )

        default_start, default_end = _resolve_date_preset_range(preset, min_date, max_date)
        if "dashboard_custom_date_range" not in st.session_state:
            st.session_state["dashboard_custom_date_range"] = (default_start, default_end)

        date_value = st.session_state["dashboard_custom_date_range"] if preset == "Custom" else (default_start, default_end)
        date_range = st.sidebar.date_input(
            "Dashboard Date Range",
            value=date_value,
            min_value=min_date,
            max_value=max_date,
            disabled=preset != "Custom",
            help="Applies to trades, portfolio snapshots, regime history, kill-switch events, candles, selections, and audit tables. Defaults to the latest available day.",
        )
        start_date, end_date = _normalize_date_range(date_range)
        if preset == "Custom" and start_date is not None and end_date is not None:
            st.session_state["dashboard_custom_date_range"] = (start_date, end_date)

        if start_date is not None and end_date is not None:
            st.sidebar.caption(f"Active range: {start_date.isoformat()} to {end_date.isoformat()}")

    st.sidebar.write("Database URL:")
    st.sidebar.code(os.getenv("AXON_DATABASE_URL", "<not set>"), language="bash")

    filtered_trades = trades_df.copy()
    if not filtered_trades.empty:
        if symbol_filter != "All":
            filtered_trades = filtered_trades[filtered_trades["symbol"] == symbol_filter]
        if mode_filter != "All":
            filtered_trades = filtered_trades[filtered_trades["trade_mode"] == mode_filter]
        if side_filter != "All":
            filtered_trades = filtered_trades[filtered_trades["side"] == side_filter]
        filtered_trades = _filter_by_date_range(filtered_trades, "created_at", start_date, end_date)

    filtered_selections = _filter_by_date_range(selections_df, "created_at", start_date, end_date)
    filtered_snaps = _filter_by_date_range(snaps_df, "created_at", start_date, end_date)
    filtered_regime = _filter_by_date_range(regime_df, "created_at", start_date, end_date)
    filtered_kill = _filter_by_date_range(kill_df, "created_at", start_date, end_date)
    filtered_promotions = _filter_by_date_range(promotion_events_df, "created_at", start_date, end_date)
    filtered_corr = _filter_by_date_range(corr_df, "as_of", start_date, end_date)

    filtered_candles = candles_df.copy()
    if not filtered_candles.empty:
        if symbol_filter != "All":
            filtered_candles = filtered_candles[filtered_candles["symbol"] == symbol_filter]
        filtered_candles = _filter_by_date_range(filtered_candles, "bar_time", start_date, end_date)

    kpis = compute_dashboard_kpis(
        trades_df=filtered_trades,
        snaps_df=filtered_snaps,
        regime_df=filtered_regime,
        kill_df=filtered_kill,
        models_df=models_df,
        promotion_events_df=filtered_promotions,
    )
    candle_kpis = compute_candle_kpis(filtered_candles)
    position_book_df, session_quality_df, execution_kpis = build_position_book_and_execution_kpis(
        trades_df=filtered_trades,
        candles_df=filtered_candles,
    )
    stress_df = build_stress_scenario_table(position_book_df)
    dd_depth, dd_duration = compute_drawdown_depth_duration(filtered_snaps)
    coverage_matrix_df = build_institutional_coverage_matrix(
        kpis=kpis,
        candle_kpis=candle_kpis,
        execution_kpis=execution_kpis,
        session_df=session_quality_df,
        stress_df=stress_df,
    )

    render_reference_inspired_shell(
        trades_df=filtered_trades,
        candles_df=filtered_candles,
        kpis=kpis,
    )

    st.markdown('<div class="section-note">Snapshot KPIs for leadership and daily operating decisions.</div>', unsafe_allow_html=True)
    kpi_cols = st.columns(6)
    with kpi_cols[0]:
        render_kpi_card("Total Trades", str(kpis["total_trades"]), "Filtered scope")
    with kpi_cols[1]:
        render_kpi_card("Fill Ratio", _fmt_pct(kpis["fill_ratio"]), "Higher is better")
    with kpi_cols[2]:
        render_kpi_card("Rejection Ratio", _fmt_pct(kpis["rejection_ratio"]), "Lower is better")
    with kpi_cols[3]:
        render_kpi_card("Equity", _fmt_money(0.0 if np.isnan(kpis["equity"]) else kpis["equity"]), "Current portfolio value")
    with kpi_cols[4]:
        render_kpi_card("Sharpe (252)", "-" if np.isnan(kpis["sharpe"]) else f"{kpis['sharpe']:.2f}", "Risk-adjusted return")
    with kpi_cols[5]:
        render_kpi_card("Max Drawdown", "-" if np.isnan(kpis["max_drawdown"]) else _fmt_pct(kpis["max_drawdown"]), "Peak-to-trough")

    kpi_cols_2 = st.columns(6)
    with kpi_cols_2[0]:
        render_kpi_card("Buy Notional", _fmt_money(kpis["buy_notional"]), "Gross bought")
    with kpi_cols_2[1]:
        render_kpi_card("Sell Notional", _fmt_money(kpis["sell_notional"]), "Gross sold")
    with kpi_cols_2[2]:
        render_kpi_card("Turnover", _fmt_money(kpis["turnover_notional"]), "Execution throughput")
    with kpi_cols_2[3]:
        render_kpi_card("Unique Symbols", str(kpis["unique_symbols"]), "Diversification breadth")
    with kpi_cols_2[4]:
        render_kpi_card("Live Ratio", "-" if np.isnan(kpis["mode_live_ratio"]) else _fmt_pct(kpis["mode_live_ratio"]), "Live vs paper split")
    with kpi_cols_2[5]:
        render_kpi_card("Median Trade Interval", "-" if np.isnan(kpis["trade_interval_min"]) else f"{kpis['trade_interval_min']:.1f} min", "Observed cadence")

    kpi_cols_3 = st.columns(4)
    with kpi_cols_3[0]:
        render_kpi_card("Candle Bars", str(candle_kpis["bars"]), "Persisted OHLC rows")
    with kpi_cols_3[1]:
        render_kpi_card("Candle Volatility", "-" if np.isnan(candle_kpis["realized_volatility"]) else _fmt_pct(candle_kpis["realized_volatility"]), "Std dev of returns")
    with kpi_cols_3[2]:
        render_kpi_card("VWAP Distance", "-" if np.isnan(candle_kpis["vwap_distance"]) else _fmt_pct(candle_kpis["vwap_distance"]), "Close vs VWAP")
    with kpi_cols_3[3]:
        render_kpi_card("Candle Freshness", "-" if np.isnan(candle_kpis["freshness_min"]) else f"{candle_kpis['freshness_min']:.1f} min", "Lower is fresher")

    exec_tab, analyst_tab, risk_tab, governance_tab = st.tabs(
        ["CEO Overview", "Data Analyst Lab", "Risk & Execution", "Governance Hub"]
    )

    with exec_tab:
        st.subheader("Executive Summary")
        alerts = build_alerts(kpis)
        for severity, message in alerts:
            if severity == "red":
                st.error(f"RED ALERT: {message}")
            elif severity == "amber":
                st.warning(f"AMBER ALERT: {message}")
            else:
                st.success(f"GREEN: {message}")

        period_kpis = build_period_kpis(
            trades_df=filtered_trades,
            snaps_df=filtered_snaps,
            regime_df=filtered_regime,
            kill_df=filtered_kill,
            models_df=models_df,
            promotion_events_df=filtered_promotions,
        )
        if period_kpis:
            st.markdown("#### KPI Comparison Strip (Today vs 30D vs 90D)")
            strip_df = pd.DataFrame(
                [
                    {
                        "Window": label,
                        "Trades": values["total_trades"],
                        "Fill Ratio": _fmt_pct(values["fill_ratio"]),
                        "Rejection Ratio": _fmt_pct(values["rejection_ratio"]),
                        "Realized PnL": _fmt_money(values["realized_pnl"]),
                        "Sharpe": "-" if np.isnan(values["sharpe"]) else f"{values['sharpe']:.2f}",
                        "Max Drawdown": "-" if np.isnan(values["max_drawdown"]) else _fmt_pct(values["max_drawdown"]),
                    }
                    for label, values in period_kpis.items()
                ]
            )
            st.dataframe(strip_df, width="stretch")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Realized PnL", _fmt_money(kpis["realized_pnl"]), delta="From trade ledger")
        with c2:
            st.metric("Cash Available", _fmt_money(0.0 if np.isnan(kpis["cash_available"]) else kpis["cash_available"]))
        with c3:
            st.metric("Lot Realized PnL", _fmt_money(execution_kpis["realized_lot_pnl"]))
        with c4:
            mode_text = f"{kpis['regime_mode']} ({kpis['regime_score']})" if kpis["regime_score"] is not None else "N/A"
            st.metric("Market Regime", mode_text)

        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.metric("Lot Unrealized PnL", "-" if np.isnan(execution_kpis["unrealized_lot_pnl"]) else _fmt_money(execution_kpis["unrealized_lot_pnl"]))
        with c6:
            st.metric("Open Positions", int(execution_kpis["open_positions"]))
        with c7:
            st.metric("Adverse Slippage", "-" if np.isnan(execution_kpis["adverse_slippage_bps"]) else f"{execution_kpis['adverse_slippage_bps']:.1f} bps")
        with c8:
            st.metric("Timestamp Latency", "-" if np.isnan(execution_kpis["timestamp_latency_sec"]) else f"{execution_kpis['timestamp_latency_sec']:.1f}s")

        d1, d2, d3 = st.columns(3)
        with d1:
            st.metric("Drawdown Depth", "-" if np.isnan(dd_depth) else _fmt_pct(dd_depth))
        with d2:
            st.metric("Drawdown Duration", "-" if np.isnan(dd_duration) else f"{dd_duration:.0f} bars")
        with d3:
            st.metric("Slippage Samples", int(execution_kpis.get("slippage_samples", 0)))

        st.markdown("#### Control-State Telemetry")
        ctl1, ctl2, ctl3, ctl4 = st.columns(4)
        with ctl1:
            st.metric("Manual Kill Switch", "ON" if manual_kill else "OFF")
        with ctl2:
            st.metric("Global Trade Mode", selected_mode)
        with ctl3:
            st.metric("Configured Run Timeframe", f"{int(ALGO_RUN_INTERVAL / 60)} min")
        with ctl4:
            st.metric("Last Trade Age", "-" if np.isnan(kpis["last_trade_age_min"]) else f"{kpis['last_trade_age_min']:.1f} min")

        eq_col, pnl_col = st.columns(2)
        with eq_col:
            st.markdown("#### Equity Curve")
            if not filtered_snaps.empty:
                st.line_chart(filtered_snaps.set_index("created_at")["current_value"])
            else:
                st.info("No portfolio snapshots available yet.")

        with pnl_col:
            st.markdown("#### Daily PnL Trend")
            if not filtered_snaps.empty:
                st.bar_chart(filtered_snaps.set_index("created_at")["daily_pnl"])
            else:
                st.info("No PnL data available yet.")

        st.markdown("#### Board-Ready KPI Table")
        board_df = pd.DataFrame(
            [
                {"KPI": "Total Trades", "Value": kpis["total_trades"]},
                {"KPI": "Filled Trades", "Value": kpis["filled_trades"]},
                {"KPI": "Fill Ratio", "Value": _fmt_pct(kpis["fill_ratio"])},
                {"KPI": "Rejection Ratio", "Value": _fmt_pct(kpis["rejection_ratio"])},
                {"KPI": "Buy/Sell Count", "Value": f"{kpis['buy_trades']} / {kpis['sell_trades']}"},
                {"KPI": "Net Quantity", "Value": kpis["net_qty"]},
                {"KPI": "Open Positions", "Value": execution_kpis["open_positions"]},
                {"KPI": "Lot Realized PnL", "Value": _fmt_money(execution_kpis["realized_lot_pnl"])},
                {"KPI": "Lot Unrealized PnL", "Value": "-" if np.isnan(execution_kpis["unrealized_lot_pnl"]) else _fmt_money(execution_kpis["unrealized_lot_pnl"])},
                {"KPI": "Daily VaR (95)", "Value": "-" if np.isnan(kpis["daily_var_95"]) else _fmt_pct(kpis["daily_var_95"])},
                {"KPI": "Daily Loss Utilization", "Value": "-" if np.isnan(kpis["daily_loss_utilization"]) else _fmt_pct(kpis["daily_loss_utilization"])},
                {"KPI": "Weekly Drawdown Utilization", "Value": "-" if np.isnan(kpis["weekly_drawdown_utilization"]) else _fmt_pct(kpis["weekly_drawdown_utilization"])},
                {"KPI": "Median Adverse Slippage", "Value": "-" if np.isnan(execution_kpis["adverse_slippage_bps"]) else f"{execution_kpis['adverse_slippage_bps']:.1f} bps"},
                {"KPI": "Median Timestamp Latency", "Value": "-" if np.isnan(execution_kpis["timestamp_latency_sec"]) else f"{execution_kpis['timestamp_latency_sec']:.1f}s"},
                {"KPI": "Promotion Approval Rate", "Value": "-" if np.isnan(kpis["promotion_approval_rate"]) else _fmt_pct(kpis["promotion_approval_rate"])},
                {"KPI": "Active Models", "Value": kpis["active_models"]},
            ]
        )
        board_df["Value"] = board_df["Value"].astype(str)
        st.dataframe(board_df, width="stretch")

        st.markdown("#### Institutional Coverage Matrix")
        st.dataframe(coverage_matrix_df, width="stretch")

        st.markdown("#### Stress Scenario Ladder")
        if not stress_df.empty:
            st.dataframe(stress_df, width="stretch")
        else:
            st.info("Stress ladder will appear once open exposure is available.")

        st.markdown("#### Coverage & Data Health")
        coverage_df = pd.DataFrame(
            [
                {"Dataset": "Trades", "Status": "Available", "Last Refresh": "-" if np.isnan(kpis["last_trade_age_min"]) else f"{kpis['last_trade_age_min']:.1f} min ago"},
                {"Dataset": "Portfolio Snapshots", "Status": "Available" if not filtered_snaps.empty else "Missing", "Last Refresh": "From snapshot feed" if not filtered_snaps.empty else "No data"},
                {"Dataset": "Candle/OHLC History", "Status": "Available" if not filtered_candles.empty else "Missing", "Last Refresh": "-" if np.isnan(candle_kpis["freshness_min"]) else f"{candle_kpis['freshness_min']:.1f} min ago"},
                {"Dataset": "Kill Switch Log", "Status": "Available" if not filtered_kill.empty else "Missing", "Last Refresh": "Event-driven"},
                {"Dataset": "Regime History", "Status": "Available" if not filtered_regime.empty else "Missing", "Last Refresh": "Strategy-driven"},
            ]
        )
        st.dataframe(coverage_df, width="stretch")

    with analyst_tab:
        st.subheader("Market Selection & Trade Analytics")
        sel_col, trade_col = st.columns(2)

        with sel_col:
            st.markdown("#### Latest Symbol Selections")
            if not filtered_selections.empty:
                latest_selection_time = filtered_selections["created_at"].max()
                latest = filtered_selections[filtered_selections["created_at"] == latest_selection_time].copy()
                latest = latest.sort_values(["selection_rank", "opportunity_score"], ascending=[True, False])
                st.caption(f"Most recent batch: {latest_selection_time}")
                st.dataframe(latest[["selection_rank", "symbol", "opportunity_score", "features"]], width="stretch")
            else:
                st.info("No symbol selection history recorded for the selected date range.")

        with trade_col:
            st.markdown("#### Trades (Filtered)")
            if not filtered_trades.empty:
                st.dataframe(filtered_trades, width="stretch")
            else:
                st.info("No trades for selected filters.")

        st.markdown("#### Per-Symbol Summary")
        if not filtered_trades.empty:
            summary = (
                filtered_trades.groupby(["symbol", "trade_mode"])
                .agg(
                    total_trades=("id", "count"),
                    filled_trades=("status", lambda s: int((s == "FILLED").sum())),
                    rejected_trades=("status", lambda s: int((s == "REJECTED").sum())),
                    avg_price=("price", "mean"),
                    first_trade_at=("created_at", "min"),
                    last_trade_at=("created_at", "max"),
                )
                .reset_index()
                .sort_values(["filled_trades", "total_trades"], ascending=False)
            )
            st.dataframe(summary, width="stretch")
        else:
            st.info("No symbol-level analytics available for current filters.")

        st.markdown("#### Daily Trade Summary")
        if not filtered_trades.empty:
            daily_trades = filtered_trades.copy()
            daily_trades["trade_date"] = daily_trades["created_at"].dt.date
            daily_trades["quantity"] = pd.to_numeric(daily_trades["quantity"], errors="coerce").fillna(0.0)
            daily_trades["price"] = pd.to_numeric(daily_trades["price"], errors="coerce").fillna(0.0)
            daily_trades["notional"] = daily_trades["quantity"] * daily_trades["price"]
            daily_summary = (
                daily_trades.groupby("trade_date")
                .apply(
                    lambda g: pd.Series(
                        {
                            "total_trades": int(len(g)),
                            "filled_trades": int((g["status"] == "FILLED").sum()),
                            "rejected_trades": int((g["status"] == "REJECTED").sum()),
                            "unique_symbols": int(g["symbol"].nunique()),
                            "buy_notional": float(g.loc[g["side"] == "BUY", "notional"].sum()),
                            "sell_notional": float(g.loc[g["side"] == "SELL", "notional"].sum()),
                            "turnover": float(g["notional"].abs().sum()),
                            "avg_trade_price": float(g["price"].mean()),
                            "realized_pnl_proxy": float(g.loc[g["side"] == "SELL", "price"].sum() - g.loc[g["side"] == "BUY", "price"].sum()),
                        }
                    )
                )
                .reset_index()
                .sort_values("trade_date", ascending=False)
            )
            st.dataframe(daily_summary, width="stretch")
        else:
            st.info("No daily trade summary is available for the selected date range.")

        st.markdown("#### Bought vs Sold by Symbol")
        if not filtered_trades.empty:
            by_symbol = (
                filtered_trades.assign(
                    quantity=pd.to_numeric(filtered_trades["quantity"], errors="coerce").fillna(0.0),
                    price=pd.to_numeric(filtered_trades["price"], errors="coerce").fillna(0.0),
                )
                .assign(notional=lambda d: d["quantity"] * d["price"])
                .groupby("symbol")
                .apply(
                    lambda g: pd.Series(
                        {
                            "buy_qty": float(g.loc[g["side"] == "BUY", "quantity"].sum()),
                            "sell_qty": float(g.loc[g["side"] == "SELL", "quantity"].sum()),
                            "net_qty": float(g.loc[g["side"] == "BUY", "quantity"].sum() - g.loc[g["side"] == "SELL", "quantity"].sum()),
                            "buy_notional": float(g.loc[g["side"] == "BUY", "notional"].sum()),
                            "sell_notional": float(g.loc[g["side"] == "SELL", "notional"].sum()),
                        }
                    )
                )
                .reset_index()
                .sort_values("buy_notional", ascending=False)
            )
            st.dataframe(by_symbol, width="stretch")
        else:
            st.info("No bought/sold breakdown available for current filters.")

        st.markdown("#### Candle Tape (Selected Scope)")
        if not filtered_candles.empty:
            candle_view = filtered_candles.sort_values("bar_time").set_index("bar_time")
            st.line_chart(candle_view[["close", "vwap"]])
            if "volume" in candle_view.columns:
                st.bar_chart(candle_view[["volume"]])
        else:
            st.info("No persisted candle bars available for selected filters yet.")

        st.markdown("#### Open Position Ledger (Lot-Matched)")
        if not position_book_df.empty:
            st.dataframe(position_book_df, width="stretch")
        else:
            st.info("No filled trades available for lot-level position ledger.")

    with risk_tab:
        st.subheader("Risk, Correlation, and Execution Quality")

        r1, r2, r3 = st.columns(3)
        with r1:
            st.metric("Kill Switch Events", int(kpis["kill_events"]))
        with r2:
            st.metric("Regime Score", "-" if kpis["regime_score"] is None else int(kpis["regime_score"]))
        with r3:
            st.metric("Regime Mode", "-" if kpis["regime_mode"] is None else str(kpis["regime_mode"]))

        st.markdown("#### Regime History")
        if not filtered_regime.empty:
            st.line_chart(filtered_regime.set_index("created_at")["score"])
        else:
            st.info("No regime history records yet.")

        st.markdown("#### Correlation Heatmap")
        if not filtered_corr.empty:
            latest_corr = filtered_corr.sort_values("as_of", ascending=False).iloc[0]
            corr_symbols = latest_corr["symbols"] or []
            corr_matrix = latest_corr["matrix"] or {}
            if corr_symbols and corr_matrix:
                corr_df_view = pd.DataFrame(corr_matrix, index=corr_symbols, columns=corr_symbols)
                st.caption(f"As of {latest_corr['as_of']} | Window: {latest_corr['window_minutes'] or 'n/a'} min")
                st.dataframe(corr_df_view.style.background_gradient(cmap="RdBu_r"), width="stretch")
            else:
                st.info("Latest correlation matrix entry is empty.")
        else:
            st.info("No correlation matrices recorded for the selected date range.")

        st.markdown("#### Engine Allocation")
        if not engines_df.empty:
            display_df = engines_df[["name", "allocation_target", "enabled"]].copy()
            display_df["allocation_target"] = display_df["allocation_target"].fillna(0.0)
            st.dataframe(display_df, width="stretch")
        else:
            alloc_engine = AllocationEngine()
            default_allocs = {a.name: f"{int(a.allocation * 100)}%" for a in alloc_engine.get_allocations()}
            st.write(default_allocs)

        st.markdown("#### Risk Limit Utilization")
        u1, u2, u3, u4 = st.columns(4)
        with u1:
            st.metric("Daily Loss Limit", _fmt_pct(MAX_DAILY_LOSS))
        with u2:
            st.metric("Daily Loss Utilization", "-" if np.isnan(kpis["daily_loss_utilization"]) else _fmt_pct(kpis["daily_loss_utilization"]))
        with u3:
            st.metric("Weekly Drawdown Limit", _fmt_pct(MAX_WEEKLY_DRAWDOWN))
        with u4:
            st.metric("Drawdown Utilization", "-" if np.isnan(kpis["weekly_drawdown_utilization"]) else _fmt_pct(kpis["weekly_drawdown_utilization"]))

        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric("VaR(95) Limit", _fmt_pct(VAR_DAILY_95_LIMIT))
        with t2:
            st.metric("Estimated Daily VaR(95)", "-" if np.isnan(kpis["daily_var_95"]) else _fmt_pct(kpis["daily_var_95"]))
        with t3:
            st.metric("Snapshot Interval", "-" if np.isnan(kpis["snapshot_interval_min"]) else f"{kpis['snapshot_interval_min']:.1f} min")

        st.markdown("#### Timeframe & Candle Monitoring")
        dominant_interval = candle_kpis.get("dominant_interval")
        dominant_minutes = _interval_to_minutes(dominant_interval) if dominant_interval else float("nan")
        timeframe_df = pd.DataFrame(
            [
                {"Metric": "Configured Algo Run Interval", "Value": f"{int(ALGO_RUN_INTERVAL / 60)} min"},
                {"Metric": "Observed Median Trade Interval", "Value": "-" if np.isnan(kpis["trade_interval_min"]) else f"{kpis['trade_interval_min']:.1f} min"},
                {"Metric": "Observed Snapshot Interval", "Value": "-" if np.isnan(kpis["snapshot_interval_min"]) else f"{kpis['snapshot_interval_min']:.1f} min"},
                {"Metric": "Dominant Candle Interval", "Value": dominant_interval or "-"},
                {"Metric": "Dominant Candle Minutes", "Value": "-" if np.isnan(dominant_minutes) else f"{dominant_minutes:.0f} min"},
                {"Metric": "Candle Freshness", "Value": "-" if np.isnan(candle_kpis["freshness_min"]) else f"{candle_kpis['freshness_min']:.1f} min"},
                {"Metric": "Bullish Candle Ratio", "Value": "-" if np.isnan(candle_kpis["bullish_ratio"]) else _fmt_pct(candle_kpis["bullish_ratio"])},
            ]
        )
        st.dataframe(timeframe_df, width="stretch")

        st.markdown("#### Candle Structure KPIs")
        csk1, csk2, csk3, csk4 = st.columns(4)
        with csk1:
            st.metric("Median Range %", "-" if np.isnan(candle_kpis["median_range_pct"]) else _fmt_pct(candle_kpis["median_range_pct"]))
        with csk2:
            st.metric("Median Body %", "-" if np.isnan(candle_kpis["median_body_pct"]) else _fmt_pct(candle_kpis["median_body_pct"]))
        with csk3:
            st.metric("Avg Candle Volume", "-" if np.isnan(candle_kpis["avg_volume"]) else f"{candle_kpis['avg_volume']:.0f}")
        with csk4:
            st.metric("Symbols In Candle Feed", int(candle_kpis["symbols"]))

        st.markdown("#### Session Execution Quality")
        if not session_quality_df.empty:
            session_display = session_quality_df.copy()
            session_display["fill_ratio"] = session_display["fill_ratio"].apply(_fmt_pct)
            session_display["rejection_ratio"] = session_display["rejection_ratio"].apply(_fmt_pct)
            session_display["avg_order_qty"] = session_display["avg_order_qty"].apply(lambda v: f"{float(v):.1f}")
            st.dataframe(session_display, width="stretch")
        else:
            st.info("No session-level execution quality available yet.")

        st.markdown("#### Slippage & Timestamp Latency")
        e1, e2, e3, e4 = st.columns(4)
        with e1:
            st.metric("Median Adverse Slippage", "-" if np.isnan(execution_kpis["adverse_slippage_bps"]) else _fmt_bps(execution_kpis["adverse_slippage_bps"]))
        with e2:
            st.metric("P90 Adverse Slippage", "-" if np.isnan(execution_kpis["p90_adverse_slippage_bps"]) else _fmt_bps(execution_kpis["p90_adverse_slippage_bps"]))
        with e3:
            st.metric("Median Timestamp Latency", "-" if np.isnan(execution_kpis["timestamp_latency_sec"]) else f"{execution_kpis['timestamp_latency_sec']:.1f}s")
        with e4:
            st.metric("P90 Timestamp Latency", "-" if np.isnan(execution_kpis["p90_timestamp_latency_sec"]) else f"{execution_kpis['p90_timestamp_latency_sec']:.1f}s")
        st.caption(
            "Latency is measured as absolute gap between trade timestamp and nearest prior candle timestamp for the same symbol."
        )

    with governance_tab:
        st.subheader("Model Registry & Approval Workflow")
        st.markdown('<div class="section-note">Formal sign-off required with reviewer, ticket, and approval note for audit integrity.</div>', unsafe_allow_html=True)

        if not models_df.empty:
            st.dataframe(
                models_df[["model_name", "model_version", "stage", "active", "metrics", "created_at"]],
                width="stretch",
            )
        else:
            st.info("No models registered yet.")

        register_col, approve_col = st.columns(2)

        with register_col:
            st.markdown("#### Register Model")
            with st.form("register_model_form", clear_on_submit=False):
                model_name = st.text_input("Model name", value="")
                model_version = st.text_input("Model version", value="")
                config_hash = st.text_input("Config hash", value="")
                stage = st.selectbox("Stage", options=["research", "paper", "production", "retired"], index=0)
                notes = st.text_area("Notes", value="")

                metric_col1, metric_col2 = st.columns(2)
                with metric_col1:
                    paper_days = st.number_input("Paper days", min_value=0, value=0, step=1)
                    sharpe = st.number_input("Sharpe", value=0.0, step=0.1, format="%.2f")
                with metric_col2:
                    win_rate = st.number_input("Win rate", min_value=0.0, max_value=1.0, value=0.0, step=0.01, format="%.2f")
                    max_drawdown_pct = st.number_input("Max drawdown pct", min_value=0.0, max_value=1.0, value=0.0, step=0.01, format="%.2f")

                register_submit = st.form_submit_button("Register model")

                if register_submit:
                    if not model_name.strip() or not model_version.strip():
                        st.error("Model name and version are required.")
                    else:
                        register_model(
                            model_name=model_name.strip(),
                            model_version=model_version.strip(),
                            config_hash=config_hash.strip() or "n/a",
                            metrics={
                                "paper_days": float(paper_days),
                                "sharpe": float(sharpe),
                                "win_rate": float(win_rate),
                                "max_drawdown_pct": float(max_drawdown_pct),
                            },
                            stage=stage,
                            notes=notes.strip() or None,
                        )
                        load_model_registry.clear()
                        st.success("Model registered successfully.")

        with approve_col:
            st.markdown("#### Human Approval Sign-off")
            if models_df.empty:
                st.info("Register a model first to submit approval decisions.")
            else:
                model_options = [
                    f"{row.model_name}::{row.model_version}::{row.stage}"
                    for row in models_df.itertuples(index=False)
                ]
                with st.form("approval_form", clear_on_submit=False):
                    selected = st.selectbox("Model", options=model_options)
                    target_stage = st.selectbox(
                        "Target stage",
                        options=["paper", "production", "retired"],
                        index=1,
                    )
                    reviewer = st.text_input("Reviewer (human sign-off)", value="")
                    ticket_id = st.text_input("Ticket / Approval ID", value="")
                    approval_note = st.text_area("Approval note", value="")
                    decision = st.radio("Decision", options=["Approve", "Reject"], horizontal=True)
                    confirmed = st.checkbox("I confirm this is a human decision and audit entry")

                    approval_submit = st.form_submit_button("Submit decision")

                    if approval_submit:
                        selected_name, selected_version, _current_stage = selected.split("::", 2)
                        if not confirmed:
                            st.error("Please confirm human sign-off before submitting.")
                        else:
                            gate = review_model_promotion(
                                model_name=selected_name,
                                model_version=selected_version,
                                target_stage=target_stage,
                                decided_by=reviewer,
                                approve=decision == "Approve",
                                approval_note=approval_note,
                                ticket_id=ticket_id,
                            )
                            load_model_registry.clear()
                            load_model_promotion_events.clear()
                            if gate.approved:
                                st.success("Promotion approved and stage updated.")
                            else:
                                st.warning("Promotion not approved. Review gate checks below.")
                            st.json({"approved": gate.approved, "checks": gate.checks, "metrics": gate.metrics})

        st.markdown("#### Approval Audit Trail")
        if not filtered_promotions.empty:
            display_events = filtered_promotions.copy()
            display_events["gate_result"] = display_events["gate_result"].apply(
                lambda v: json.dumps(v, indent=2) if isinstance(v, dict) else str(v)
            )
            st.dataframe(
                display_events[
                    [
                        "created_at",
                        "model_name",
                        "model_version",
                        "from_stage",
                        "to_stage",
                        "approved",
                        "decided_by",
                        "gate_result",
                    ]
                ],
                width="stretch",
            )
        else:
            st.info("No promotion decisions recorded for the selected date range.")


if __name__ == "__main__":
    main()
