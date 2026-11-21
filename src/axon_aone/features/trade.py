"""
Trading features and strategy execution module.
Implements the core trading logic and signal generation.
"""

import datetime
import json
import logging
from axon_aone.config import (
    TRADE_MODE,
    START_CAPITAL,
    MAX_RISK_PER_TRADE,
    MAX_DAILY_LOSS,
    MAX_WEEKLY_DRAWDOWN,
    MAX_CONCURRENT_TRADES,
    FORCE_EXIT_TIME,
    ENTRY_CUTOFF_TIME,
    PROMOTION_CHECK_TIME,
    INTRADAY_PROFIT_VAULT,
    OVERNIGHT_PROFIT_VAULT,
    MAX_SWING_POSITIONS,
    MAX_SWING_DAYS,
    RISK_CONFIG,
    FIXED_PROFIT_TARGET_PCT,
    PROFIT_PROTECT_ACTIVATION_PCT,
    PROFIT_PROTECT_DROP_PCT,
    MAX_NEW_ENTRIES_PER_CYCLE,
    MAX_CORRELATED_POSITIONS,
    CORRELATION_BLOCK_THRESHOLD,
    EXECUTION_MAX_SLIPPAGE_PCT,
)
from axon_aone.execution.broker import execute_trade, get_available_funds
from axon_aone.execution.oms import get_oms_service
from axon_aone.services.order_store import append_scheduler_order
from axon_aone.services.daily_deepdive import get_daily_deepdive_logger
from axon_aone.services.compliance import ComplianceGate, OrderRequest
from axon_aone.services.telegram_notify import send_telegram_message
from axon_aone.portfolio.allocation import AllocationEngine
from axon_aone.core.regime import calculate_regime
from axon_aone.core.risk_engine import PortfolioSnapshot, RiskEngine
from axon_aone.core.kill_switch import KillSwitch
from axon_aone.core.correlation import compute_correlation_from_universe
from axon_aone.db import (
    SessionLocal,
    Trade as DbTrade,
    RegimeHistory as DbRegimeHistory,
    KillSwitchLog as DbKillSwitchLog,
    CorrelationMatrix as DbCorrelationMatrix,
)

logger = logging.getLogger(__name__)

# ===== STATE =====
state = {
    "total_capital": START_CAPITAL,
    "tradable_capital": START_CAPITAL,
    "investment_bucket": 0.0,
    "vault_capital": 0.0,
    "daily_pnl": 0.0,
    "weekly_pnl": 0.0,
    "daily_realized_pnl": 0.0,
    "open_trades": [],
    "swing_trades": [],
    "trade_log": []
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_atr(candles, period: int = 14) -> float:
    """Calculate ATR from candle data using available OHLC values."""
    if not candles or len(candles) < 2:
        return 0.0

    true_ranges = []
    previous_close = None

    for candle in candles:
        high = _safe_float(candle.get("high"), _safe_float(candle.get("close")))
        low = _safe_float(candle.get("low"), _safe_float(candle.get("close")))
        close = _safe_float(candle.get("close"))

        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )

        if true_range > 0:
            true_ranges.append(true_range)
        previous_close = close

    if not true_ranges:
        return 0.0

    window = true_ranges[-period:]
    return sum(window) / len(window)


def calculate_stop_loss_price(entry_price: float, candles) -> float:
    """Derive a long stop-loss price from ATR and configured multiplier."""
    entry = _safe_float(entry_price)
    if entry <= 0:
        return 0.0

    atr = calculate_atr(candles)
    multiplier = _safe_float(RISK_CONFIG.get("STOP_LOSS_ATR_MULTIPLIER", 2.0), 2.0)
    if atr <= 0 or multiplier <= 0:
        return 0.0

    return max(0.0, entry - (atr * multiplier))


