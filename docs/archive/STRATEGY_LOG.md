**Strategy Log — Axon Aone**

Purpose: record of every trading strategy, idea, rule, and implementation decision considered during the project, with file references, current status, parameters, tests, and recommended next steps.

1) Value-Oriented ("Warren")
- Description: Fundamental, margin-of-safety based ideas: select high-quality companies, size conservatively, hold for multi-week/months, focus on downside protection.
- Implemented features:
  - Fundamental screener (`src/axon_aone/features/screener.py`) — simple scoring, top-N selection. (Added)
  - Data ingestion for fundamentals and history: CSV + `yfinance` helpers (`src/axon_aone/features/data_ingest.py`). (Added)
  - Risk-based sizing to limit capital at risk per trade (`src/axon_aone/features/trade.py`). (Implemented)
  - Vaulting profits into `investment_bucket` (profit-taking & capital preservation) (`src/axon_aone/features/trade.py`, `src/axon_aone/services/vault_manager.py`). (Implemented)
- Key params / defaults: `MAX_RISK_PER_TRADE` / `START_CAPITAL` in `src/axon_aone/config.py`.
- Tests: persistence and vault tests (`tests/test_persistence_and_vault.py`).
- Limitations: fundamental scoring is simple (scaffold); mapping Indian tickers to `yfinance`/alpha-vantage needs refinement.
- Next steps: enrich screener with financial ratios, add earnings / quality filters, integrate paid fundamentals API for reliability.

2) Growth/Scale-Oriented ("Elon")
- Description: automation-first, high-frequency trend capture, scaling position size with confidence, automation, monitoring, metrics for observability.
- Implemented features:
  - Deterministic backtester to evaluate execution and slippage (`src/axon_aone/backtester.py`, `scripts/run_backtest.py`). (Added)
  - Execution instrumentation & Prometheus metrics (`src/axon_aone/execution/broker.py` instrumentation, `/metrics` endpoint in `src/axon_aone/web_server.py`). (Added)
  - Web dashboard + endpoints (`src/axon_aone/web_server.py`, `src/axon_aone/templates/dashboard.html`). (Added)
  - Monitoring & alerting scaffolding (`src/axon_aone/services/monitor.py`) and Telegram notification (`src/axon_aone/services/telegram_notify.py`). (Added + local stub `src/telegram.py` for tests)
- Key params / defaults: executor latency histograms and counters instrumented; backtester supports slippage, commission, ATR stop, next-open fills.
- Tests: strategy-level unit tests in `tests/test_accounting.py` (buy/sell flow). Backtester has a runner script for manual/backtest runs.
- Limitations: production observability (Prometheus/Grafana dashboards) not deployed; real-time scaling policies need guardrails.
- Next steps: add tuned scaling policies, auto-scaling infra (K8s HPA), and a runbook for alerts.

3) Hybrid / Combined (Warren + Elon)
- Objective: combine value screening with automated execution and robust risk controls — capture large winners while protecting capital.
- Implementations / decisions taken:
  - Use fundamental screener to shortlist (Warren) then apply trend/resumption entries and ATR stops for execution (Elon). Code paths: `features/screener.py` + `features/trade.py`.
  - Size positions using risk % of tradable capital, not naive fixed sizes (`features/trade.py`).
  - Vault profits into an `investment_bucket` and optionally release via auto-release policy (`services/vault_manager.py`).
  - Deterministic backtester to validate combined approach and parameter sweeps (`backtester.py`).
- Rationale: preserve capital (value bias) while scaling winners using automation & telemetry.
- Next steps: implement combined backtest scenarios (fundamental filter -> momentum entry), add parameter grid search harness.

4) Execution & Risk Controls
- Stop-loss styles supported: ATR-based stop and static stop (`backtester.py`, `features/trade.py`).
- Fill modeling: next-open fills, slippage percentage, and commission pipeline in backtester (so PnL math reflects realistic fills).
- Metrics instrumented: orders placed, fills, latency histogram, failed order counters (`execution/broker.py`).
- Persistence: durable state and trade log via SQLite (`src/axon_aone/services/state_store.py`).
- Tests: accounting and persistence tests cover basic flows (`tests/test_accounting.py`, `tests/test_persistence_and_vault.py`).
- Next steps: extend execution quality checks, store raw fill events and reconciliation data, simulate partial fills in backtester.

5) Screening & Data
- Data sources considered: broker LTP/candles, `yfinance`, Alpha Vantage, CSV historicals.
- Implemented: `features/data_ingest.py` (CSV + yfinance helper), `features/screener.py` (scoring). Broker market data used when live (`src/axon_aone/data/feed.py`).
- Limitations: some providers require symbol/token mapping for NSE; further domain work needed.

6) Profit Vaulting & Automation
- Mechanism: detect realized profit increases `total_capital` and sweep a percentage to `investment_bucket` (vault). Vault auto-release policy can return funds to tradable capital on schedule or by rule (`services/vault_manager.py`).
- File references: `features/trade.py`, `services/vault_manager.py`, `services/state_store.py`.
- Tests: vault persistence test (`tests/test_persistence_and_vault.py`).

7) Monitoring, Alerts & Notifications
- Implemented: Prometheus metrics, `/metrics` endpoint, basic `services/monitor.py` for drawdown checks, and `services/telegram_notify.py` to send alerts. `src/telegram.py` stub used to allow offline testing.
- Next steps: connect Prometheus + Grafana using Docker Compose or K8s, configure alert rules and escalation.

8) Backtesting & Validation
- Deterministic backtester supports:
  - Replay of historical candles
  - ATR stop logic
  - Slippage and commission
  - Next-open fills option
  - Simple portfolio accounting (cash, tradable capital, PnL)
- Files: `src/axon_aone/backtester.py`, `scripts/run_backtest.py`.
- Next steps: add batched parameter sweeps, cross-validate against live fills, implement more realistic order book slippage models.

9) Operational / Deployment Considerations
- Docker + K8s manifests present (`Dockerfile`, `docker-compose.yml`, `k8s/`). For persistence, mount a volume for SQLite or switch to external DB for HA.
- Secrets: inject broker and telegram secrets via environment or secrets manager. See `DEPLOYMENT.md` for env var list.

10) Tests & CI
- Tests added/updated: `tests/test_accounting.py`, `tests/test_persistence_and_vault.py`, plus placeholder tests.
- Warnings resolved: converted `test_angel_connection.py` into pytest-friendly auto-skip tests.
- Next steps: add CI workflows (lint, unit tests, build image, run backtest smoke test), and test coverage thresholds.

Appendix: Implementation status legend
- Implemented: code added and unit-tested locally.
- Added/Scaffolded: code added but needs more data or parameter tuning.
- Not implemented: mentioned but not implemented here.

If you'd like this exported as JSON or a compact CSV for change-tracking, I can create that as well.

Document created: March 2, 2026
