# Axon – Capital Engine Architecture

## Overview

**Axon** is a streamlined, single-broker trading system specifically designed for **Angel One Smart API** with an integrated **capital engine** and **analytics stack**. It features:
- Automated trading during Indian market hours (9:15 AM – 3:30 PM IST)
- Capital engine (regime, risk engine, kill‑switch, sandbox, allocation, correlation)
- Integrated risk management, portfolio heat monitoring, and kill‑switch controls
- PostgreSQL-backed persistence for trades, portfolio snapshots, regimes, correlations, and engine config
- Streamlit dashboard for performance analytics (equity, PnL, Sharpe, drawdown)
- Clean, modular architecture for easy customization

---

## Directory Structure

```
Axon/
│
├── src/axon_aone/              # Main source code
│   ├── __init__.py
│   ├── main.py                     # Compatibility wrapper for python -m axon_aone.main
│   ├── config.py                   # Configuration (market hours, risk params, symbols)
│   ├── utils.py                    # Utility functions
│   │
│   ├── brokers/                    # Angel One Smart API integration
│   │   ├── __init__.py
│   │   ├── base_broker.py          # Abstract broker interface
│   │   └── angel_one_broker.py     # Angel One SmartConnect implementation
│   │
│   ├── core/                       # Capital engine primitives
│   │   ├── regime.py               # Regime scoring and modes
│   │   ├── risk_engine.py          # Per-trade risk checks & portfolio heat
│   │   ├── kill_switch.py          # Kill-switch triggers (loss, regime, heat)
│   │   ├── sandbox.py              # Mock execution with slippage
│   │   ├── execution_engine.py     # Live vs mock routing
│   │   ├── correlation.py          # Correlation matrix computation
│   │   └── allocation.py           # Engine allocation definitions
│   │
│   ├── data/                       # Market data operations
│   │   ├── __init__.py
│   │   └── feed.py                 # MarketDataFeed class for quote/candle data
│   │
│   ├── orchestration/              # Canonical runtime entrypoint and market-hours scheduler
│   │   ├── __init__.py
│   │   ├── main.py                 # Canonical CLI/runtime dispatch
│   │   └── scheduler.py            # TradingScheduler used by the runtime
│   │
│   ├── execution/                  # Trade execution
│   │   ├── __init__.py
│   │   └── broker.py               # Order execution interface
│   │
│   ├── features/                   # Trading strategy & signals
│   │   ├── __init__.py
│   │   └── trade.py                # Trading algorithm & signal generation
│   │
│   ├── risk/                       # Legacy risk helpers
│   │   ├── __init__.py
│   │   └── manager.py              # Original risk assessment & position limits
│   │
│   ├── services/                   # Background services
│   │   ├── __init__.py
│   │   ├── scheduler_service.py    # TradingScheduler for market hours automation
│   │   └── token_manager.py        # Token management for Angel One API
│   │   └── telegram_notify.py      # Telegram notifications for orders / kill‑switch
│   │
│   └── strategies/                 # Strategy definitions
│       └── __init__.py
│
├── dashboard/                      # Streamlit performance dashboard
│   └── app.py                      # Equity, PnL, regime, allocation, correlations
│
├── tests/                          # Unit tests
│   ├── __init__.py
│   ├── test_brokers.py
│   ├── test_capital_engine_core.py
│   └── test_db_and_perf.py
│
├── examples/                       # Example scripts
│   ├── run_mock_mode.py           # Test in mock mode
│   ├── run_scheduler.py           # Run automated scheduler
│   └── run_with_angel_one.py      # Live trading with Angel One
│
├── logs/                          # Trading logs (date-based folders)
│
├── run_trader.py                  # Command-line entry point
│
├── requirements.txt               # Python dependencies
├── pyproject.toml                # Poetry configuration
│
├── .env.example                  # Environment template (copy to .env locally, not committed)
├── .gitignore                    # Git ignore rules
│
├── README.md                     # Full documentation
├── QUICKSTART.md                 # Quick reference guide
├── ARCHITECTURE.md               # This file
└── WEB_*                         # Web architecture / quick start / interface docs
```

---

## Core Components

### 1. **Broker Integration** (`brokers/`)

**BaseBroker** (Abstract)
- Defines interface for broker implementations
- Methods: authenticate, get_quote, get_positions, place_order, close_position, etc.

**AngelOneBroker** (Concrete)
- Implementation using Angel One SmartConnect API
- Uses `smartapi-python` library with TOTP authentication
- Handles order placement, position management, market data

