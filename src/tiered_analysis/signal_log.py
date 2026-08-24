# -*- coding: utf-8 -*-
"""Log tier reports into DSA's existing decision-signal system (slice 6).

DSA already has the recommendation log the design doc asked for: the
``decision_signals`` table (every recommendation with entry/stop/target),
the outcome job that fetches the subsequent price path
(``decision_signal_outcome_service``), and a web page that renders each
signal's ``data_quality_summary``. Building a parallel log would violate
the repo's reuse rule — so this module is a thin CLIENT adapter:

- ``build_signal_payload``: pure mapping TierReport -> service payload.
  ``data_quality_summary`` carries the run's warnings (coverage grades
  retired 2026-08-19); the existing signals page displays it as-is.
- ``log_tier_report``: submits via ``DecisionSignalService`` (injected in
  tests). Logging must never crash an analysis run — failures come back
  as a structured ``SignalLogResult`` with the reason, not an exception.

Boundary note: this imports DSA services as a client, same as Tier1Stage
consumes DSA analysis results. It does not modify the decision path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .providers.base import Market
from .schema import (
    TRADING_DAYS_PER_WEEK,
    Direction,
    TierReport,
    coerce_price,
)

logger = logging.getLogger(__name__)

SOURCE_TYPE = "agent"
SOURCE_AGENT = "tiered_analysis"
TRIGGER_SOURCE = "tiered_analysis"
GENERATOR = "tiered_analysis_v1"
#: data_quality_summary warning cap — keep the stored JSON bounded.
MAX_LOGGED_WARNINGS = 20


def score_band(final_score: Any) -> Optional[str]:
    """Score group for the forward-test breakdown (owner decision
    2026-08-08): the debate's sell (<4) and buy (>6) verdict regions are
    each split in half so "does an 8-10 beat a 6-8?" is answerable; the
    4-6 hold region stays whole as the control group. Keep the 4/6 edges
    aligned with debate.SELL_BELOW / debate.HOLD_MAX."""
    number = coerce_price(final_score)
    if number is None or not 0.0 <= number <= 10.0:
        return None
    if number < 2.0:
        return "0-2"
    if number < 4.0:
        return "2-4"
    if number <= 6.0:
        return "4-6"
    if number <= 8.0:
        return "6-8"
    return "8-10"


def debate_final_score(report: TierReport) -> Optional[float]:
    """The deep analysis's 0-10 weighted vote score, when the run has one."""
    detail = report.debate_detail or {}
    verdict = detail.get("verdict") or {}
    return coerce_price(verdict.get("final_score"))


@dataclass(frozen=True)
class SignalLogResult:
    """Outcome of one logging attempt — never an exception."""

    logged: bool
    reason: Optional[str] = None
    signal_id: Optional[int] = None
    created: Optional[bool] = None


def coerce_confidence(value: Any) -> Optional[float]:
    """Normalize TierReport's textual confidence to the service's 0-1 scale.

    Accepts fractions ("0.72"), percent-scale numbers (83 -> 0.83), and
    returns None for text labels or out-of-range values — a missing
    confidence is honest; a fabricated one is not.
    """
    number = coerce_price(value)
    if number is None:
        return None
    if 0.0 <= number <= 1.0:
        return number
    if 1.0 < number <= 100.0:
        return number / 100.0
    return None


