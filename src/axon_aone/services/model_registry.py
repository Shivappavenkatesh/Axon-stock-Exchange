"""Model registry and promotion-gate workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from axon_aone.config import (
    MODEL_PROMOTION_MAX_DRAWDOWN_PCT,
    MODEL_PROMOTION_MIN_PAPER_DAYS,
    MODEL_PROMOTION_MIN_SHARPE,
    MODEL_PROMOTION_MIN_WIN_RATE,
)
from axon_aone.db import ModelPromotionEvent, ModelRegistryEntry, SessionLocal


@dataclass
class PromotionGateResult:
    approved: bool
    checks: Dict[str, bool]
    metrics: Dict[str, float]


def evaluate_promotion_gates(metrics: Dict[str, Any]) -> PromotionGateResult:
    normalized = {
        "paper_days": float(metrics.get("paper_days", 0.0) or 0.0),
        "sharpe": float(metrics.get("sharpe", 0.0) or 0.0),
        "win_rate": float(metrics.get("win_rate", 0.0) or 0.0),
        "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0) or 0.0),
    }

    checks = {
        "paper_days": normalized["paper_days"] >= float(MODEL_PROMOTION_MIN_PAPER_DAYS),
        "sharpe": normalized["sharpe"] >= float(MODEL_PROMOTION_MIN_SHARPE),
        "win_rate": normalized["win_rate"] >= float(MODEL_PROMOTION_MIN_WIN_RATE),
        "max_drawdown_pct": normalized["max_drawdown_pct"] <= float(MODEL_PROMOTION_MAX_DRAWDOWN_PCT),
    }
    return PromotionGateResult(approved=all(checks.values()), checks=checks, metrics=normalized)


def register_model(
    model_name: str,
    model_version: str,
    config_hash: str,
    metrics: Dict[str, Any],
    stage: str = "research",
    notes: str | None = None,
) -> int:
    session = SessionLocal()
    try:
        row = ModelRegistryEntry(
            model_name=model_name,
            model_version=model_version,
            stage=stage,
            config_hash=config_hash,
            metrics=metrics,
            notes=notes,
            active=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return int(row.id)
    finally:
        session.close()


def list_models(model_name: str | None = None) -> List[ModelRegistryEntry]:
    session = SessionLocal()
    try:
        query = session.query(ModelRegistryEntry)
        if model_name:
            query = query.filter(ModelRegistryEntry.model_name == model_name)
        return query.order_by(ModelRegistryEntry.created_at.desc(), ModelRegistryEntry.id.desc()).all()
    finally:
        session.close()


def attempt_promotion(
    model_name: str,
    model_version: str,
    target_stage: str,
    decided_by: str = "system",
) -> PromotionGateResult:
    return review_model_promotion(
        model_name=model_name,
        model_version=model_version,
        target_stage=target_stage,
        decided_by=decided_by,
        approve=True,
        approval_note="automatic_attempt",
        ticket_id="auto",
    )


def review_model_promotion(
    model_name: str,
    model_version: str,
    target_stage: str,
    decided_by: str,
    approve: bool,
    approval_note: str,
    ticket_id: str,
) -> PromotionGateResult:
    session = SessionLocal()
    try:
        row = (
            session.query(ModelRegistryEntry)
            .filter(
                ModelRegistryEntry.model_name == model_name,
                ModelRegistryEntry.model_version == model_version,
                ModelRegistryEntry.active.is_(True),
            )
            .order_by(ModelRegistryEntry.id.desc())
            .first()
        )
        if row is None:
            return PromotionGateResult(
                approved=False,
                checks={"model_exists": False},
                metrics={},
            )

        gate = evaluate_promotion_gates(row.metrics or {})
        reviewer = (decided_by or "").strip()
        note = (approval_note or "").strip()
        ticket = (ticket_id or "").strip()

        signoff_checks = {
            "human_reviewer_present": reviewer not in {"", "system"},
            "approval_note_present": note != "",
            "ticket_id_present": ticket != "",
            "manual_approval": bool(approve),
        }
        final_approved = gate.approved and all(signoff_checks.values())

        event = ModelPromotionEvent(
            model_name=model_name,
            model_version=model_version,
            from_stage=row.stage,
            to_stage=target_stage,
            approved=final_approved,
            gate_result={
                "checks": gate.checks,
                "metrics": gate.metrics,
                "review": {
                    "signoff_checks": signoff_checks,
                    "reviewer": reviewer or "unknown",
                    "approval_note": note,
                    "ticket_id": ticket,
                },
            },
            decided_by=reviewer or "unknown",
        )
        session.add(event)

        if final_approved:
            row.stage = target_stage

        session.commit()
        merged_checks = dict(gate.checks)
        merged_checks.update(signoff_checks)
        return PromotionGateResult(
            approved=final_approved,
            checks=merged_checks,
            metrics=gate.metrics,
        )
    finally:
        session.close()


def list_promotion_events(limit: int = 200) -> List[ModelPromotionEvent]:
    session = SessionLocal()
    try:
        lim = max(1, int(limit))
        return (
            session.query(ModelPromotionEvent)
            .order_by(ModelPromotionEvent.created_at.desc(), ModelPromotionEvent.id.desc())
            .limit(lim)
            .all()
        )
    finally:
        session.close()


__all__ = [
    "PromotionGateResult",
    "attempt_promotion",
    "evaluate_promotion_gates",
    "list_models",
    "list_promotion_events",
    "register_model",
    "review_model_promotion",
]