```python
from axon_aone.brokers import get_broker

broker = get_broker(
    "angel_one",
    api_key="xxx",
    client_id="xxx",
    pin="1234",
    totp_secret="your_totp_secret"
)
broker.authenticate()
quote = broker.get_quote("RELIANCE", "4119")
positions = broker.get_positions()
```

### 2. **Market Data** (`data/feed.py`)

**MarketDataFeed** Class
- Fetches real-time quotes from Angel One API
- Retrieves 1-minute candlestick data for technical analysis
- Falls back to mock data if API unavailable
- Scans a configurable liquid-symbol universe
- Ranks candidates using market features plus realized trade feedback
- Persists the latest selected symbol batch for dashboard inspection

```python
from axon_aone.data.feed import fetch_market_data

# Live data from Angel One
data = fetch_market_data(use_mock=False)

# Mock data for testing
data = fetch_market_data(use_mock=True)

# Data structure:
# {
#   "symbol": "RELIANCE",
#   "price": 2850.50,
#   "high": 2860.0,
#   "low": 2840.0,
#   "volume": 5000000,
#   "vwap": 2847.30,
#   "candles": [{"open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
# }
```

### 3. **Trading Algorithm** (`features/trade.py`)

**Signal Generation**
- `should_buy()`: Identifies buy opportunities
- `should_sell()`: Identifies exit points
- `trend_persistence()`: Checks for sustained uptrends
- `resumption_entry()`: Detects resumption after pullback

**Trade Execution**
- `run_day()`: Main algorithm loop
- Processes ranked market data, generates signals, and manages open positions
- Applies ATR-based stops and a fixed `+2%` live profit target
- Reserves tradable capital on entry and releases it on exit

```python
from axon_aone.features.trade import run_day

universe = fetch_market_data()
run_day(universe, use_mock=False)
```

### 4. **Risk Management** (`core/risk_engine.py` and `features/trade.py`)

**Risk Controls**
- Daily loss limits (configured from `risk_config.py`)
- Weekly drawdown limits (configured from `risk_config.py`)
- Position sizing based on per-trade risk and max-position notional
- ATR-derived stop-loss calculation
- Capital reservation and release as positions open and close
- Force exit at 2:00 PM IST

```python
from axon_aone.risk.manager import can_open_new_trade

# Check if position can be opened
can_trade = can_open_new_trade(
    entry_price=2850,
    stop_loss_price=2800,
    quantity=1,
    tradable_capital=100000
)
```

### 5. **Scheduler** (`orchestration/scheduler.py`)

**TradingScheduler** Class
- Manages background execution during market hours
- Runs algorithm every 5 minutes (configurable)
- Automatic pre-market setup
- Force exit at 2:00 PM
- Market close cleanup

```python
from axon_aone.orchestration.scheduler import TradingScheduler

scheduler = TradingScheduler(use_mock=False)
scheduler.schedule_trading(main_function)
scheduler.start()  # Runs in background
```

### 6. **Configuration** (`config.py`)

Key Settings:
```python
# Trading hours (IST)
MARKET_OPEN_TIME = datetime.time(9, 15)
MARKET_CLOSE_TIME = datetime.time(15, 30)
FORCE_EXIT_TIME = datetime.time(14, 0)

# Risk parameters
# Canonical risk parameters live in `risk_config.py` (percent-based).
# `config.py` exports commonly used limits as fractions of capital.
MAX_RISK_PER_TRADE = 0.01          # Example: 1% per trade
MAX_DAILY_LOSS = 0.03              # Example: 3% daily limit
MAX_WEEKLY_DRAWDOWN = 0.06         # Example: 6% weekly limit
MAX_CONCURRENT_TRADES = 25         # Example: 25 concurrent positions

# Algorithm interval
ALGO_RUN_INTERVAL = 300            # 5 minutes

# Symbol universe / ranking
AUTO_SELECT_SYMBOLS = True
AUTO_SELECT_TOP_N = 3
MARKET_SCAN_SYMBOLS = ["RELIANCE-EQ", "TCS-EQ", "INFY-EQ", ...]
FIXED_PROFIT_TARGET_PCT = 0.02

# Angel One credentials (from environment)
ANGEL_ONE_API_KEY = os.getenv("ANGEL_ONE_API_KEY")
```

---

## Data Flow

### Single Execution Mode
```
run_trader.py
    ↓
orchestration/main.py::main()
    ↓
fetch_market_data() [from Angel One or mock]
    ↓
select_trade_candidates(universe) [rank top symbols]
    ↓
run_day(universe) [trading algorithm]
    ├─ should_buy() [signal generation]
    ├─ execute_trade() [order placement]
    └─ manage open positions [target / stop / force exit]
    ↓
capital engine [position sizing, risk checks, capital reservation]
    ↓
DB + logs [trades, symbol selections, scheduler order logs]
```

