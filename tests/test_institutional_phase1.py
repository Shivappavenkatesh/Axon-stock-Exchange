from types import SimpleNamespace

from axon_aone.execution.oms import OmsService
from axon_aone.services.compliance import ComplianceGate, OrderRequest
from axon_aone.services.reconciliation import generate_reconciliation_report


def test_compliance_gate_blocks_restricted_symbol_and_notional():
    gate = ComplianceGate(
        max_order_notional_pct=5.0,
        max_order_quantity=100,
        restricted_symbols={"BANNED-EQ"},
        max_concurrent_trades=5,
    )

    request = OrderRequest(
        symbol="BANNED-EQ",
        side="BUY",
        quantity=200,
        price=100.0,
        total_capital=100_000,
        tradable_capital=50_000,
    )

    decision = gate.evaluate(request, open_trade_count=2)
    assert decision.allowed is False
    assert "restricted_symbol" in decision.reasons
    assert "max_order_quantity_exceeded" in decision.reasons


def test_oms_service_is_idempotent_on_duplicate_order_id():
    oms = OmsService()

    def fake_executor(**kwargs):
        return {"status": "PAPER", "kwargs": kwargs}

    first = oms.submit_order(
        order_id="ORD-1",
        symbol="AAA",
        quantity=10,
        side="BUY",
        order_type="MARKET",
        price=None,
        use_mock=True,
        executor=fake_executor,
    )
    second = oms.submit_order(
        order_id="ORD-1",
        symbol="AAA",
        quantity=10,
        side="BUY",
        order_type="MARKET",
        price=None,
        use_mock=True,
        executor=fake_executor,
    )

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.status == first.status

    events = oms.get_events("ORD-1")
    states = [event["state"] for event in events]
    assert "NEW" in states
    assert "SENT" in states
    assert "FILLED" in states
    assert "DUPLICATE_REQUEST" in states


def test_reconciliation_report_detects_missing_and_status_mismatch(monkeypatch):
    scheduler_orders = [
        {"id": "ORD-1", "status": "FILLED"},
        {"id": "ORD-2", "status": "FILLED"},
    ]

    db_rows = [
        SimpleNamespace(external_id="ORD-1", status="FILLED"),
        SimpleNamespace(external_id="ORD-2", status="REJECTED"),
    ]

    class FakeQuery:
        def all(self):
            return db_rows

    class FakeSession:
        def query(self, _model):
            return FakeQuery()

        def close(self):
            return None

    monkeypatch.setattr("axon_aone.services.reconciliation.read_scheduler_orders", lambda limit=None: scheduler_orders)
    monkeypatch.setattr("axon_aone.services.reconciliation.SessionLocal", lambda: FakeSession())

    report = generate_reconciliation_report()

    assert report.scheduler_count == 2
    assert report.trade_count == 2
    assert report.missing_in_db == []
    assert len(report.status_mismatches) == 1
    assert report.status_mismatches[0]["id"] == "ORD-2"
