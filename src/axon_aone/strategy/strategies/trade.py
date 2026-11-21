"""Trading strategy and signal execution logic."""

import datetime
import logging

from axon_aone.config import (
    FORCE_EXIT_TIME,
    MAX_SWING_DAYS,
    MAX_SWING_POSITIONS,
    OVERNIGHT_PROFIT_VAULT,
    PROMOTION_CHECK_TIME,
    START_CAPITAL,
    INTRADAY_PROFIT_VAULT,
    TRADE_MODE,
)
from axon_aone.db import (
    CorrelationMatrix as DbCorrelationMatrix,
    KillSwitchLog as DbKillSwitchLog,
    RegimeHistory as DbRegimeHistory,
    SessionLocal,
    Trade as DbTrade,
)
from axon_aone.execution.broker import execute_trade
from axon_aone.portfolio.correlation import compute_correlation_from_universe
from axon_aone.risk.engine import PortfolioSnapshot, RiskEngine
from axon_aone.risk.kill_switch import KillSwitch
from axon_aone.services.order_store import append_scheduler_order
from axon_aone.services.telegram_notify import send_telegram_message
from axon_aone.strategy.regime import calculate_regime

logger = logging.getLogger(__name__)

state = {
    "total_capital": START_CAPITAL,
    "tradable_capital": START_CAPITAL,
    "investment_bucket": 0.0,
    "daily_pnl": 0.0,
    "weekly_pnl": 0.0,
    "open_trades": [],
    "swing_trades": [],
    "trade_log": [],
}


