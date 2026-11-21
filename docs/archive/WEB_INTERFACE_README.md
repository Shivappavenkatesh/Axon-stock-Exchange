# Axon Trading - Web Based Terminal

A modern web-based interface for the Axon Trading System with real-time order management, live portfolio tracking, and both mock and live trade execution.

## 🌟 Features

### Trading Terminal
- **Instant Trade Execution**: Place buy/sell orders with a single click
- **Flexible Order Types**: Support for MARKET and LIMIT orders
- **Dual Mode Trading**: 
  - 🟣 Mock Mode (Paper Trading) - Risk-free simulation
  - 🟠 Live Mode (Angel One) - Real trade execution
- **Real-time Order Status**: WebSocket-powered instant updates
- **Quick Statistics**: Track total trades, filled orders, and open positions

### Order Management
- **Order History**: Complete view of all executed orders
- **Order Filtering**: Filter by symbol, status, or mode
- **Order Details**: Click any order to view complete execution details
- **Cancel Orders**: Cancel pending orders in real-time
- **Order Tracking**: Monitor order lifecycle from placement to execution

### Positions & Portfolio
- **Open Positions**: View current holdings with real-time P&L
- **Portfolio Dashboard**: 
  - Total capital tracking
  - Current portfolio value
  - Available cash
  - Daily profit/loss
- **Position Analytics**: Average prices, current prices, and P&L percentages

### Market Intelligence
- **Market Status**: Real-time indicator showing market open/closed status
- **Market Hours**: IST-based market timing (9:15 AM - 3:30 PM)
- **Trading Statistics**: Overview of daily trading activity

## 📋 Requirements

```
Python 3.8+
Flask >= 2.3.0
Flask-SocketIO >= 5.3.0
python-socketio >= 5.9.0
python-engineio >= 4.7.0
eventlet >= 0.33.0
SQLAlchemy
psycopg2 (or psycopg2-binary) for PostgreSQL
Streamlit (for the analytics dashboard)
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Set environment variables for **live trading** and **database access**:

```bash
# Linux/Mac
export ANGEL_ONE_API_KEY="your_api_key"
export ANGEL_ONE_CLIENT_ID="your_client_id"
export ANGEL_ONE_PIN="your_pin"
export ANGEL_ONE_TOTP_SECRET="your_totp_secret"

# Windows PowerShell
$env:ANGEL_ONE_API_KEY="your_api_key"
$env:ANGEL_ONE_CLIENT_ID="your_client_id"
$env:ANGEL_ONE_PIN="your_pin"
$env:ANGEL_ONE_TOTP_SECRET="your_totp_secret"

# Database URL (PostgreSQL recommended; SQLite allowed for testing)
# Example PostgreSQL URL
export AXON_DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/axon"
```

### 3. Start the Server

**Production Mode (Default):**
```bash
python run_web.py
```

**With Custom Port:**
```bash
python run_web.py --port 8080
```

**Debug Mode (Development):**
```bash
python run_web.py --debug
```

**Listen on All Interfaces:**
```bash
python run_web.py --host 0.0.0.0 --port 5000
```

### 4. Access the Interface

Open your browser and navigate to:
- **Local access**: http://localhost:5000
- **Remote access**: http://<your-machine-ip>:5000

## 🎯 Usage Guide

### Placing a Trade

1. **Navigate to Trading Terminal tab**
2. **Enter Symbol**: Stock symbol (e.g., RELIANCE, INFY, TCS)
3. **Set Quantity**: Number of shares to trade
4. **Choose Side**: BUY or SELL
5. **Select Order Type**: 
   - MARKET: Execute immediately at market price
   - LIMIT: Execute at specific price (fill in Price field)
6. **Choose Mode**:
   - Mock: Paper trading (no real capital used)
   - Live: Real trading with Angel One
7. **Click "Place Trade"**

### Monitoring Orders

1. **Navigate to Orders tab**
2. **View all orders** with status updates
3. **Filter by Symbol or Status** using filter controls
4. **Click any order** to view complete details
5. **Cancel pending orders** using the Cancel button

### Tracking Positions

1. **Navigate to Positions tab**
2. **View open positions** with:
   - Current quantity held
   - Average entry price
   - Current market price
   - Unrealized P&L
   - P&L percentage
3. **Monitor real-time updates** as prices change

### Portfolio Dashboard

1. **Navigate to Portfolio tab**
2. **Review portfolio metrics**:
   - Total Capital: Initial investment amount
   - Current Value: Total portfolio worth
   - Cash Available: Liquid capital
   - Daily P&L: Today's profit/loss

## 🏗️ Architecture

### Backend (Flask)

```
src/axon_aone/
├── web_server.py           # Flask app and REST API
├── execution/broker.py     # Trade execution
├── features/trade.py       # Trading logic
├── config.py               # Configuration
└── ... (other modules)
```

**API Endpoints:**
- `GET /api/health` - Server health check
- `GET /api/market-status` - Current market status
- `GET /api/portfolio` - Portfolio summary
- `GET /api/orders` - List all orders
- `GET /api/orders/<id>` - Get order details
- `POST /api/trade` - Place new trade
- `POST /api/orders/<id>/cancel` - Cancel order
- `GET /api/positions` - Open positions
- `GET /api/stats` - Trading statistics
- `GET /api/scheduler/orders` - Orders placed by the automated trading scheduler (read from shared log)

**WebSocket Events:**
- `order_update` - Real-time order status changes
- `position_update` - Position updates
- `portfolio_update` - Portfolio changes
- `market_status` - Market status changes

### Frontend (HTML/CSS/JavaScript)

```
src/axon_aone/
├── templates/
│   └── index.html          # Main trading interface
├── static/
│   ├── css/
│   │   └── style.css       # Styling
│   └── js/
│       └── client.js       # WebSocket client & UI logic
```

**Features:**
- Real-time WebSocket communication
- Responsive design (works on mobile and desktop)
- Tab-based navigation
- Real-time order and position updates
- Order detail modals

## 💾 Data Storage

Orders and positions are stored in-memory during runtime. For production use, implement:

1. **Database Integration** (PostgreSQL/MySQL)
   - Persist all orders
   - Historical P&L tracking
   - Position history

2. **Redis Caching** (for real-time data)
   - Fast order lookups
   - Real-time state sharing
   - WebSocket message queue

## 🔒 Security Considerations

For production deployment:

1. **Enable HTTPS/WSS**: Use SSL certificates
2. **Add Authentication**: Implement login with JWT
3. **Input Validation**: Validate all trade parameters
4. **Rate Limiting**: Limit API calls per user
5. **CORS Configuration**: Restrict cross-origin requests
6. **API Key Management**: Store credentials securely
7. **Audit Logging**: Log all trades for compliance

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Use a different port
python run_web.py --port 8080
```

