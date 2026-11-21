"""Market-hours aware trading scheduler."""

import datetime
import logging

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from axon_aone.config import (
    ALGO_RUN_INTERVAL,
    FORCE_EXIT_TIME,
    MARKET_CLOSE_TIME,
    MARKET_OPEN_TIME,
)
from axon_aone.db import get_global_trade_mode
from axon_aone.services.daily_deepdive import get_daily_deepdive_logger
from axon_aone.services.risk_committee import maybe_generate_previous_month_report


class TradingScheduler:
    def __init__(self, use_mock: bool = False):
        self.logger = logging.getLogger(__name__)
        self.use_mock = use_mock
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self.market_open = False
        self.tz = pytz.timezone("Asia/Kolkata")
        self.scheduler.configure(timezone=self.tz)

        self.logger.info("Trading Scheduler initialized")
        self.logger.info(
            f"Market hours: {MARKET_OPEN_TIME.strftime('%H:%M')} - {MARKET_CLOSE_TIME.strftime('%H:%M')} IST"
        )
        self.logger.info(f"Algorithm run interval: {ALGO_RUN_INTERVAL} seconds")

    def schedule_trading(self, trading_func, *args, **kwargs):
        self.logger.info(f"Scheduling trading algorithm every {ALGO_RUN_INTERVAL}s during market hours")
        self.scheduler.add_job(
            self._run_trading_iteration,
            IntervalTrigger(seconds=ALGO_RUN_INTERVAL),
            args=[trading_func, args, kwargs],
            id="market_hours_trading",
            name="Market Hours Trading Algorithm",
            replace_existing=True,
        )

        market_open_setup_time = self._subtract_minutes(MARKET_OPEN_TIME, 5)
        self.scheduler.add_job(
            self._pre_market_setup,
            CronTrigger(
                hour=market_open_setup_time.hour,
                minute=market_open_setup_time.minute,
                day_of_week="mon-fri",
                timezone=self.tz,
            ),
            id="pre_market_setup",
            name="Pre-Market Setup",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._market_open_announcement,
            CronTrigger(
                hour=MARKET_OPEN_TIME.hour,
                minute=MARKET_OPEN_TIME.minute,
                day_of_week="mon-fri",
                timezone=self.tz,
            ),
            id="market_open",
            name="Market Open",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._force_exit_positions,
            CronTrigger(
                hour=FORCE_EXIT_TIME.hour,
                minute=FORCE_EXIT_TIME.minute,
                day_of_week="mon-fri",
                timezone=self.tz,
            ),
            id="force_exit",
            name="Force Exit Positions",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._market_close,
            CronTrigger(
                hour=MARKET_CLOSE_TIME.hour,
                minute=MARKET_CLOSE_TIME.minute,
                day_of_week="mon-fri",
                timezone=self.tz,
            ),
            id="market_close",
            name="Market Close Cleanup",
            replace_existing=True,
        )

    def start(self):
        if not self.is_running:
            self.scheduler.start()
            self.is_running = True
            self.logger.info("Scheduler started successfully")

    def stop(self):
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            self.logger.info("Scheduler stopped")

    def get_status(self) -> dict:
        return {
            "running": self.is_running,
            "market_open": self.market_open,
            "job_count": len(self.scheduler.get_jobs()),
        }

    def _run_trading_iteration(self, trading_func, args, kwargs):
        now = datetime.datetime.now(self.tz)
        if now.weekday() >= 5:
            return

        market_open = now.time() >= MARKET_OPEN_TIME
        market_close = now.time() >= MARKET_CLOSE_TIME
        if not (market_open and not market_close):
            return

        try:
            self.logger.debug(f"Running trading iteration at {now.strftime('%H:%M:%S')}")
            try:
                mode = get_global_trade_mode()
                use_mock = mode == "mock"
                kw = dict(kwargs or {})
                kw["use_mock"] = use_mock
                self.logger.debug(f"Global trade mode from DB: {mode} (use_mock={use_mock})")
                try:
                    trading_func(*args, **kw)
                except TypeError as exc:
                    if "use_mock" not in str(exc) or "multiple values" not in str(exc):
                        raise
                    trading_func(**kw)
            except Exception:
                trading_func(*args, **(kwargs or {}))
        except Exception as e:
            self.logger.error(f"Error in trading iteration: {e}", exc_info=True)

    def _pre_market_setup(self):
        self.logger.info("🟢 Pre-market setup: Preparing for market open")

    def _market_open_announcement(self):
        self.market_open = True
        self.logger.info("📈 MARKET OPEN - Trading algorithm is active")

    def _force_exit_positions(self):
        self.logger.info("⚠️  FORCE EXIT TIME - Closing all open positions")

    def _market_close(self):
        self.market_open = False
        mode = "mock"
        try:
            mode = get_global_trade_mode()
        except Exception:
            mode = "mock"

        try:
            paths = get_daily_deepdive_logger().finalize_day(mode=mode)
            self.logger.info(
                "Daily deep-dive report generated: json=%s md=%s",
                paths["json"],
                paths["md"],
            )
        except Exception as exc:
            self.logger.error("Failed to finalize daily deep-dive report: %s", exc)

        try:
            monthly_paths = maybe_generate_previous_month_report()
            if monthly_paths is not None:
                self.logger.info(
                    "Monthly risk-committee pack generated: json=%s md=%s",
                    monthly_paths["json"],
                    monthly_paths["md"],
                )
        except Exception as exc:
            self.logger.error("Failed to generate monthly risk-committee pack: %s", exc)

        self.logger.info("📉 MARKET CLOSED - Scheduler paused until next market open")

    @staticmethod
    def _subtract_minutes(time_obj: datetime.time, minutes: int) -> datetime.time:
        temp = datetime.datetime.combine(datetime.datetime.today(), time_obj)
        temp -= datetime.timedelta(minutes=minutes)
        return temp.time()
