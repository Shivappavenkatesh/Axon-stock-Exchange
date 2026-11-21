"""
Market data feed module for Angel One Smart API.
Fetches and processes real-time and historical market data.
"""

import logging
from datetime import datetime, timedelta
import threading
from datetime import datetime, timedelta
import threading
from typing import List, Dict, Any
from axon_aone.db import SessionLocal, Trade, SymbolSelection, CandleBar
from axon_aone.config import (
    TRACKED_SYMBOLS,
    ACTIVE_BROKER,
    BROKER_CREDENTIALS,
    get_exchange_token,
    get_market_scan_symbols,
    ANGEL_ONE_INTRADAY_INTERVAL_MINUTES,
    AUTO_SELECT_SYMBOLS,
    AUTO_SELECT_TOP_N,
    MARKET_SCAN_BATCH_SIZE,
    SYMBOL_SELECTION_MIN_SCORE,
    SYMBOL_SELECTION_RELATIVE_TO_BEST,
    LEARNING_MIN_CLOSED_TRADES,
)
from axon_aone.brokers import get_broker

logger = logging.getLogger(__name__)
_market_scan_cursor = 0
_market_scan_lock = threading.Lock()


def _get_open_trade_symbols() -> set[str]:
    """Return currently open symbols from the in-process trading state."""
    try:
        from axon_aone.features.trade import state as trade_state

        return {
            str(position.get("symbol", "")).strip()
            for position in trade_state.get("open_trades", [])
            if str(position.get("symbol", "")).strip()
        }
    except Exception:
        return set()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_candle_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def persist_candles(symbol: str, interval: str, candles: List[Dict[str, Any]], broker: str) -> None:
    """Persist candle bars for dashboard analytics and timeframe monitoring."""
    if not candles:
        return

    parsed_rows: List[Dict[str, Any]] = []
    for candle in candles:
        bar_time = _parse_candle_timestamp(candle.get("timestamp"))
        if bar_time is None:
            continue

        parsed_rows.append(
            {
                "bar_time": bar_time,
                "open": _safe_float(candle.get("open")),
                "high": _safe_float(candle.get("high")),
                "low": _safe_float(candle.get("low")),
                "close": _safe_float(candle.get("close")),
                "volume": _safe_float(candle.get("volume")),
                "vwap": _safe_float(candle.get("vwap"), _safe_float(candle.get("close"))),
            }
        )

    if not parsed_rows:
        return

    session = SessionLocal()
    try:
        times = [row["bar_time"] for row in parsed_rows]
        existing_times = {
            row[0]
            for row in session.query(CandleBar.bar_time)
            .filter(
                CandleBar.symbol == symbol,
                CandleBar.interval == str(interval),
                CandleBar.broker == broker,
                CandleBar.bar_time.in_(times),
            )
            .all()
        }

        for row in parsed_rows:
            if row["bar_time"] in existing_times:
                continue
            session.add(
                CandleBar(
                    symbol=symbol,
                    interval=str(interval),
                    broker=broker,
                    bar_time=row["bar_time"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    vwap=row["vwap"],
                )
            )
        session.commit()
    except Exception as exc:
        logger.warning("Unable to persist candles for %s: %s", symbol, exc)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def _calculate_atr_from_candles(candles: List[Dict[str, Any]], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0

    true_ranges: List[float] = []
    previous_close = None
    for candle in candles:
        high = _safe_float(candle.get("high"), _safe_float(candle.get("close")))
        low = _safe_float(candle.get("low"), _safe_float(candle.get("close")))
        close = _safe_float(candle.get("close"))

        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))

        if true_range > 0:
            true_ranges.append(true_range)
        previous_close = close

    if not true_ranges:
        return 0.0

    window = true_ranges[-period:]
    return sum(window) / len(window)