### Scheduler Mode (Background, 24/7)
```
run_trader.py --schedule
    ↓
orchestration/main.py::run_scheduled()
    ↓
TradingScheduler.start()
    ├─ 9:10 AM: Pre-market setup
    ├─ 9:15 AM: Market open announcement
    ├─ Every 5 min: fetch_market_data() → run_day()
    ├─ 2:00 PM: Force exit positions
    └─ 3:30 PM: Market close cleanup
```

---

## Multi-User Docker Deployment

### Docker Compose Structure
```
docker-compose.yml
├── Service: axon-aone-user1
│   ├── Build: Dockerfile
│   ├── Environment: USER1_ANGEL_ONE_API_KEY, etc.
│   ├── Volumes: logs/user1/
│   └── Network: axon-aone-network
│
└── Service: axon-aone-user2
    ├── Build: Dockerfile
    ├── Environment: USER2_ANGEL_ONE_API_KEY, etc.
    ├── Volumes: logs/user2/
    └── Network: axon-aone-network
```

Each user gets:
- Isolated Docker container
- Separate logs directory
- Independent Angel One credentials
- Separate trading state

Runtime note:
- `run_trader.py` is the CLI wrapper.
- `src/axon_aone/orchestration/main.py` is the canonical runtime module.
- `src/axon_aone/main.py` is kept as a compatibility wrapper so `python -m axon_aone.main` continues to work.

---

## Communication Patterns

### 1. Environment Variables
```bash
# Set credentials
export ANGEL_ONE_API_KEY=your_api_key
export ANGEL_ONE_CLIENT_ID=your_client_id
export ANGEL_ONE_PIN=your_pin
export ANGEL_ONE_TOTP_SECRET=your_totp_secret

# Or in .env file
ANGEL_ONE_API_KEY=your_api_key
ANGEL_ONE_CLIENT_ID=your_client_id
```

### 2. Configuration Files
```python
# config.py - central configuration
from axon_aone.config import (
    MARKET_OPEN_TIME,
    MAX_RISK_PER_TRADE,
    AUTO_SELECT_TOP_N,
    FIXED_PROFIT_TARGET_PCT,
)
```

### 3. Logging
```python
import logging
logger = logging.getLogger(__name__)
logger.info("Trade executed")
logger.error(f"Order failed: {error}")
```

---

## Extension Points

### Adding New Signals
```python
# In features/trade.py
def my_signal(candles):
    # Custom signal logic
    return True  # Buy signal
```

### Customizing Risk Rules
```python
# In risk/manager.py
def custom_position_size(capital, risk):
    return capital * risk * 0.5  # Custom formula
```

### Changing Market Hours
```python
# In config.py
MARKET_OPEN_TIME = datetime.time(9, 30)  # Custom market
ALGO_RUN_INTERVAL = 60  # Run every minute
```

---

## Performance Considerations

### Memory Usage
- ~50-100 MB per container (baseline)
- ~10-20 MB for market data (20 symbols)
- Minimal disk I/O

### Network Usage
- ~10-20 API calls per 5 minutes
- ~10-50 KB per API call
- ~1-2 MB per hour

### CPU Usage
- Lightweight computation (signal generation)
- <5% CPU utilization per container
- Good for shared hosting

---

## Deployment Options

### 1. **Local Development**
```bash
python run_trader.py --mock  # Test locally
```

### 2. **Single Container**
```bash
docker build -t axon-aone .
docker run -e ANGEL_ONE_API_KEY=xxx axon-aone
```

### 3. **Multi-User Docker Compose**
```bash
docker-compose up -d
docker-compose ps
docker-compose logs -f
```

### 4. **Cloud Deployment**
- Azure Container Instances
- AWS ECS
- Google Cloud Run
- Kubernetes (with Docker image)

---

## Monitoring & Debugging

### Check Logs
```bash
# Local mode
tail -f logs/user1/trading_*.log

# Docker mode
docker logs axon-aone-user1
docker-compose logs -f axon-aone-user1
```

### Debug Mode
```python
# In main.py
logging.basicConfig(level=logging.DEBUG)  # More verbose output
```

### Health Checks
```bash
docker ps  # Check container status
docker-compose ps  # Check all services
docker logs --tail=50 container_name  # Recent logs
```

---

## Future Enhancements

Potential areas for expansion:
- Additional technical indicators
- Machine learning signal generation
- Advanced risk management models
- Performance analytics dashboard
- Order management improvements
- WebSocket support for real-time data
- Multi-timeframe analysis

---

**Architecture Document** | Axon Aone v1.0 | Angel One Smart API Trading Scheduler
