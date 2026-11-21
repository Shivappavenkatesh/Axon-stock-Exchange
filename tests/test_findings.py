"""One test per engineering requirement in the Axon spec (review findings 1-14)."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from axon.clock import IST
from axon.context import build
from axon.health import check
from axon.market_filter import intraday_vix, nifty_trend
from axon.models import Candle, Instrument, Mode, Part, Signal
from axon.modes import ModeChangeRefused, change_mode
from axon.report import build_daily_report
from axon.risk import RiskEngine
from axon.sizing import size_position
from axon.strategies.intraday_vwap import IntradayVwapStrategy
from tests.conftest import HOLIDAY, MONDAY, SYMBOLS, at, reopen

ROOT = Path(__file__).resolve().parents[1]


def buys(ax, symbol=None):
    return [o for o in ax.ledger.orders() if o["side"] == "BUY" and o["status"] == "FILLED"
            and (symbol is None or o["symbol"] == symbol)]


# 1 ------------------------------------------------------------------ never sells
def test_f1_stop_hit_is_sold_in_the_same_cycle(system):
    system.data.set_climb("AAA-EQ")
    system.engine.run_cycle(at(10, 20))
    pos = system.ledger.open_positions("paper")
    assert [p.symbol for p in pos] == ["AAA-EQ"]
    system.data.price_override["AAA-EQ"] = pos[0].stop - 1
    system.engine.run_cycle(at(10, 25))
    assert system.ledger.open_positions("paper") == []
    closed = system.ledger.closed_positions("paper")
    assert closed[0]["exit_reason"].startswith("stop-loss hit")


def test_f1_forced_exit_closes_everything_at_2_45(system):
    system.data.set_climb("AAA-EQ")
    system.engine.run_cycle(at(10, 20))
    assert system.ledger.open_positions("paper")
    system.engine.run_cycle(at(14, 45))
    assert system.ledger.open_positions("paper") == []
    assert system.ledger.closed_positions("paper")[0]["exit_reason"] == "forced exit 2:45 PM"


# 2 ------------------------------------------------------------------ repeat buys
def test_f2_repeating_signal_is_bought_once(system):
    system.data.set_climb("AAA-EQ")
    for minute in (20, 25, 30, 35):
        system.engine.run_cycle(at(10, minute))
    assert len(buys(system, "AAA-EQ")) == 1
    assert len(system.ledger.open_positions("paper")) == 1


def test_f2_daily_trade_limit_blocks_the_next_entry(system):
    ledger, now = system.ledger, at(10, 20)
    for sym in SYMBOLS[:3]:
        ledger.record_order(ts=now, book="paper", part=Part.INTRADAY, symbol=sym, side="BUY", quantity=1,
                            order_type="MARKET", reference_price=100, status="FILLED", fill_price=100,
                            filled_quantity=1)
    risk = RiskEngine(system.settings, ledger)
    sig = Signal(Part.INTRADAY, Instrument("DDD-EQ", "4"), 100, 98, 104, 1, "test")
    approval = risk.approve_entry(sig, "paper", now, risk.current_brakes("paper"), 1_000_000)
    assert not approval.ok and "3 trades a day" in approval.reason


# 3 ------------------------------------------------------------------ open order API
@pytest.fixture
def client(system):
    from werkzeug.security import generate_password_hash

    from axon.web.app import create_app

    app = create_app(system, username="shiva", password_hash=generate_password_hash("s3cret!"),
                     secret_key="test", clock=lambda: at(10, 0))
    app.testing = True
    return app.test_client()


def login(client):
    return client.post("/login", data={"username": "shiva", "password": "s3cret!"})


def test_f3_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/mode", json={"part": "intraday", "mode": "live"},
                       headers={"X-Axon-Request": "1"}).status_code == 401
    assert client.post("/api/kill-switch", json={"active": True}).status_code == 401
    assert client.get("/").status_code == 302  # redirected to login


def test_f3_live_needs_login_plus_typed_confirmation(client, system):
    login(client)
    r = client.post("/api/mode", json={"part": "intraday", "mode": "live"}, headers={"X-Axon-Request": "1"})
    assert r.status_code == 409
    assert system.ledger.get_mode(Part.INTRADAY) is Mode.PAPER


def test_f3_state_changes_need_the_request_header(client):
    login(client)
    assert client.post("/api/kill-switch", json={"active": True}).status_code == 403


def test_f3_no_manual_order_endpoint_and_localhost_default(client):
    login(client)
    assert client.post("/api/trade", json={}, headers={"X-Axon-Request": "1"}).status_code == 404
    import axon.web.app as web

    assert '"AXON_WEB_HOST", "127.0.0.1"' in inspect.getsource(web.main)


def test_f3_app_refuses_to_start_without_credentials(system, monkeypatch):
    from axon.web.app import WebConfigError, create_app

    for k in ("AXON_WEB_USERNAME", "AXON_WEB_PASSWORD_HASH", "AXON_WEB_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(WebConfigError):
        create_app(system)


# 4 ------------------------------------------------------------------ tested code is the code that runs
def test_f4_scheduler_and_tests_share_one_engine(system):
    from axon.scheduler import Scheduler

    sched = Scheduler(system)
    assert sched.axon.engine is system.engine
    assert isinstance(system.engine.strategies[Part.INTRADAY], IntradayVwapStrategy)
    src = inspect.getsource(Scheduler.tick)
    assert "engine.run_cycle" in src


# 5 ------------------------------------------------------------------ live orders on made-up prices
def test_f5_live_data_failure_places_zero_orders_and_one_alert(system):
    system.ledger.record_cash_flow("live", "deposit", 1_000_000, at(8, 0))
    system.ledger.set_mode(Part.INTRADAY, Mode.LIVE, at(9, 0), "test")
    system.data.set_climb("AAA-EQ")
    system.data.fail = True
    system.engine.run_cycle(at(10, 20))
    system.engine.run_cycle(at(10, 25))
    assert system.live.calls == []
    skipped = [a for a in system.ledger.alerts() if "skipped a cycle" in a["message"]]
    assert len(skipped) == 1


def test_f5_paper_mode_uses_real_prices_not_random(tmp_settings):
    ax = build(tmp_settings, real_data=object())
    assert ax.engine.data_for_mode(Mode.PAPER) is not ax.engine.data_for_mode(Mode.TEST)
    assert getattr(ax.engine.data_for_mode(Mode.TEST), "is_real") is False


# 6 ------------------------------------------------------------------ brakes
def test_f6_losing_month_triggers_each_brake_in_order_and_survives_restart(system):
    ledger = system.ledger
    t0 = at(9, 20)
    ledger.open_position(ts=t0, book="paper", part=Part.INTRADAY, symbol="AAA-EQ", token="1", exchange="NSE",
                         quantity=900, price=1000.0, costs=0.0, stop=None, target=None)
    risk = RiskEngine(system.settings, ledger)
    levels = []
    for day in range(22):
        price = 1000.0 * (1 - 0.01 * day)
        ledger.update_marks({"AAA-EQ": price}, book="paper")
        state = risk.evaluate_brakes("paper", t0 + timedelta(days=day))
        if not levels or state.level != levels[-1]:
            levels.append(state.level)
    assert levels == [0.0, 8.0, 12.0, 15.0]
    ledger = reopen(ledger)
    restarted = RiskEngine(system.settings, ledger).current_brakes("paper")
    assert restarted.locked and restarted.close_satellites and not restarted.entries_allowed


def test_f6_deposits_and_payouts_do_not_move_the_brakes(system):
    ledger = system.ledger
    before = ledger.nav_per_unit("paper")
    ledger.record_cash_flow("paper", "deposit", 500_000, at(9, 0))
    assert ledger.nav_per_unit("paper") == pytest.approx(before)
    ledger.record_cash_flow("paper", "payout", 200_000, at(9, 1))
    assert ledger.nav_per_unit("paper") == pytest.approx(before)
    assert RiskEngine(system.settings, ledger).evaluate_brakes("paper", at(9, 2)).level == 0


def test_f6_intraday_stops_for_the_day_after_one_percent_loss(system):
    system.data.set_climb("AAA-EQ")
    system.engine.run_cycle(at(10, 20))
    pos = system.ledger.open_positions("paper")[0]
    # gap down far below the stop, so the loss on this trade exceeds 1% of capital
    system.data.price_override["AAA-EQ"] = pos.entry_price - 12_000 / pos.quantity
    system.engine.run_cycle(at(10, 25))
    assert system.ledger.is_halted("paper", Part.INTRADAY, MONDAY.date())
    system.data.set_climb("BBB-EQ")
    system.engine.run_cycle(at(10, 30))
    assert buys(system, "BBB-EQ") == []


# 7 ------------------------------------------------------------------ market filter
def _daily(closes):
    start = datetime(2025, 1, 1, tzinfo=IST)
    return [Candle(start + timedelta(days=i), c, c, c, c, 1) for i, c in enumerate(closes)]


def test_f7_bear_market_turns_the_filter_off():
    bull = _daily([10000 + 10 * i for i in range(260)])
    bear = _daily([20000 - 30 * i for i in range(260)])
    assert nifty_trend(bull).allowed
    assert not nifty_trend(bear).allowed
    assert not nifty_trend(bull[:100]).allowed  # not enough history -> off


def test_f7_high_vix_blocks_intraday_entries():
    assert intraday_vix(14.0, 20.0).allowed
    assert not intraday_vix(26.5, 20.0).allowed
    assert not intraday_vix(None, 20.0).allowed


# 8 ------------------------------------------------------------------ sizing
def test_f8_intraday_worked_example():
    # ₹10,00,000 capital; stock ₹1,000; 5-min ATR ₹4 -> stop 1.5 x 4 = ₹6 below
    r = size_position(capital=1_000_000, price=1000, stop=994, risk_pct=0.25, capital_cap_pct=5,
                      adtv=100e7, adtv_cap_pct=0.25)
    assert (r.by_risk, r.by_capital, r.by_liquidity) == (416, 50, 2500)
    assert r.quantity == 50 and r.limited_by == "capital" and r.planned_risk == 300


def test_f8_swing_worked_example():
    # ₹10,00,000; risk 0.75%; stock ₹1,000; daily ATR ₹25 -> stop ₹950; ADTV ₹20 crore
    r = size_position(capital=1_000_000, price=1000, stop=950, risk_pct=0.75, capital_cap_pct=10,
                      adtv=20e7, adtv_cap_pct=1.0)
    assert (r.by_risk, r.by_capital, r.by_liquidity) == (150, 100, 2000)
    assert r.quantity == 100 and r.planned_risk == 5000


def test_f8_brake_halves_size_and_unknown_liquidity_blocks():
    half = size_position(capital=1_000_000, price=1000, stop=950, risk_pct=0.75, capital_cap_pct=100,
                         adtv=1e12, adtv_cap_pct=1.0, risk_multiplier=0.5)
    assert half.quantity == 75
    assert size_position(capital=1_000_000, price=1000, stop=950, risk_pct=0.75, capital_cap_pct=10,
                         adtv=None, adtv_cap_pct=1.0).quantity == 0


# 9 ------------------------------------------------------------------ no past-results bonus
def test_f9_ranking_ignores_trade_history(system):
    strategy = system.engine.strategies[Part.INTRADAY]
    assert "ledger" not in inspect.signature(strategy.entries).parameters
    for i, sym in enumerate(SYMBOLS):
        system.data.set_climb(sym, start=1000 + i * 100, step=1 + i)
    from axon.strategies.base import MarketView

    def ranking():
        now = at(10, 20)
        insts = system.engine.candidates(Part.INTRADAY)
        quotes = {i.symbol: system.data.quote(i, now) for i in insts}
        candles = {i.symbol: [c for c in system.data.intraday_candles(i, now) if c.start + timedelta(minutes=5) <= now]
                   for i in insts}
        return [s.instrument.symbol for s in strategy.entries(insts, MarketView(now, quotes, candles))]

    first = ranking()
    system.ledger.open_position(ts=at(9, 30), book="paper", part=Part.INTRADAY, symbol=first[0], token="1",
                                exchange="NSE", quantity=10, price=1000, costs=0, stop=None, target=None)
    pid = system.ledger.open_positions("paper")[0].id
    system.ledger.close_position(pid, ts=at(9, 40), price=500, costs=0, reason="big loss")
    assert ranking() == first


# 10 ------------------------------------------------------------------ daily report
def test_f10_report_lists_every_fill_and_matches_ledger(system):
    system.data.set_climb("AAA-EQ")
    system.data.set_climb("BBB-EQ", start=1500)
    system.engine.run_cycle(at(10, 20))
    system.engine.run_cycle(at(14, 45))
    report = build_daily_report(system.ledger, MONDAY.date())
    ledger_fills = [o for o in system.ledger.orders(day=MONDAY.date()) if o["status"] == "FILLED"]
    assert len(report["fills"]) == len(ledger_fills) >= 4
    realized = sum(p["realized_pnl"] for p in system.ledger.closed_positions(day=MONDAY.date()))
    assert sum(report["realized_pnl"].values()) == pytest.approx(realized)
    assert report["costs_actual"] > 0


# 11 ------------------------------------------------------------------ mode per part
def test_f11_mode_change_is_logged_announced_and_survives_restart(system):
    change_mode(ledger=system.ledger, alerter=system.alerter, settings=system.settings, part=Part.INTRADAY,
                new_mode=Mode.TEST, actor="shiva", now=at(9, 0))
    assert system.ledger.mode_changes()[-1]["new_mode"] == "test"
    assert any("Mode change: intraday PAPER -> TEST" in m for m in system.sent)
    ledger = reopen(system.ledger)
    assert ledger.get_mode(Part.INTRADAY) is Mode.TEST


def test_f11_startup_flag_is_gone():
    from axon.__main__ import main

    with pytest.raises(SystemExit):
        main(["run", "--angel-one"])


def test_f11_live_refused_before_paper_test_and_from_test_mode(system):
    with pytest.raises(ModeChangeRefused, match="paper test"):
        change_mode(ledger=system.ledger, alerter=system.alerter, settings=system.settings, part=Part.INTRADAY,
                    new_mode=Mode.LIVE, actor="shiva", now=at(9, 0), confirm="LIVE intraday")
    system.ledger.set_mode(Part.INTRADAY, Mode.TEST, at(9, 0), "test")
    with pytest.raises(ModeChangeRefused, match="never go straight to LIVE"):
        change_mode(ledger=system.ledger, alerter=system.alerter, settings=system.settings, part=Part.INTRADAY,
                    new_mode=Mode.LIVE, actor="shiva", now=at(9, 1), confirm="LIVE intraday")
    with pytest.raises(ModeChangeRefused, match="not built yet"):
        change_mode(ledger=system.ledger, alerter=system.alerter, settings=system.settings, part=Part.SWING,
                    new_mode=Mode.PAPER, actor="shiva", now=at(9, 2))


# 12 ------------------------------------------------------------------ holidays
def test_f12_scheduler_skips_a_listed_holiday_with_one_log_line(system):
    system.data.set_climb("AAA-EQ", day=HOLIDAY)
    r1 = system.engine.run_cycle(HOLIDAY)
    r2 = system.engine.run_cycle(HOLIDAY + timedelta(minutes=5))
    assert r1.status == r2.status == "skipped" and "Guru Nanak" in r1.reason
    assert len(system.ledger.events("skip_day")) == 1
    assert system.ledger.orders() == []


# 13 ------------------------------------------------------------------ duplicates deleted
def test_f13_one_web_server_one_trading_module_one_risk_engine():
    src = ROOT / "src"
    assert not (src / "axon_aone").exists(), "old package should be deleted"
    py = [p.relative_to(src).as_posix() for p in src.rglob("*.py")]
    assert [p for p in py if p.endswith("app.py") or "web_server" in p] == ["axon/web/app.py"]
    assert [p for p in py if p.endswith("risk.py") or "risk_engine" in p or "kill_switch" in p] == ["axon/risk.py"]
    assert [p for p in py if p.startswith("axon/strategies/") and p.endswith(".py")
            and not p.endswith(("__init__.py", "base.py"))] == ["axon/strategies/intraday_vwap.py"]


# 14 ------------------------------------------------------------------ health check
def test_f14_health_fails_when_the_loop_stops(system):
    now = at(11, 0)
    system.ledger.beat("alive", now)
    system.ledger.beat("cycle", now - timedelta(minutes=3))
    assert check(system.ledger, system.calendar, now)[0]
    system.ledger.beat("cycle", now - timedelta(minutes=15))
    ok, msg = check(system.ledger, system.calendar, now)
    assert not ok and "10 minutes" in msg
    system.ledger.beat("alive", now - timedelta(minutes=20))
    assert not check(system.ledger, system.calendar, now)[0]
