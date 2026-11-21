"""
Risk Manager for Trading Algorithm
"""

from axon_aone.config import (
    MAX_RISK_PER_TRADE,
    MAX_DAILY_LOSS,
    MAX_WEEKLY_DRAWDOWN,
)


def assess_daily_loss(state: dict) -> bool:
    max_loss = MAX_DAILY_LOSS * state["total_capital"]
    return state["daily_pnl"] <= -max_loss


def assess_weekly_drawdown(state: dict) -> bool:
    max_drawdown = MAX_WEEKLY_DRAWDOWN * state["total_capital"]
    return state["weekly_pnl"] <= -max_drawdown


def calculate_position_risk(entry_price, stop_loss_price, quantity):
    return abs(entry_price - stop_loss_price) * quantity


def can_open_new_trade(entry_price, stop_loss_price, quantity, state: dict):
    trade_risk = calculate_position_risk(entry_price, stop_loss_price, quantity)
    if trade_risk > state["tradable_capital"] * MAX_RISK_PER_TRADE:
        return False
    return True


def manage_open_trades(state: dict):
    for trade in state["open_trades"]:
        if assess_daily_loss(state) or assess_weekly_drawdown(state):
            trade["force_exit"] = True
            state["trade_log"].append({
                "symbol": trade["symbol"],
                "action": "FORCE_EXIT",
                "reason": "Risk parameters exceeded"
            })
