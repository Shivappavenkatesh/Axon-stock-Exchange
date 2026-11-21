"""
Run the deterministic backtester using MarketDataFeed output (mock mode) or
from a JSON input file. Saves results to `backtest_results.json`.

Usage:
  python scripts/run_backtest.py --mock
  python scripts/run_backtest.py --input path/to/backtest_input.json
  python scripts/run_backtest.py --mock --fundamentals fundamentals.json --top 5
"""
import argparse
import json
import sys
from pathlib import Path

# Make `src/` importable when run from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from axon_aone.data.feed import MarketDataFeed
from axon_aone.backtester import Backtester
from axon_aone.features.screener import top_n


def feed_to_backtest_input(feed_data):
    """Convert MarketDataFeed.fetch_market_data() list into mapping symbol->candles."""
    out = {}
    for stock in feed_data:
        sym = stock.get("symbol")
        # ensure candle dicts have timestamp/open/high/low/close/volume
        candles = []
        for c in stock.get("candles", []):
            candle = {
                "timestamp": c.get("timestamp"),
                "open": c.get("open"),
                "high": c.get("high"),
                "low": c.get("low"),
                "close": c.get("close"),
                "volume": c.get("volume"),
                "vwap": c.get("vwap"),
            }
            candles.append(candle)
        out[sym] = candles
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true", help="Use MarketDataFeed mock data")
    p.add_argument("--input", type=str, help="Path to backtest_input.json")
    p.add_argument("--output", type=str, default="backtest_results.json")
    p.add_argument("--fundamentals", type=str, help="Optional fundamentals JSON (symbol -> metrics) to screen the universe first")
    p.add_argument("--top", type=int, default=10, help="Number of top-scored symbols to keep when --fundamentals is given")
    args = p.parse_args()

    if args.mock:
        feed = MarketDataFeed(use_mock=True)
        data = feed.fetch_market_data()
        bt_input = feed_to_backtest_input(data)
    elif args.input:
        path = Path(args.input)
        if not path.exists():
            print(f"Input file not found: {path}")
            return
        with path.open("r", encoding="utf-8") as f:
            bt_input = json.load(f)
    else:
        print("Specify --mock to use mock data or --input <file>")
        return

    # Optional fundamental scoring
    if args.fundamentals:
        fpath = Path(args.fundamentals)
        if not fpath.exists():
            print(f"Fundamentals file not found: {fpath}")
            return
        with fpath.open("r", encoding="utf-8") as f:
            fund = json.load(f)
        top = top_n(fund, n=args.top)
        selected = [s for s, _ in top]
        # Filter bt_input to selected symbols only
        bt_input = {s: bt_input[s] for s in selected if s in bt_input}
        print(f"Running backtest on top {len(bt_input)} screened symbols")

    # Run backtester with more realistic params
    bt = Backtester(bt_input, start_capital=100000, fill_at="next_open", slippage_pct=0.0005, commission_pct=0.0002, use_atr_stop=True)
    results = bt.run()

    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Backtest complete. Results written to {out_path}")


if __name__ == "__main__":
    main()