### Connection Issues
1. Check firewall settings
2. Verify host/port configuration
3. Check browser console for errors (F12)

### WebSocket Connection Failed
1. Check Flask-SocketIO is installed: `pip install flask-socketio`
2. Verify firewall allows WebSocket connections
3. Check browser console for CORS errors

### Orders Not Appearing
1. Refresh the page (F5)
2. Check browser console for JavaScript errors
3. Verify Flask server is running

## 📊 Example Order Flow

```
User Input → API Call → Execute Trade → Update State → 
WebSocket Broadcast → Real-time UI Update → Display to User
```

Example JSON order:
```json
{
  "id": "ORD_20240222_093015_001",
  "symbol": "RELIANCE",
  "quantity": 100,
  "side": "BUY",
  "order_type": "MARKET",
  "status": "FILLED",
  "trade_mode": "mock",
  "timestamp": "2024-02-22T09:30:15.123456",
  "filled_quantity": 100,
  "execution_time": "2024-02-22T09:30:16.234567",
  "broker_response": {
    "status": "PAPER",
    "order_id": "PAPER_147896532"
  }
}
```

## 🚀 Performance Optimization

1. **WebSocket over HTTP**: Real-time updates without polling
2. **Responsive UI**: CSS Grid and Flexbox for efficient layout
3. **Efficient Filtering**: Client-side order filtering
4. **Connection Pooling**: Database connection optimization (when added)

## 📝 Logs

Logs are displayed in the console with timestamps and levels:
- INFO: Important application events
- ERROR: Errors and exceptions
- DEBUG: Detailed debugging information (debug mode only)

## 🔄 Real-time Updates

All connected clients receive updates via WebSocket:

1. **Order Updates**: Instant status changes
2. **Position Updates**: Real-time holdings changes
3. **Portfolio Updates**: Balance and P&L changes
4. **Market Status**: Market open/close notifications

## 🌐 Multi-Client Support

- Multiple users can connect simultaneously
- Each client receives real-time updates
- Shared order history and positions
- Synchronized state across all clients

## 📚 API Rate Limits

Adjust in `web_server.py` if needed:

```python
# Example: Add rate limiting middleware
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
```

## 🤝 Integration with Existing System

The web interface integrates seamlessly with:
- ✓ Existing trading logic (features/trade.py)
- ✓ Broker execution (execution/broker.py)
- ✓ Market data feeds (data/feed.py)
- ✓ Configuration system (config.py)
- ✓ Risk management (risk/)
- ✓ Strategies (strategies/)

## 🎓 Development

### Adding New API Endpoints

```python
@app.route('/api/new-endpoint', methods=['GET', 'POST'])
def new_endpoint():
    """New endpoint description."""
    data = request.json
    # ... implementation
    return jsonify({'result': 'success'})
```

### Adding WebSocket Events

```python
@socketio.on('custom_event')
def handle_custom_event(data):
    """Handle custom event."""
    # ... implementation
    emit('response_event', data, broadcast=True)
```

## ✅ Testing

Run tests:
```bash
pytest tests/
```

## 📄 License

Same as parent Axon project

## 🤖 Support

For issues or questions:
1. Check troubleshooting section
2. Review logs for error messages
3. Check Flask and Socket.IO documentation
4. Report bugs in project issue tracker

---

**Version**: 1.0  
**Last Updated**: February 2024  
**Status**: Production Ready ✓
