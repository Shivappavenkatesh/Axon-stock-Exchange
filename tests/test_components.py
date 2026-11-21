"""Tests for the building blocks: costs, broker adapter, rate limit, ledger, pass test,
income rule, scheduler routine and a full TEST-mode day."""

from __future__ import annotations

from datetime import timedelta

import pytest

from axon.broker.angel_one import AngelOneClient, AngelOneError, build_order_payload, parse_candles
from axon.broker.base import RateLimiter
from axon.config import CostSchedule
from axon.costs import CostModel
from axon.evaluation import pass_test
from axon.income import month_end_income
from axon.models import Instrument, Mode, OrderIntent, Part, Product, Quote, Side
from axon.scheduler import Scheduler
from tests.conftest import MONDAY, at


# ------------------------------------------------------------------ costs
def test_delivery_round_trip_includes_stt_both_sides_and_dp_on_sell():
    m = CostModel(CostSchedule(slippage_pct=0.0))
    buy = m.one_side(Side.BUY, Product.DELIVERY, 1000, 100)
    sell = m.one_side(Side.SELL, Product.DELIVERY, 1000, 100)
    assert buy.stt == pytest.approx(100) and sell.stt == pytest.approx(100)
    assert buy.dp == 0 and sell.dp == pytest.approx(23.6)
    assert buy.brokerage == 20 and buy.stamp == pytest.approx(15)


def test_intraday_costs_and_cost_test():
    m = CostModel(CostSchedule())
    sell = m.one_side(Side.SELL, Product.INTRADAY, 1000, 50)
    assert sell.stt == pytest.approx(12.5) and sell.dp == 0
    ok, cost = m.passes_cost_test(Product.INTRADAY, 1000, 50, planned_risk=300)
    assert not ok and cost > 60  # ~₹110 of costs against ₹300 of risk fails the 20% test
    ok, _ = m.passes_cost_test(Product.INTRADAY, 1000, 50, planned_risk=1000)
    assert ok


def test_small_order_brokerage_minimum():
    m = CostModel(CostSchedule(slippage_pct=0.0))
    assert m.one_side(Side.BUY, Product.INTRADAY, 100, 10).brokerage == 5.0  # 0.1% = ₹1, minimum ₹5


# ------------------------------------------------------------------ Angel One adapter
def _intent(part, side=Side.BUY, order_type="MARKET", limit=None):
    return OrderIntent(part, Mode.LIVE, Instrument("TCS-EQ", "11536"), side, 5, 3500.0, order_type=order_type,
                       limit_price=limit)


def test_order_payload_product_tag_and_no_surveillance_consent():
    p = build_order_payload(_intent(Part.SWING), "ALGO123")
    assert p["producttype"] == "DELIVERY" and p["ordertag"] == "ALGO123"
    assert "scripconsent" not in p
    assert build_order_payload(_intent(Part.INTRADAY), "")["producttype"] == "INTRADAY"
    lim = build_order_payload(_intent(Part.CORE, order_type="LIMIT", limit=3490.5), "X")
    assert lim["ordertype"] == "LIMIT" and lim["price"] == "3490.50"
    with pytest.raises(AngelOneError):
        build_order_payload(_intent(Part.CORE, order_type="LIMIT"), "X")


class FakeSmart:
    def __init__(self):
        self.orders, self.logged_out = [], False

    def generateSession(self, *a):
        return {"status": True}

    def placeOrder(self, payload):
        self.orders.append(payload)
        return "OID1"

    def orderBook(self):
        return {"data": [{"orderid": "OID1", "orderstatus": "complete", "averageprice": "3501.5", "filledshares": "5"}]}

    def terminateSession(self, client):
        self.logged_out = True


def _client(ip="203.0.113.10", static="203.0.113.10"):
    fake = FakeSmart()
    c = AngelOneClient(api_key="k", client_id="c", pin="p", totp_secret="t", algo_id="ALGO", static_ip=static,
                       connect_factory=lambda: fake, public_ip_lookup=lambda: ip,
                       rate_limiter=RateLimiter(2, clock=lambda: 0.0, sleep=lambda s: None))
    return c, fake


def test_live_order_refused_from_unregistered_ip():
    c, fake = _client(ip="198.51.100.7")
    r = c.place(_intent(Part.INTRADAY), Quote("TCS-EQ", 3500, MONDAY))
    assert r.status == "REJECTED" and "static IP" in r.message and fake.orders == []