def calculate_position_size(entry_price: float, stop_loss_price: float, tradable_capital: float) -> int:
    """Size a position from risk budget and max-position limits."""
    try:
        entry = float(entry_price)
        stop = float(stop_loss_price)
        capital = float(tradable_capital)
    except (TypeError, ValueError):
        return 0

    if entry <= 0 or capital <= 0:
        return 0

    per_share_risk = abs(entry - stop)
    if per_share_risk <= 0:
        return 0

    max_risk_amount = capital * MAX_RISK_PER_TRADE
    if max_risk_amount <= 0:
        return 0

    max_position_pct = float(RISK_CONFIG.get("MAX_POSITION_PCT", 5.0)) / 100.0
    max_position_notional = capital * max_position_pct
    if max_position_notional <= 0:
        return 0

    qty_by_risk = int(max_risk_amount // per_share_risk)
    qty_by_notional = int(max_position_notional // entry)
    return max(0, min(qty_by_risk, qty_by_notional))


def calculate_profit_target_price(entry_price: float) -> float:
    """Return the fixed-percent profit target for a long position."""
    entry = _safe_float(entry_price)
    if entry <= 0:
        return 0.0

    target_pct = max(0.0, _safe_float(FIXED_PROFIT_TARGET_PCT))
    return entry * (1.0 + target_pct)


def normalize_order_status(status) -> str:
    """Map broker/mock responses to the UI-facing status set."""
    if status is True or status in ["PAPER", "SUCCESS"]:
        return "FILLED"
    if status is False or status in ["ERROR", "REJECTED"]:
        return "REJECTED"
    return "PENDING"


def reserve_capital_for_filled_order(symbol: str, quantity: int, entry_price: float, stop_loss_price: float) -> float:
    """Reserve capital for a filled opening trade and track it in state."""
    qty = max(0, int(quantity))
    fill_price = _safe_float(entry_price)
    stop_price = _safe_float(stop_loss_price)
    target_price = calculate_profit_target_price(fill_price)
    reserved_capital = max(0.0, qty * fill_price)
    if reserved_capital <= 0:
        return 0.0

    state["tradable_capital"] = max(0.0, _safe_float(state.get("tradable_capital")) - reserved_capital)
    state.setdefault("open_trades", []).append(
        {
            "symbol": symbol,
            "quantity": qty,
            "entry_price": fill_price,
            "stop_loss": stop_price,
            "target": target_price,
            "atr": abs(fill_price - stop_price),
            "allocated_capital": reserved_capital,
            "peak_price": fill_price,
            "opened_at": datetime.datetime.now().isoformat(),
        }
    )
    return reserved_capital


def release_capital_for_closed_trade(position: dict) -> float:
    """Release previously reserved capital when a position is closed."""
    released_capital = max(0.0, _safe_float(position.get("allocated_capital")))
    if released_capital <= 0:
        return 0.0

    state["tradable_capital"] = max(0.0, _safe_float(state.get("tradable_capital")) + released_capital)
    return released_capital


def _extract_rejection_reason(result: dict) -> str:
    """Extract a compact rejection reason from broker/mock response."""
    if not isinstance(result, dict):
        return "unknown"
    for key in ("message", "reason", "error", "status", "description"):
        value = result.get(key)
        if value:
            return str(value)
    return "unknown"


def _extract_fill_price(result: dict, fallback_price: float = 0.0) -> float:
    """Best-effort extraction of effective fill price from broker payload."""
    if not isinstance(result, dict):
        return _safe_float(fallback_price)

    for key in ("average_price", "fill_price", "price"):
        val = _safe_float(result.get(key), 0.0)
        if val > 0:
            return val

    payload = result.get("payload")
    if isinstance(payload, dict):
        for key in ("average_price", "fill_price", "price"):
            val = _safe_float(payload.get(key), 0.0)
            if val > 0:
                return val

    return _safe_float(fallback_price)


def _capture_profit_to_vault(realized_pnl: float, overnight: bool = False) -> float:
    """Move a configurable portion of realized profits into the vault bucket."""
    pnl = _safe_float(realized_pnl)
    if pnl <= 0:
        return 0.0

    vault_ratio = _safe_float(OVERNIGHT_PROFIT_VAULT if overnight else INTRADAY_PROFIT_VAULT)
    vault_ratio = min(1.0, max(0.0, vault_ratio))
    vaulted = pnl * vault_ratio

    if vaulted <= 0:
        return 0.0

    state["investment_bucket"] = _safe_float(state.get("investment_bucket")) + vaulted
    state["vault_capital"] = _safe_float(state.get("vault_capital")) + vaulted
    state["tradable_capital"] = max(0.0, _safe_float(state.get("tradable_capital")) - vaulted)
    return vaulted


def effective_entry_cutoff_time() -> datetime.time:
    """Return the configured last time new entries are allowed."""
    cutoff = ENTRY_CUTOFF_TIME or FORCE_EXIT_TIME
    return cutoff if cutoff <= FORCE_EXIT_TIME else FORCE_EXIT_TIME


def entry_cutoff_reached(current_time=None) -> bool:
    """True when the scheduler should stop opening new positions for the day."""
    current = current_time or now()
    return current >= effective_entry_cutoff_time()


def _estimate_order_notional(entry_price: float, quantity: int) -> float:
    """Return the estimated capital needed for a market buy order."""
    price = max(0.0, _safe_float(entry_price))
    qty = max(0, int(quantity))
    return price * qty


def _format_time_label(value: datetime.time) -> str:
    """Format scheduler times consistently for logs."""
    return value.strftime("%H:%M")


def _is_insufficient_funds_response(response) -> bool:
    """Best-effort check for broker rejections caused by lack of funds."""
    if response is None:
        return False

    candidates = []
    if isinstance(response, dict):
        for key in ("message", "reason", "error", "description", "status"):
            value = response.get(key)
            if value:
                candidates.append(str(value))
        payload = response.get("payload")
        if payload:
            try:
                candidates.append(json.dumps(payload))
            except TypeError:
                candidates.append(str(payload))
    else:
        candidates.append(str(response))

    haystack = " ".join(candidates).lower()
    return any(token in haystack for token in ("insufficient", "lack of funds", "not enough funds", "rms"))


def _symbol_allocated_capital(symbol: str) -> float:
    """Sum currently allocated capital for a symbol across open trades."""
    total = 0.0
    for trade in state.get("open_trades", []):
        if trade.get("symbol") == symbol:
            total += max(0.0, _safe_float(trade.get("allocated_capital")))
    return total


def _correlation_blocks_new_entry(
    symbol: str,
    open_symbols: list[str],
    correlation_matrix: dict | None,
    threshold: float,
    max_correlated_positions: int,
) -> bool:
    """Block new entries when too many highly-correlated open positions exist."""
    if not correlation_matrix or not open_symbols:
        return False

    row = correlation_matrix.get(symbol)
    if not isinstance(row, dict):
        return False

    highly_correlated = 0
    for other in open_symbols:
        if other == symbol:
            continue
        corr = _safe_float(row.get(other), 0.0)
        if abs(corr) >= threshold:
            highly_correlated += 1
            if highly_correlated >= max_correlated_positions:
                return True

    return False


def _persist_regime(regime_state) -> None:
    """Best-effort persistence of regime state for this run."""
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
    """Best-effort persistence of kill-switch activations."""
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
    """Best-effort persistence of a scheduler-generated trade."""
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
            atr=order.get("atr"),
            reserved_capital=order.get("reserved_capital"),
            opportunity_score=order.get("opportunity_score"),
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
    """Best-effort persistence of a correlation matrix snapshot."""
    try:
        session = SessionLocal()
        row = DbCorrelationMatrix(
            symbols=list(symbols),
            matrix=matrix,
            window_minutes=window_minutes,
        )
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


# ===== UTILITIES =====
def now():
    """Get current time."""
    return datetime.datetime.now().time()


def kill_day(state_dict):
    """Check if daily loss limit exceeded."""
    return state_dict["daily_pnl"] <= -MAX_DAILY_LOSS * state_dict["total_capital"]


def apply_slippage(price, cap_type, side):
    """Apply slippage to price."""
    slip = {
        "large": 0.0005,
        "mid": 0.0015,
        "small": 0.003,
        "etf": 0.0005
    }.get(cap_type, 0.001)

    return price * (1 + slip) if side == "BUY" else price * (1 - slip)


# ===== MARKET CONTEXT =====
def market_allowed(index_trend_ok, volatility_ok):
    """Check if market conditions allow trading."""
    return index_trend_ok and volatility_ok


# ===== TREND ANALYSIS =====
def trend_persistence(candles, lookback=3):
    """Check for persistent uptrend."""
    if len(candles) < lookback:
        return False

    recent = candles[-lookback:]
    for c in recent:
        if c.get("close", 0) <= c.get("vwap", 0):
            return False
    return True


def resumption_entry(candles):
    """Check for resumption entry signal."""
    if len(candles) < 2:
        return False
    
    prev, curr = candles[-2], candles[-1]
    if prev.get("close") is None or prev.get("vwap") is None:
        return False
    if prev["close"] > prev["vwap"]:
        return False
    return curr["close"] > prev["close"] and curr["low"] >= prev["low"]


# ===== SIGNAL ENGINE =====
def should_buy(stock, use_mock=False):
    """
    Determine if a stock should be bought.
    
    Args:
        stock: Stock data dict with price, candles, etc.
        use_mock: If True, use simpler logic for mock mode
    
    Returns:
        True if buy signal triggered, False otherwise
    """
    if use_mock:
        # Simple mock logic
        candles = stock.get("candles", [])
        return trend_persistence(candles, lookback=2) if candles else False
    
    candles = stock.get("candles", [])
    vwap = stock.get("vwap", stock.get("price", 0))
    price = stock.get("price", 0)
    
    # Buy only if price is above VWAP and trend persists
    if price <= vwap:
        return False
    
    return trend_persistence(candles, lookback=3) or resumption_entry(candles)


def should_sell(position, current_price, use_mock=False, regime_state=None):
    """
    Determine if a position should be sold.
    
    Args:
        position: Position dict with entry_price, stop_loss, etc.
        current_price: Current market price
        use_mock: If True, use simpler logic for mock mode
    
    Returns:
        True if sell signal triggered, False otherwise
    """
    if use_mock:
        # Simple mock logic - sell at 1% profit or stop loss
        pl = (current_price - position.get("entry_price", 0)) / position.get("entry_price", 1)
        return pl >= 0.01 or pl <= -0.01
    
    entry_price = position.get("entry_price", 0)
    stop_loss = position.get("stop_loss", 0)
    target = position.get("target", 0)
    
    # Sell at stop loss or target
    if stop_loss and current_price <= stop_loss:
        return True
    if target and current_price >= target:
        return True

    # Profit-protection: after a healthy move up, exit if price drops sharply
    # from peak while regime is no longer supportive.
    peak_price = _safe_float(position.get("peak_price"), entry_price)
    activation_gain = max(0.0, _safe_float(PROFIT_PROTECT_ACTIVATION_PCT, 0.10))
    drop_from_peak = max(0.0, _safe_float(PROFIT_PROTECT_DROP_PCT, 0.05))
    if entry_price > 0 and peak_price > 0 and current_price > 0:
        gain_from_entry = (peak_price - entry_price) / entry_price
        drawdown_from_peak = (peak_price - current_price) / peak_price
        regime_mode = getattr(regime_state, "mode", None)
        regime_mode_value = getattr(regime_mode, "value", regime_mode)
        regime_bad = regime_state is not None and regime_mode_value != "bull"
        if gain_from_entry >= activation_gain and drawdown_from_peak >= drop_from_peak and regime_bad:
            return True
    
    # Sell at market close
    if now() >= FORCE_EXIT_TIME:
        return True
    
    return False


def run_day(universe, use_mock=False):
    """
    Run the trading algorithm for a day.
    
    Args:
        universe: List of stock data dicts from market data feed
        use_mock: If True, run in mock/paper trading mode
    """
    logger.info(f"Running trading algorithm for {len(universe)} symbols")
    compliance_gate = ComplianceGate()
    oms = get_oms_service()
    metrics = {
        "buy_signals": 0,
        "entry_attempts": 0,
        "entry_filled": 0,
        "entry_rejected": 0,
        "exit_attempts": 0,
        "exit_filled": 0,
        "exit_rejected": 0,
        "kill_switch_triggers": 0,
        "exception_count": 0,
        "skip_reasons": {},
        "reject_reasons": {},
        "realized_pnl": 0.0,
        "vaulted_profit": 0.0,
        "slippage_alerts": 0,
        "slippage_bps_samples": [],
        "portfolio_heat": None,
    }

    def _note_skip(reason: str) -> None:
        skip = metrics["skip_reasons"]
        skip[reason] = int(skip.get(reason, 0)) + 1

    def _note_reject(side: str, result: dict) -> None:
        reason = _extract_rejection_reason(result)
        reject = metrics["reject_reasons"]
        key = f"{side}:{reason}"
        reject[key] = int(reject.get(key, 0)) + 1

    # Compute a simple regime state (currently using placeholder
    # booleans; can be extended to use real market data).
    index_ok = True  # TODO: derive from index candles
    volatility_ok = True  # TODO: derive from volatility metrics
    regime_state = calculate_regime(index_trend_ok=index_ok, volatility_ok=volatility_ok)
    _persist_regime(regime_state)

    # Compute and persist a simple rolling correlation matrix from the
    # universe, if enough candle data is available.
    corr_matrix = None
    try:
        corr_result = compute_correlation_from_universe(universe, window=30)
        if corr_result is not None:
            corr_matrix = corr_result.matrix
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

    # Build a snapshot for the risk engine / kill switch.
    risk_engine = RiskEngine()
    allocation_engine = AllocationEngine()

    # Approximate open risk from open_trades using entry/stop/quantity
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

    return_samples = []
    exposure_notional = 0.0
    stress_positions = []
    for stock in universe:
        candles = stock.get("candles", []) or []
        closes = [_safe_float(c.get("close")) for c in candles if _safe_float(c.get("close")) > 0]
        if len(closes) >= 2:
            for idx in range(1, min(len(closes), 6)):
                prev_close = closes[-(idx + 1)]
                last_close = closes[-idx]
                if prev_close > 0:
                    return_samples.append((last_close - prev_close) / prev_close)

    for trade in state.get("open_trades", []):
        qty = int(trade.get("quantity", 0) or 0)
        entry = _safe_float(trade.get("entry_price"))
        if qty > 0 and entry > 0:
            exposure_notional += qty * entry
            stress_positions.append({"quantity": qty, "entry_price": entry})

    snapshot.var_95 = risk_engine.compute_var_95(
        returns=return_samples,
        exposure_notional=exposure_notional,
        capital=max(1.0, snapshot.total_capital),
    )
    snapshot.stress_loss_pct = risk_engine.compute_stress_loss_pct(
        open_positions=stress_positions,
        stress_drop_pct=risk_engine.stress_scenario_loss_limit,
        capital=max(1.0, snapshot.total_capital),
    )
    snapshot.portfolio_heat = risk_engine.compute_portfolio_heat(open_risk=open_risk, snapshot=snapshot)
    kill_switch = KillSwitch()

    if kill_switch.check(snapshot=snapshot, regime=regime_state):
        reason = kill_switch.last_reason or "kill_switch_triggered"
        metrics["kill_switch_triggers"] += 1
        _note_skip(reason)
        logger.warning(f"Kill switch active ({reason}); skipping trading iteration")
        _persist_kill_switch(reason)
        metrics["portfolio_heat"] = snapshot.portfolio_heat
        get_daily_deepdive_logger().record_iteration(
            metrics=metrics,
            state=state,
            mode="mock" if use_mock else "live",
        )
        return

    live_available_funds = None
    if not use_mock:
        live_available_funds = get_available_funds(use_mock=False)
        if live_available_funds is not None:
            snapshot.tradable_capital = min(snapshot.tradable_capital, live_available_funds)
            logger.info(
                f"Broker-reported available funds: {live_available_funds:.2f}; "
                f"effective tradable capital {snapshot.tradable_capital:.2f}"
            )
        else:
            logger.warning("Broker available funds unavailable; falling back to internal tradable_capital")
    
    # Check for buy signals
    price_by_symbol = {
        stock.get("symbol"): _safe_float(stock.get("price"))
        for stock in universe
        if stock.get("symbol")
    }

    for position in list(state.get("open_trades", [])):
        symbol = position.get("symbol")
        current_price = price_by_symbol.get(symbol, 0.0)
        if current_price <= 0:
            _note_skip("missing_current_price")
            continue

        # Track peak for profit-protection logic.
        peak_price = _safe_float(position.get("peak_price"), _safe_float(position.get("entry_price")))
        if current_price > peak_price:
            position["peak_price"] = current_price

        if not should_sell(position, current_price, use_mock=use_mock, regime_state=regime_state):
            continue

        qty = int(position.get("quantity", 0))
        if qty <= 0:
            continue

        try:
            metrics["exit_attempts"] += 1
            exit_order_id = f"SCHED_EXIT_{symbol}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            oms_result = oms.submit_order(
                order_id=exit_order_id,
                symbol=symbol,
                quantity=qty,
                side="SELL",
                order_type="MARKET",
                price=None,
                use_mock=use_mock,
                executor=execute_trade,
            )
            result = oms_result.response

            order_status = normalize_order_status(result.get("status", "ERROR"))
            timestamp = datetime.datetime.now().isoformat()
            released_capital = 0.0
            realized_pnl = 0.0
            vaulted_profit = 0.0
            if order_status == "FILLED":
                metrics["exit_filled"] += 1
                released_capital = release_capital_for_closed_trade(position)
                fill_price = _extract_fill_price(result, fallback_price=current_price)
                if fill_price > 0 and current_price > 0:
                    slippage_bps = abs((fill_price - current_price) / current_price) * 10000.0
                    metrics["slippage_bps_samples"].append(slippage_bps)
                    if slippage_bps >= (EXECUTION_MAX_SLIPPAGE_PCT * 100.0):
                        metrics["slippage_alerts"] += 1

                entry_price = _safe_float(position.get("entry_price"))
                realized_pnl = (fill_price - entry_price) * qty if entry_price > 0 else 0.0
                state["daily_pnl"] = _safe_float(state.get("daily_pnl")) + realized_pnl
                state["weekly_pnl"] = _safe_float(state.get("weekly_pnl")) + realized_pnl
                state["daily_realized_pnl"] = _safe_float(state.get("daily_realized_pnl")) + realized_pnl
                state["total_capital"] = _safe_float(state.get("total_capital")) + realized_pnl
                state["tradable_capital"] = _safe_float(state.get("tradable_capital")) + realized_pnl

                vaulted_profit = _capture_profit_to_vault(realized_pnl)
                metrics["realized_pnl"] += realized_pnl
                metrics["vaulted_profit"] += vaulted_profit
                try:
                    state["open_trades"].remove(position)
                except ValueError:
                    pass
                snapshot.tradable_capital = state["tradable_capital"]
                open_risk = max(0.0, open_risk - abs(_safe_float(position.get("entry_price")) - _safe_float(position.get("stop_loss"))) * qty)
                snapshot.portfolio_heat = risk_engine.compute_portfolio_heat(open_risk=open_risk, snapshot=snapshot)

            exit_order = {
                "id": exit_order_id,
                "symbol": symbol,
                "quantity": qty,
                "side": "SELL",
                "order_type": "MARKET",
                "price": None,
                "trade_mode": "mock" if use_mock else "live",
                "status": order_status,
                "timestamp": timestamp,
                "filled_quantity": qty if order_status == "FILLED" else 0,
                "average_price": current_price if order_status == "FILLED" else 0.0,
                "execution_time": timestamp if order_status == "FILLED" else None,
                "broker_response": result,
                "source": "scheduler",
                "atr": position.get("atr"),
                "reserved_capital": -released_capital if released_capital else 0.0,
                "realized_pnl": realized_pnl,
                "vaulted_profit": vaulted_profit,
            }

            _persist_scheduler_trade(exit_order)
            append_scheduler_order(exit_order)

            trade_mode_label = "MOCK" if use_mock else "LIVE"
            if order_status == "FILLED":
                send_telegram_message(
                    f"[Axon][Scheduler] Exit FILLED:\n"
                    f"ID: {exit_order['id']}\n"
                    f"SELL {qty} {symbol} ({trade_mode_label})\n"
                    f"Released Capital: {released_capital:.2f}\n"
                    f"Realized PnL: {realized_pnl:.2f} | Vaulted: {vaulted_profit:.2f}"
                )
            elif order_status == "REJECTED":
                metrics["exit_rejected"] += 1
                _note_reject("exit", result)
                send_telegram_message(
                    f"[Axon][Scheduler] Exit REJECTED:\n"
                    f"ID: {exit_order['id']}\n"
                    f"SELL {qty} {symbol} ({trade_mode_label})\n"
                    f"Reason: {result}"
                )
        except Exception as e:
            metrics["exception_count"] += 1
            logger.error(f"Error executing exit trade for {symbol}: {e}", exc_info=True)

    buy_signals = 0
    open_symbols = {
        str(position.get("symbol", "")).strip()
        for position in state.get("open_trades", [])
        if str(position.get("symbol", "")).strip()
    }
    filled_entries_this_cycle = 0
    current_sector_exposure = {}
    for trade in state.get("open_trades", []):
        sector = str(trade.get("sector") or "UNKNOWN")
        current_sector_exposure[sector] = current_sector_exposure.get(sector, 0.0) + (
            _safe_float(trade.get("entry_price")) * max(0, int(trade.get("quantity", 0)))
        )
    allocation_plan = allocation_engine.build_allocation_plan(
        candidates=universe,
        total_capital=snapshot.total_capital,
        current_sector_exposure=current_sector_exposure,
    )

    if entry_cutoff_reached():
        logger.info(
            f"Entry cutoff reached at {_format_time_label(effective_entry_cutoff_time())}; "
            "skipping new buy orders"
        )
    else:
        for stock in universe:
            symbol = stock.get("symbol")
            if symbol in open_symbols:
                continue
            if not should_buy(stock, use_mock=use_mock):
                continue

            buy_signals += 1
            metrics["buy_signals"] += 1
            logger.info(f"Buy signal for {symbol}")

            if len(state.get("open_trades", [])) >= MAX_CONCURRENT_TRADES:
                _note_skip("max_concurrent_trades")
                continue
            if filled_entries_this_cycle >= MAX_NEW_ENTRIES_PER_CYCLE:
                _note_skip("max_new_entries_per_cycle")
                continue
            if symbol not in allocation_plan:
                _note_skip("optimizer_constraint_block")
                continue

            side = "BUY"
            order_type = "MARKET"
            price = None

            try:
                entry_price = stock.get("price", 0) or 0
                stop_price = calculate_stop_loss_price(entry_price=entry_price, candles=stock.get("candles", []))
                if stop_price <= 0 or stop_price >= entry_price:
                    _note_skip("stop_loss_unavailable")
                    logger.info(f"Skipping {symbol}: unable to derive ATR-based stop loss")
                    continue

                effective_tradable_capital = snapshot.tradable_capital
                if live_available_funds is not None:
                    effective_tradable_capital = min(effective_tradable_capital, live_available_funds)

                qty = calculate_position_size(
                    entry_price=entry_price,
                    stop_loss_price=stop_price,
                    tradable_capital=effective_tradable_capital,
                )
                plan_max_notional = allocation_plan[symbol].max_notional
                qty = min(qty, int(plan_max_notional // max(entry_price, 1e-9)))
                if live_available_funds is not None and entry_price > 0:
                    qty = min(qty, int(live_available_funds // entry_price))

                if qty <= 0:
                    _note_skip("position_size_zero")
                    logger.info(
                        f"Skipping {symbol}: computed position size is 0 with effective capital {effective_tradable_capital:.2f}"
                    )
                    continue

                required_capital = _estimate_order_notional(entry_price, qty)
                if live_available_funds is not None and required_capital > live_available_funds:
                    _note_skip("broker_funds_insufficient")
                    logger.info(
                        f"Skipping {symbol}: required capital {required_capital:.2f} exceeds broker funds {live_available_funds:.2f}"
                    )
                    continue

                max_symbol_capital = snapshot.total_capital * (float(RISK_CONFIG.get("MAX_POSITION_PCT", 5.0)) / 100.0)
                if (_symbol_allocated_capital(symbol) + (entry_price * qty)) > max_symbol_capital:
                    _note_skip("symbol_concentration_limit")
                    logger.info(f"Skipping {symbol}: concentration limit reached")
                    continue

                compliance_decision = compliance_gate.evaluate(
                    OrderRequest(
                        symbol=symbol,
                        side=side,
                        quantity=qty,
                        price=entry_price,
                        total_capital=snapshot.total_capital,
                        tradable_capital=snapshot.tradable_capital,
                    ),
                    open_trade_count=len(state.get("open_trades", [])),
                )
                if not compliance_decision.allowed:
                    _note_skip("compliance_block")
                    for reason in compliance_decision.reasons:
                        _note_skip(f"compliance:{reason}")
                    logger.info("Compliance blocked %s: %s", symbol, ",".join(compliance_decision.reasons))
                    continue

                if _correlation_blocks_new_entry(
                    symbol=symbol,
                    open_symbols=list(open_symbols),
                    correlation_matrix=corr_matrix,
                    threshold=CORRELATION_BLOCK_THRESHOLD,
                    max_correlated_positions=MAX_CORRELATED_POSITIONS,
                ):
                    _note_skip("correlation_limit")
                    logger.info(f"Skipping {symbol}: highly correlated book concentration")
                    continue

                if not risk_engine.can_open_trade(
                    entry_price=entry_price,
                    stop_loss_price=stop_price,
                    quantity=qty,
                    snapshot=snapshot,
                ):
                    _note_skip("risk_engine_block")
                    logger.info(f"RiskEngine blocked new trade for {symbol} due to risk limits")
                    continue

                metrics["entry_attempts"] += 1
                order_id = f"SCHED_{symbol}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                oms_result = oms.submit_order(
                    order_id=order_id,
                    symbol=symbol,
                    quantity=qty,
                    side=side,
                    order_type=order_type,
                    price=price,
                    use_mock=use_mock,
                    executor=execute_trade,
                )
                result = oms_result.response

                order_status = normalize_order_status(result.get("status", "ERROR"))
                if order_status == "FILLED":
                    metrics["entry_filled"] += 1
                    filled_entries_this_cycle += 1
                elif order_status == "REJECTED":
                    metrics["entry_rejected"] += 1
                    _note_reject("entry", result)

                timestamp = datetime.datetime.now().isoformat()
                atr = abs(entry_price - stop_price)
                order = {
                    "id": order_id,
                    "symbol": symbol,
                    "quantity": qty,
                    "side": side,
                    "order_type": order_type,
                    "price": price,
                    "trade_mode": "mock" if use_mock else "live",
                    "status": order_status,
                    "timestamp": timestamp,
                    "filled_quantity": qty if order_status == "FILLED" else 0,
                    "average_price": entry_price if order_status == "FILLED" else 0.0,
                    "execution_time": timestamp if order_status == "FILLED" else None,
                    "broker_response": result,
                    "source": "scheduler",
                    "atr": atr,
                    "reserved_capital": 0.0,
                    "target": calculate_profit_target_price(entry_price),
                    "opportunity_score": stock.get("opportunity_score"),
                }

                if order_status == "FILLED":
                    fill_price = _extract_fill_price(result, fallback_price=entry_price)
                    if fill_price > 0 and entry_price > 0:
                        slippage_bps = abs((fill_price - entry_price) / entry_price) * 10000.0
                        metrics["slippage_bps_samples"].append(slippage_bps)
                        if slippage_bps >= (EXECUTION_MAX_SLIPPAGE_PCT * 100.0):
                            metrics["slippage_alerts"] += 1
                    reserved_capital = reserve_capital_for_filled_order(
                        symbol=symbol,
                        quantity=qty,
                        entry_price=fill_price,
                        stop_loss_price=stop_price,
                    )
                    if state.get("open_trades"):
                        state["open_trades"][-1]["sector"] = str(stock.get("sector") or "UNKNOWN")
                    open_symbols.add(symbol)
                    if live_available_funds is not None:
                        live_available_funds = max(0.0, live_available_funds - reserved_capital)
                    snapshot.tradable_capital = state["tradable_capital"]
                    if live_available_funds is not None:
                        snapshot.tradable_capital = min(snapshot.tradable_capital, live_available_funds)
                    open_risk += abs(fill_price - stop_price) * qty
                    snapshot.portfolio_heat = risk_engine.compute_portfolio_heat(
                        open_risk=open_risk,
                        snapshot=snapshot,
                    )
                    order["reserved_capital"] = reserved_capital
                    logger.info(
                        f"Reserved capital for {symbol}: {reserved_capital:.2f}; "
                        f"tradable_capital now {state['tradable_capital']:.2f}"
                    )
                elif not use_mock and _is_insufficient_funds_response(result):
                    refreshed_funds = get_available_funds(use_mock=False)
                    if refreshed_funds is not None:
                        live_available_funds = max(0.0, _safe_float(refreshed_funds, 0.0))
                        snapshot.tradable_capital = min(state["tradable_capital"], live_available_funds)
                        logger.warning(
                            f"Broker rejected BUY for {symbol} due to funds; refreshed available funds {live_available_funds:.2f}"
                        )

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
                metrics["exception_count"] += 1
                logger.error(f"Error executing scheduled trade for {symbol}: {e}", exc_info=True)

    if buy_signals == 0:
        zero_price_symbols = sum(1 for s in universe if (s.get("price") or 0) == 0)
        if zero_price_symbols:
            _note_skip("universe_price_zero")
            logger.warning(
                f"No buy signals generated; {zero_price_symbols}/{len(universe)} symbols have price=0 (check quote parsing)"
            )
        else:
            _note_skip("no_buy_signal")
            logger.info("No buy signals generated this iteration")
    
    # Check for sell signals on existing positions
    # Would check against open_trades list
    if metrics["slippage_bps_samples"]:
        metrics["avg_slippage_bps"] = sum(metrics["slippage_bps_samples"]) / len(metrics["slippage_bps_samples"])
    else:
        metrics["avg_slippage_bps"] = 0.0
    metrics["portfolio_heat"] = snapshot.portfolio_heat
    get_daily_deepdive_logger().record_iteration(
        metrics=metrics,
        state=state,
        mode="mock" if use_mock else "live",
    )
    logger.debug(f"Trading algorithm iteration completed")
