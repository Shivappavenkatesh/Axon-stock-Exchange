"""Capital allocation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from axon_aone.config import MAX_NEW_EXPOSURE_PCT, MAX_SECTOR_EXPOSURE, RISK_CONFIG


@dataclass
class EngineAllocation:
    name: str
    allocation: float
    enabled: bool = True


@dataclass
class AllocationConstraints:
    max_single_position_pct: float
    max_sector_pct: float
    max_new_exposure_pct: float


@dataclass
class SymbolAllocationPlan:
    symbol: str
    sector: str
    max_notional: float
    score: float


class AllocationEngine:
    def __init__(self) -> None:
        self._default_engine = EngineAllocation(name="trend_engine", allocation=1.0, enabled=True)
        self._constraints = AllocationConstraints(
            max_single_position_pct=float(RISK_CONFIG.get("MAX_POSITION_PCT", 5.0)) / 100.0,
            max_sector_pct=MAX_SECTOR_EXPOSURE,
            max_new_exposure_pct=MAX_NEW_EXPOSURE_PCT,
        )

    def get_allocations(self) -> List[EngineAllocation]:
        return [self._default_engine]

    def build_allocation_plan(
        self,
        candidates: List[dict],
        total_capital: float,
        current_sector_exposure: Dict[str, float] | None = None,
    ) -> Dict[str, SymbolAllocationPlan]:
        """Build a constrained max-notional plan for candidate entries."""
        if total_capital <= 0:
            return {}

        sector_used = {k: max(0.0, float(v)) for k, v in (current_sector_exposure or {}).items()}
        plan: Dict[str, SymbolAllocationPlan] = {}
        remaining_new_budget = total_capital * self._constraints.max_new_exposure_pct

        ranked = sorted(
            candidates,
            key=lambda c: float(c.get("opportunity_score", 0.0) or 0.0),
            reverse=True,
        )

        for candidate in ranked:
            symbol = candidate.get("symbol")
            if not symbol or remaining_new_budget <= 0:
                continue

            sector = str(candidate.get("sector") or "UNKNOWN")
            score = float(candidate.get("opportunity_score", 0.0) or 0.0)

            symbol_cap = total_capital * self._constraints.max_single_position_pct
            sector_cap_total = total_capital * self._constraints.max_sector_pct
            sector_remaining = max(0.0, sector_cap_total - sector_used.get(sector, 0.0))

            max_notional = max(0.0, min(symbol_cap, sector_remaining, remaining_new_budget))
            if max_notional <= 0:
                continue

            plan[symbol] = SymbolAllocationPlan(
                symbol=symbol,
                sector=sector,
                max_notional=max_notional,
                score=score,
            )

            sector_used[sector] = sector_used.get(sector, 0.0) + max_notional
            remaining_new_budget -= max_notional

        return plan
