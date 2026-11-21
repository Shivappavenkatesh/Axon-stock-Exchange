Capital Engine Implementation Roadmap

This document provides a complete, structured Markdown version of the capital engine architecture, implementation phases, and scaffold.

Status (Axon repo):
- Core capital engine modules (regime, risk engine, kill-switch, sandbox, execution, correlation, allocation) are implemented under src/axon_aone/core/.
- PostgreSQL-backed persistence (trades, symbol selections, portfolio snapshots, regime history, correlation matrices, kill-switch logs, engines) is implemented in src/axon_aone/db.py.
- Streamlit dashboard for equity, PnL, regime, engine allocation, correlations, trade diagnostics, and latest symbol selections is implemented in dashboard/app.py.
- Tests exist for the capital engine core, symbol ranking, DB seeding/backfill, and performance metric calculations under tests/.
- The live trading loop now uses auto-ranked symbol selection, risk-based sizing, ATR stop-losses, fixed `+2%` profit targets, and capital reservation / release.

1. Capital Engine Implementation Sequence

Phase 1 — Infrastructure Setup (Day 1–3)

Cloud Server: AWS EC2 (t3.small+), Ubuntu 22.04, 30GB storage, static IP, firewall (22, 443). Install Python 3.10+, Git, Nginx, Supervisor, PostgreSQL/SQLite.

Zerodha Setup: Kite Connect API, API key/secret, manual token generation, sandbox test order.

Telegram Bot: Create via BotFather, get token & chat ID, test message.

Domain + SSL: Domain/subdomain, Nginx reverse proxy, Certbot SSL, secure webhook.

Phase 2 — Backend Core (Day 4–10)

Database Schema: trades, symbol_selections, engines, portfolio_snapshots, regime_history, correlation_matrix, structural_hunter, kill_switch_log, global_state.

Regime Engine: Daily NIFTY trend, breadth, VIX, liquidity → regime score (0–100) + mode.

Global Risk Engine: Portfolio heat, risk-per-trade, drawdown throttle, kill-switch logic.

Allocation Engine: Monthly scoring (Sharpe, PF, DD stability, regime alignment).

Execution Engine: Order placement, modification, reconciliation, partial fills, retry logic.

Performance Tracker: 5 min sync of positions, equity, DD, heat, engine PnL, Sharpe, and symbol selection diagnostics.

Correlation Engine: 30 day rolling correlations, beta, sector exposure.

Kill Switch Monitor: Daily/weekly loss, DD, correlation cluster, regime collapse triggers.

Symbol Selection Engine: score liquid NSE candidates using market micro-signals plus realized trade feedback; persist the latest ranked selection set for dashboard review.

Sandbox Engine: Simulated capital pool with slippage, brokerage, graduation logic.

Phase 3 — Streamlit Dashboard (Day 11–15)

Portfolio Overview: Equity curve, DD, heat, regime, kill switch, allocation.

Engine Performance: Allocation, Sharpe, DD, PF, rolling PnL, manual toggles.

Trade Monitor: Open trades, R-multiple, unrealized PnL, engine tag, manual close.

Correlation & Exposure: Heatmap, sector/asset exposure, beta, convex exposure.

Structural Hunter: Score, revenue growth, allocation, thesis log.

Sandbox Lab: PnL, Sharpe, DD, graduation countdown.

Phase 4 — System Testing (Day 16–20)

Test: daily loss trigger, DD >25%, correlation spike, broker rejection, server kill, restart recovery, webhook flood, Telegram downtime.

Phase 5 — Full Simulation (30 Days)

Track: Sharpe, DD, engine health, correlation stability, kill switch, slippage.

Phase 6 — Live Activation

Week 1: 25% capital → Week 4: 100% if no guardrail breach.

2. Project Scaffold (v1.0)

Folder Structure

capital_engine/
├── main.py
├── config.py
├── db.py
├── scheduler.py
├── requirements.txt
├── core/
│   ├── regime.py
│   ├── risk.py
│   ├── allocation.py
│   ├── correlation.py
│   ├── performance.py
│   ├── kill_switch.py
│   ├── sandbox.py
│   ├── execution.py
│   ├── broker_zerodha.py
│   ├── telegram.py
├── engines/
│   ├── trend_engine.py
│   ├── etf_engine.py
│   ├── options_engine.py
│   ├── structural_engine.py
│   ├── statarb_engine.py
└── dashboard/
    └── app.py

