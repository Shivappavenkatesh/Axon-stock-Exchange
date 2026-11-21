"""Wires settings, ledger, data sources, brokers and strategies together. The scheduler,
the web app, the CLI and the tests all build the system through here, so the tested code
path is the one that trades (finding 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from axon.alerts import Alerter
from axon.broker.base import RateLimiter
from axon.broker.paper import PaperBroker
from axon.clock import TradingCalendar
from axon.config import Settings, load_settings
from axon.costs import CostModel
from axon.engine import Engine
from axon.ledger import Ledger
from axon.market_data import BrokerMarketData, RandomMarketData
from axon.models import Mode, Part
from axon.strategies.intraday_vwap import IntradayVwapStrategy
from axon.universe import load_symbol_set, load_universe


@dataclass
class Axon:
    settings: Settings
    ledger: Ledger
    calendar: TradingCalendar
    alerter: Alerter
    engine: Engine
    _angel: Optional[object] = None

    def angel(self):
        """One Angel One client (one API key), created only when PAPER or LIVE needs it."""
        if self._angel is None:
            from axon.broker.angel_one import AngelOneClient

            self._angel = AngelOneClient.from_env(algo_id=self.settings.algo_id, static_ip=self.settings.static_ip)
            self._angel.rate = RateLimiter(self.settings.max_orders_per_second)
        return self._angel

    def logout(self) -> None:
        if self._angel is not None:
            self._angel.logout()


def build(settings: Optional[Settings] = None, ledger: Optional[Ledger] = None, *, alert_sender=None,
          test_data: Optional[RandomMarketData] = None, real_data=None, live_broker=None) -> Axon:
    settings = settings or load_settings()
    ledger = ledger or Ledger(settings.db_path)
    calendar = TradingCalendar.from_file(settings.holidays_file)
    alerter = Alerter(ledger, settings.telegram_token, settings.telegram_chat_id, sender=alert_sender)
    paper_broker = PaperBroker(CostModel(settings.costs))
    test_source = test_data or RandomMarketData()
    holder: dict = {}

    def data_for_mode(mode: Mode):
        if mode is Mode.TEST:
            return test_source
        if real_data is not None:
            return real_data
        return BrokerMarketData(holder["axon"].angel())

    def broker_for_mode(mode: Mode):
        if mode is Mode.LIVE:
            return live_broker if live_broker is not None else holder["axon"].angel()
        return paper_broker

    engine = Engine(
        settings=settings, ledger=ledger, calendar=calendar,
        strategies={Part.INTRADAY: IntradayVwapStrategy(settings.intraday)},
        data_for_mode=data_for_mode, broker_for_mode=broker_for_mode, alerter=alerter,
        universe=load_universe(settings.universe_file),
        surveillance=load_symbol_set(settings.surveillance_file),
    )
    axon = Axon(settings, ledger, calendar, alerter, engine)
    holder["axon"] = axon
    return axon
