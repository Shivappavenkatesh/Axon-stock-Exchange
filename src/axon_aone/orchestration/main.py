"""Primary runtime entrypoint wiring for Axon."""

import json
import logging
import sys
import time
from typing import Sequence

from axon_aone.data.feed import fetch_market_data
from axon_aone.db import init_db
from axon_aone.orchestration.scheduler import TradingScheduler
from axon_aone.risk.engine import RiskEngine
from axon_aone.strategy.strategies.trade import run_day


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def main(use_mock: bool = False):
    setup_logging()
    init_db()
    risk_engine = RiskEngine()
    logger = logging.getLogger(__name__)
    try:
        logger.info("Loaded risk config:\n%s", json.dumps(risk_engine.get_config(), indent=2))
    except Exception:
        logger.info("Loaded risk config (could not pretty-print)")

    logger.info("Starting Axon Aone Trading Algorithm")
    logger.info("Running in mock mode (paper trading with mock data)" if use_mock else "Running in live mode with Angel One broker")

    try:
        universe = fetch_market_data(use_mock=use_mock)
        if not universe:
            logger.warning("No market data available. Exiting...")
            return
        logger.info(f"Fetched data for {len(universe)} symbols")
        run_day(universe, use_mock=use_mock)
    except Exception as e:
        logger.error(f"Error in main: {e}", exc_info=True)

    logger.info("Algorithm execution completed")


def run_scheduled(use_mock: bool = False):
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("🚀 Starting Axon Aone - Angel One Smart API Trading Scheduler")
    logger.info("=" * 70)
    logger.info("")
    logger.info("   Broker: Angel One SmartConnect API")
    logger.info(f"   Mode: {'Mock/Paper Trading' if use_mock else 'Live Trading'}")
    logger.info("")
    logger.info("Scheduler will automatically:")
    logger.info("   ✓ Run algorithm every 5 minutes during market hours")
    logger.info("   ✓ Monitor market from 9:15 AM to 3:30 PM IST (Monday-Friday)")
    logger.info("   ✓ Force exit all positions at 2:00 PM IST")
    logger.info("   ✓ Close positions after market close")
    logger.info("")
    logger.info("Press Ctrl+C to stop the scheduler")
    logger.info("")

    logger.info("Initializing trading scheduler...")
    risk_engine = RiskEngine()
    try:
        logger.info("Loaded risk config:\n%s", json.dumps(risk_engine.get_config(), indent=2))
    except Exception:
        logger.info("Loaded risk config (could not pretty-print)")
    scheduler = TradingScheduler(use_mock=use_mock)
    scheduler.schedule_trading(main)
    scheduler.start()

    try:
        while True:
            scheduler.get_status()
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Keyboard interrupt received. Stopping scheduler...")
        scheduler.stop()
        logger.info("Scheduler stopped successfully.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Scheduler error: {e}", exc_info=True)
        scheduler.stop()
        sys.exit(1)


def parse_runtime_args(argv: Sequence[str] | None = None) -> tuple[bool, bool]:
    args = list(sys.argv[1:] if argv is None else argv)
    use_scheduler = False
    use_mock = True

    for arg in args:
        lowered = arg.lower()
        if lowered == "--angel-one":
            use_mock = False
        elif lowered == "--mock":
            use_mock = True
        elif lowered == "--schedule":
            use_scheduler = True

    return use_scheduler, use_mock


def run_cli(argv: Sequence[str] | None = None) -> None:
    use_scheduler, use_mock = parse_runtime_args(argv)
    if use_scheduler:
        run_scheduled(use_mock=use_mock)
    else:
        main(use_mock=use_mock)


if __name__ == "__main__":
    run_cli()
