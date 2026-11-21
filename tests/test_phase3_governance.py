from pathlib import Path
from datetime import date

from axon_aone.db import ModelPromotionEvent, ModelRegistryEntry, SessionLocal, init_db
from axon_aone.services.model_registry import (
    attempt_promotion,
    evaluate_promotion_gates,
    review_model_promotion,
    register_model,
)
from axon_aone.services.risk_committee import (
    generate_monthly_risk_committee_report,
    maybe_generate_previous_month_report,
)


def test_evaluate_promotion_gates_blocks_on_weak_metrics():
    weak = evaluate_promotion_gates(
        {
            "paper_days": 5,
            "sharpe": 0.5,
            "win_rate": 0.4,
            "max_drawdown_pct": 0.2,
        }
    )
    assert weak.approved is False
    assert weak.checks["paper_days"] is False
    assert weak.checks["sharpe"] is False


def test_register_and_promote_model_when_gates_pass():
    init_db()

    model_name = "phase3_test_model"
    model_version = "v1.0.0"
    register_model(
        model_name=model_name,
        model_version=model_version,
        config_hash="abc123",
        metrics={
            "paper_days": 40,
            "sharpe": 1.8,
            "win_rate": 0.6,
            "max_drawdown_pct": 0.05,
        },
        stage="paper",
    )

    result = attempt_promotion(model_name=model_name, model_version=model_version, target_stage="production", decided_by="pytest")
    assert result.approved is True

    session = SessionLocal()
    try:
        latest = (
            session.query(ModelRegistryEntry)
            .filter(ModelRegistryEntry.model_name == model_name)
            .order_by(ModelRegistryEntry.id.desc())
            .first()
        )
        assert latest is not None
        assert latest.stage == "production"
    finally:
        session.close()


def test_generate_monthly_risk_committee_report(tmp_path: Path, monkeypatch):
    init_db()

    monkeypatch.setattr("axon_aone.services.risk_committee.RISK_COMMITTEE_REPORT_DIR", str(tmp_path))

    paths = generate_monthly_risk_committee_report(year=2026, month=2)
    assert paths["json"].exists()
    assert paths["md"].exists()

    payload = paths["json"].read_text(encoding="utf-8")
    assert "trade_summary" in payload
    assert "model_registry" in payload

    # Running the idempotent helper should skip if file already exists.
    generated = maybe_generate_previous_month_report(today=date(2026, 3, 14))
    assert generated is None


def test_review_model_promotion_requires_human_signoff_fields():
    init_db()

    model_name = "phase4_test_model"
    model_version = "v2.0.0"
    register_model(
        model_name=model_name,
        model_version=model_version,
        config_hash="def456",
        metrics={
            "paper_days": 50,
            "sharpe": 2.0,
            "win_rate": 0.65,
            "max_drawdown_pct": 0.04,
        },
        stage="paper",
    )

    # Missing reviewer/ticket/note should fail despite strong gate metrics.
    denied = review_model_promotion(
        model_name=model_name,
        model_version=model_version,
        target_stage="production",
        decided_by="",
        approve=True,
        approval_note="",
        ticket_id="",
    )
    assert denied.approved is False
    assert denied.checks["human_reviewer_present"] is False
    assert denied.checks["ticket_id_present"] is False

    approved = review_model_promotion(
        model_name=model_name,
        model_version=model_version,
        target_stage="production",
        decided_by="risk_committee_user",
        approve=True,
        approval_note="monthly committee approved",
        ticket_id="RC-2026-03",
    )
    assert approved.approved is True

    session = SessionLocal()
    try:
        latest_model = (
            session.query(ModelRegistryEntry)
            .filter(ModelRegistryEntry.model_name == model_name)
            .order_by(ModelRegistryEntry.id.desc())
            .first()
        )
        assert latest_model is not None
        assert latest_model.stage == "production"

        events = (
            session.query(ModelPromotionEvent)
            .filter(ModelPromotionEvent.model_name == model_name)
            .order_by(ModelPromotionEvent.id.asc())
            .all()
        )
        assert len(events) >= 2
        assert events[-1].approved is True
        assert events[-1].decided_by == "risk_committee_user"
    finally:
        session.close()
