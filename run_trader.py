#!/usr/bin/env python
"""
Axon Aone - Angel One Smart API Trading Scheduler

This is the main entry point for the trading application.
It runs a background scheduler that automatically executes trades during market hours.

Usage:
    python run_trader.py                  # Run with mock mode (default)
    python run_trader.py --angel-one      # Run with Angel One broker (live)
    python run_trader.py --mock           # Run in mock/paper trading mode
    python run_trader.py --schedule       # Run scheduler (runs during market hours)

Market Hours:
    - Runs Monday to Friday
    - Market open: 9:15 AM IST
    - Market close: 3:30 PM IST
    - Force exit: 2:00 PM IST
    - Algorithm runs every 5 minutes during market hours

Environment Variables:
    ANGEL_ONE_API_KEY       - Angel One API key from SmartAPI portal
    ANGEL_ONE_CLIENT_ID     - Angel One user ID (e.g., AACE123456)
    ANGEL_ONE_PIN           - 4-digit MPIN for authentication
    ANGEL_ONE_TOTP_SECRET   - Base32 TOTP secret for 2FA
"""

import os
import sys
import logging

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from axon_aone.orchestration.main import main, parse_runtime_args, run_scheduled


def print_banner():
    """Print application banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     📈 Axon Aone - Angel One Smart API Trading 📈       ║
    ║                                                               ║
    ║              Background Scheduler Edition v1.0                ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_help():
    """Print help message."""
    help_text = """
Usage: python run_trader.py [OPTIONS]

OPTIONS:
    --angel-one            Use Angel One broker (live trading)
    
    --mock                 Use mock/paper trading (no real orders)
    
    --schedule             Run as background scheduler (market hours only)
    
    --help                 Show this help message

EXAMPLES:
    python run_trader.py                    # Mock mode (default)
    python run_trader.py --angel-one        # Live trading with Angel One
    python run_trader.py --mock             # Mock mode
    python run_trader.py --schedule         # Run scheduler in mock mode
    python run_trader.py --schedule --angel-one  # Run scheduler with Angel One

MARKET HOURS (IST - Indian Standard Time):
    Start:  9:15 AM (Monday-Friday)
    Close:  3:30 PM (Monday-Friday)
    
    Algorithm runs every 5 minutes during market hours
    """
    print(help_text)


def parse_arguments():
    """Parse command-line arguments."""
    args = sys.argv[1:]
    for arg in args:
        if arg.lower() == "--help":
            print_help()
            sys.exit(0)

    return parse_runtime_args(args)


def main_entry():
    """Main entry point."""
    print_banner()
    
    use_scheduler, use_mock = parse_arguments()
    
    try:
        if use_scheduler:
            run_scheduled(use_mock=use_mock)
        else:
            main(use_mock=use_mock)
    except KeyboardInterrupt:
        print("\n\nShutdown signal received.")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main_entry()
