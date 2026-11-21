# Institutional Trading Playbook

## Objective
Build Axon into an institutional-grade trading platform with disciplined risk, robust execution, measurable edge, and scalable operations.

Important: no system can guarantee maximum profits or unicorn picks. This playbook is designed to maximize expected returns while controlling downside and preventing blowups.

## North Star
- Long-term target: grow capital toward 100+ crore through repeatable process, not one-off bets.
- Priority order: survival -> consistency -> compounding -> scale.

## Strategy Principles (Blended: Warren + Elon + Jeff + Mark)
- Warren: quality + margin of safety + concentration only when conviction and risk controls align.
- Elon: aggressive experimentation, fast feedback loops, rapid iteration.
- Jeff: process obsession, metrics, operational excellence, postmortems.
- Mark: data flywheel, adaptive ranking, continuous optimization.

## Institutional Coverage Matrix

### A. Alpha Research and Idea Pipeline
Status: Partial
- Universe definition by liquidity/sector/regime.
- Factor and theme tagging (quality, momentum, valuation, narrative catalysts).
- Regime-specific model variants with champion/challenger.
- Research notebook to production promotion checklist.
Acceptance criteria:
- At least 3 uncorrelated alpha sleeves with independent validation windows.
- Each sleeve has documented hypothesis, fail conditions, and monitoring metrics.

### B. Portfolio Construction
Status: Partial
- Position sizing by volatility/risk budget.
- Sector, theme, and single-name concentration limits.
- Correlation-aware exposure cap.
- Turnover and capacity limits.
Acceptance criteria:
- Pre-trade optimizer satisfies all hard constraints before order creation.
- Daily exposure report: name, sector, factor, regime buckets.

### C. Pre-Trade Risk and Compliance
Status: Missing
- Hard blocks: restricted symbols, kill-state, account limits, mandate checks.
- Soft warnings: liquidity stress, gap risk, borrow/short constraints (if used).
- Fat-finger checks: max notional, max quantity, limit price deviation.
Acceptance criteria:
- 100% of orders pass through compliance gate service.
- Every reject has machine-readable reason and audit trail.

### D. Execution and OMS/EMS
Status: Partial
- Order state machine: new, working, partial, filled, canceled, rejected.
- Retry/cancel-replace policies with idempotency keys.
- Slippage and fill-quality monitoring by symbol/time bucket.
- Broker health checks and fallback policy.
Acceptance criteria:
- No orphan orders in reconciliation.
- Daily TCA: arrival slippage, fill ratio, rejection ratio.

### E. Post-Trade Reconciliation and Accounting
Status: Missing
- Trade/position reconciliation against broker statements.
- Corporate actions handling and realized/unrealized PnL attribution.
- Fees, charges, taxes, and net performance attribution.
Acceptance criteria:
- End-of-day break count = 0.
- PnL explains to ledger within tolerance.

### F. Data Quality and Reliability
Status: Partial
- OHLCV quality checks and stale quote detection.
- Schema drift alerts and source health scoring.
- Time sync checks across components.
Acceptance criteria:
- Data quality SLA dashboard with alerting.
- No strategy execution on stale/invalid data.

### G. Model Governance
Status: Missing
- Model registry with versioned configs and artifacts.
- Promotion gates: backtest, forward test, paper test, capital ramp.
- Rollback playbook and incident response.
Acceptance criteria:
- Every model decision traceable to version + config hash.
- Rollback tested monthly.

### H. Infrastructure and Security
Status: Partial
- Secrets management and key rotation.
- Immutable audit logs.
- Backups, disaster recovery runbooks, restore drills.
- Role-based access and dual controls for live mode.
Acceptance criteria:
- Recovery time and data loss targets documented and tested.
- Security checklist passed before live capital increase.

### I. Business Governance and Operating Cadence
Status: Missing
- Weekly risk committee.
- Monthly strategy review and decommission decisions.
- Capital allocation committee with sleeve scorecards.
Acceptance criteria:
- Standard review packs generated automatically.
- Explicit go/no-go decisions recorded each month.

## KPI Framework (Institutional Dashboard)

### Return and Risk KPIs
- CAGR, monthly return, rolling 3/6/12-month return.
- Max drawdown, time-to-recover, downside deviation.
- Sharpe, Sortino, Calmar.
- Hit rate, payoff ratio, expectancy.

### Execution KPIs
- Fill ratio, rejection ratio.
- Average slippage (bps), tail slippage p95/p99.
- Time-to-fill and partial-fill completion rate.

### Portfolio KPIs
- Concentration by symbol/sector.
- Correlation heat and effective number of bets.
- Gross/net exposure and regime-adjusted leverage.

### Operations KPIs
- Reconciliation break count.
- Data quality incidents.
- Mean time to detect and mean time to resolve incidents.

## Capital Scaling Rules
- Phase 1: paper -> micro capital.
- Phase 2: add capital only after 8-12 weeks of stable risk-adjusted returns.
- Phase 3: increase in steps with hard drawdown circuit breakers.
- Rule: if drawdown exceeds threshold, step down capital and revert to safe profile.

## Unicorn Discovery Framework
Use as a sleeve, not entire portfolio.
- Fundamental moat signals: durable demand, high gross margin trend, reinvestment runway.
- Market structure signals: expanding liquidity, improving institutional participation.
- Technical confirmation: sustained relative strength with controlled volatility.
- Risk rule: thesis invalidation exits are mandatory.

## 90-Day Execution Plan

### Days 1-30 (Foundation)
- Build pre-trade compliance gate and order state machine.
- Build reconciliation service and daily break report.
- Add full TCA metrics into daily deep-dive outputs.
Success gate:
- Zero critical compliance bypasses.
- Reconciliation break count <= 1 for 10 consecutive sessions.

### Days 31-60 (Risk and Portfolio Depth)
- Implement exposure optimizer with hard constraints.
- Add scenario stress tests and VaR monitoring.
- Add strategy sleeve attribution reporting.
Success gate:
- All pre-trade orders validated by portfolio constraints.
- Stress and VaR limits enforced with automated blocks.

### Days 61-90 (Governance and Scale)
- Add model registry + promotion workflow.
- Add monthly risk committee reporting package.
- Enable controlled capital ramp protocol.
Success gate:
- Audit-ready decision log and model lineage.
- Stable performance under ramp with no policy violations.

## Immediate Build Order
1. Pre-trade compliance service (hard blocks first).
2. Reconciliation and accounting service.
3. OMS order lifecycle and idempotent retries.
4. VaR/stress risk layer with circuit breakers.
5. Portfolio optimizer and sleeve allocator.
6. Model registry and governance workflow.

## Done Definition (Institutional Ready)
- Every order validated, explainable, and reconciled.
- Every risk limit enforceable in code with audit logs.
- Every model versioned, monitored, and rollback-capable.
- Every capital increase justified by KPI gates, not intuition.
