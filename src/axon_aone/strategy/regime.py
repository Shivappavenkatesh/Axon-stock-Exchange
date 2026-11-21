"""Regime engine for strategy participation and throttling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegimeMode(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"


@dataclass
class RegimeState:
    score: int
    mode: RegimeMode
    trend_score: int = 0
    breadth_score: int = 0
    vix_score: int = 0
    liquidity_score: int = 0


def calculate_regime(index_trend_ok: bool = True, volatility_ok: bool = True) -> RegimeState:
    """Compute a simple regime score and market mode."""
    trend_score = 40 if index_trend_ok else 10
    vix_score = 40 if volatility_ok else 10
    breadth_score = 10
    liquidity_score = 10

    base = trend_score + breadth_score + vix_score + liquidity_score
    score = max(0, min(100, base))

    if score >= 70:
        mode = RegimeMode.BULL
    elif score <= 30:
        mode = RegimeMode.BEAR
    else:
        mode = RegimeMode.SIDEWAYS

    return RegimeState(
        score=score,
        mode=mode,
        trend_score=trend_score,
        breadth_score=breadth_score,
        vix_score=vix_score,
        liquidity_score=liquidity_score,
    )