def _load_symbol_feedback() -> Dict[str, Dict[str, float]]:
    """Load simple realized-performance feedback per symbol from trade history."""
    session = SessionLocal()
    try:
        trades = (
            session.query(Trade)
            .filter(Trade.status == "FILLED")
            .order_by(Trade.created_at.asc(), Trade.id.asc())
            .all()
        )
    except Exception as exc:
        logger.warning("Unable to load trade feedback for symbol ranking: %s", exc)
        return {}
    finally:
        try:
            session.close()
        except Exception:
            pass

    feedback: Dict[str, Dict[str, float]] = {}
    open_positions: Dict[str, List[Dict[str, float]]] = {}

    for trade in trades:
        symbol = trade.symbol
        side = (trade.side or "").upper()
        quantity = int(trade.quantity or 0)
        price = _safe_float(trade.average_price if hasattr(trade, "average_price") else None, _safe_float(trade.price))
        if quantity <= 0 or price <= 0:
            continue

        stats = feedback.setdefault(
            symbol,
            {
                "closed_trades": 0.0,
                "wins": 0.0,
                "total_pnl": 0.0,
                "avg_pnl_pct": 0.0,
            },
        )

        if side == "BUY":
            open_positions.setdefault(symbol, []).append({"quantity": quantity, "price": price})
            continue

        if side != "SELL":
            continue

        remaining = quantity
        buy_lots = open_positions.get(symbol, [])
        realized_pnl = 0.0
        matched_qty = 0

        while remaining > 0 and buy_lots:
            lot = buy_lots[0]
            matched = min(remaining, int(lot["quantity"]))
            realized_pnl += (price - lot["price"]) * matched
            matched_qty += matched
            lot["quantity"] -= matched
            remaining -= matched
            if lot["quantity"] <= 0:
                buy_lots.pop(0)

        if matched_qty <= 0:
            continue

        # Reconstruct cost basis from realized pnl relation using matched lots.
        # matched lots were consumed above; use price delta ratio instead.
        avg_buy_price = price - (realized_pnl / matched_qty)
        cost_basis = avg_buy_price * matched_qty
        pnl_pct = (realized_pnl / cost_basis) if cost_basis > 0 else 0.0

        stats["closed_trades"] += 1.0
        stats["wins"] += 1.0 if realized_pnl > 0 else 0.0
        stats["total_pnl"] += realized_pnl
        previous_count = max(0.0, stats["closed_trades"] - 1.0)
        stats["avg_pnl_pct"] = (
            ((stats["avg_pnl_pct"] * previous_count) + pnl_pct) / stats["closed_trades"]
            if stats["closed_trades"] > 0
            else 0.0
        )

    return feedback


def compute_opportunity_score(stock: Dict[str, Any]) -> float:
    """Assign a simple opportunity score for ranking candidate symbols."""
    price = _safe_float(stock.get("price"))
    vwap = _safe_float(stock.get("vwap"), price)
    candles = stock.get("candles", []) or []
    if price <= 0 or not candles:
        return float("-inf")

    closes = [_safe_float(candle.get("close")) for candle in candles if _safe_float(candle.get("close")) > 0]
    if not closes:
        return float("-inf")

    last_close = closes[-1]
    lookback_close = closes[-4] if len(closes) >= 4 else closes[0]
    momentum = ((last_close - lookback_close) / lookback_close) if lookback_close > 0 else 0.0
    vwap_edge = ((price - vwap) / vwap) if vwap > 0 else 0.0

    recent_candles = candles[-3:]
    trend_score = sum(1 for candle in recent_candles if _safe_float(candle.get("close")) > _safe_float(candle.get("vwap"), _safe_float(candle.get("close")))) / max(1, len(recent_candles))

    volumes = [_safe_float(candle.get("volume")) for candle in candles if _safe_float(candle.get("volume")) > 0]
    if len(volumes) >= 2:
        baseline_volume = sum(volumes[:-1]) / max(1, len(volumes) - 1)
        volume_ratio = volumes[-1] / baseline_volume if baseline_volume > 0 else 1.0
    else:
        volume_ratio = 1.0

    atr = _calculate_atr_from_candles(candles)
    normalized_atr = (atr / price) if price > 0 else 0.0

    return (
        (momentum * 100.0 * 0.45)
        + (vwap_edge * 100.0 * 0.30)
        + (trend_score * 10.0)
        + (min(volume_ratio, 3.0) * 2.5)
        - (normalized_atr * 100.0 * 0.20)
    )


