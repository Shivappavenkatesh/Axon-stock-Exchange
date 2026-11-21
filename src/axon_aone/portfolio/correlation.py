"""Correlation helpers for portfolio construction and exposure checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class CorrelationResult:
    symbols: List[str]
    matrix: Dict[str, Dict[str, float]]
    window_size: int


def _extract_close_series(universe: List[Dict[str, Any]], window: int) -> pd.DataFrame:
    series_map: Dict[str, List[float]] = {}
    for stock in universe:
        symbol = stock.get("symbol")
        candles = stock.get("candles") or []
        if not symbol or not candles:
            continue
        closes = [candle.get("close", 0.0) for candle in candles[-window:]]
        if len(closes) < 2:
            continue
        series_map[symbol] = closes
    if not series_map:
        return pd.DataFrame()
    return pd.DataFrame(series_map)


def compute_correlation_from_universe(
    universe: List[Dict[str, Any]],
    window: int = 30,
) -> Optional[CorrelationResult]:
    df = _extract_close_series(universe, window=window)
    if df.empty:
        return None

    returns = df.pct_change().dropna(how="all")
    if returns.empty:
        return None

    corr = returns.corr()
    symbols = list(corr.columns)
    matrix_dict: Dict[str, Dict[str, float]] = {
        row_symbol: {col_symbol: float(value) for col_symbol, value in row.items()}
        for row_symbol, row in corr.to_dict(orient="index").items()
    }
    return CorrelationResult(symbols=symbols, matrix=matrix_dict, window_size=window)
