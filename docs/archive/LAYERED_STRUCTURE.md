# Axon Layered Structure

This document defines a cleaner layered layout for the codebase so each concern has a clear home and the runtime path from research to execution is easier to reason about.

## Recommended Layers

### 1. Research Layer
Purpose:
- Idea generation
- due diligence tools
- screening
- backtests
- signal research
- notebooks and one-off analysis

What belongs here:
- DD scorecards
- universe selection tools
- factor research
- backtest prototypes
- experiment reports

Suggested paths:
```text
research/
  dd/
  backtests/
  screens/
  notebooks/
  reports/
```

Current candidates:
- scripts/master_dd_scorecard.py
- scripts/dd_template.json
- examples/
- dashboard/ for analytics output, if you later split dashboard from trading runtime

Rule:
Research code should not directly place live trades.

### 2. Strategy Layer
Purpose:
- Convert market observations into signals and trade intents

What belongs here:
- signal generation
- entry and exit rules
- regime-aware strategy rules
- strategy configs and parameters

Suggested paths:
```text
src/axon_aone/strategy/
  signals/
  rules/
  portfolios/
  strategies/
```

Current mapping:
- src/axon_aone/features/trade.py
- src/axon_aone/strategies/
- parts of src/axon_aone/core/regime.py

Rule:
Strategy code should produce intents like buy, sell, size candidate, and stop candidate. It should not talk to brokers directly.

### 3. Portfolio / Capital Layer
Purpose:
- Transform multiple strategy intents into a portfolio-level allocation plan

What belongs here:
- allocation engine
- capital budgeting
- exposure balancing
- correlation-aware sizing
- heat budgeting

Suggested paths:
```text
src/axon_aone/portfolio/
  allocation.py
  correlation.py
  exposure.py
  capital.py
```

Current mapping:
- src/axon_aone/core/allocation.py
- src/axon_aone/core/correlation.py

Rule:
This layer decides what should be funded, not how orders are sent.

### 4. Risk Layer
Purpose:
- Stop bad trades, bad exposures, and bad system states before execution

What belongs here:
- per-trade risk rules
- portfolio heat limits
- kill-switch logic
- daily and weekly loss limits
- exception-based safety rules

Suggested paths:
```text
src/axon_aone/risk/
  engine.py
  kill_switch.py
  limits.py
  manager.py
  policies/
```

Current mapping:
- src/axon_aone/core/risk_engine.py
- src/axon_aone/core/kill_switch.py
- src/axon_aone/risk/manager.py

Rule:
Risk must be able to veto strategy and execution decisions.

### 5. Execution Layer
Purpose:
- Turn approved orders into broker-compatible requests and manage fills

What belongs here:
- execution engine
- broker adapters
- order normalization
- slippage and sandbox fills
- order state transitions

Suggested paths:
```text
src/axon_aone/execution/
  engine.py
  orders.py
  broker.py
  sandbox.py
  brokers/
```

Current mapping:
- src/axon_aone/core/execution_engine.py
- src/axon_aone/core/sandbox.py
- src/axon_aone/execution/broker.py
- src/axon_aone/brokers/

Rule:
Execution should receive approved order instructions, not invent them.

### 6. Data Layer
Purpose:
- Provide clean market, account, and reference data to the rest of the system

What belongs here:
- market data feed
- instrument metadata
- broker account snapshots
- persistence access
- token and session state needed for data access

Suggested paths:
```text
src/axon_aone/data/
  market/
  broker/
  reference/
  storage/
```

Current mapping:
- src/axon_aone/data/feed.py
- src/axon_aone/db.py
- parts of src/axon_aone/services/token_manager.py
- parts of src/axon_aone/services/order_store.py

Rule:
Data layer should be reusable by research, strategy, and execution.

### 7. Orchestration Layer
Purpose:
- Coordinate system timing, workflows, and application lifecycle

What belongs here:
- CLI entrypoints
- scheduler
- runtime wiring
- mode switching between mock and live
- startup and shutdown flow

