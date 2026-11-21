"""
Flask WebSocket server for real-time trading and order management.
Provides REST API and real-time updates for the web-based trading interface.
"""

import logging
import json
import threading
import queue
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
from functools import wraps

from axon_aone.execution.broker import get_open_positions
from axon_aone.strategy.strategies.trade import run_day
from axon_aone.data.feed import fetch_market_data
from axon_aone.config import (
    START_CAPITAL,
    MARKET_OPEN_TIME,
    MARKET_CLOSE_TIME,
    TRACKED_SYMBOLS,
    BROKER_CREDENTIALS,
    EXCHANGE_TOKEN_MAP,
    get_exchange_token,
)
from axon_aone.brokers import get_broker
from axon_aone.services.order_store import read_scheduler_orders
from axon_aone.services.telegram_notify import send_telegram_message
from axon_aone.services import metrics as prom_metrics
from axon_aone.execution.engine import ExecutionEngine
from axon_aone.risk.engine import PortfolioSnapshot, RiskEngine
from axon_aone.risk.kill_switch import KillSwitch
from axon_aone.db import (
    SessionLocal,
    Trade as DbTrade,
    PortfolioSnapshot as DbPortfolioSnapshot,
    is_manual_kill_switch_active,
    get_global_trade_mode,
)

# Initialize Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('WEB_SECRET_KEY', 'axon-trading-secret')

# Simple env-based web login credentials
WEB_USERNAME = os.getenv('WEB_USERNAME')
WEB_PASSWORD = os.getenv('WEB_PASSWORD')

# Use threading async mode so that Flask's built-in server and ssl_context
# are supported reliably across environments (especially on Windows).
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

logger = logging.getLogger(__name__)

# In-memory store for orders (in production, use database)
orders_store = {
    'orders': [],
    'positions': [],
    'portfolio': {
        'total_capital': START_CAPITAL,
        'current_value': START_CAPITAL,
        'daily_pnl': 0,
        'cash_available': START_CAPITAL
    }
}

order_counter = 0
active_connections = set()


_execution_engine = ExecutionEngine()
_risk_engine = RiskEngine()
_kill_switch = KillSwitch()

# MarketFeed WebSocket integration (Angel One SmartAPI)
_market_feed_started = False
_market_feed_lock = threading.Lock()
_market_feed_broker = None
# Last known ticks keyed by symbol for UI / new connections
_last_ticks_by_symbol: dict[str, dict] = {}


