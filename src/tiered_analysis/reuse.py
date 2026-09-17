# -*- coding: utf-8 -*-
"""Run reuse (2026-09-17): hand one run's outlook to another user's run.

Two runs of the same ticker, on the same trading day, judged against the
same max hold time, share everything up to and including the outlook:
the fetched data, the news screening, the six dimension cards and the
judge's (quick or debate) call. Only what comes AFTER the outlook is
personal — the plan levels (the take-profit is built from the user's
reward goal), the AI plan review (it may trim the share count), sizing
and the buy-now/buy-later action.

So a reused run is an ordinary ``run_tiered_analysis`` call with the
shared stages replaced by the stored result: the data layer comes from
``precollected_providers`` over the source's dimensions, and the judge
is a stand-in that returns the source's outlook. The personal stages
then run for real with the requester's own settings and key, and the
result serializes like any other run. The requester pays for at most
one small AI call (the plan review, bullish outlooks only).

The endpoint decides WHICH run may be reused (src/tiered_analysis/
history.find_reusable_run: same ticker, trading day and hold weeks; the
same or a deeper tier; the same or a stronger model of the same
provider). This module only knows how to turn a stored result back into
pipeline pieces, and refuses (``ReuseUnavailable``) when the stored
shape lacks what that takes — the caller then runs a fresh analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .providers.base import Citation, DimensionProvider, DimensionResult, SourceKind
from .quick_judge import QuickOutlook, QuickResult
from .schema import Direction, Outlook, TierReport
from .tiers import TierState

#: Outlooks worth handing on. Unknown (the judge failed) and stopped
#: (stale data) runs are never reused — the requester runs afresh.
REUSABLE_OUTLOOKS = frozenset({
    Outlook.BULLISH.value, Outlook.NEUTRAL.value, Outlook.BEARISH.value,
})


class ReuseUnavailable(RuntimeError):
    """The stored result cannot stand in for a fresh run."""


def is_reusable_result(result: Any) -> bool:
    """Whether a stored result carries a usable outlook and the pieces a
    reused run needs (dimensions and the judge's detail)."""
    if not isinstance(result, dict):
        return False
    if result.get("outlook") not in REUSABLE_OUTLOOKS:
        return False
    if not isinstance(result.get("dimensions"), list) or not result["dimensions"]:
        return False
    depth = result.get("depth")
    if depth == 2:
        tier2 = result.get("tier2")
        return isinstance(tier2, dict) and isinstance(tier2.get("debate_detail"), dict)
    if depth == 1:
        detail = result.get("debate_detail")
        return (
            isinstance(detail, dict)
            and isinstance(detail.get("outlook"), dict)
            and detail["outlook"].get("final_score") is not None
        )
    return False


def dimensions_from_result(result: Dict[str, Any]) -> List[DimensionResult]:
    """The stored dimension cards as the dataclasses the pipeline takes.
    The stored shape is api/v1/endpoints/tiered.py's serialization."""
    dimensions: List[DimensionResult] = []
    for raw in result.get("dimensions") or []:
        if not isinstance(raw, dict) or not raw.get("dimension"):
            raise ReuseUnavailable("stored dimension is missing its name")
        try:
            kind = SourceKind(raw.get("kind"))
        except ValueError as exc:
            raise ReuseUnavailable(f"stored dimension has an unknown kind: {exc}")
        citations = [
            Citation(
                source_name=str(c.get("source_name") or ""),
                url=c.get("url"),
                title=c.get("title"),
                snippet=c.get("snippet"),
            )
            for c in (raw.get("citations") or [])
            if isinstance(c, dict)
        ]
        dimensions.append(DimensionResult(
            dimension=str(raw["dimension"]),
            kind=kind,
            payload=raw.get("payload"),
            narrative=raw.get("narrative"),
            citations=citations,
            warnings=list(raw.get("warnings") or []),
            formulas=raw.get("formulas"),
            field_notes=raw.get("field_notes"),
        ))
    if not dimensions:
        raise ReuseUnavailable("stored result has no dimensions")
    return dimensions


class ReusedQuickJudge:
    """Stands in for ``QuickJudge``: returns the source run's outlook."""

    def __init__(self, outlook: QuickOutlook) -> None:
        self._outlook = outlook

    def run(self, symbol: str, dimensions: Sequence[DimensionResult],
            hold_weeks: int = 2) -> QuickResult:
        return QuickResult(outlook=self._outlook)


class ReusedTier2Stage:
    """Stands in for ``Tier2Stage``: returns the source run's debate."""

    tier = 2

    def __init__(self, section: Dict[str, Any]) -> None:
        self._section = section

    def run(self, state: TierState) -> TierReport:
        foundation = state.reports[1]
        section = self._section
        return TierReport(
            tier=2,
            symbol=state.symbol,
            market=state.market,
            direction=Direction.from_decision_type(section.get("direction")),
            confidence=None,
            score=foundation.score,
            levels=foundation.levels,
            narrative=section.get("narrative") or None,
            warnings=list(section.get("warnings") or []),
            debate_detail=section.get("debate_detail"),
        )


@dataclass(frozen=True)
class ReuseKit:
    """The pieces that make ``run_tiered_analysis`` a reused run."""

    depth: int
    providers: List[DimensionProvider]
    quick_judge: Optional[ReusedQuickJudge] = None
    tier2_stage: Optional[ReusedTier2Stage] = None


def reuse_kit(result: Dict[str, Any]) -> ReuseKit:
    """Build the stand-ins from a stored result; raises
    ``ReuseUnavailable`` when the result is not fit to reuse."""
    from .integration import precollected_providers

    if not is_reusable_result(result):
        raise ReuseUnavailable("stored result has no reusable outlook")
    providers = precollected_providers(dimensions_from_result(result))
    depth = int(result["depth"])
    if depth == 2:
        return ReuseKit(
            depth=2, providers=providers,
            tier2_stage=ReusedTier2Stage(dict(result["tier2"])),
        )
    detail = result["debate_detail"]["outlook"]
    final = result.get("final") if isinstance(result.get("final"), dict) else {}
    direction = Direction.from_decision_type(final.get("direction") or result.get("direction"))
    if direction is Direction.UNKNOWN:
        raise ReuseUnavailable("stored result has no direction")
    outlook = QuickOutlook(
        direction=direction,
        final_score=float(detail["final_score"]),
        summary=str(result.get("narrative") or ""),
    )
    return ReuseKit(depth=1, providers=providers, quick_judge=ReusedQuickJudge(outlook))