def _persist_regime(regime_state) -> None:
    try:
        session = SessionLocal()
        row = DbRegimeHistory(score=regime_state.score, mode=regime_state.mode.value)
        session.add(row)
        session.commit()
    except Exception as e:
        logger.error(f"Error persisting regime history: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def _persist_kill_switch(reason: str) -> None:
    try:
        session = SessionLocal()
        row = DbKillSwitchLog(reason=reason, active=True)
        session.add(row)
        session.commit()
    except Exception as e:
        logger.error(f"Error persisting kill-switch log: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def _persist_scheduler_trade(order: dict) -> None:
    try:
        session = SessionLocal()
        db_trade = DbTrade(
            external_id=order.get("id", ""),
            symbol=order.get("symbol", ""),
            side=order.get("side", ""),
            quantity=order.get("quantity", 0),
            order_type=order.get("order_type", ""),
            price=order.get("price"),
            status=order.get("status", ""),
            trade_mode=order.get("trade_mode", ""),
            broker="angel_one",
            broker_response=order.get("broker_response"),
        )
        session.add(db_trade)
        session.commit()
    except Exception as e:
        logger.error(f"Error persisting scheduler trade: {e}")
        try:
            session.rollback()
        except Exception:
            pass


def _persist_correlation_matrix(symbols, matrix, window_minutes: int) -> None:
    try:
        session = SessionLocal()
        row = DbCorrelationMatrix(symbols=list(symbols), matrix=matrix, window_minutes=window_minutes)
        session.add(row)
        session.commit()
    except Exception as e:
        logger.error(f"Error persisting correlation matrix: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def now():
    return datetime.datetime.now().time()


def kill_day(state_dict, risk_engine: RiskEngine):
    return state_dict["daily_pnl"] <= -risk_engine.max_daily_loss_pct * state_dict["total_capital"]


def apply_slippage(price, cap_type, side):
    slip = {"large": 0.0005, "mid": 0.0015, "small": 0.003, "etf": 0.0005}.get(cap_type, 0.001)
    return price * (1 + slip) if side == "BUY" else price * (1 - slip)


def market_allowed(index_trend_ok, volatility_ok):
    return index_trend_ok and volatility_ok


def trend_persistence(candles, lookback=3):
    if len(candles) < lookback:
        return False
    recent = candles[-lookback:]
    for candle in recent:
        if candle.get("close", 0) <= candle.get("vwap", 0):
            return False
    return True


def resumption_entry(candles):
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    if prev.get("close") is None or prev.get("vwap") is None:
        return False
    if prev["close"] > prev["vwap"]:
        return False
    return curr["close"] > prev["close"] and curr["low"] >= prev["low"]


def should_buy(stock, use_mock=False):
    if use_mock:
        candles = stock.get("candles", [])
        return trend_persistence(candles, lookback=2) if candles else False

    candles = stock.get("candles", [])
    vwap = stock.get("vwap", stock.get("price", 0))
    price = stock.get("price", 0)
    if price <= vwap:
        return False
    return trend_persistence(candles, lookback=3) or resumption_entry(candles)


def should_sell(position, current_price, use_mock=False):
    if use_mock:
        pl = (current_price - position.get("entry_price", 0)) / position.get("entry_price", 1)
        return pl >= 0.01 or pl <= -0.01

    stop_loss = position.get("stop_loss", 0)
    target = position.get("target", 0)
    if current_price <= stop_loss:
        return True
    if current_price >= target:
        return True
    if now() >= FORCE_EXIT_TIME:
        return True
    return False


def run_day(universe, use_mock=False):
    logger.info(f"Running trading algorithm for {len(universe)} symbols")

    index_ok = True
    volatility_ok = True
    regime_state = calculate_regime(index_trend_ok=index_ok, volatility_ok=volatility_ok)
    _persist_regime(regime_state)

    try:
        corr_result = compute_correlation_from_universe(universe, window=30)
        if corr_result is not None:
            _persist_correlation_matrix(
                symbols=corr_result.symbols,
                matrix=corr_result.matrix,
                window_minutes=corr_result.window_size,
            )
    except Exception as e:
        logger.error(f"Error computing correlation matrix: {e}")

    if not market_allowed(index_ok, volatility_ok):
        logger.info(
            "Market conditions not favorable for trading; "
            f"regime_score={regime_state.score}, mode={regime_state.mode.value}"
        )
        return

    risk_engine = RiskEngine()
    open_risk = 0.0
    for trade in state.get("open_trades", []):
        try:
            entry_price = float(trade.get("entry_price", 0.0))
            stop_loss = float(trade.get("stop_loss", 0.0))
            qty = int(trade.get("quantity", 0))
            open_risk += abs(entry_price - stop_loss) * qty
        except Exception:
            continue

    snapshot = PortfolioSnapshot(
        total_capital=state["total_capital"],
        tradable_capital=state["tradable_capital"],
        daily_pnl=state["daily_pnl"],
        weekly_pnl=state["weekly_pnl"],
    )
    snapshot.portfolio_heat = risk_engine.compute_portfolio_heat(open_risk=open_risk, snapshot=snapshot)
    kill_switch = KillSwitch()
    if kill_day(state, risk_engine):
        reason = "daily_loss_limit_reached"
        logger.warning(f"Daily loss limit reached ({reason}); skipping trading iteration")
        _persist_kill_switch(reason)
        return

    if kill_switch.check(snapshot=snapshot, regime=regime_state):
        reason = kill_switch.last_reason or "kill_switch_triggered"
        logger.warning(f"Kill switch active ({reason}); skipping trading iteration")
        _persist_kill_switch(reason)
        return

    for stock in universe:
        symbol = stock.get("symbol")
        if should_buy(stock, use_mock=use_mock):
            qty = 1
            logger.info(f"Buy signal for {symbol}")
            side = "BUY"
            order_type = "MARKET"
            price = None

            try:
                entry_price = stock.get("price", 0) or 0
                stop_price = entry_price * (0.99 if entry_price else 0)
                if not risk_engine.can_open_trade(
                    entry_price=entry_price,
                    stop_loss_price=stop_price,
                    quantity=qty,
                    snapshot=snapshot,
                ):
                    logger.info(f"RiskEngine blocked new trade for {symbol} due to risk limits")
                    continue

                result = execute_trade(
                    symbol=symbol,
                    quantity=qty,
                    side=side,
                    order_type=order_type,
                    price=price,
                    use_mock=use_mock,
                )
                status = result.get("status", "ERROR")

                if status is True or status in ["PAPER", "SUCCESS"]:
                    order_status = "FILLED"
                elif status is False or status in ["ERROR", "REJECTED"]:
                    order_status = "REJECTED"
                else:
                    order_status = "PENDING"

                timestamp = datetime.datetime.now().isoformat()
                order = {
                    "id": f"SCHED_{symbol}_{int(datetime.datetime.now().timestamp())}",
                    "symbol": symbol,
                    "quantity": qty,
                    "side": side,
                    "order_type": order_type,
                    "price": price,
                    "trade_mode": "mock" if use_mock else "live",
                    "status": order_status,
                    "timestamp": timestamp,
                    "filled_quantity": qty if order_status == "FILLED" else 0,
                    "average_price": 0.0,
                    "execution_time": timestamp if order_status == "FILLED" else None,
                    "broker_response": result,
                    "source": "scheduler",
                }

                _persist_scheduler_trade(order)
                append_scheduler_order(order)

                trade_mode_label = "MOCK" if use_mock else "LIVE"
                if order_status == "FILLED":
                    send_telegram_message(
                        f"[Axon][Scheduler] Order FILLED:\n"
                        f"ID: {order['id']}\n"
                        f"{side} {qty} {symbol} ({trade_mode_label})\n"
                        f"Type: {order_type}{f' @ {price}' if price else ''}"
                    )
                elif order_status == "REJECTED":
                    send_telegram_message(
                        f"[Axon][Scheduler] Order REJECTED:\n"
                        f"ID: {order['id']}\n"
                        f"{side} {qty} {symbol} ({trade_mode_label})\n"
                        f"Type: {order_type}{f' @ {price}' if price else ''}\n"
                        f"Reason: {result}"
                    )

            except Exception as e:
                logger.error(f"Error executing scheduled trade for {symbol}: {e}", exc_info=True)

    logger.debug("Trading algorithm iteration completed")