def build_symbol_ranking_features(stock: Dict[str, Any], feedback: Dict[str, Dict[str, float]] | None = None) -> Dict[str, float]:
    """Build explicit ranking-model features for a symbol."""
    price = _safe_float(stock.get("price"))
    vwap = _safe_float(stock.get("vwap"), price)
    candles = stock.get("candles", []) or []
    closes = [_safe_float(candle.get("close")) for candle in candles if _safe_float(candle.get("close")) > 0]
    volumes = [_safe_float(candle.get("volume")) for candle in candles if _safe_float(candle.get("volume")) > 0]

    lookback_close = closes[-4] if len(closes) >= 4 else (closes[0] if closes else 0.0)
    last_close = closes[-1] if closes else price
    momentum_pct = ((last_close - lookback_close) / lookback_close) if lookback_close > 0 else 0.0
    vwap_edge_pct = ((price - vwap) / vwap) if vwap > 0 else 0.0
    trend_ratio = 0.0
    if candles:
        recent = candles[-3:]
        trend_ratio = sum(
            1.0
            for candle in recent
            if _safe_float(candle.get("close")) > _safe_float(candle.get("vwap"), _safe_float(candle.get("close")))
        ) / max(1, len(recent))

    volume_ratio = 1.0
    if len(volumes) >= 2:
        baseline_volume = sum(volumes[:-1]) / max(1, len(volumes) - 1)
        volume_ratio = volumes[-1] / baseline_volume if baseline_volume > 0 else 1.0

    atr = _calculate_atr_from_candles(candles)
    normalized_atr = (atr / price) if price > 0 else 0.0

    symbol_feedback = (feedback or {}).get(stock.get("symbol"), {})
    closed_trades = symbol_feedback.get("closed_trades", 0.0)
    win_rate = (symbol_feedback.get("wins", 0.0) / closed_trades) if closed_trades > 0 else 0.5
    avg_realized_pnl_pct = symbol_feedback.get("avg_pnl_pct", 0.0)
    realized_pnl = symbol_feedback.get("total_pnl", 0.0)
    learning_confidence = min(1.0, closed_trades / max(1.0, float(LEARNING_MIN_CLOSED_TRADES)))

    return {
        "momentum_pct": momentum_pct,
        "vwap_edge_pct": vwap_edge_pct,
        "trend_ratio": trend_ratio,
        "volume_ratio": volume_ratio,
        "normalized_atr": normalized_atr,
        "win_rate": win_rate,
        "avg_realized_pnl_pct": avg_realized_pnl_pct,
        "realized_pnl": realized_pnl,
        "closed_trades": closed_trades,
        "learning_confidence": learning_confidence,
    }


def score_symbol_ranking_model(features: Dict[str, float]) -> float:
    """Explicit weighted ranking model using market features and realized outcomes."""
    learning_confidence = features.get("learning_confidence")
    if learning_confidence is None:
        learning_confidence = min(1.0, features.get("closed_trades", 0.0) / max(1.0, float(LEARNING_MIN_CLOSED_TRADES)))
    return (
        (features.get("momentum_pct", 0.0) * 100.0 * 0.25)
        + (features.get("vwap_edge_pct", 0.0) * 100.0 * 0.20)
        + (features.get("trend_ratio", 0.0) * 8.0)
        + (min(features.get("volume_ratio", 1.0), 3.0) * 2.0)
        - (features.get("normalized_atr", 0.0) * 100.0 * 0.15)
        + (features.get("win_rate", 0.5) * 12.0 * learning_confidence)
        + (features.get("avg_realized_pnl_pct", 0.0) * 100.0 * 0.10 * learning_confidence)
        + (min(features.get("realized_pnl", 0.0) / 1000.0, 5.0) * 0.8 * learning_confidence)
    )


