# Axon

Axon is a core-and-satellite trading system for Angel One, built to the **Axon Strategy Spec** (60% core, 30% swing, 10% intraday, hard 15% maximum drawdown).

This version builds the **foundation and the intraday part**. Core and swing come next; until then they are fixed in OFF mode. See [docs/AXON_SPEC_STATUS.md](docs/AXON_SPEC_STATUS.md) for which spec items are built, where the code differs from the spec text, and what is left.

> This is software to test a trading design, not financial advice. Keep intraday in PAPER mode until it passes its 60-trade test.

## How it works

Every 5 minutes during market hours, for each part that is switched on:

1. Skip weekends and NSE holidays.
2. Check that real prices are fresh. If not, skip the cycle and alert on Telegram. Random prices are never used outside TEST mode.
3. Update positions and the portfolio brakes (−8% halve risk, −12% no new entries, −15% close swing and intraday and lock until reviewed). Drawdown is measured on value per unit, so deposits and payouts don't distort it.
4. Check exits for every open position before any new buy.
5. Stop intraday for the day after a 1% loss.
6. New entries: time window, India VIX filter, risk-engine approval, sizing (risk, liquidity and capital caps), cost test (round-trip cost at most 20% of planned risk), order.

Every fill goes into one SQLite ledger with its costs and estimated tax, so state survives restarts.

### Modes (per part)

| Mode | Prices | Orders | Use |
|---|---|---|---|
| OFF | none | none | default for core and swing |
| TEST | random | simulated | development only; can never go LIVE |
| PAPER | real (Angel One) | simulated, full costs | default for intraday; probation runs here |
| LIVE | real | real | only after the paper test passes, with login plus typed confirmation |

Each mode keeps its own money book, so practice results never mix with real money.

## Layout

```
src/axon/
  engine.py          the trading cycle
  risk.py            the one risk engine: brakes, daily stop, kill switch, entry approval
  ledger.py          the one ledger (SQLite): positions, orders, costs, tax, value per unit, modes
  costs.py           Angel One cost model and the cost test
  sizing.py          position sizing
  universe.py        liquidity tiers from 20-day ADTV
  market_data.py     real vs test data, freshness/gap/jump checks
  market_filter.py   Nifty 200-day trend, India VIX
  strategies/        one strategy interface; intraday_vwap.py
  broker/            paper broker and the Angel One adapter (CNC/MIS, algo tag, static IP, rate limit, logout)
  scheduler.py       daily routine; health.py; report.py; income.py; modes.py
  web/               the one dashboard (login required)
  data/              universe, NSE holidays, surveillance list
research/            due-diligence scorecard and fundamentals screener (not in the trading path)
tests/               one test per spec engineering requirement, plus components
deploy/archive/, docs/archive/   previous deploy scripts and docs, kept for reference
```

## Quick start (paper)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in Angel One keys, dashboard login, Telegram
export PYTHONPATH=src

python -m axon hash-password    # paste the result into AXON_WEB_PASSWORD_HASH
python -m axon deposit paper 1000000
python -m axon status
python -m axon run              # the trading loop
python -m axon web              # dashboard on http://127.0.0.1:8080
```

Without Angel One keys, use TEST mode: `python -m axon mode intraday test`, `python -m axon deposit test 1000000`.

Other commands: `cycle`, `health`, `report [YYYY-MM-DD]`, `kill-switch on|off`, `mode PART MODE [--confirm "LIVE intraday"]`, `income BOOK YYYY-MM [--record]`, `withdraw BOOK AMOUNT`.

## Deploying

Run it on **one VM whose public IP is registered with Angel One** (AWS Elastic IP or Azure static IP). Live orders are refused from any other IP.

```bash
docker compose up -d --build
ssh -L 8080:127.0.0.1:8080 user@your-server   # then open http://localhost:8080
```

- Open only SSH (port 22) in the firewall; the dashboard is published to localhost on the server.
- The trader container is restarted automatically if its health check fails (no finished cycle in 10 minutes during market hours).
- Before market open each day, update `src/axon/data/surveillance.txt` with NSE's ASM/GSM lists, and add each new year's holiday list to `nse_holidays.csv`.

The old Azure Container Instances and Kubernetes setups are in `deploy/archive/`. They can't keep a fixed outgoing IP as configured, so they don't meet the static-IP rule.

## Tests

```bash
PYTHONPATH=src python -m pytest -q
```

GitHub Actions runs the same tests on every push and pull request.

## Secrets

Never commit credentials. `.env`, keys, databases and logs are git-ignored and kept out of Docker images.
