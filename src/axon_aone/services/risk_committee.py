"""Monthly risk-committee report pack generation."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from datetime import UTC  # Python 3.11+
except ImportError:  # pragma: no cover - Python 3.10 fallback
    UTC = timezone.utc

from axon_aone.config import RISK_COMMITTEE_REPORT_DIR
from axon_aone.db import ModelRegistryEntry, RiskCommitteeReport, SessionLocal, Trade


def _previous_month(today: date | None = None) -> Tuple[int, int]:
    base = today or datetime.now(UTC).date()
    if base.month == 1:
        return (base.year - 1, 12)
    return (base.year, base.month - 1)


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def _summarize_trades(rows: List[Trade]) -> Dict[str, Any]:
    buys = [r for r in rows if (r.side or "").upper() == "BUY"]
    sells = [r for r in rows if (r.side or "").upper() == "SELL"]

    open_lots: Dict[str, List[dict]] = {}
    realized_pnl = 0.0
    wins = 0
    losses = 0

    for row in rows:
        symbol = row.symbol
        qty = int(row.quantity or 0)
        price = float(row.price or 0.0)
        side = (row.side or "").upper()
        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            open_lots.setdefault(symbol, []).append({"qty": qty, "price": price})
            continue

        if side != "SELL":
            continue

        remaining = qty
        pnl = 0.0
        lots = open_lots.get(symbol, [])
        while remaining > 0 and lots:
            lot = lots[0]
            matched = min(remaining, int(lot["qty"]))
            pnl += (price - float(lot["price"])) * matched
            lot["qty"] -= matched
            remaining -= matched
            if lot["qty"] <= 0:
                lots.pop(0)

        realized_pnl += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    closed = wins + losses
    win_rate = (wins / closed) if closed > 0 else 0.0

    return {
        "total_trades": len(rows),
        "buy_trades": len(buys),
        "sell_trades": len(sells),
        "closed_roundtrips": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "realized_pnl": realized_pnl,
    }


def _latest_model_summary(session) -> List[Dict[str, Any]]:
    rows = (
        session.query(ModelRegistryEntry)
        .filter(ModelRegistryEntry.active.is_(True))
        .order_by(ModelRegistryEntry.created_at.desc(), ModelRegistryEntry.id.desc())
        .all()
    )

    latest_by_name: Dict[str, ModelRegistryEntry] = {}
    for row in rows:
        if row.model_name not in latest_by_name:
            latest_by_name[row.model_name] = row

    summary = []
    for row in latest_by_name.values():
        summary.append(
            {
                "model_name": row.model_name,
                "model_version": row.model_version,
                "stage": row.stage,
                "metrics": row.metrics or {},
                "config_hash": row.config_hash,
            }
        )
    return summary


def generate_monthly_risk_committee_report(year: int, month: int) -> Dict[str, Path]:
    session = SessionLocal()
    try:
        start, end = _month_range(year, month)
        trades = (
            session.query(Trade)
            .filter(Trade.created_at >= start, Trade.created_at < end)
            .order_by(Trade.created_at.asc(), Trade.id.asc())
            .all()
        )

        trade_summary = _summarize_trades(trades)
        model_summary = _latest_model_summary(session)

        report_payload = {
            "period": f"{year:04d}-{month:02d}",
            "generated_at": datetime.now(UTC).isoformat(),
            "trade_summary": trade_summary,
            "model_registry": model_summary,
            "decisions": {
                "capital_ramp": "hold",
                "risk_limits": "unchanged",
                "notes": "Auto-generated draft. Committee must approve final actions.",
            },
        }

        out_dir = Path(RISK_COMMITTEE_REPORT_DIR) / f"{year:04d}-{month:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "report.json"
        md_path = out_dir / "report.md"

        json_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        md_lines = [
            f"# Monthly Risk Committee Report - {year:04d}-{month:02d}",
            "",
            f"Generated at: {report_payload['generated_at']}",
            "",
            "## Trade Summary",
            f"- Total trades: {trade_summary['total_trades']}",
            f"- Closed roundtrips: {trade_summary['closed_roundtrips']}",
            f"- Win rate: {trade_summary['win_rate']:.2%}",
            f"- Realized PnL: {trade_summary['realized_pnl']:.2f}",
            "",
            "## Model Registry Snapshot",
        ]
        if model_summary:
            for item in model_summary:
                md_lines.append(
                    f"- {item['model_name']} {item['model_version']} | stage={item['stage']} | metrics={item['metrics']}"
                )
        else:
            md_lines.append("- No active models registered")
        md_lines.extend(
            [
                "",
                "## Draft Decisions",
                f"- Capital ramp: {report_payload['decisions']['capital_ramp']}",
                f"- Risk limits: {report_payload['decisions']['risk_limits']}",
                f"- Notes: {report_payload['decisions']['notes']}",
                "",
            ]
        )
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        row = RiskCommitteeReport(
            year=year,
            month=month,
            summary=report_payload,
            decisions=report_payload.get("decisions"),
            report_path=str(json_path),
        )
        session.add(row)
        session.commit()

        return {"json": json_path, "md": md_path}
    finally:
        session.close()


def maybe_generate_previous_month_report(today: date | None = None) -> Dict[str, Path] | None:
    year, month = _previous_month(today=today)
    out_dir = Path(RISK_COMMITTEE_REPORT_DIR) / f"{year:04d}-{month:02d}"
    json_path = out_dir / "report.json"
    if json_path.exists():
        return None
    return generate_monthly_risk_committee_report(year=year, month=month)


__all__ = [
    "generate_monthly_risk_committee_report",
    "maybe_generate_previous_month_report",
]