requirements.txt

kiteconnect
streamlit
pandas
numpy
sqlalchemy
apscheduler
requests
python-dotenv
scipy

config.py

MODE = "SIMULATION"
INITIAL_CAPITAL = 1000000
MAX_RISK_PER_TRADE = 0.01
MAX_PORTFOLIO_HEAT = 0.10
DAILY_LOSS_LIMIT = 0.03
WEEKLY_LOSS_LIMIT = 0.06
DRAWDOWN_THROTTLE = 0.15
DRAWDOWN_KILL = 0.25
DATABASE_URL = "sqlite:///capital_engine.db"

main.py

from core.regime import calculate_regime
from core.risk import RiskEngine
from core.execution import ExecutionEngine
from core.kill_switch import KillSwitch
from scheduler import start_scheduler

def start():
    print("Capital Engine Starting...")
    regime_score = calculate_regime()
    print(f"Current Regime Score: {regime_score}")
    risk_engine = RiskEngine()
    execution_engine = ExecutionEngine()
    kill_switch = KillSwitch()
    start_scheduler()

if __name__ == "__main__":
    start()

core/regime.py

def calculate_regime():
    trend_score = 20
    breadth_score = 20
    vix_score = 20
    liquidity_score = 20
    return trend_score + breadth_score + vix_score + liquidity_score

core/risk.py

class RiskEngine:
    def __init__(self):
        self.portfolio_heat = 0
        self.drawdown = 0

    def approve_trade(self, risk_percent):
        if risk_percent > 0.02:
            return False
        if self.portfolio_heat >= 0.10:
            return False
        if self.drawdown >= 0.25:
            return False
        return True

core/kill_switch.py

class KillSwitch:
    def __init__(self):
        self.active = False

    def check(self, daily_loss, drawdown):
        if daily_loss >= 0.03 or drawdown >= 0.25:
            self.active = True
        return self.active

core/execution.py

from config import MODE
from core.sandbox import SandboxEngine
from core.broker_zerodha import ZerodhaBroker

class ExecutionEngine:
    def __init__(self):
        self.sandbox = SandboxEngine()
        self.broker = ZerodhaBroker()

    def execute(self, order):
        if MODE == "SIMULATION":
            return self.sandbox.simulate(order)
        else:
            return self.broker.place_order(order)

core/sandbox.py

class SandboxEngine:
    def simulate(self, order):
        print(f"Simulated order: {order}")
        return {"status": "simulated"}

core/performance.py

def calculate_sharpe(returns):
    import numpy as np
    return np.mean(returns) / np.std(returns)

core/correlation.py

import pandas as pd

def compute_correlation(df):
    return df.corr()

core/telegram.py

import requests

def send_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})

core/broker_zerodha.py

from kiteconnect import KiteConnect

class ZerodhaBroker:
    def __init__(self):
        self.kite = KiteConnect(api_key="YOUR_API_KEY")

    def place_order(self, order):
        print(f"Live order placed: {order}")
        return {"status": "live"}

scheduler.py

from apscheduler.schedulers.background import BackgroundScheduler
from core.regime import calculate_regime

def scheduled_tasks():
    score = calculate_regime()
    print(f"Scheduled Regime Score: {score}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_tasks, 'interval', minutes=5)
    scheduler.start()

dashboard/app.py

import streamlit as st
import pandas as pd

st.title("Capital Engine Dashboard")

st.metric("Equity", "₹1,000,000")
st.metric("Drawdown", "0%")
st.metric("Regime", "Base Mode")

st.subheader("Engine Allocation")
st.write({
    "Trend": "35%",
    "ETF": "20%",
    "Options": "15%",
    "Structural": "15%",
    "StatArb": "10%"
})

3. Summary

This Markdown file consolidates the full implementation roadmap, architecture, and scaffold for the capital engine, ready for development and expansion.