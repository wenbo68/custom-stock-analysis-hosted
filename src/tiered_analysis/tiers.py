# -*- coding: utf-8 -*-
"""Tier stages (docs/tiered-analysis-design.md §4).

Deterministic orchestration: every failure surfaces as an explicit
UNKNOWN-direction report with warnings (fail-loud), never an exception
swallowed mid-pipeline.

Tier 1 (the one-call quick judge) lives in ``quick_judge.py`` since
2026-08-10 — the legacy stage that delegated to the DSA single-shot
analysis is retired, so this package no longer touches the DSA decision
path at all.

Tier 2 (the evidence vote) runs the tiered package's own LLM engine.
Outlook redesign (2026-07-20): tier 3 is retired — the deterministic
risk card replaced it — and a failed tier-2 debate no longer falls back
to a weaker judge; the run fails honestly instead.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .providers.base import DimensionResult, Market
from .schema import Direction, SniperLevels, TierReport


@dataclass
class TierState:
    """Shared state threaded through the tier stages for one symbol."""

    symbol: str
    market: Market
    reports: Dict[int, TierReport] = field(default_factory=dict)
    #: Collected dimension results, set by the orchestration layer so
    #: higher tiers can debate over the evidence (falls back to the
    #: dimensions attached to the tier-1 report when unset).
    dimensions: List[DimensionResult] = field(default_factory=list)
    #: Shares of this stock the user already holds (per-run input, 0 =
    #: none) — drives the action table and the sell share count.
    ownership: int = 0
    #: Max hold time in weeks (per-run input, 2026-08-08): the debate
    #: judges evidence against this horizon and the grader scores at it.
    hold_weeks: int = 2


class TierStage(ABC):
    tier: int

    @abstractmethod
    def run(self, state: TierState) -> TierReport:
        """Produce this tier's report; failures return UNKNOWN-direction
        reports with explicit warnings."""


class Tier2Stage(TierStage):
    """The evidence vote over the collected dimensions (v2 slice 4).

    The engine is injected for tests; the default is a lazy DebateEngine
    (the tiered package's own LLM calls). Any failure — no foundation
    report, no evidence, LLM down — is a report with an UNKNOWN
    direction and explicit warnings. There is deliberately no
    fallback to the tier-1 one-blob verdict: substituting the weakest
    judge when the best one fails would present a downgrade as a result.
    """

    tier = 2

    def __init__(self, engine: Optional[Any] = None) -> None:
        self._engine = engine

    def _failed(self, state: TierState, levels: SniperLevels,
                warnings: List[str], detail: Optional[Dict[str, Any]] = None
                ) -> TierReport:
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            direction=Direction.UNKNOWN,
            levels=levels,
            warnings=warnings,
            debate_detail=detail,
        )

    def run(self, state: TierState) -> TierReport:
        foundation = state.reports.get(1)
        if foundation is None:
            return self._failed(
                state, SniperLevels(),
                ["tier 2 requires the data-layer foundation report"],
            )

        dimensions = state.dimensions or foundation.dimensions
        if not dimensions:
            return self._failed(
                state, foundation.levels,
                ["no collected evidence to vote on — no outlook (re-run)"],
            )

        engine = self._engine
        if engine is None:
            from .debate import DebateEngine

            engine = DebateEngine()
        result = engine.run(
            state.symbol, foundation, dimensions, hold_weeks=state.hold_weeks
        )

        if result.verdict is None:
            return self._failed(
                state, foundation.levels,
                list(result.warnings)
                + ["debate produced no verdict — no outlook (re-run)"],
                detail=result.to_detail(),
            )

        verdict = result.verdict
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            direction=verdict.direction,
            # The verdict is computed by formula from the vote outcomes,
            # so there is no judge confidence — the score lives in
            # debate_detail.verdict.final_score.
            confidence=None,
            score=foundation.score,
            levels=foundation.levels,
            narrative=verdict.summary or None,
            warnings=list(result.warnings),
            debate_detail=result.to_detail(),
        )