Suggested paths:
```text
src/axon_aone/orchestration/
  main.py
  scheduler.py
  runtime.py
  workflows/
```

Current mapping:
- src/axon_aone/orchestration/main.py
- src/axon_aone/orchestration/scheduler.py
- src/axon_aone/main.py (compatibility wrapper)
- run_trader.py
- run_web.py

Rule:
Orchestration should compose layers, not hold business logic that belongs in risk, strategy, or execution.

### 8. Interface Layer
Purpose:
- Expose the system to humans and external clients

What belongs here:
- web server
- API routes
- templates
- frontend assets
- dashboard apps
- Telegram notifications

Suggested paths:
```text
src/axon_aone/interfaces/
  web/
  api/
  dashboard/
  telegram/
```

Current mapping:
- src/axon_aone/web_server.py
- src/axon_aone/templates/
- src/axon_aone/static/
- src/axon_aone/services/telegram_notify.py
- dashboard/app.py

Rule:
The interface layer should call orchestration or application services, not directly encode trading rules.

### 9. Infrastructure Layer
Purpose:
- Shared configuration, logging, helpers, and environment wiring

What belongs here:
- config
- utilities
- environment loading
- logging
- integration setup

Suggested paths:
```text
src/axon_aone/infrastructure/
  config.py
  logging.py
  settings.py
  utils.py
```

Current mapping:
- src/axon_aone/config.py
- src/axon_aone/utils.py

Rule:
Infrastructure supports all other layers and should avoid owning domain logic.

## Target Runtime Flow

```text
Research -> Strategy -> Portfolio -> Risk -> Execution -> Interface / Reporting
                         ^             |
                         |             v
                     Data Layer   Kill Switch

Orchestration wires everything together.
Infrastructure supports all layers.
```

## Recommended Target Tree

```text
Axon/
  research/
    dd/
    backtests/
    screens/
    notebooks/
    reports/
  src/axon_aone/
    strategy/
    portfolio/
    risk/
    execution/
    data/
    orchestration/
    interfaces/
    infrastructure/
  dashboard/
  tests/
```

## Practical Migration Plan

### Phase 1: Clarify without breaking imports
- Keep existing files where they are.
- Treat this document as the canonical layer map.
- Put all new work into the target layers instead of adding to `core/` or `features/`.

### Phase 2: Split overloaded modules
- Move `core/risk_engine.py` into `risk/engine.py`.
- Move `core/kill_switch.py` into `risk/kill_switch.py`.
- Move `core/execution_engine.py` into `execution/engine.py`.
- Move `core/sandbox.py` into `execution/sandbox.py`.
- Move `core/allocation.py` and `core/correlation.py` into `portfolio/`.
- Move `features/trade.py` into `strategy/strategies/`.

### Phase 3: Separate runtime from research
- Move DD and research scripts out of `scripts/` into `research/`.
- Keep `scripts/` only for operational utilities like token refresh and deployment helpers.

### Phase 4: Add application services
- Create thin service-level workflows between orchestration and domain layers.
- Example: `build_trade_plan`, `validate_trade_plan`, `execute_trade_plan`, `record_trade_result`.

## What To Consider Going Forward

When adding a new file, ask:
1. Is this research-only or live-runtime code?
2. Does it generate signals, manage capital, block risk, or place orders?
3. Does it belong to a domain layer or is it just orchestration glue?
4. Can strategy run without broker access? It should.
5. Can risk veto execution? It must.
6. Can research reuse data without importing web or broker runtime? Ideally yes.

## Recommended Ownership Of Existing Folders

### Keep
- `brokers/` as broker integration until merged into execution.
- `data/` as data layer.
- `services/` only for orchestration and notifications.
- `dashboard/` as analytics or interface layer.

### Gradually reduce
- `core/` because it mixes risk, execution, portfolio, and strategy-support logic.
- `features/` because the name is too broad for trading-specific strategy logic.

### Prefer going forward
- `strategy/`
- `portfolio/`
- `risk/`
- `execution/`
- `orchestration/`
- `interfaces/`
- `infrastructure/`
- `research/`
