# -*- coding: utf-8 -*-
"""Tiered-analysis API: run tier 1 for a symbol from the web UI.

A full run takes minutes (data fetch + LLM), so POST /analyze returns a
task id immediately; the run executes in a background thread. Runs
persist in the tiered_runs table (src/tiered_analysis/history.py), so
GET /runs serves a clickable history that survives page navigation and
server restarts, and GET /runs/{task_id} returns the stored full report.

Public server (2026-09-14): every route here needs a signed-in user. A
run carries that user's own model and keys and belongs to them — the
list and detail routes only ever show the caller's runs.

Run queue (2026-09-15): a new run is stored ``queued`` and the global
queue (src/tiered_analysis/run_queue.py) starts it when one of the
``TIERED_MAX_CONCURRENT_RUNS`` slots is free. An exact duplicate of the
caller's own unfinished run (same ticker and inputs) is refused with a
409 naming that run, so a double click never pays twice.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.auth.session import current_user
from src.tiered_analysis import history
from src.tiered_analysis.llm_support import LlmTranscript
from src.tiered_analysis.run_context import RunSettings
from src.tiered_analysis.run_queue import QueuedRun, RunQueue
from src.user_settings import EncryptionNotConfigured, run_settings_for

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_analysis(stock_code: str, depth: int = 1,
                  sizing_overrides: Optional[Dict[str, float]] = None,
                  hold_weeks: int = 2,
                  transcript: Optional[LlmTranscript] = None,
                  settings: Optional[RunSettings] = None):
    """Indirection so tests can patch the multi-minute production run."""
    from src.tiered_analysis.integration import run_tiered_analysis

    return run_tiered_analysis(
        stock_code, depth=depth, sizing_overrides=sizing_overrides,
        hold_weeks=hold_weeks, transcript=transcript, settings=settings,
    )


class SizingOverride(BaseModel):
    """Per-run sizing inputs; saved settings fill whatever is omitted."""

    capital: Optional[float] = Field(default=None, gt=0)
    risk_fraction: Optional[float] = Field(default=None, gt=0, lt=1)
    #: Target reward-to-risk ratio for the plan (target = entry + R × risk).
    reward_risk: Optional[float] = Field(default=None, gt=1, le=10)


class TieredAnalyzeRequest(BaseModel):
    stock_code: str
    #: 1 = the one-blob judge, 2 = the evidence vote. Tier 3 is retired
    #: (outlook redesign) — depth 3 is a validation error, not a clamp.
    depth: int = Field(default=1, ge=1, le=2)
    sizing: Optional[SizingOverride] = None
    #: Max hold time in weeks (2026-08-08): the horizon the AI judges
    #: against, shown on the report and used as the grading window.
    hold_weeks: int = Field(default=2, ge=1, le=4)
    #: Clock-gate override ("run anyway"): start during the trading day,
    #: analyzing the PREVIOUS completed session's close.
    run_anyway: bool = False

    @field_validator("stock_code")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("stock_code must not be blank")
        return cleaned


def _serialize_levels(levels: Any) -> Dict[str, Any]:
    return {
        "entry": levels.entry,
        "secondary_entry": levels.secondary_entry,
        "stop_loss": levels.stop_loss,
        "take_profit": levels.take_profit,
    }


def _serialize_tier_section(report: Any) -> Optional[Dict[str, Any]]:
    """Tier 2/3 section: verdict + audit trail, no dimension duplication."""
    if report is None:
        return None
    section: Dict[str, Any] = {
        "tier": report.tier,
        "direction": report.direction.value,
        "confidence": report.confidence,
        "score": report.score,
        "levels": _serialize_levels(report.levels),
        "narrative": report.narrative,
        "warnings": list(report.warnings),
    }
    if report.debate_detail is not None:
        section["debate_detail"] = report.debate_detail
    if report.risk_detail is not None:
        section["risk_detail"] = report.risk_detail
    return section


def _serialize_outcome(outcome: Any) -> Dict[str, Any]:
    report = outcome.report
    dimensions = []
    for dim in report.dimensions:
        dimensions.append({
            "dimension": dim.dimension,
            "kind": dim.kind.value,
            "is_actionable": dim.is_actionable,
            "payload": dim.payload,
            # UI formula receipts for derived metrics (technicals v2);
            # None on other dimensions and old runs.
            "formulas": dim.formulas,
            "narrative": dim.narrative,
            "warnings": list(dim.warnings),
            # The same notes keyed by the payload field ("group.key")
            # each is about; None on old stored runs.
            "field_notes": dim.field_notes,
            "citations": [
                {
                    "source_name": c.source_name,
                    "url": c.url,
                    "title": c.title,
                    "snippet": c.snippet,
                }
                for c in (dim.citations or [])
            ],
        })

    state_reports = getattr(outcome.state, "reports", {}) or {}
    final = outcome.final_report or report
    return {
        "symbol": report.symbol,
        "market": report.market.value,
        "tier": report.tier,
        "direction": report.direction.value,
        "score": report.score,
        "confidence": report.confidence,
        "levels": _serialize_levels(report.levels),
        "levels_detail": report.levels_detail,
        "narrative": report.narrative,
        "warnings": list(report.warnings),
        "dimensions": dimensions,
        # v2 slice 6 (additive): depth, deeper-tier sections, sizing, cost.
        "depth": outcome.depth,
        "final": {
            "tier": final.tier,
            "direction": final.direction.value,
            "outlook": outcome.outlook.value,
            "action": outcome.action.value,
            "confidence": final.confidence,
            "levels": _serialize_levels(final.levels),
        },
        "tier2": _serialize_tier_section(state_reports.get(2)),
        "sizing": outcome.sizing,
        "llm_usage": outcome.llm_usage,
        # Outlook redesign (additive): the impersonal judgment, the
        # personal action, and the earnings date (displayed on the
        # fundamentals card; kept here for old consumers).
        "outlook": outcome.outlook.value,
        "action": outcome.action.value,
        "earnings": outcome.earnings.to_detail() if outcome.earnings else None,
        # Retired 2026-07-22 — always None on new runs; old stored runs
        # still carry their card.
        "risk_card": outcome.risk_card,
        # Plan review (additive): structured per-column trade-plan
        # warnings — numbers only, the frontend words them.
        "plan_warnings": outcome.plan_warnings,
        # Max hold time (additive, 2026-08-08): the horizon in weeks the
        # AI was judged against; absent on old stored runs.
        "hold_weeks": getattr(outcome, "hold_weeks", None),
    }


def _settings_for_queued_run(owner_id: Optional[int]) -> RunSettings:
    """The owner's model and keys as they are when the run STARTS (a
    queued run may wait a while; the key on file then is the one that
    pays). Raises when there is no owner or no usable LLM key — the run
    is then marked failed with that reason."""
    if owner_id is None:
        raise RuntimeError("run has no owner")
    settings = run_settings_for(owner_id)
    if not settings.is_llm_configured:
        raise RuntimeError("no LLM model and API key on file for this run's owner")
    return settings


def _execute_run(run: QueuedRun) -> None:
    """The queue's runner: execute one run and record its outcome. Never
    raises — a failure lands on the run row."""
    try:
        settings = _settings_for_queued_run(run.owner_id)
        inputs = run.inputs
        outcome = _run_analysis(
            run.stock_code,
            depth=int(inputs.get("tier") or 1),
            sizing_overrides=inputs.get("sizing_overrides") or None,
            hold_weeks=int(inputs.get("hold_weeks") or 2),
            transcript=LlmTranscript.for_run(run.task_id),
            settings=settings,
        )
        history.mark_done(run.task_id, _serialize_outcome(outcome))
    except Exception as exc:
        logger.error("tiered analysis task failed for %s: %s",
                     run.stock_code, exc, exc_info=True)
        history.mark_failed(run.task_id, str(exc))


#: The one queue this process runs; app startup calls ``resume`` on it.
run_queue = RunQueue(_execute_run)

#: Serializes the duplicate check with the row insert so two clicks that
#: arrive together cannot both pass the check.
_submit_lock = threading.Lock()


def _effective_run_inputs(request: TieredAnalyzeRequest) -> Dict[str, Any]:
    """The settings the run will actually use — request overrides on top
    of saved .env values, with the web-form fallbacks underneath (the
    same resolution run_tiered_analysis performs) — recorded on the run
    row so history shows them while the run is still in flight."""
    from src.tiered_analysis.settings import (
        load_sizing_settings,
        merge_overrides,
        with_fallback_defaults,
    )

    sizing = request.sizing
    settings = with_fallback_defaults(merge_overrides(
        load_sizing_settings(),
        capital=sizing.capital if sizing else None,
        risk_fraction=sizing.risk_fraction if sizing else None,
        reward_risk=sizing.reward_risk if sizing else None,
    ))
    return {
        "tier": request.depth,
        "capital": settings.capital,
        "risk_fraction": settings.risk_fraction,
        "reward_risk": settings.reward_risk,
        "hold_weeks": request.hold_weeks,
    }


def _settings_for_run(user: Dict[str, Any]) -> RunSettings:
    """The caller's model and keys; 400 when they have not set up an LLM
    key yet (the run would only fail minutes later otherwise)."""
    try:
        settings = run_settings_for(user["id"])
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail={
            "error": "encryption_not_configured", "message": str(exc)})
    if not settings.is_llm_configured:
        raise HTTPException(status_code=400, detail={
            "error": "llm_not_configured",
            "message": "pick a model and add its API key in the user block first",
        })
    return settings


@router.post("/analyze", status_code=202)
def start_tiered_analysis(
    request: TieredAnalyzeRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    """Kick off a tiered run in the background; returns a pollable task.

    CLOCK GATE (2026-08-08): runs are rejected (409, code market_open)
    from market open until 30 minutes past the close in the exchange's
    own timezone — the app analyzes completed trading days only.
    ``run_anyway: true`` overrides and analyzes the previous completed
    session instead.

    DUPLICATE (2026-09-15): the caller's own queued/running run with the
    same ticker and inputs is refused (409, code duplicate_run, with
    that run's task_id and status).

    The response ``status`` is ``running`` when a slot was free, else
    ``queued`` — the run starts by itself when one frees up.
    """
    from src.tiered_analysis.run_gate import clock_gate

    # Refuse up front when the caller has no LLM key; the run itself
    # re-reads the settings when it leaves the queue.
    _settings_for_run(user)
    gate = clock_gate(request.stock_code, override=request.run_anyway)
    if gate.blocked:
        logger.info(
            "tiered run blocked by clock gate for %s (%s)",
            request.stock_code, gate.detail,
        )
        # Session bounds ride along (ISO, market-local offset embedded) so
        # the popup can word the hours in market time AND the user's time.
        detail: Dict[str, Any] = {"code": "market_open", "market": gate.market}
        if gate.session_open is not None and gate.session_close is not None:
            detail["session_open"] = gate.session_open.isoformat()
            detail["session_close"] = gate.session_close.isoformat()
        raise HTTPException(status_code=409, detail=detail)

    inputs = _effective_run_inputs(request)
    if request.sizing is not None:
        overrides = request.sizing.model_dump(exclude_none=True)
        if overrides:
            inputs["sizing_overrides"] = overrides

    with _submit_lock:
        duplicate = history.find_active_duplicate(
            user["id"], request.stock_code, inputs)
        if duplicate is not None:
            logger.info("tiered run refused as a duplicate of %s for %s",
                        duplicate["task_id"], request.stock_code)
            raise HTTPException(status_code=409, detail={
                "code": "duplicate_run",
                "task_id": duplicate["task_id"],
                "status": duplicate["status"],
            })
        task_id = uuid.uuid4().hex
        history.create_run(task_id, request.stock_code, inputs=inputs,
                           owner_id=user["id"],
                           status=history.STATUS_QUEUED)
    status = run_queue.submit(task_id)
    return {"task_id": task_id, "stock_code": request.stock_code,
            "depth": request.depth, "status": status}


@router.get("/sizing-defaults")
def get_sizing_defaults() -> Dict[str, Optional[float]]:
    """Saved sizing settings (.env-backed) — capital and risk fraction —
    so the run form can show the values a run would use when the user
    provides none. Both are null when no defaults are configured."""
    from src.tiered_analysis.settings import load_sizing_settings

    settings = load_sizing_settings()
    return {"capital": settings.capital,
            "risk_fraction": settings.risk_fraction,
            "reward_risk": settings.reward_risk}


@router.get("/runs")
def list_tiered_runs(
    limit: int = 50, user: Dict[str, Any] = Depends(current_user)
) -> Dict[str, List[Dict[str, Any]]]:
    """The caller's run history, newest first (summaries only)."""
    return {"items": history.list_runs(limit=limit, owner_id=user["id"])}


@router.get("/runs/{task_id}")
def get_tiered_run(
    task_id: str, user: Dict[str, Any] = Depends(current_user)
) -> Dict[str, Any]:
    """One of the caller's runs with its stored full report."""
    run = history.get_run(task_id, owner_id=user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/runs/{task_id}/transcript")
def get_tiered_run_transcript(
    task_id: str, user: Dict[str, Any] = Depends(current_user)
) -> Dict[str, List[Dict[str, Any]]]:
    """The run's LLM exchanges (prompt, raw reply, error) in call order —
    served separately from the run so the report stays light."""
    if history.get_run(task_id, owner_id=user["id"]) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"items": history.list_transcript(task_id)}