def build_signal_payload(
    report: TierReport, trace_id: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Map a TierReport to a DecisionSignalService payload.

    Returns ``(payload, None)`` or ``(None, skip_reason)`` — reports with
    no usable direction or market are skipped, not force-fitted.
    """
    if report.direction == Direction.UNKNOWN:
        return None, "direction is unknown — nothing to log"
    if report.market == Market.UNKNOWN:
        return None, "market is unknown — the signal service requires one"

    entries = [
        level
        for level in (report.levels.entry, report.levels.secondary_entry)
        if level is not None
    ]

    payload: Dict[str, Any] = {
        "stock_code": report.symbol,
        "market": report.market.value,
        "source_type": SOURCE_TYPE,
        "source_agent": SOURCE_AGENT,
        "trace_id": trace_id,
        "trigger_source": TRIGGER_SOURCE,
        "action": report.direction.value,
        "confidence": coerce_confidence(report.confidence),
        "score": report.score,
        "entry_low": min(entries) if entries else None,
        "entry_high": max(entries) if entries else None,
        "stop_loss": report.levels.stop_loss,
        "target_price": report.levels.take_profit,
        "reason": report.narrative,
        # Coverage grades are retired (2026-08-19): data problems live
        # in the warnings themselves; the outcome page's quality label
        # reads "unknown" without a stored level, which is honest.
        "data_quality_summary": {
            "warnings": list(report.warnings[:MAX_LOGGED_WARNINGS]),
        },
        "evidence": {"dimensions": _evidence_entries(report)},
        "metadata": {
            "generator": GENERATOR,
            "tier": report.tier,
            "sizing_empty": report.sizing.is_empty,
        },
    }
    # Plan provenance (2026-08-11): the exact final plan plus the
    # formula plan it started from, so the forward test can grade the
    # AI's plan adjustments against the untouched formula as a paired
    # control on the very same run.
    payload["metadata"]["plan"] = {
        "entry": report.levels.entry,
        "stop_loss": report.levels.stop_loss,
        "take_profit": report.levels.take_profit,
    }
    base_plan, plan_adjusted = plan_provenance(report)
    if base_plan is not None:
        payload["metadata"]["base_plan"] = base_plan
        payload["metadata"]["plan_adjusted"] = plan_adjusted
    # Max hold time (2026-08-08): the grading window travels WITH the
    # signal so the forward test scores each call at the horizon the AI
    # was actually judged against.
    if report.hold_weeks is not None:
        horizon_days = report.hold_weeks * TRADING_DAYS_PER_WEEK
        payload["metadata"]["hold_weeks"] = report.hold_weeks
        payload["metadata"]["horizon_days"] = horizon_days
        # The signal's own horizon column: the outcome job grades a
        # signal at exactly this window when set, so the forward test
        # scores the call at the hold time the AI was judged against.
        payload["horizon"] = f"{horizon_days}d"
    # Score calibration (2026-08-08): the debate's weighted vote score —
    # the number the score-band stats group by. The top-level "score"
    # column keeps its historical tier-1 meaning untouched.
    final_score = debate_final_score(report)
    if final_score is not None:
        payload["metadata"]["final_score"] = final_score
        payload["metadata"]["score_band"] = score_band(final_score)
    if not report.sizing.is_empty:
        # Slice 6: the ledger records the position the user actually saw,
        # so v3's backtest can grade it. shares == 0 is meaningful ("the
        # risk verdict said don't open"), not an omission.
        payload["metadata"]["sizing"] = {
            "capital": report.sizing.capital,
            "risk_fraction": report.sizing.risk_fraction,
            "shares": report.sizing.shares,
        }
    return payload, None


def plan_provenance(
    report: TierReport,
) -> Tuple[Optional[Dict[str, Optional[float]]], bool]:
    """The formula plan from the levels audit trail, plus whether the
    final plan differs from it (i.e. an AI adjustment survived).

    Single source of truth for "was this plan AI-adjusted?" — the
    signal metadata and the forward-test console both read it, so they
    can never disagree. Returns ``(None, False)`` when the report
    carries no audit trail (older callers) — absence is honest, a
    guessed base is not.
    """
    detail = report.levels_detail or {}
    levels = detail.get("levels") or {}
    base_plan: Dict[str, Optional[float]] = {}
    adjusted = False
    for key in ("entry", "stop_loss", "take_profit"):
        info = levels.get(key) or {}
        base = coerce_price(info.get("base"))
        final = coerce_price(info.get("final"))
        base_plan[key] = base
        if base is not None and final is not None and base != final:
            adjusted = True
    if all(value is None for value in base_plan.values()):
        return None, False
    return base_plan, adjusted


def _evidence_entries(report: TierReport) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for dim in report.dimensions:
        entry: Dict[str, Any] = {
            "dimension": dim.dimension,
            "kind": dim.kind.value,
            "is_actionable": dim.is_actionable,
        }
        if dim.payload:
            entry["payload"] = dim.payload
        if dim.narrative:
            entry["narrative"] = dim.narrative
        if dim.warnings:
            entry["warnings"] = list(dim.warnings)
        if dim.citations:
            entry["citations"] = [
                citation.url or citation.source_name
                for citation in dim.citations
            ]
        entries.append(entry)
    return entries


def _default_service():
    from src.services.decision_signal_service import DecisionSignalService

    return DecisionSignalService()


def log_tier_report(
    report: TierReport,
    service: Any = None,
    trace_id: Optional[str] = None,
) -> SignalLogResult:
    """Persist one tier report as a decision signal; never raises."""
    payload, skip_reason = build_signal_payload(report, trace_id=trace_id)
    if payload is None:
        return SignalLogResult(logged=False, reason=skip_reason)

    try:
        if service is None:
            service = _default_service()
        response = service.create_signal(payload) or {}
    except Exception as exc:
        logger.warning(
            "tiered_analysis signal log failed for %s: %s", report.symbol, exc
        )
        return SignalLogResult(
            logged=False, reason=f"signal service failed: {exc}"
        )

    item = response.get("item") or {}
    return SignalLogResult(
        logged=True,
        signal_id=item.get("id"),
        created=bool(response.get("created")),
    )
