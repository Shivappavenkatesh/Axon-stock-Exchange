"""
Risk management module for trading algorithm.
Manages risk parameters and position sizing.
"""

import logging
from axon_aone.config import (
    MAX_RISK_PER_TRADE,
    MAX_DAILY_LOSS,
    MAX_WEEKLY_DRAWDOWN,
)

logger = logging.getLogger(__name__)

from axon_aone.risk.engine import PortfolioSnapshot, RiskEngine
from axon_aone.risk.kill_switch import KillSwitch, KillSwitchConfig


def assess_daily_loss(daily_pnl: float, total_capital: float) -> bool:
    """
    Check if daily loss exceeds maximum allowed.
    
    Args:
        daily_pnl: Daily P&L amount
        total_capital: Total capital
    
    Returns:
        True if daily loss exceeded maximum, False otherwise
    """
    max_daily_loss = MAX_DAILY_LOSS * total_capital
    return daily_pnl <= -max_daily_loss


def assess_weekly_drawdown(weekly_pnl: float, total_capital: float) -> bool:
    """
    Check if weekly drawdown exceeds maximum allowed.
    
    Args:
        weekly_pnl: Weekly P&L amount
        total_capital: Total capital
    
    Returns:
        True if weekly drawdown exceeded maximum, False otherwise
    """
    max_weekly_drawdown = MAX_WEEKLY_DRAWDOWN * total_capital
    return weekly_pnl <= -max_weekly_drawdown


def calculate_position_risk(entry_price: float, stop_loss_price: float, quantity: int) -> float:
    """
    Calculate risk for a position.
    
    Args:
        entry_price: Entry price
        stop_loss_price: Stop loss price
        quantity: Position quantity
    
    Returns:
        Risk amount
    """
    return abs(entry_price - stop_loss_price) * quantity


def can_open_new_trade(entry_price: float, stop_loss_price: float, quantity: int, 
                       tradable_capital: float) -> bool:
    """
    Check if a new trade can be opened based on risk parameters.
    
    Args:
        entry_price: Entry price
        stop_loss_price: Stop loss price
        quantity: Position quantity
        tradable_capital: Available tradable capital
    
    Returns:
        True if trade can be opened, False otherwise
    """
    trade_risk = calculate_position_risk(entry_price, stop_loss_price, quantity)
    max_risk = tradable_capital * MAX_RISK_PER_TRADE
    return trade_risk <= max_risk


def manage_risk_on_positions(positions: list, daily_pnl: float, weekly_pnl: float,
                             total_capital: float) -> list:
    """
    Apply risk management rules to positions.
    
    Args:
        positions: List of open positions
        daily_pnl: Daily P&L
        weekly_pnl: Weekly P&L
        total_capital: Total capital
    
    Returns:
        List of positions flagged for forced exit if risk limits exceeded
    """
    force_exit_positions = []
    
    if assess_daily_loss(daily_pnl, total_capital):
        logger.warning(f"Daily loss limit exceeded: {daily_pnl}")
        force_exit_positions.extend(positions)
    
    if assess_weekly_drawdown(weekly_pnl, total_capital):
        logger.warning(f"Weekly drawdown limit exceeded: {weekly_pnl}")
        force_exit_positions.extend(positions)
    
    return force_exit_positions


__all__ = [
    "PortfolioSnapshot",
    "RiskEngine",
    "KillSwitch",
    "KillSwitchConfig",
    "assess_daily_loss",
    "assess_weekly_drawdown",
    "calculate_position_risk",
    "can_open_new_trade",
    "manage_risk_on_positions",
]
