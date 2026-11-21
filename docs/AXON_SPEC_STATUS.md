# Axon spec status

Tracks the Axon Strategy Spec (21 Nov 2026) against the code. Phase 1 (this branch) is the foundation plus Part 3 (intraday).

## Engineering requirements (review findings 1–14)

| # | Requirement | Code | Test (tests/test_findings.py) |
|---|---|---|---|
| 1 | Exits checked every cycle before buys; forced exit 2:45 PM | `engine.py` step 4, `strategies/intraday_vwap.py` | `test_f1_*` |
| 2 | Every fill is a position; one position per stock; trade limits | `ledger.py`, `risk.approve_entry` | `test_f2_*` |
| 3 | Login on every route; localhost only; typed confirmation for live; no manual order API | `web/app.py`, `docker-compose.yml` | `test_f3_*` |
| 4 | One strategy interface, risk engine, broker adapter; tests use the scheduler's wiring | `context.build` | `test_f4_*` |
| 5 | No fresh real prices: skip and alert; random prices only in TEST | `engine._probe_exchange`, `engine._load`, `market_data.py` | `test_f5_*` |
| 6 | P&L in the ledger; brakes −8/−12/−15 from peak; survive restart | `ledger.snapshot_nav`, `risk.evaluate_brakes` | `test_f6_*` |
| 7 | Real market filter inputs | `market_filter.py` (India VIX for intraday; Nifty 200-day ready for swing) | `test_f7_*` |
| 8 | Sizing from risk, liquidity and capital | `sizing.py` | `test_f8_*` (worked examples) |
| 9 | No past-results bonus in ranking | `intraday_vwap.evaluate` | `test_f9_*` |
| 10 | Daily report from the ledger | `report.py` | `test_f10_*` |
| 11 | Mode per part in the ledger, logged and announced; no startup flag | `modes.py`, `__main__.py` | `test_f11_*` |
| 12 | NSE holiday calendar plus exchange-status check | `clock.py`, `data/nse_holidays.csv`, `engine._probe_exchange` | `test_f12_*` |
| 13 | One copy of each module | old `axon_aone` package deleted | `test_f13_*` |
| 14 | Health check fails if no cycle in 10 minutes during market hours | `health.py`, `Dockerfile`, `docker-compose.yml` (autoheal) | `test_f14_*` |

## Where the code differs from the spec text (review fixes)

1. **Paper means real prices.** The spec's finding 5 says "random prices exist only in paper mode". Here random prices exist only in a separate TEST mode, which can never go live. PAPER uses real Angel One prices with simulated orders, so the intraday probation measures something real.
2. **Drawdown on value per unit.** Deposits buy units and payouts redeem them, so neither looks like profit or loss. The peak is never reset; only the intraday 1% daily stop resets each day. The spec's "reset daily and weekly" wording is not used, as there is no weekly limit any more.
3. **One position per stock** applies across parts within a book, as the spec says (`AXON_ONE_POSITION_ACROSS_PARTS=true`). Set it to `false` for one position per stock per part.
4. **Exits** apply each part's own rules. The core never gets stop-losses. Swing stop timing (intraday or on close) is decided when swing is built.
5. **India VIX level**: starts at 20 (`AXON_INTRADAY_MAX_VIX`). Not in the spec; add it to the open questions.
6. **Intraday sleeve cap**: open intraday positions are capped at the part's 10% allocation, so at most two full-size (5%) positions are open at once.
7. **Live gate**: LIVE also requires the paper test (60 trades, positive after costs and estimated tax, still positive without the best 3 days) and `AXON_STATIC_IP` to be set.
8. **Payouts** are calculated automatically at month end but recorded only when you confirm (`python -m axon income live YYYY-MM --record`).

## What to expect from intraday

With the spec's settings (5% capital cap, stop 1.5 × 5-minute ATR, 0.05% slippage per side), a trade passes the cost test (round trip at most 20% of planned risk) only when the stock's 5-minute ATR is at least:

| Capital | 5-minute ATR needed (% of price) |
|---|---|
| ₹10 lakh | 0.77% |
| ₹1 crore | 0.49% |
| ₹10 crore | 0.46% |

Large tier A stocks usually move less than that in 5 minutes, so **intraday will rarely trade**. Slippage alone is 0.1% of the position per round trip. This is the spec's cost rule working as written, and it is worth deciding before the paper run: accept that intraday mostly sits out (and likely fails its deletion test), or revisit the rule for intraday. Note that, because size is usually capped at 5% of capital, a wider stop raises the planned risk and makes the test easier to pass.

## Built in phase 1

- Ledger with value-per-unit accounting, brakes, modes, kill switch, cost ledger (expected vs actual, measured slippage after 50 orders), tax ledger (estimates; confirm with a CA), data-check log, alerts, heartbeat
- Liquidity tiers from 20-day ADTV; surveillance exclusion list
- Angel One adapter: daily login, logout after close, CNC and MIS orders, order tag, static-IP check, 2 orders/second ceiling, no buys at the upper price limit
- Monthly income rule (calculation and alert)

## Not built yet

| Spec item | Phase |
|---|---|
| Part 1 core: ETFs, gold and debt mix, quality screen, P/E guard, crash buying, rebalancing | 2 |
| Part 2 swing: 200/50/20-day setup, R targets, trailing exit, time stop, sector limits | 2 |
| Adjusted price history (splits, bonuses, delisted stocks) and backtests | 3 |
| Automatic download of NSE ASM/GSM lists and the full NSE/BSE universe | 2 |
| Payday savings automation | later |
| Hedge overlay, tax-aware engine | extensions |

## Deployment notes

- Static IP: run on one VM with a fixed public IP. Azure Container Instances and Kubernetes (in `deploy/archive/`) don't keep a fixed outgoing IP as configured.
- The Prometheus `/metrics` endpoint and the Streamlit dashboard from the old code were removed; the health check and the new dashboard replace them.
