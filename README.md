# Axon – Angel One Capital Engine

Automated Angel One trading system with an integrated **capital engine** (regime, risk, kill-switch, sandbox execution), a **background scheduler**, a **web trading terminal**, and a **PostgreSQL + Streamlit performance dashboard**.

> This repository combines the two earlier projects (Axon main and Axon Aone) into one codebase: the capital engine, scheduler and web terminal from Axon main, plus the backtester, fundamentals screener, Prometheus metrics, Kubernetes manifests and Azure Container Instances deployment from Axon Aone.

---

## Key Features

- **🤖 Automatic Scheduling** – Runs every 5 minutes during market hours (9:15 AM – 3:30 PM IST)
- **📅 Market Hours Aware** – Only trades Monday–Friday; respects market open/close times
- **🧠 Capital Engine** – Regime scoring, risk engine, kill-switch, sandbox execution, and allocation engine
- **🛡️ Risk Management** – Risk-based position sizing, ATR stop-losses, fixed profit targets, daily/weekly loss limits, portfolio heat limits, and kill‑switch controls
- **🔐 Angel One SmartAPI** – Exclusive Angel One Smart API integration with proper 2FA/TOTP authentication
- **🎯 Auto Symbol Selection** – Ranks a broad NSE scan universe and selects the strongest candidates using market features plus realized trade feedback
- **📊 PostgreSQL Persistence** – Trades, symbol selections, portfolio snapshots, regime history, kill‑switch logs, correlations, and engines
- **📈 Streamlit Dashboard** – Equity curve, daily PnL, regime history, engine allocation, correlations, Sharpe / drawdown, and latest symbol selection diagnostics
- **🌐 Web Interface** – Real-time trading terminal over Flask + Socket.IO (mock and live modes)
- **🧪 Backtester** – Deterministic replay of the entry/exit rules on mock or saved candles (`scripts/run_backtest.py`)
- **🔎 Fundamentals Screener** – Scores symbols on growth, ROE, leverage and size; can pre-filter the backtest universe
- **📟 Prometheus Metrics** – `/metrics` on the web server: order counts by side/status, execution latency, position fetches
- **☸️ Kubernetes & Azure** – Manifests in `k8s/`, Azure Container Instances scripts, and scheduled start/stop to save cost

---

## Repository Layout

| Path | Purpose |
|---|---|
| `src/axon_aone/` | Python package: capital engine (`core/`, `risk/`, `execution/`, `portfolio/`), strategy, scheduler (`orchestration/`), web app (`interfaces/web/`), services |
| `src/axon_aone/backtester.py`, `features/screener.py`, `features/data_ingest.py` | Backtesting and fundamentals screening |
| `run_trader.py`, `run_web.py`, `docker_entrypoint.py` | Entry points (scheduler, web terminal, container) |
| `dashboard/` | Streamlit performance dashboard |
| `research/`, `scripts/` | Due-diligence scorecard, token updater, backtest runner, AWS bootstrap |
| `k8s/` | Kubernetes manifests (namespace, secrets template, deployment, HPA, PDB) |
| `deploy-aws-*.ps1` | AWS EC2 (Mumbai) deployment |
| `deploy-azure*.{sh,ps1}`, `azure-deploy-*.json`, `setup-azure.sh`, `scheduled-*.sh` | Azure VM / Container Instances deployment |
| `tests/` | Pytest suite |

## 🧪 Backtesting & Screening

```bash
# Backtest on mock data
python scripts/run_backtest.py --mock

# Backtest saved candles ({"SYMBOL": [{timestamp, open, high, low, close, volume}, ...]})
python scripts/run_backtest.py --input backtest_input.json

# Screen by fundamentals first, keep the top 5
python scripts/run_backtest.py --mock --fundamentals fundamentals.json --top 5
```

Results are written to `backtest_results.json`.

## 📟 Monitoring

With `prometheus-client` installed, the web server exposes `GET /metrics` with `axon_execute_total{side,status}`, `axon_execute_latency_seconds` and `axon_positions_total{status}`. Without the package the endpoint returns 503 and trading is unaffected.

---

## 🚀 Quick Start

For a single-VM AWS deployment that stays inside free-tier guardrails, see [AWS_FREE_TIER_DEPLOYMENT.md](AWS_FREE_TIER_DEPLOYMENT.md). For a Mumbai-region EC2 launcher, use [deploy-aws-ec2-mumbai.ps1](deploy-aws-ec2-mumbai.ps1).

### 1. Install Dependencies

