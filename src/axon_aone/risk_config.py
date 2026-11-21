from copy import deepcopy
from typing import Any, Dict, List


DEFAULT_RISK_CONFIG: Dict[str, Any] = {
    # Basic per-trade / sizing
    "PER_TRADE_RISK_PCT": 1.0,
    "STOP_LOSS_ATR_MULTIPLIER": 2.0,
    "MAX_POSITION_PCT": 5.0,
    "MAX_SECTOR_PCT": 20.0,
    "MAX_CONCURRENT_POSITIONS": 25,

    # Limits (time horizons)
    "DAILY_LOSS_LIMIT_PCT": 3.0,
    "INTRADAY_LIMIT_PCT": 1.0,
    "WEEKLY_LOSS_LIMIT_PCT": 6.0,
    "MONTHLY_LOSS_LIMIT_PCT": 10.0,
    "MAX_DRAWDOWN_PCT": 20.0,
    "MAX_SINGLE_DAY_PNL_PCT": 4.0,

    # Trading / liquidity
    "DAILY_TURNOVER_CAP_PCT": 20.0,
    "MAX_ORDERS_PER_DAY": 200,
    "MAX_NOTIONAL_PCT_OF_ADV": 2.0,
    "MAX_ORDER_PCT_OF_ADV": 1.0,
    "SLIPPAGE_TOLERANCE_PCT": 0.2,
    "TRANSACTION_COST_PCT": 0.15,

    # Leverage / cash
    "MAX_LEVERAGE": 1.5,
    "CASH_BUFFER_PCT": 3.0,

    # Strategy budgets (example split, tuneable)
    "RISK_BUDGET_BY_STRATEGY": {
        "warren": 30,
        "jeff": 25,
        "mark": 20,
        "elon": 15,
        "emotional_ai": 10,
    },
    "STRATEGY_MAX_DRAWDOWN_PCT": 10.0,

    # Statistical controls
    "VAR_DAILY_95_PCT": 3.0,
    "TAIL_RISK_BUDGET_PCT": 2.0,

    # Decision thresholds
    "CONFIDENCE_THRESHOLD": 0.6,
    "HIGH_IMPACT_CONFIDENCE_THRESHOLD": 0.8,
    "HUMAN_REVIEW_THRESHOLD_PCT": 2.0,

    # Kill-switches and operational
    "KILL_SWITCHES": {
        "GLOBAL_DRAWDOWN_PCT": 20.0,
        "DAILY_LOSS_PCT": 3.0,
        "BROKER_CONNECTION_FAILURE_SECONDS": 60,
        "FAILED_ORDERS_THRESHOLD": 5,
    },

    "MAX_ORDER_RETRIES": 3,
}


def get_default_risk_config() -> Dict[str, Any]:
    return deepcopy(DEFAULT_RISK_CONFIG)


def merge_with_defaults(user_config: Dict[str, Any]) -> Dict[str, Any]:
    out = get_default_risk_config()
    for k, v in (user_config or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = deepcopy(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def validate_risk_config(cfg: Dict[str, Any]) -> None:
    """
    Validate the provided risk config dictionary against basic sanity checks.
    Raises ValueError with messages if invalid.
    """
    errors: List[str] = []

    def pct_ok(key: str):
        val = cfg.get(key)
        if not isinstance(val, (int, float)):
            errors.append(f"{key} must be numeric (got {type(val).__name__})")
            return
        if val < 0 or val > 100:
            errors.append(f"{key} must be between 0 and 100 (got {val})")

    # percentage-based checks
    pct_keys = [
        "PER_TRADE_RISK_PCT",
        "MAX_POSITION_PCT",
        "MAX_SECTOR_PCT",
        "DAILY_LOSS_LIMIT_PCT",
        "INTRADAY_LIMIT_PCT",
        "WEEKLY_LOSS_LIMIT_PCT",
        "MONTHLY_LOSS_LIMIT_PCT",
        "MAX_DRAWDOWN_PCT",
        "MAX_SINGLE_DAY_PNL_PCT",
        "DAILY_TURNOVER_CAP_PCT",
        "MAX_NOTIONAL_PCT_OF_ADV",
        "MAX_ORDER_PCT_OF_ADV",
        "SLIPPAGE_TOLERANCE_PCT",
        "TRANSACTION_COST_PCT",
        "CASH_BUFFER_PCT",
        "STRATEGY_MAX_DRAWDOWN_PCT",
        "VAR_DAILY_95_PCT",
        "TAIL_RISK_BUDGET_PCT",
        "CONFIDENCE_THRESHOLD",
        "HIGH_IMPACT_CONFIDENCE_THRESHOLD",
        "HUMAN_REVIEW_THRESHOLD_PCT",
    ]

    for key in pct_keys:
        if key in cfg:
            pct_ok(key)

    # numeric-int checks
    int_keys = ["MAX_CONCURRENT_POSITIONS", "MAX_ORDERS_PER_DAY", "MAX_ORDER_RETRIES"]
    for key in int_keys:
        if key in cfg:
            val = cfg.get(key)
            if not isinstance(val, int) or val < 0:
                errors.append(f"{key} must be a non-negative integer (got {val})")

    # nested checks
    rb = cfg.get("RISK_BUDGET_BY_STRATEGY")
    if rb is not None:
        if not isinstance(rb, dict):
            errors.append("RISK_BUDGET_BY_STRATEGY must be a dict of strategy->pct")
        else:
            total = 0
            for k, v in rb.items():
                if not isinstance(v, (int, float)):
                    errors.append(f"RISK_BUDGET_BY_STRATEGY[{k}] must be numeric")
                else:
                    total += v
            if total <= 0:
                errors.append("Sum of RISK_BUDGET_BY_STRATEGY must be > 0")

    # KILL_SWITCHES
    ks = cfg.get("KILL_SWITCHES")
    if ks is not None:
        if not isinstance(ks, dict):
            errors.append("KILL_SWITCHES must be a dict")

    if errors:
        raise ValueError("Invalid risk config:\n" + "\n".join(errors))


def validate_and_merge(user_config: Dict[str, Any]) -> Dict[str, Any]:
    merged = merge_with_defaults(user_config or {})
    validate_risk_config(merged)
    return merged


__all__ = [
    "DEFAULT_RISK_CONFIG",
    "get_default_risk_config",
    "merge_with_defaults",
    "validate_risk_config",
    "validate_and_merge",
]
