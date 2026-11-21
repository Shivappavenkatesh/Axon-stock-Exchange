"""
Fundamental screener that scores companies on simple quality and growth metrics.

Input: mapping symbol -> fundamentals dict with keys like:
  - revenue_growth (float, % as 0.12 for 12%)
  - roe (float)
  - debt_to_equity (float)
  - market_cap (float)

Exports:
  - score_universe(fundamentals: dict) -> dict(symbol -> score)
  - top_n(fundamentals: dict, n: int) -> list of symbols
"""

from typing import Dict, Any, List, Tuple


def _score_one(f: Dict[str, Any]) -> float:
    # Defensive defaults
    revenue_growth = float(f.get("revenue_growth", 0.0))
    roe = float(f.get("roe", 0.0))
    debt_to_equity = float(f.get("debt_to_equity", 9999.0))
    market_cap = float(f.get("market_cap", 0.0))

    # Score components
    growth_score = max(min(revenue_growth * 10, 10), -10)  # scale
    quality_score = max(min(roe, 30), -10) / 3.0
    leverage_penalty = -min(debt_to_equity, 10)
    size_bonus = 0.0 if market_cap <= 0 else min(market_cap / 1e9, 5)  # large caps get small bonus

    score = growth_score + quality_score + leverage_penalty + size_bonus
    return score


def score_universe(fundamentals: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for sym, f in fundamentals.items():
        try:
            out[sym] = _score_one(f)
        except Exception:
            out[sym] = 0.0
    return out


def top_n(fundamentals: Dict[str, Dict[str, Any]], n: int = 10) -> List[Tuple[str, float]]:
    scores = score_universe(fundamentals)
    items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return items[:n]