```bash
# From your workspace
cd Axon-stock-Exchange

# Create virtual environment (optional but recommended)
python -m venv .venv

# Activate (Windows PowerShell)
 .\.venv\Scripts\Activate.ps1

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Angel One Credentials

Angel One Smart API requires 4 credentials for authentication:

| Credential | Description | How to Get |
|------------|-------------|------------|
| `ANGEL_ONE_API_KEY` | API Key from SmartAPI portal | [SmartAPI Portal](https://smartapi.angelbroking.com/) |
| `ANGEL_ONE_CLIENT_ID` | Your Angel One User ID | Your trading account ID (e.g., `A123456`) |
| `ANGEL_ONE_PIN` | 4-digit trading MPIN | Set in Angel One app |
| `ANGEL_ONE_TOTP_SECRET` | TOTP secret for 2FA | Angel One App > Profile > Settings > TOTP |

**Set Environment Variables (Windows PowerShell):**
```powershell
$env:ANGEL_ONE_API_KEY = "your_api_key"
$env:ANGEL_ONE_CLIENT_ID = "your_client_id"
$env:ANGEL_ONE_PIN = "your_pin"
$env:ANGEL_ONE_TOTP_SECRET = "your_totp_secret"
```

**Set Environment Variables (Linux/Mac):**
```bash
export ANGEL_ONE_API_KEY="your_api_key"
export ANGEL_ONE_CLIENT_ID="your_client_id"
export ANGEL_ONE_PIN="your_pin"
export ANGEL_ONE_TOTP_SECRET="your_totp_secret"
```

### 3. Test Connection & Run Tests

```bash
# Live connectivity smoke test (skips if credentials are missing)
python test_angel_connection.py

# Full unit test suite (capital engine, DB metrics, etc.)
python -m pytest
```

### 4. Run Trading System

```bash
# Mock mode (paper trading – no broker credentials needed)
python run_trader.py

# Live trading with Angel One
python run_trader.py --angel-one

# Background scheduler (runs during market hours)
python run_trader.py --schedule --angel-one
```

Runtime note:
- `run_trader.py` is the user-facing CLI wrapper.
- `src/axon_aone/orchestration/main.py` is the canonical runtime module.
- `src/axon_aone/main.py` remains available as a compatibility wrapper for `python -m axon_aone.main`.

### 5. Run The Master DD Scorecard

The repository also includes a standalone due-diligence scorecard CLI for stocks, ETFs, and Bitcoin. It applies layer-by-layer gating, hard-fail checks, weighted scoring, and position-sizing guidance.

```bash
# Generate a DD input template
python research/dd/master_dd_scorecard.py --init-template research/dd/dd_template.json

# Evaluate a stock DD case
python research/dd/master_dd_scorecard.py --asset stock --input research/dd/dd_template.json

# Evaluate an ETF DD case
python research/dd/master_dd_scorecard.py --asset etf --input research/dd/dd_template.json

# Evaluate a Bitcoin DD case
python research/dd/master_dd_scorecard.py --asset bitcoin --input research/dd/dd_template.json
```

Compatibility note:
- `scripts/master_dd_scorecard.py` still works as a thin wrapper, but the canonical home is now `research/dd/`.

Expected output includes:
- `decision`: `investable` or `reject`
- `blocked_layer`: first layer that stopped progression
- `auto_fail_reasons`: hard-stop rule violations
- `weighted_score`: aggregate DD score out of 100
- `position_sizing`: suggested position percentage and risk tier

---

## 🌐 Web Interface

Modern web-based trading dashboard with real-time updates, backed by the capital engine and PostgreSQL persistence.

```bash
# Start web server
python run_web.py

# Or use platform scripts
 .\start-web.ps1   # Windows
 ./start-web.sh    # Linux/Mac
```

**Access at:** http://localhost:5000

### Web Login

The web dashboard is protected by a simple login that validates credentials against environment variables:

- `WEB_USERNAME` – required web login username
- `WEB_PASSWORD` – required web login password

Set them before starting the web server. If they are not set, login will always fail and the UI will show an error message.

### Web Features
- 📊 **Trading Terminal** – Place BUY/SELL orders in mock or live mode
- 📈 **Portfolio Dashboard** – Real-time P&L and equity tracking
- 📋 **Order Management** – View / cancel orders; see broker responses
- 💼 **Position & Portfolio Tracking** – Current holdings and portfolio metrics
- 🔄 **WebSocket Updates** – Live data without refresh
- 📲 **Telegram Alerts** – Optional Telegram notifications for orders and kill‑switch events

---

## 📁 Project Structure

```
Axon/
├── src/axon_aone/
│   ├── brokers/                 # Angel One Smart API integration
│   ├── core/                    # Capital engine (regime, risk, kill‑switch, sandbox, execution, allocation, correlation)
│   ├── data/                    # Market data feed
│   ├── execution/               # Broker execution adapter
│   ├── features/trade.py        # Trading algorithm using capital engine
│   ├── orchestration/           # Canonical runtime entrypoint and market-hours scheduler
│   ├── risk/                    # Legacy risk helpers (some logic superseded by core/risk_engine.py)
│   ├── services/                # Scheduler, token manager, Telegram notifier, order store
│   ├── templates/               # Web UI templates
│   ├── static/                  # CSS, JavaScript
│   ├── config.py                # Configuration
│   ├── db.py                    # SQLAlchemy models and DB session
│   ├── main.py                  # Compatibility wrapper for python -m axon_aone.main
│   └── web_server.py            # Web server & WebSocket events
├── dashboard/                   # Streamlit performance dashboard (equity, PnL, regime, allocation, correlations)
├── examples/                    # Example scripts
├── logs/                        # Local trading logs
├── tests/                       # Unit tests (capital engine, DB metrics, etc.)
├── requirements.txt
├── run_trader.py                # CLI runner
├── run_web.py                   # Web server runner
└── test_angel_connection.py     # Angel One connection tests (environment-aware)
```

---

## ⚙️ Configuration

Edit `src/axon_aone/config.py` to customize most runtime settings.

Runtime entrypoint code lives in `src/axon_aone/orchestration/main.py`.

Risk limits live in `src/axon_aone/risk_config.py` (percent-based). `config.py`
exports commonly used limits as fractions of capital for backwards compatibility.

```python
# Trading hours (IST)
MARKET_OPEN_TIME = datetime.time(hour=9, minute=15)
MARKET_CLOSE_TIME = datetime.time(hour=15, minute=30)

