"""Daily order/trade reconciliation for institutional controls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from axon_aone.db import SessionLocal, Trade
from axon_aone.services.order_store import read_scheduler_orders


@dataclass
class ReconciliationReport:
    generated_at: str
    scheduler_count: int
    trade_count: int
    missing_in_db: List[str]
    status_mismatches: List[Dict[str, str]]

    @property
    def break_count(self) -> int:
        return len(self.missing_in_db) + len(self.status_mismatches)


_STATUS_MAP = {
    "PAPER": "FILLED",
    "SUCCESS": "FILLED",
    True: "FILLED",
    False: "REJECTED",
}


def _normalize_status(status) -> str:
    if status in _STATUS_MAP:
        return _STATUS_MAP[status]
    return str(status or "UNKNOWN").upper()


def generate_reconciliation_report() -> ReconciliationReport:
    scheduler_orders = read_scheduler_orders(limit=None)
    scheduler_by_id: Dict[str, dict] = {
        str(o.get("id")): o for o in scheduler_orders if o.get("id")
    }

    session = SessionLocal()
    try:
        rows = session.query(Trade).all()
    finally:
        session.close()

    db_by_id = {str(row.external_id): row for row in rows if row.external_id}

    missing_in_db = sorted([order_id for order_id in scheduler_by_id if order_id not in db_by_id])
    status_mismatches: List[Dict[str, str]] = []

    for order_id, scheduler_order in scheduler_by_id.items():
        row = db_by_id.get(order_id)
        if row is None:
            continue
        scheduler_status = _normalize_status(scheduler_order.get("status"))
        db_status = _normalize_status(row.status)
        if scheduler_status != db_status:
            status_mismatches.append(
                {
                    "id": order_id,
                    "scheduler_status": scheduler_status,
                    "db_status": db_status,
                }
            )

    return ReconciliationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        scheduler_count=len(scheduler_by_id),
        trade_count=len(db_by_id),
        missing_in_db=missing_in_db,
        status_mismatches=status_mismatches,
    )


def persist_reconciliation_report(report: ReconciliationReport) -> Path:
    root = Path(os.getenv("AXON_RECONCILIATION_DIR", "logs/reconciliation"))
    root.mkdir(parents=True, exist_ok=True)
    filename = datetime.now(timezone.utc).strftime("%Y-%m-%d.json")
    path = root / filename

    payload = {
        "generated_at": report.generated_at,
        "scheduler_count": report.scheduler_count,
        "trade_count": report.trade_count,
        "break_count": report.break_count,
        "missing_in_db": report.missing_in_db,
        "status_mismatches": report.status_mismatches,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


__all__ = [
    "ReconciliationReport",
    "generate_reconciliation_report",
    "persist_reconciliation_report",
]