def test_live_order_fills_and_session_logs_out():
    c, fake = _client()
    r = c.place(_intent(Part.INTRADAY), Quote("TCS-EQ", 3500, MONDAY))
    assert r.status == "FILLED" and r.fill_price == 3501.5 and fake.orders[0]["ordertag"] == "ALGO"
    c.logout()
    assert fake.logged_out


def test_no_buy_at_upper_price_limit():
    c, fake = _client()
    r = c.place(_intent(Part.INTRADAY), Quote("TCS-EQ", 3850, MONDAY, upper_circuit=3850))
    assert r.status == "REJECTED" and "upper price limit" in r.message and fake.orders == []


def test_parse_candles():
    rows = [["2026-11-23T09:15:00+05:30", 1, 2, 0.5, 1.5, 100]]
    c = parse_candles(rows)[0]
    assert c.close == 1.5 and c.start.hour == 9


# ------------------------------------------------------------------ rate limit
def test_rate_limit_can_never_exceed_two_per_second(monkeypatch):
    monkeypatch.setenv("AXON_MAX_ORDERS_PER_SECOND", "10")
    from axon.config import load_settings

    assert load_settings().max_orders_per_second == 2.0
    t = {"now": 0.0}
    slept = []
    rl = RateLimiter(10, clock=lambda: t["now"], sleep=lambda s: (slept.append(s), t.__setitem__("now", t["now"] + s)))
    for _ in range(3):
        rl.wait()
    assert rl.min_interval == 0.5 and sum(slept) == pytest.approx(1.0)


def test_brake_levels_cannot_be_loosened(monkeypatch):
    monkeypatch.setenv("AXON_BRAKE_CLOSE_PCT", "40")
    from axon.config import load_settings

    assert load_settings().brakes.close_satellites_at == 15.0


# ------------------------------------------------------------------ pass test and income
def _closed_trade(ledger, day_offset, pnl, part=Part.INTRADAY):
    ts = MONDAY + timedelta(days=day_offset)
    pid = ledger.open_position(ts=ts, book="paper", part=part, symbol=f"S{day_offset}", token="1", exchange="NSE",
                               quantity=1, price=1000, costs=0, stop=None, target=None)
    ledger.close_position(pid, ts=ts + timedelta(hours=1), price=1000 + pnl, costs=0, reason="t")
    return pid


def test_pass_test_requires_60_trades_and_no_lucky_days(system):
    ledger = system.ledger
    for i in range(59):
        _closed_trade(ledger, i, 10)
    assert not pass_test(ledger, Part.INTRADAY).passed
    _closed_trade(ledger, 59, 10)
    assert pass_test(ledger, Part.INTRADAY).passed


def test_pass_test_fails_when_three_lucky_days_carry_the_result(system):
    ledger = system.ledger
    for i in range(57):
        _closed_trade(ledger, i, -5)
    for i in range(57, 60):
        _closed_trade(ledger, i, 500)
    result = pass_test(ledger, Part.INTRADAY)
    assert not result.passed and "best 3 days" in result.reason


def test_income_rule(system):
    ledger = system.ledger
    _closed_trade(ledger, 0, 400)
    d = month_end_income(ledger, "paper", "2026-11")
    assert d.payout == pytest.approx(d.net_profit / 2) and d.payout > 0
    assert month_end_income(ledger, "paper", "2026-12").payout == 0


# ------------------------------------------------------------------ whole system
def test_test_mode_runs_a_full_day_without_real_data(tmp_settings):
    from axon.context import build

    ax = build(tmp_settings, alert_sender=lambda m: None)
    ax.ledger.set_mode(Part.INTRADAY, Mode.TEST, at(8, 0), "test")
    ax.ledger.record_cash_flow("test", "deposit", 1_000_000, at(8, 0))
    assert ax.engine.refresh_liquidity(Mode.TEST, at(8, 45)) == 4
    t = at(9, 15)
    while t < at(15, 30):
        ax.engine.run_cycle(t)
        t += timedelta(minutes=5)
    assert ax.ledger.open_positions("test") == []  # forced exit cleared the day
    assert ax.ledger.last_beat("cycle") is not None


def test_scheduler_routine_runs_brief_cycles_and_report(system):
    system.data.set_climb("AAA-EQ")
    sched = Scheduler(system)
    t = at(8, 40)
    while t <= at(15, 40):
        sched.tick(t)
        t += timedelta(minutes=1)
    msgs = "\n".join(system.sent)
    assert "morning brief" in msgs and "Daily report written" in msgs
    assert (system.settings.reports_dir / f"{MONDAY.date()}.md").exists()
    assert system.ledger.open_positions("paper") == []