# Database URL (PostgreSQL by default; can be SQLite for testing)
AXON_DATABASE_URL = os.getenv("AXON_DATABASE_URL", "postgresql+psycopg2://user:pass@localhost:5432/axon")

# Risk management
# (Canonical source: src/axon_aone/risk_config.py)
from axon_aone.config import MAX_RISK_PER_TRADE, MAX_DAILY_LOSS, MAX_CONCURRENT_TRADES

# Live trade exits
FIXED_PROFIT_TARGET_PCT = 0.02        # default +2% target
STOP_LOSS_ATR_MULTIPLIER = 2.0        # from risk_config.py

# Auto universe selection
AUTO_SELECT_SYMBOLS = True
AUTO_SELECT_TOP_N = 0            # 0 => adaptive threshold-only selection
AXON_MARKET_SCAN_SYMBOLS = "RELIANCE-EQ,INFY-EQ,TCS-EQ,..."

# Force exit before market close
FORCE_EXIT_TIME = datetime.time(hour=14, minute=0)
```

### Blended Titan Profile

You can enable a pre-tuned mixed best-practice profile (quality + asymmetry +
risk-first + process discipline) without changing code:

```bash
AXON_STRATEGY_PROFILE=blended_titan_mode
```

When enabled, defaults are tuned for:
- tighter per-trade and daily/weekly risk
- adaptive opportunity selection (no fixed stock count cap by default)
- stronger relative-to-best symbol filtering
- profit-protection exits after strong gains and peak drawdowns
- bounded new entries per cycle and correlated-position concentration limits
- confidence-weighted learning (small sample outcomes get dampened)
- execution quality monitoring (slippage guardrails + rejection reason telemetry)

All profile values remain overrideable via environment variables in `.env`.

---

## 📊 Trading Algorithm

For a complete institutional-grade buildout plan (risk, compliance, OMS/EMS,
reconciliation, governance, and KPI gates), see
`INSTITUTIONAL_TRADING_PLAYBOOK.md`.

The system implements:
- **Trend Analysis** - VWAP-based trend detection with pullback resumption entries
- **Universe Selection** - Ranks a liquid NSE candidate list and selects the highest-scoring symbols before signal generation
- **Exit Rules** - Fixed `+2%` profit target, ATR-based stop loss, and force exit at 2 PM
- **Risk Management** - Risk-based sizing, tradable-capital reservation/release, daily/weekly limits, and portfolio heat checks
- **Phase 2 Controls** - VaR/stress scenario circuit breakers and constraint-aware allocation planning (symbol/sector/new-exposure caps)
- **Phase 3 Governance** - Model registry with promotion gates and automatic monthly risk-committee report packs

### Current Live Trade Lifecycle

1. Fetch quotes and candles for the configured scan universe.
2. Rank symbols using momentum, VWAP edge, short-term trend, volume expansion, ATR-normalized volatility, win rate, and realized PnL feedback.
3. Select the top `N` symbols above the configured score threshold.
4. Size each trade from per-trade risk budget and max-position notional.
5. Open trades with an ATR-derived stop and a fixed `+2%` profit target.
6. Reserve capital while a position is open and release it when the position is closed.
7. Persist both executed trades and the latest symbol-selection batch for dashboard review.

---

## 🔧 Troubleshooting

### Authentication Failed
1. Verify all 4 credentials are correct
2. Check TOTP secret is in base32 format (like `SH263ORE3L6GJF5RRFOIJJ34CE`)
3. Run `python test_angel_connection.py` to debug

### TOTP Generation Failed
- TOTP secret must be base32 encoded (NOT UUID format)
- Get from: Angel One App > Profile > Settings > TOTP > Reset > Copy secret

### No Market Data
- Check market hours (9:15 AM - 3:30 PM IST, Mon-Fri)
- Verify credentials have API access enabled
- Use mock mode for testing: `python run_trader.py`

---

## 📄 License

MIT License - See LICENSE file for details

---

## ⚠️ Disclaimer

**Trading Disclaimer**: This software is for educational purposes. Live trading carries risk of loss. Test thoroughly in mock mode before live trading. Always maintain proper risk management.

**Not Financial Advice**: This tool does not provide financial advice. Consult a financial advisor before trading.

---

**Version**: 1.0.0 | **License**: MIT | **Python**: 3.8+
