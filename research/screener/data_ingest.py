"""
Data ingestion helpers for the screener.

Supports CSV loading and a placeholder for public API fetches.
"""
from typing import Dict, Any, List
import csv
import json
import requests


def load_from_csv(path: str, key_column: str = "symbol") -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get(key_column)
            if not sym:
                continue
            # Convert numeric fields when possible
            converted = {}
            for k, v in row.items():
                try:
                    converted[k] = float(v) if v not in (None, "") else 0.0
                except Exception:
                    converted[k] = v
            out[sym] = converted
    return out


def fetch_alpha_vantage(symbols: List[str], api_key: str) -> Dict[str, Dict[str, Any]]:
    """Fetches basic indicators from Alpha Vantage (placeholder).

    Requires an API key. Returns a minimal fundamentals mapping.
    """
    if not api_key:
        raise RuntimeError("Alpha Vantage API key required")

    base = "https://www.alphavantage.co/query"
    out: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        # Example: use COMPANY_OVERVIEW
        params = {"function": "OVERVIEW", "symbol": sym, "apikey": api_key}
        r = requests.get(base, params=params, timeout=10)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
            out[sym] = {
                "market_cap": float(data.get("MarketCapitalization", 0)) if data.get("MarketCapitalization") else 0,
                "roe": float(data.get("ReturnOnEquityTTM", 0)) if data.get("ReturnOnEquityTTM") else 0,
                "revenue_growth": 0.0,
                "debt_to_equity": float(data.get("DebtToEquity", 0)) if data.get("DebtToEquity") else 0,
            }
        except Exception:
            continue
    return out


def fetch_yfinance(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch basic fundamentals/metrics from Yahoo Finance using yfinance.

    Returns a mapping symbol -> {market_cap, roe, revenue_growth, debt_to_equity}
    """
    try:
        import yfinance as yf
    except Exception:
        raise RuntimeError("yfinance package not installed. Install with 'pip install yfinance'")

    out: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            info = t.info if hasattr(t, 'info') else {}
            out[sym] = {
                "market_cap": float(info.get("marketCap", 0) or 0),
                "roe": float(info.get("returnOnEquity", 0) or 0),
                "revenue_growth": float(info.get("revenueGrowth", 0) or 0),
                "debt_to_equity": float(info.get("debtToEquity", 0) or 0),
            }
        except Exception:
            out[sym] = {"market_cap": 0, "roe": 0, "revenue_growth": 0, "debt_to_equity": 0}
    return out