def persist_symbol_selections(selected: List[Dict[str, Any]]) -> None:
    """Persist selected symbols and their ranking diagnostics for dashboard review."""
    if not selected:
        return

    session = SessionLocal()
    try:
        for rank, stock in enumerate(selected, start=1):
            row = SymbolSelection(
                symbol=stock.get("symbol", ""),
                opportunity_score=_safe_float(stock.get("opportunity_score")),
                selection_rank=rank,
                features=stock.get("ranking_features"),
            )
            session.add(row)
        session.commit()
    except Exception as exc:
        logger.warning("Unable to persist symbol selections: %s", exc)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def select_trade_candidates(
    universe: List[Dict[str, Any]],
    top_n: int = AUTO_SELECT_TOP_N,
    min_score: float = SYMBOL_SELECTION_MIN_SCORE,
) -> List[Dict[str, Any]]:
    """Return the highest-ranked candidate symbols from the fetched universe."""
    feedback = _load_symbol_feedback()
    ranked: List[Dict[str, Any]] = []
    for stock in universe:
        ranking_features = build_symbol_ranking_features(stock, feedback=feedback)
        score = score_symbol_ranking_model(ranking_features)
        enriched = dict(stock)
        enriched["opportunity_score"] = score
        enriched["ranking_features"] = ranking_features
        ranked.append(enriched)

    ranked.sort(key=lambda item: item.get("opportunity_score", float("-inf")), reverse=True)
    selected = [stock for stock in ranked if stock.get("opportunity_score", float("-inf")) >= min_score]

    # Keep candidates close to today's best score so the engine stays focused on
    # strongest opportunities while remaining fully adaptive to market breadth.
    if selected:
        best_score = selected[0].get("opportunity_score", float("-inf"))
        relative_cut = float(SYMBOL_SELECTION_RELATIVE_TO_BEST)
        if best_score != float("-inf") and relative_cut > 0 and best_score > 0:
            selected = [
                stock
                for stock in selected
                if stock.get("opportunity_score", float("-inf")) >= best_score * relative_cut
            ]

    # top_n <= 0 means no fixed cap (score-threshold only selection).
    if int(top_n) <= 0:
        return selected
    return selected[: int(top_n)]


def _get_scan_batch(symbols: List[str]) -> List[str]:
    """Rotate through the broader universe so each cycle scans only a safe batch."""
    if not symbols:
        return []

    batch_size = max(1, int(MARKET_SCAN_BATCH_SIZE))
    if batch_size >= len(symbols):
        return symbols

    global _market_scan_cursor
    with _market_scan_lock:
        start = _market_scan_cursor % len(symbols)
        end = start + batch_size
        if end <= len(symbols):
            batch = symbols[start:end]
        else:
            batch = symbols[start:] + symbols[: end - len(symbols)]
        _market_scan_cursor = (start + batch_size) % len(symbols)

    return batch


def _get_symbols_to_fetch(symbols: List[str], use_auto_selection: bool, open_symbols: set[str]) -> List[str]:
    """Build the fetch list, always including open symbols for exit management."""
    base_symbols = _get_scan_batch(symbols) if use_auto_selection else list(symbols)
    combined = list(base_symbols)
    seen = set(base_symbols)
    for symbol in open_symbols:
        if symbol not in seen:
            combined.append(symbol)
            seen.add(symbol)
    return combined


