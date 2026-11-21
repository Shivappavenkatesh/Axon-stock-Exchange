#!/usr/bin/env python3
"""Master DD Scorecard Engine.

Converts a 7-layer due-diligence framework into a deterministic decision process
with hard-stop rules, weighted scoring, and position sizing guidance.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class CheckStatus(str, Enum):
    PASS = "pass"
    WATCH = "watch"
    FAIL = "fail"
    MISSING = "missing"


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    BITCOIN = "bitcoin"


STATUS_POINTS = {
    CheckStatus.PASS: 1.0,
    CheckStatus.WATCH: 0.5,
    CheckStatus.FAIL: 0.0,
    CheckStatus.MISSING: 0.0,
}


LAYER_WEIGHTS = {
    1: 20.0,
    2: 15.0,
    3: 15.0,
    4: 15.0,
    5: 15.0,
    6: 10.0,
    7: 10.0,
}


BASE_POSITION_CAP = {
    AssetType.STOCK: 0.10,
    AssetType.ETF: 0.15,
    AssetType.BITCOIN: 0.05,
}


@dataclass(frozen=True)
class DDCheck:
    check_id: int
    layer: int
    title: str
    hard_fail: bool


CHECKS: List[DDCheck] = [
    DDCheck(1, 1, "Regulatory & Legal DD", True),
    DDCheck(2, 1, "Governance & Integrity DD", True),
    DDCheck(3, 2, "Promoter / Management DD", True),
    DDCheck(4, 2, "Incentive & Lifestyle DD", False),
    DDCheck(5, 2, "Human Capital DD", False),
    DDCheck(6, 3, "Business Model DD", False),
    DDCheck(7, 3, "Industry & Sector DD", False),
    DDCheck(8, 3, "Competitive DD", False),
    DDCheck(9, 4, "Financial Statement DD", True),
    DDCheck(10, 4, "Balance Sheet Quality DD", False),
    DDCheck(11, 4, "Capital Allocation DD", False),
    DDCheck(12, 5, "Risk Enumeration DD", True),
    DDCheck(13, 5, "Stress-Test DD", True),
    DDCheck(14, 5, "Subsidiary & Group Structure DD", False),
    DDCheck(15, 6, "Valuation DD", False),
    DDCheck(16, 6, "Liquidity & Exit DD", True),
    DDCheck(17, 6, "Price-Fundamental DD", False),
    DDCheck(18, 6, "Crowding & Sentiment DD", False),
    DDCheck(19, 7, "Asymmetry DD", True),
    DDCheck(20, 7, "Inflection-Point DD", False),
    DDCheck(21, 7, "Narrative Gap DD", False),
    DDCheck(22, 7, "Time Compression DD", False),
    DDCheck(23, 7, "Failure-Mode DD", True),
    DDCheck(24, 7, "Short-Seller DD", False),
    DDCheck(25, 7, "Behavioral DD", False),
]


def _parse_status(raw: Optional[str]) -> CheckStatus:
    if raw is None:
        return CheckStatus.MISSING
    normalized = raw.strip().lower()
    for status in CheckStatus:
        if normalized == status.value:
            return status
    return CheckStatus.MISSING


def _validate_asset(asset: str) -> AssetType:
    try:
        return AssetType(asset.lower())
    except ValueError as exc:
        raise ValueError("asset must be one of: stock, etf, bitcoin") from exc


def _status_map(payload: Dict) -> Dict[int, CheckStatus]:
    checks_payload = payload.get("checks", {})
    output: Dict[int, CheckStatus] = {}
    for check in CHECKS:
        raw_value = checks_payload.get(str(check.check_id), checks_payload.get(check.check_id))
        output[check.check_id] = _parse_status(raw_value)
    return output


def _layer_checks(layer: int) -> List[DDCheck]:
    return [c for c in CHECKS if c.layer == layer]


def _layer_status(check_statuses: Dict[int, CheckStatus], layer: int) -> Tuple[str, List[str], bool]:
    issues: List[str] = []
    layer_items = _layer_checks(layer)
    has_missing = False

    for check in layer_items:
        status = check_statuses[check.check_id]
        if status is CheckStatus.MISSING:
            has_missing = True
            issues.append(f"Check {check.check_id} missing")
        elif status is CheckStatus.FAIL:
            issues.append(f"Check {check.check_id} failed")

    if layer == 1 and issues:
        return "failed", issues, True

    if has_missing:
        return "incomplete", issues, True

    any_fail = any(check_statuses[c.check_id] is CheckStatus.FAIL for c in layer_items)
    if any_fail:
        return "failed", issues, True

    return "passed", issues, False


def _weighted_score(check_statuses: Dict[int, CheckStatus]) -> float:
    score = 0.0
    for layer, weight in LAYER_WEIGHTS.items():
        checks = _layer_checks(layer)
        layer_points = sum(STATUS_POINTS[check_statuses[c.check_id]] for c in checks)
        layer_max = float(len(checks))
        layer_ratio = (layer_points / layer_max) if layer_max else 0.0
        score += weight * layer_ratio
    return round(score, 2)


def _auto_fail_reasons(payload: Dict, check_statuses: Dict[int, CheckStatus]) -> List[str]:
    reasons: List[str] = []

    for check in CHECKS:
        if check.hard_fail and check_statuses[check.check_id] is CheckStatus.FAIL:
            reasons.append(f"Hard-fail trigger: Check {check.check_id} ({check.title})")

    risks = payload.get("risks", [])
    if isinstance(risks, list) and len([r for r in risks if str(r).strip()]) < 3:
        reasons.append("Hard-fail trigger: Fewer than 3 explicit risks listed")

    upside_multiple = payload.get("upside_multiple")
    if upside_multiple is not None:
        try:
            if float(upside_multiple) < 10.0:
                reasons.append("Hard-fail trigger: Asymmetry upside < 10x")
        except (TypeError, ValueError):
            reasons.append("Hard-fail trigger: Invalid upside_multiple")

    return reasons


def _position_sizing(
    asset_type: AssetType,
    weighted_score: float,
    auto_fail: bool,
    blocked_layer: Optional[int],
    check_statuses: Dict[int, CheckStatus],
) -> Dict[str, object]:
    if auto_fail or blocked_layer is not None:
        return {
            "recommended_position_pct": 0.0,
            "risk_tier": "no-position",
            "reason": "Hard-fail or layer gate not cleared",
        }

    base_cap = BASE_POSITION_CAP[asset_type]
    confidence = max(0.0, min(1.0, weighted_score / 100.0))
    watch_count = sum(1 for s in check_statuses.values() if s is CheckStatus.WATCH)
    fail_count = sum(1 for s in check_statuses.values() if s is CheckStatus.FAIL)

    penalty = 1.0 - (watch_count * 0.015) - (fail_count * 0.05)
    penalty = max(0.2, penalty)
    raw_size = base_cap * confidence * penalty

    if asset_type is AssetType.BITCOIN:
        raw_size *= 0.85

    size_pct = round(raw_size * 100.0, 2)

    if size_pct >= 7.0:
        tier = "high-conviction"
    elif size_pct >= 3.0:
        tier = "medium-conviction"
    elif size_pct > 0.0:
        tier = "starter"
    else:
        tier = "no-position"

    return {
        "recommended_position_pct": size_pct,
        "risk_tier": tier,
        "reason": "Score-weighted sizing with watch/fail penalties",
    }


def evaluate_dd(asset: str, payload: Dict) -> Dict[str, object]:
    asset_type = _validate_asset(asset)
    check_statuses = _status_map(payload)

    layer_results: List[Dict[str, object]] = []
    blocked_layer: Optional[int] = None

    for layer in range(1, 8):
        status, issues, blocked = _layer_status(check_statuses, layer)
        layer_results.append({"layer": layer, "status": status, "issues": issues})
        if blocked and blocked_layer is None:
            blocked_layer = layer
            break

    auto_fail_reasons = _auto_fail_reasons(payload, check_statuses)
    auto_fail = len(auto_fail_reasons) > 0
    weighted = _weighted_score(check_statuses)

    position = _position_sizing(
        asset_type=asset_type,
        weighted_score=weighted,
        auto_fail=auto_fail,
        blocked_layer=blocked_layer,
        check_statuses=check_statuses,
    )

    decision = "reject" if auto_fail or blocked_layer is not None else "investable"
    return {
        "asset": asset_type.value,
        "decision": decision,
        "blocked_layer": blocked_layer,
        "auto_fail": auto_fail,
        "auto_fail_reasons": auto_fail_reasons,
        "weighted_score": weighted,
        "layer_results": layer_results,
        "position_sizing": position,
    }


def template_payload() -> Dict[str, object]:
    checks = {str(c.check_id): "missing" for c in CHECKS}
    return {
        "checks": checks,
        "risks": ["", "", ""],
        "upside_multiple": 10,
        "downside_multiple": 1,
        "notes": {
            "1": "Add legal/regulatory notes",
            "2": "Add governance notes",
            "12": "List at least 3 explicit risks",
            "19": "Upside asymmetry should ideally be >= 10x for axon risk",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Master DD Scorecard Engine")
    parser.add_argument("--asset", choices=[a.value for a in AssetType], help="Asset type")
    parser.add_argument("--input", type=Path, help="Path to DD JSON input")
    parser.add_argument("--init-template", type=Path, help="Write template input JSON and exit")
    args = parser.parse_args()

    if args.init_template:
        args.init_template.write_text(json.dumps(template_payload(), indent=2), encoding="utf-8")
        print(f"Template written: {args.init_template}")
        return

    if not args.asset or not args.input:
        parser.error("--asset and --input are required unless --init-template is used")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate_dd(asset=args.asset, payload=payload)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
