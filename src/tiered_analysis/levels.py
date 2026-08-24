# -*- coding: utf-8 -*-
"""Deterministic base price levels + adjustment validation (v2 slice 3).

Anchor-and-adjust (docs/tiered-analysis-formulas.md §2-3): formulas compute
a base for every level; the LLM may propose bounded adjustments (validated
here); code re-checks ordering and reward-to-risk after every accepted
adjustment. A rejected adjustment never edits the number — the base stands
and the rejection is surfaced as a warning.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .providers.base import DimensionResult
from .providers.technicals import read_metric
from .schema import SniperLevels
from .stops import DEFAULT_ATR_MULTIPLIER, suggest_atr_stop

#: Default target multiple when the user picked none: twice the upside of
#: the accepted downside (the run form's reward filter overrides this).
REWARD_RISK_MULTIPLE = 2.0

#: Below this reward-to-risk the plan is flagged loudly — but still issued
#: (owner decision 2026-07-22: always give a plan; the warning row carries
#: the judgment, the user decides).
MIN_REWARD_RISK = 1.5

#: An adjustment may move a level at most one typical daily swing from its
#: base — beyond that it is re-invention, not context.
ADJUSTMENT_BAND_ATR_MULTIPLE = 1.0

#: Level keys, in both SniperLevels field order and adjustment-application
#: order (entry first so stop/target checks see the final entry). The
#: backup entry is retired (owner decision, 2026-07-21): the plan is one
#: order at the ideal entry — old stored runs may still carry one.
LEVEL_KEYS = ("entry", "stop_loss", "take_profit")


def _valid(value: Optional[float]) -> bool:
    return value is not None and value > 0


@dataclass(frozen=True)
class LevelBasis:
    """One formula-computed level with its full audit trail."""

    value: float
    formula: str
    inputs: Dict[str, float]


@dataclass(frozen=True)
class BaseLevels:
    entry: Optional[LevelBasis] = None
    stop_loss: Optional[LevelBasis] = None
    take_profit: Optional[LevelBasis] = None
    warnings: List[str] = field(default_factory=list)

    def get(self, key: str) -> Optional[LevelBasis]:
        return getattr(self, key)

    @property
    def is_empty(self) -> bool:
        return all(self.get(key) is None for key in LEVEL_KEYS)


#: Psychological round-number steps by price magnitude: (min close, step).
_ROUND_STEPS = ((100.0, 10.0), (20.0, 5.0), (5.0, 1.0), (1.0, 0.5), (0.0, 0.1))


def round_number_below(close: float) -> Optional[float]:
    """Largest round price strictly below the close — a weak support line
    (crowd orders cluster at round numbers); joins the candidate set but
    never anchors an entry alone."""
    if close <= 0:
        return None
    step = next(step for threshold, step in _ROUND_STEPS if close >= threshold)
    level = math.floor(close / step) * step
    if level >= close:
        level -= step
    return level if level > 0 else None


def compute_base_levels(
    close: Optional[float],
    sma_50: Optional[float] = None,
    sma_200: Optional[float] = None,
    support_1: Optional[float] = None,
    atr: Optional[float] = None,
    resistance_1: Optional[float] = None,
    high_1y: Optional[float] = None,
    reward_risk: float = REWARD_RISK_MULTIPLE,
) -> BaseLevels:
    """The base levels; missing inputs degrade loudly, never silently.

    v2 anchors (technicals redesign 2026-07-27): supports are the
    nearest pivot low below the close plus the 50/200-day averages
    (the payload's coordinate fields); resistance is the nearest pivot
    high, with the one-year high as the landmark cap.

    ``reward_risk`` is the user's chosen target multiple (target = entry
    + reward_risk × risk). No condition voids the plan (owner decisions
    2026-07-22 and 2026-07-24: always give a plan — the warning row
    carries the judgment, the user decides). A close at or below the
    50-day average draws a trend warning, and the plan review flags it
    so the AI can tighten stop/target/shares; a resistance-capped target
    that misses the user's chosen ratio draws a warning the same way.
    """
    warnings: List[str] = []

    if not _valid(close):
        return BaseLevels(
            warnings=["no close price — deterministic levels cannot be computed"]
        )

    if _valid(sma_50):
        if close <= sma_50:
            warnings.append(
                f"trend warning: close {close:g} is at or below the 50-day "
                f"average {sma_50:g} (downtrend) — a pullback buy against "
                "the trend carries extra downside risk"
            )
    else:
        warnings.append("sma_50 unavailable — trend check skipped")

    structural = [
        v for v in (sma_50, sma_200, support_1) if _valid(v)
    ]
    if not structural:
        return BaseLevels(
            warnings=[
                "no structural support anchors (sma_50 / sma_200 / "
                "support_1) — no entry base, so no deterministic levels"
            ]
        )
    round_level = round_number_below(close)
    candidates = structural + ([round_level] if _valid(round_level) else [])

    # Levels are prices: round every computed value to cents at the
    # source, or binary float dust (385.46000000000004) leaks into the
    # audit trail, the signal ledger, and every display downstream.
    entry_value = round(min(close, max(candidates)), 2)
    entry = LevelBasis(
        value=entry_value,
        formula="min(close, max(support candidates))",
        inputs=_present(
            close=close,
            sma_50=sma_50,
            sma_200=sma_200,
            support_1=support_1,
            round_level=round_level,
        ),
    )

    stop: Optional[LevelBasis] = None
    target: Optional[LevelBasis] = None
    stop_value = suggest_atr_stop(entry_value, atr)
    stop_value = round(stop_value, 2) if stop_value is not None else None
    if stop_value is None:
        warnings.append(
            "no usable ATR — no volatility stop, and no target without a stop"
        )
    else:
        stop = LevelBasis(
            value=stop_value,
            formula="ideal_entry − 2 × atr_14",
            inputs={
                "ideal_entry": entry_value,
                "atr_14": atr,
                "multiplier": DEFAULT_ATR_MULTIPLIER,
            },
        )

        geometric = round(
            entry_value + reward_risk * (entry_value - stop_value), 2
        )
        resistances = [
            v
            for v in (resistance_1, high_1y)
            if _valid(v) and v > close
        ]
        nearest_res = min(resistances) if resistances else None
        if nearest_res is not None and nearest_res < geometric:
            target_value = round(nearest_res, 2)
            risk = entry_value - stop_value
            actual_ratio = (target_value - entry_value) / risk if risk > 0 else 0.0
            if actual_ratio < reward_risk:
                warnings.append(
                    f"reward below goal: overhead resistance at {nearest_res:g} "
                    f"caps the plan's reward-to-risk at {actual_ratio:.2f}, below "
                    f"your {reward_risk:g}× goal"
                )
            target = LevelBasis(
                value=target_value,
                formula=f"min(ideal_entry + {reward_risk:g} × (ideal_entry − "
                "stop_loss), nearest overhead resistance)",
                inputs=_present(
                    ideal_entry=entry_value,
                    stop_loss=stop_value,
                    geometric_target=geometric,
                    resistance_1=resistance_1,
                    high_1y=high_1y,
                ),
            )
        else:
            target = LevelBasis(
                value=geometric,
                formula=f"ideal_entry + {reward_risk:g} × (ideal_entry − stop_loss)",
                inputs={
                    "ideal_entry": entry_value,
                    "stop_loss": stop_value,
                    "reward_risk_multiple": reward_risk,
                },
            )

    return BaseLevels(
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        warnings=warnings,
    )


def _present(**values: Optional[float]) -> Dict[str, float]:
    return {name: value for name, value in values.items() if value is not None}


def bases_from_dimensions(
    dimensions: Sequence[DimensionResult],
    reward_risk: float = REWARD_RISK_MULTIPLE,
) -> BaseLevels:
    """Pull the level inputs out of the technicals dimension payload."""
    payload: Optional[Dict[str, Any]] = None
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            payload = dim.payload
            break
    if payload is None:
        return BaseLevels(
            warnings=[
                "technicals unavailable — deterministic levels cannot be computed"
            ]
        )

    return compute_base_levels(
        close=read_metric(payload, "price", "close"),
        sma_50=read_metric(payload, "daily", "sma_50"),
        sma_200=read_metric(payload, "daily", "sma_200"),
        support_1=read_metric(payload, "levels", "support_1"),
        atr=read_metric(payload, "volatility", "atr_14"),
        resistance_1=read_metric(payload, "levels", "resistance_1"),
        high_1y=read_metric(payload, "price", "high_1y"),
        reward_risk=reward_risk,
    )


@dataclass(frozen=True)
class AdjustmentProposal:
    """One LLM proposal, already evidence-validated by the adjuster."""

    level: str
    value: float
    #: One entry per flagged check the adjustment fixes, each in the
    #: shape {"check": <flagged check name>, "text": <one sentence>,
    #: "links": [{ref, value}, ...]} — the check name is the UI's
    #: deterministic keyword, the links are debate-style citations.
    reasons: Tuple[Dict[str, Any], ...] = ()
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LevelDecision:
    """Final verdict for one level: base, accepted adjustment, or rejection."""

    base: Optional[LevelBasis] = None
    adjusted: Optional[float] = None
    reasons: Tuple[Dict[str, Any], ...] = ()
    evidence: Tuple[str, ...] = ()
    rejection: Optional[str] = None

    @property
    def final(self) -> Optional[float]:
        if self.adjusted is not None:
            return self.adjusted
        return self.base.value if self.base is not None else None


def _ordering_problem(finals: Dict[str, Optional[float]]) -> Optional[str]:
    """Sanity of the whole set for a buy; None when consistent."""
    entry = finals["entry"]
    stop = finals["stop_loss"]
    target = finals["take_profit"]

    pairs = [
        (stop, entry, "stop-loss must stay below the entry"),
        (entry, target, "entry must stay below the target"),
    ]
    for low, high, message in pairs:
        if low is not None and high is not None and low >= high:
            return f"levels out of order: {message}"
    # No reward-to-risk floor here (owner decision 2026-07-22): a thin
    # ratio is a warning on the plan, never a reason to revert a level.
    return None


def apply_adjustments(
    bases: BaseLevels,
    proposals: Sequence[AdjustmentProposal],
    atr: Optional[float],
) -> Tuple[Dict[str, LevelDecision], List[str]]:
    """Validate proposals one level at a time, in LEVEL_KEYS order.

    Each acceptance immediately re-checks ordering and reward-to-risk on
    the resulting set; a violation reverts that single proposal.
    """
    decisions: Dict[str, LevelDecision] = {
        key: LevelDecision(base=bases.get(key)) for key in LEVEL_KEYS
    }
    warnings: List[str] = []

    def _reject(proposal: AdjustmentProposal, why: str) -> None:
        decisions[proposal.level] = LevelDecision(
            base=bases.get(proposal.level),
            rejection=why,
        )
        warnings.append(f"adjustment for {proposal.level} rejected: {why}")

    ordered = sorted(
        (p for p in proposals if p.level in LEVEL_KEYS),
        key=lambda p: LEVEL_KEYS.index(p.level),
    )
    for proposal in (p for p in proposals if p.level not in LEVEL_KEYS):
        warnings.append(f"adjustment for unknown level {proposal.level!r} ignored")

    for proposal in ordered:
        current = decisions[proposal.level]
        if current.adjusted is not None:
            warnings.append(
                f"duplicate adjustment for {proposal.level} ignored "
                "(first proposal kept)"
            )
            continue
        base = bases.get(proposal.level)
        if base is None:
            _reject(proposal, "no deterministic base exists to adjust")
            continue
        if atr is None or atr <= 0:
            _reject(proposal, "no ATR available — the adjustment band is undefined")
            continue
        if abs(proposal.value - base.value) > ADJUSTMENT_BAND_ATR_MULTIPLE * atr:
            _reject(
                proposal,
                f"moves the level more than {ADJUSTMENT_BAND_ATR_MULTIPLE:g} × ATR "
                f"({atr:g}) away from its base {base.value:g}",
            )
            continue

        candidate = LevelDecision(
            base=base,
            adjusted=proposal.value,
            reasons=proposal.reasons,
            evidence=proposal.evidence,
        )
        finals = {
            key: (candidate.final if key == proposal.level else decisions[key].final)
            for key in LEVEL_KEYS
        }
        problem = _ordering_problem(finals)
        if problem is not None:
            _reject(proposal, problem)
            continue
        decisions[proposal.level] = candidate

    return decisions, warnings


def decisions_to_sniper(decisions: Dict[str, LevelDecision]) -> SniperLevels:
    return SniperLevels(**{key: decisions[key].final for key in LEVEL_KEYS})


def decisions_to_detail(
    decisions: Dict[str, LevelDecision], warnings: Sequence[str]
) -> Dict[str, Any]:
    """JSON-ready audit trail: base + formula + adjustment per level."""
    levels: Dict[str, Any] = {}
    for key in LEVEL_KEYS:
        decision = decisions[key]
        levels[key] = {
            "base": decision.base.value if decision.base else None,
            "formula": decision.base.formula if decision.base else None,
            "inputs": dict(decision.base.inputs) if decision.base else None,
            "adjusted": decision.adjusted,
            "reasons": [dict(reason) for reason in decision.reasons],
            "evidence": list(decision.evidence),
            "rejection": decision.rejection,
            "final": decision.final,
        }
    return {"levels": levels, "warnings": list(warnings)}