class MarketDataFeed:
    """Fetch and process market data from Angel One API."""

    def __init__(self, use_mock: bool = False):
        """
        Initialize market data feed.
        
        Args:
            use_mock: If True, use mock data instead of Angel One API.
        """
        self.use_mock = use_mock
        self.broker = None
        self.broker_name = ACTIVE_BROKER
        
        if not use_mock:
            try:
                credentials = BROKER_CREDENTIALS.get("angel_one", {})
                self.broker = get_broker(
                    self.broker_name,
                    api_key=credentials.get("api_key", ""),
                    client_id=credentials.get("client_id", ""),
                    pin=credentials.get("pin", ""),
                    totp_secret=credentials.get("totp_secret", "")
                )
                if self.broker.authenticate():
                    logger.info(f"Market data feed initialized with Angel One broker.")
                else:
                    logger.error(f"Failed to authenticate with Angel One. Falling back to mock data.")
                    self.use_mock = True
            except Exception as e:
                logger.error(f"Failed to initialize Angel One: {e}. Falling back to mock data.")
                self.use_mock = True
        else:
            self.broker_name = "mock"
            logger.info("Market data feed initialized in mock mode.")

    def fetch_market_data(self, symbols: List[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch current market data for a list of symbols.
        
        Args:
            symbols: List of symbol names. Uses TRACKED_SYMBOLS if None.
        
        Returns:
            List of dicts with symbol, price, candles, etc.
        """
        use_auto_selection = symbols is None and AUTO_SELECT_SYMBOLS
        universe_symbols = symbols or (get_market_scan_symbols() if use_auto_selection else TRACKED_SYMBOLS)
        open_symbols = _get_open_trade_symbols() if use_auto_selection else set()
        symbols = _get_symbols_to_fetch(universe_symbols, use_auto_selection=use_auto_selection, open_symbols=open_symbols)
        data = []

        if not self.use_mock and self.broker:
            for symbol in symbols:
                try:
                    exchange_token = get_exchange_token(symbol)
                    quote = self.broker.get_quote(symbol, exchange_token)
                    candles = self.broker.get_intraday_minute_data(
                        symbol,
                        exchange_token,
                        interval=ANGEL_ONE_INTRADAY_INTERVAL_MINUTES,
                    )

                    # Type validation
                    if not isinstance(quote, dict):
                        logger.error(f"Malformed quote for {symbol}")
                        continue

                    if not isinstance(candles, list):
                        logger.warning(f"Candles not a list for {symbol}")
                        candles = []
                    
                    processed_candles = self._process_candles(candles)
                    persist_candles(
                        symbol=symbol,
                        interval=str(ANGEL_ONE_INTRADAY_INTERVAL_MINUTES),
                        candles=processed_candles,
                        broker=self.broker_name,
                    )

                    # Prefer quote VWAP if present; otherwise fall back to last candle VWAP.
                    quote_vwap = quote.get("vwap") if isinstance(quote, dict) else None
                    last_candle_vwap = processed_candles[-1].get("vwap") if processed_candles else None
                    vwap = quote_vwap if quote_vwap not in (None, 0, 0.0, "") else last_candle_vwap

                    stock_data = {
                        "symbol": symbol,
                        "price": quote.get("ltp") or quote.get("price", 0),
                        "high": quote.get("high", 0),
                        "low": quote.get("low", 0),
                        "volume": quote.get("volume", 0),
                        "avg_volume": quote.get("volume", 0),
                        "vwap": vwap if vwap is not None else (quote.get("ltp") or quote.get("price", 0)),
                        "candles": processed_candles,
                        "daily_trend_ok": True,
                    }
                    data.append(stock_data)
                    logger.debug(f"Fetched data for {symbol}: {stock_data['price']}")

                except Exception as e:
                    logger.error(f"Error fetching data for {symbol}: {e}")
                    continue
        else:
            # Mock mode - generate sample data
            data = self._generate_mock_data(symbols)
            for stock in data:
                persist_candles(
                    symbol=stock.get("symbol", ""),
                    interval=str(ANGEL_ONE_INTRADAY_INTERVAL_MINUTES),
                    candles=stock.get("candles", []),
                    broker="mock",
                )

        if use_auto_selection and data:
            managed_positions = [stock for stock in data if stock.get("symbol") in open_symbols]
            candidate_data = [stock for stock in data if stock.get("symbol") not in open_symbols]
            candidate_count = len(candidate_data)
            selected_candidates = select_trade_candidates(
                candidate_data,
                top_n=AUTO_SELECT_TOP_N,
                min_score=SYMBOL_SELECTION_MIN_SCORE,
            )
            selected_symbols = {stock.get("symbol") for stock in selected_candidates}
            data = selected_candidates + [
                stock for stock in managed_positions if stock.get("symbol") not in selected_symbols
            ]
            persist_symbol_selections(selected_candidates)
            logger.info(
                "Auto-selected %d/%d symbols for trading from scan batch %d/%d with %d open positions tracked: %s",
                len(selected_candidates),
                candidate_count,
                candidate_count,
                len(universe_symbols),
                len(managed_positions),
                ", ".join(stock.get("symbol", "") for stock in data),
            )

        return data

    def _process_candles(self, candles: List[Dict]) -> List[Dict]:
        """
        Process raw candle data into standardized format.
        
        Args:
            candles: Raw candle data from broker
        
        Returns:
            Processed candle list with standard OHLCV format
        """
        processed: List[Dict[str, Any]] = []

        # SmartAPI candle data commonly lacks VWAP. When missing/zero, approximate an
        # intraday VWAP using cumulative typical_price * volume / cumulative volume.
        cumulative_pv = 0.0
        cumulative_vol = 0.0

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            open_px = float(candle.get("open", 0) or 0)
            high_px = float(candle.get("high", 0) or 0)
            low_px = float(candle.get("low", 0) or 0)
            close_px = float(candle.get("close", 0) or 0)
            volume = int(float(candle.get("volume", 0) or 0))

            vwap_raw = candle.get("vwap")
            try:
                vwap_val = float(vwap_raw) if vwap_raw not in (None, "") else 0.0
            except Exception:
                vwap_val = 0.0

            typical_price = (high_px + low_px + close_px) / 3.0 if (high_px or low_px or close_px) else close_px
            if volume > 0:
                cumulative_pv += typical_price * volume
                cumulative_vol += volume

            if vwap_val in (0, 0.0, None) and cumulative_vol > 0:
                vwap_val = cumulative_pv / cumulative_vol
            elif vwap_val in (0, 0.0, None):
                vwap_val = close_px

            processed.append(
                {
                    "timestamp": candle.get("timestamp"),
                    "open": open_px,
                    "high": high_px,
                    "low": low_px,
                    "close": close_px,
                    "volume": volume,
                    "vwap": vwap_val,
                }
            )

        return processed

    def _generate_mock_data(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Generate mock market data for testing.
        
        Args:
            symbols: List of symbols to generate data for
        
        Returns:
            List of mock stock data dicts
        """
        import random
        
        mock_data = []
        for symbol in symbols:
            base_price = random.uniform(100, 2000)
            mock_data.append({
                "symbol": symbol,
                "price": base_price,
                "high": base_price * 1.02,
                "low": base_price * 0.98,
                "volume": random.randint(1000000, 5000000),
                "avg_volume": random.randint(1000000, 3000000),
                "vwap": base_price * 0.995,
                "candles": self._generate_mock_candles(base_price),
                "daily_trend_ok": True,
            })
        return mock_data

    def _generate_mock_candles(self, base_price: float, count: int = 20) -> List[Dict]:
        """
        Generate mock candlestick data.
        
        Args:
            base_price: Base price for candles
            count: Number of candles to generate
        
        Returns:
            List of mock candles
        """
        import random
        
        candles = []
        current_price = base_price
        now = datetime.now()
        step = max(1, int(ANGEL_ONE_INTRADAY_INTERVAL_MINUTES))
        for i in range(count):
            change = random.uniform(-0.02, 0.02)
            current_price *= (1 + change)
            ts = now - timedelta(minutes=step * (count - i - 1))
            candles.append({
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "open": current_price * 0.98,
                "high": current_price * 1.01,
                "low": current_price * 0.97,
                "close": current_price,
                "volume": random.randint(100000, 1000000),
                "vwap": current_price,
            })
        return candles


# Persistent feed instances keyed by (use_mock,) so the broker (and its
# authenticated session) survives across scheduler cycles.  This also lets
# the module-level candle cache in the broker remain warm.
_feed_instances: Dict[bool, "MarketDataFeed"] = {}


def fetch_market_data(use_mock: bool = False, broker_name: str = None) -> List[Dict[str, Any]]:
    """
    Convenience function to fetch market data.

    Re-uses a persistent MarketDataFeed (and therefore a persistent broker
    with an active auth session) so repeated calls don't re-authenticate
    and the in-process candle cache stays warm.

    Args:
        use_mock: If True, use mock data
        broker_name: Broker name (ignored, Angel One only)

    Returns:
        List of stock market data dicts
    """
    feed = _feed_instances.get(use_mock)

    # Create on first call, or re-create if the broker lost its session.
    if feed is None or (not use_mock and feed.broker and not getattr(feed.broker, 'authenticated', False)):
        feed = MarketDataFeed(use_mock=use_mock)
        _feed_instances[use_mock] = feed

    return feed.fetch_market_data()