def _persist_trade(order: dict, broker_result: dict | None) -> None:
    """Best-effort persistence of a trade to the database."""
    try:
        session = SessionLocal()
        db_trade = DbTrade(
            external_id=order.get('id', ''),
            symbol=order.get('symbol', ''),
            side=order.get('side', ''),
            quantity=order.get('quantity', 0),
            order_type=order.get('order_type', ''),
            price=order.get('price'),
            status=order.get('status', ''),
            trade_mode=order.get('trade_mode', ''),
            broker='angel_one',
            broker_response=broker_result,
        )
        session.add(db_trade)
        session.commit()
    except Exception as e:
        logger.error(f"Error persisting trade to DB: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def _persist_portfolio_snapshot() -> None:
    """Best-effort persistence of the current portfolio snapshot."""
    try:
        portfolio = orders_store['portfolio']
        session = SessionLocal()
        snap = DbPortfolioSnapshot(
            total_capital=portfolio.get('total_capital', 0.0),
            current_value=portfolio.get('current_value', 0.0),
            cash_available=portfolio.get('cash_available', 0.0),
            daily_pnl=portfolio.get('daily_pnl', 0.0),
        )
        session.add(snap)
        session.commit()
    except Exception as e:
        logger.error(f"Error persisting portfolio snapshot to DB: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


def next_order_id():
    """Generate next order ID."""
    global order_counter
    order_counter += 1
    return f"ORD_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{order_counter}"


def get_market_status():
    """Check if market is currently open."""
    now = datetime.now().time()
    weekday = datetime.now().weekday()
    
    # Market only runs Monday-Friday
    if weekday >= 5:  # Saturday=5, Sunday=6
        return "CLOSED", "Weekend"
    
    if now < MARKET_OPEN_TIME:
        return "CLOSED", "Pre-market"
    elif now > MARKET_CLOSE_TIME:
        return "CLOSED", "Post-market"
    else:
        return "OPEN", "Market hours"


def broadcast_order_update(order):
    """Broadcast order update to all connected clients."""
    # In recent python-socketio versions, 'broadcast' is no longer a valid
    # keyword argument. Emitting without room/namespace sends to all clients.
    socketio.emit('order_update', order)


def broadcast_position_update(positions):
    """Broadcast position update to all connected clients."""
    socketio.emit('position_update', positions)


def broadcast_portfolio_update(portfolio):
    """Broadcast portfolio update to all connected clients."""
    socketio.emit('portfolio_update', portfolio)


def broadcast_tick_update(ticks):
    """Broadcast tick update(s) to all connected clients and cache by symbol.

    The payload from SmartAPI may be a dict with a "data" list or a bare list.
    We normalise and update _last_ticks_by_symbol so new clients get the latest snapshot.
    """
    global _last_ticks_by_symbol

    try:
        # Normalise to a list of tick dicts
        if isinstance(ticks, dict) and "data" in ticks:
            items = ticks.get("data") or []
        elif isinstance(ticks, list):
            items = ticks
        else:
            items = [ticks]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Try to extract token and ltp fields defensively
            token = item.get("symboltoken") or item.get("tk") or item.get("token")
            ltp = item.get("ltp") or item.get("ap") or item.get("close")

            symbol = None
            if token:
                # Reverse-lookup using EXCHANGE_TOKEN_MAP
                for sym, tok in EXCHANGE_TOKEN_MAP.items():
                    if str(tok) == str(token):
                        symbol = sym
                        break

            # Fallback: if symbol already present in item
            if not symbol:
                symbol = item.get("symbol") or item.get("tradingsymbol")

            if symbol:
                payload = {
                    "symbol": symbol,
                    "token": token,
                    "ltp": ltp,
                    "raw": item,
                }
                _last_ticks_by_symbol[symbol] = payload

        socketio.emit("tick_update", ticks)

    except Exception as e:  # pragma: no cover
        logger.error(f"Error in broadcast_tick_update: {e}")


def _start_market_feed_if_needed() -> None:
    """Lazily start Angel One MarketFeed WebSocket and broadcast ticks.

    This is best-effort and will no-op if credentials or SmartAPI are missing.
    """
    global _market_feed_started, _market_feed_broker

    with _market_feed_lock:
        if _market_feed_started:
            return

        try:
            credentials = BROKER_CREDENTIALS.get("angel_one", {})
            if not credentials:
                logger.info("No Angel One credentials configured; MarketFeed will not be started.")
                return

            broker = get_broker(
                "angel_one",
                api_key=credentials.get("api_key", ""),
                client_id=credentials.get("client_id", ""),
                pin=credentials.get("pin", ""),
                totp_secret=credentials.get("totp_secret", ""),
            )

            if not getattr(broker, "authenticate", None) or not broker.authenticate():
                logger.error("Angel One authentication failed; MarketFeed will not be started.")
                return

            # Build channel list for tracked symbols (cash market by default)
            channels: list[str] = []
            for symbol in TRACKED_SYMBOLS:
                try:
                    token = get_exchange_token(symbol)
                    if token:
                        channels.append(f"nse_cm|{token}")
                except Exception as e:
                    logger.error(f"Error resolving token for {symbol}: {e}")

            if not channels:
                logger.warning("No MarketFeed channels resolved; MarketFeed will not be started.")
                return

            def _on_tick(payload):
                try:
                    broadcast_tick_update(payload)
                except Exception as e:  # pragma: no cover
                    logger.error(f"Error handling MarketFeed tick: {e}")

            def _on_error(err: Exception):
                logger.error(f"Angel One MarketFeed error: {err}")

            def _on_close():
                global _market_feed_started
                logger.info("Angel One MarketFeed closed; marking as stopped.")
                with _market_feed_lock:
                    _market_feed_started = False

            def _runner():
                try:
                    broker.start_market_feed(channels, on_tick=_on_tick, on_error=_on_error, on_close=_on_close)
                except Exception as e:  # pragma: no cover
                    logger.error(f"Unexpected error starting MarketFeed: {e}")

            thread = threading.Thread(target=_runner, daemon=True)
            thread.start()
            _market_feed_broker = broker
            _market_feed_started = True
            logger.info(f"Angel One MarketFeed started for channels: {channels}")

        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to start MarketFeed: {e}")


def login_required(view_func):
    """Decorator to require login for web pages."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get('logged_in'):
            next_url = request.path
            return redirect(url_for('login', next=next_url))
        return view_func(*args, **kwargs)

    return wrapped


# ============ REST API ENDPOINTS ============

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'market_status': get_market_status()[0]
    })


@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics endpoint (requires prometheus-client)."""
    rendered = prom_metrics.render_latest()
    if rendered is None:
        return jsonify({'error': 'metrics unavailable: prometheus-client not installed'}), 503
    payload, content_type = rendered
    return app.response_class(payload, mimetype=content_type)


@app.route('/api/market-status', methods=['GET'])
def market_status():
    """Get current market status."""
    status, details = get_market_status()
    return jsonify({
        'status': status,
        'details': details,
        'market_open': MARKET_OPEN_TIME.isoformat(),
        'market_close': MARKET_CLOSE_TIME.isoformat(),
        'current_time': datetime.now().time().isoformat()
    })


@app.route('/api/global-state', methods=['GET'])
def global_state():
    """Expose global runtime flags for the web UI.

    Returns:
        manual_kill: whether the manual kill switch is active
        trade_mode:  current global default trade mode ("mock"/"live")
    """
    try:
        manual_kill = is_manual_kill_switch_active()
    except Exception:
        manual_kill = False

    try:
        trade_mode = get_global_trade_mode()
    except Exception:
        trade_mode = "mock"

    return jsonify({
        'manual_kill': manual_kill,
        'trade_mode': trade_mode,
    })


@app.route('/api/portfolio', methods=['GET'])
def portfolio():
    """Get portfolio summary."""
    return jsonify(orders_store['portfolio'])


@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Get all orders."""
    symbol = request.args.get('symbol')
    status = request.args.get('status')
    source = request.args.get('source')
    
    orders = orders_store['orders']
    
    if symbol:
        orders = [o for o in orders if o['symbol'] == symbol]
    if status:
        orders = [o for o in orders if o['status'] == status]
    if source:
        orders = [o for o in orders if o.get('source', 'manual') == source]
    
    return jsonify({
        'total': len(orders),
        'orders': sorted(orders, key=lambda x: x['timestamp'], reverse=True)
    })


@app.route('/api/scheduler/orders', methods=['GET'])
def get_scheduler_orders():
    """Get orders placed by the automated trading scheduler.

    These are read from the shared scheduler order log so they are
    available even when the scheduler runs in a separate process.
    """
    try:
        limit_param = request.args.get('limit')
        limit = int(limit_param) if limit_param else None
    except ValueError:
        limit = None

    orders = read_scheduler_orders(limit=limit)

    symbol = request.args.get('symbol')
    status = request.args.get('status')

    if symbol:
        orders = [o for o in orders if o.get('symbol') == symbol]
    if status:
        orders = [o for o in orders if o.get('status') == status]

    return jsonify({
        'total': len(orders),
        'orders': orders,
    })


@app.route('/api/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    """Get specific order details."""
    order = next((o for o in orders_store['orders'] if o['id'] == order_id), None)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    return jsonify(order)


@app.route('/api/positions', methods=['GET'])
def positions():
    """Get all open positions."""
    return jsonify({
        'total': len(orders_store['positions']),
        'positions': orders_store['positions']
    })


@app.route('/api/historical', methods=['GET'])
def historical_data():
    """Fetch historical OHLCV data via Angel One SmartAPI.

    Query parameters:
        symbol   - required, e.g. RELIANCE
        interval - optional, default ONE_MINUTE
        days     - optional, number of days back from now (default 5)
        exchange - optional, default NSE
    """
    try:
        symbol = request.args.get('symbol', '').upper().strip()
        if not symbol:
            return jsonify({'error': 'symbol is required'}), 400

        interval = request.args.get('interval', 'ONE_MINUTE')
        exchange = request.args.get('exchange', 'NSE')

        days_param = request.args.get('days')
        try:
            days = int(days_param) if days_param is not None else 5
        except ValueError:
            return jsonify({'error': 'days must be an integer'}), 400

        if days <= 0:
            return jsonify({'error': 'days must be positive'}), 400

        credentials = BROKER_CREDENTIALS.get("angel_one", {})
        if not credentials:
            return jsonify({'error': 'Angel One credentials are not configured on the server'}), 500

        broker = get_broker(
            "angel_one",
            api_key=credentials.get("api_key", ""),
            client_id=credentials.get("client_id", ""),
            pin=credentials.get("pin", ""),
            totp_secret=credentials.get("totp_secret", ""),
        )

        if not getattr(broker, 'authenticate', None) or not broker.authenticate():
            return jsonify({'error': 'Failed to authenticate with Angel One SmartAPI'}), 502

        try:
            token = get_exchange_token(symbol)
        except Exception as e:
            logger.error(f"Error resolving exchange token for {symbol}: {e}")
            return jsonify({'error': f'Failed to resolve exchange token for {symbol}'}), 500

        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=days)

        # Use the new generic historical data method if available
        if hasattr(broker, 'get_historical_data'):
            candles = broker.get_historical_data(
                symbol=symbol,
                exchange_token=token,
                interval=interval,
                from_date=from_dt,
                to_date=to_dt,
                exchange=exchange,
            )
        else:
            # Fallback to intraday helper (will ignore custom days)
            candles = broker.get_intraday_minute_data(symbol, token, interval=interval, exchange=exchange)

        return jsonify({
            'symbol': symbol,
            'interval': interval,
            'exchange': exchange,
            'from': from_dt.isoformat(timespec='minutes'),
            'to': to_dt.isoformat(timespec='minutes'),
            'candles': candles,
        })

    except Exception as e:
        logger.error(f"Error in /api/historical: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/trade', methods=['POST'])
def place_trade():
    """Place a new trade."""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['symbol', 'quantity', 'side', 'trade_mode']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        quantity = int(data['quantity'])
        side = data['side'].upper()
        trade_mode = data['trade_mode'].lower()  # 'mock' or 'live'
        order_type = data.get('order_type', 'MARKET').upper()
        
        # Handle price field - can be None for MARKET orders
        price_value = data.get('price')
        price = float(price_value) if price_value else None
        
        # Validate inputs
        if side not in ['BUY', 'SELL']:
            return jsonify({'error': 'Side must be BUY or SELL'}), 400
        if quantity <= 0:
            return jsonify({'error': 'Quantity must be positive'}), 400
        
        # Create order record
        order_id = next_order_id()
        order = {
            'id': order_id,
            'symbol': symbol,
            'quantity': quantity,
            'side': side,
            'order_type': order_type,
            'price': price,
            'trade_mode': trade_mode,
            'status': 'PENDING',
            'timestamp': datetime.now().isoformat(),
            'filled_quantity': 0,
            'average_price': 0,
            'execution_time': None,
            'broker_response': None
        }

        # Send Telegram notification for new order
        send_telegram_message(f"[Axon] New order placed:\nID: {order_id}\n{side} {quantity} {symbol} ({trade_mode.upper()})\nType: {order_type}{f' @ {price}' if price else ''}")
        
        # Execute trade asynchronously
        def execute_async():
            try:
                logger.info(f"Executing trade: {order_id} - {side} {quantity} {symbol}")
                
                # Build a minimal portfolio snapshot for risk/kill checks
                portfolio = orders_store['portfolio']
                snapshot = PortfolioSnapshot(
                    total_capital=portfolio.get('total_capital', 0),
                    tradable_capital=portfolio.get('cash_available', 0),
                    daily_pnl=portfolio.get('daily_pnl', 0),
                    weekly_pnl=0.0,
                )

                # Kill switch gate
                if _kill_switch.check(snapshot=snapshot):
                    reason = _kill_switch.last_reason or "kill_switch_triggered"
                    logger.warning(f"Kill switch active ({reason}); rejecting web trade")
                    order['status'] = 'REJECTED'
                    order['broker_response'] = {'error': f'Kill switch active: {reason}'}
                    _persist_trade(order, order['broker_response'])
                    broadcast_order_update(order)
                    send_telegram_message(
                        f"[Axon] Order REJECTED (Kill Switch):\nID: {order_id}\n{side} {quantity} {symbol} ({trade_mode.upper()})\n"
                        f"Type: {order_type}{f' @ {price}' if price else ''}\nReason: {reason}"
                    )
                    return

                # Basic per-trade risk gate using a notional 1% stop
                entry_price = price or 0
                if entry_price > 0:
                    stop_price = entry_price * 0.99
                else:
                    stop_price = entry_price

                if not _risk_engine.can_open_trade(
                    entry_price=entry_price,
                    stop_loss_price=stop_price,
                    quantity=quantity,
                    snapshot=snapshot,
                ):
                    logger.info(f"RiskEngine blocked web trade for {symbol} due to risk limits")
                    order['status'] = 'REJECTED'
                    order['broker_response'] = {'error': 'Risk limits exceeded'}
                    _persist_trade(order, order['broker_response'])
                    broadcast_order_update(order)
                    send_telegram_message(
                        f"[Axon] Order REJECTED (Risk):\nID: {order_id}\n{side} {quantity} {symbol} ({trade_mode.upper()})\n"
                        f"Type: {order_type}{f' @ {price}' if price else ''}"
                    )
                    return

                # Execute via capital engine execution wrapper
                exec_result = _execution_engine.execute(
                    symbol=symbol,
                    quantity=quantity,
                    side=side,
                    order_type=order_type,
                    price=price,
                    trade_mode=trade_mode,
                )

                status = exec_result.status
                result = exec_result.raw

                # Update order status
                # SmartAPI returns boolean True/False for live orders,
                # while mock orders use string codes like "PAPER".
                if status is True or status in ['PAPER', 'SUCCESS']:
                    order['status'] = 'FILLED'
                    order['filled_quantity'] = quantity
                    order['execution_time'] = datetime.now().isoformat()
                    order['broker_response'] = result
                    _persist_trade(order, result)

                    # Update portfolio
                    update_portfolio_after_trade(order)
                    _persist_portfolio_snapshot()
                    send_telegram_message(f"[Axon] Order FILLED:\nID: {order_id}\n{side} {quantity} {symbol} ({trade_mode.upper()})\nType: {order_type}{f' @ {price}' if price else ''}")
                else:
                    order['status'] = 'REJECTED'
                    order['broker_response'] = result
                    _persist_trade(order, result)
                    send_telegram_message(f"[Axon] Order REJECTED:\nID: {order_id}\n{side} {quantity} {symbol} ({trade_mode.upper()})\nType: {order_type}{f' @ {price}' if price else ''}\nReason: {result}")
                
                # Broadcast update
                broadcast_order_update(order)
                
                logger.info(f"Order {order_id} completed with status: {order['status']}")
                
            except Exception as e:
                logger.error(f"Error executing trade {order_id}: {e}")
                order['status'] = 'ERROR'
                order['broker_response'] = {'error': str(e)}
                broadcast_order_update(order)
                send_telegram_message(f"[Axon] Order ERROR:\nID: {order_id}\n{side} {quantity} {symbol} ({trade_mode.upper()})\nType: {order_type}{f' @ {price}' if price else ''}\nError: {e}")
        
        # Add order to store
        orders_store['orders'].append(order)
        broadcast_order_update(order)
        
        # Execute in background thread
        thread = threading.Thread(target=execute_async, daemon=True)
        thread.start()
        
        return jsonify({
            'message': 'Trade order submitted',
            'order_id': order_id,
            'order': order
        }), 201
        
    except Exception as e:
        logger.error(f"Error placing trade: {e}")
        return jsonify({'error': str(e)}), 400


def update_portfolio_after_trade(order):
    """Update portfolio after trade execution."""
    portfolio = orders_store['portfolio']
    
    # For mock/demo, just track the trade
    # In production, fetch actual positions from broker
    if order['side'] == 'BUY':
        portfolio['cash_available'] -= order['filled_quantity'] * (order['average_price'] or 100)
    else:
        portfolio['cash_available'] += order['filled_quantity'] * (order['average_price'] or 100)
    
    # Update open positions
    update_positions()


def update_positions():
    """Update open positions from broker or store."""
    try:
        # For mock mode, just track from orders
        positions = {}
        
        for order in orders_store['orders']:
            if order['status'] in ['FILLED', 'PARTIALLY_FILLED']:
                symbol = order['symbol']
                if symbol not in positions:
                    positions[symbol] = {
                        'symbol': symbol,
                        'quantity': 0,
                        'average_price': 0,
                        'current_price': 0,
                        'pnl': 0,
                        'pnl_percent': 0
                    }
                
                if order['side'] == 'BUY':
                    positions[symbol]['quantity'] += order['filled_quantity']
                else:
                    positions[symbol]['quantity'] -= order['filled_quantity']
        
        orders_store['positions'] = list(positions.values())
        broadcast_position_update(orders_store['positions'])
        
    except Exception as e:
        logger.error(f"Error updating positions: {e}")


@app.route('/api/orders/<order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    """Cancel an open order."""
    try:
        order = next((o for o in orders_store['orders'] if o['id'] == order_id), None)
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        if order['status'] not in ['PENDING', 'PARTIALLY_FILLED']:
            return jsonify({'error': f'Cannot cancel order in {order["status"]} status'}), 400
        
        order['status'] = 'CANCELLED'
        order['timestamp_cancelled'] = datetime.now().isoformat()
        
        broadcast_order_update(order)
        return jsonify({'message': 'Order cancelled', 'order': order})
        
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        return jsonify({'error': str(e)}), 400


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get trading statistics."""
    orders = orders_store['orders']
    
    total_trades = len(orders)
    filled_trades = len([o for o in orders if o['status'] == 'FILLED'])
    cancelled_trades = len([o for o in orders if o['status'] == 'CANCELLED'])
    
    buy_orders = [o for o in orders if o['side'] == 'BUY' and o['status'] == 'FILLED']
    sell_orders = [o for o in orders if o['side'] == 'SELL' and o['status'] == 'FILLED']
    
    return jsonify({
        'total_trades': total_trades,
        'filled_trades': filled_trades,
        'cancelled_trades': cancelled_trades,
        'buy_orders': len(buy_orders),
        'sell_orders': len(sell_orders),
        'open_positions': len(orders_store['positions']),
        'portfolio': orders_store['portfolio']
    })


# ============ SOCKETIO EVENTS ============

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    active_connections.add(request.sid)
    logger.info(f"Client connected: {request.sid}")
    
    # Send current state to new client
    emit('sync_orders', orders_store['orders'])
    emit('sync_positions', orders_store['positions'])
    emit('sync_portfolio', orders_store['portfolio'])
    # Send last known ticks snapshot (if any)
    try:
        if _last_ticks_by_symbol:
            emit('sync_ticks', list(_last_ticks_by_symbol.values()))
    except Exception as e:  # pragma: no cover
        logger.error(f"Error sending sync_ticks on connect: {e}")


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    active_connections.discard(request.sid)
    logger.info(f"Client disconnected: {request.sid}")


@socketio.on('subscribe_updates')
def handle_subscribe(data=None):
    """Subscribe to real-time updates."""
    logger.info(f"Client subscribed: {request.sid}")
    # Lazily start MarketFeed WebSocket when first client subscribes
    try:
        _start_market_feed_if_needed()
    except Exception as e:  # pragma: no cover
        logger.error(f"Error starting MarketFeed on subscribe: {e}")
    emit('ack', {'data': 'Subscribed to updates'})


@socketio.on('request_status')
def handle_status_request(data=None):
    """Client requests current status."""
    emit('market_status', {
        'status': get_market_status()[0],
        'details': get_market_status()[1],
        'timestamp': datetime.now().isoformat()
    })


# ============ AUTH & PAGES ============

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Simple login page that checks credentials against env variables.

    Expected environment variables:
        WEB_USERNAME, WEB_PASSWORD
    """
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if WEB_USERNAME and WEB_PASSWORD:
            if username == WEB_USERNAME and password == WEB_PASSWORD:
                session['logged_in'] = True
                session['username'] = username
                next_url = request.args.get('next') or url_for('index')
                return redirect(next_url)
            else:
                error = 'Invalid username or password.'
        else:
            error = 'Server login is not configured. Please set WEB_USERNAME and WEB_PASSWORD.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Log out the current user and redirect to login page."""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """Serve main trading interface (requires login)."""
    return render_template('index.html')


@app.route('/dashboard')
@login_required
def dashboard():
    """Serve dashboard page (requires login)."""
    return render_template('dashboard.html')


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors."""
    return jsonify({'error': 'Internal server error'}), 500


def run_web_server(host='0.0.0.0', port=5000, debug=False,
                   use_https=False, certfile=None, keyfile=None):
    """Run the Flask web server.

    Args:
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug mode
        use_https: Enable HTTPS/TLS
        certfile: Path to TLS certificate (PEM). If not provided and
                  use_https is True, an ad-hoc self-signed cert is used.
        keyfile: Path to TLS private key (PEM), required if certfile given.
    """
    logging.basicConfig(level=logging.INFO)

    scheme = "https" if use_https else "http"
    logger.info(f"Starting Axon Trading Web Server on {scheme}://{host}:{port}")

    # Configure SSL context for HTTPS if requested
    ssl_context = None
    if use_https:
        if certfile and keyfile:
            ssl_context = (certfile, keyfile)
        else:
            # Use Werkzeug's ad-hoc self-signed certificate for local dev
            ssl_context = 'adhoc'

    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        ssl_context=ssl_context,
        allow_unsafe_werkzeug=True,
    )


if __name__ == '__main__':
    run_web_server(debug=True)
