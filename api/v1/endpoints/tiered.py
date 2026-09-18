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
``MAX_CONCURRENT_RUNS`` slots is free. An exact duplicate of the
caller's own unfinished run (same ticker and inputs) is refused with a
409 naming that run, so a double click never pays twice.

Run reuse (2026-09-17): when another run — anyone's — of the same ticker
on the same trading day with the same max hold time, the same or a
deeper tier and the same or a stronger model of the same provider
exists, the new run borrows its outlook instead of paying for its own
(src/tiered_analysis/reuse.py). A finished source finishes the new run
within seconds (only the personal trade-plan stages run); a source
still in flight parks the new run as ``waiting`` until the source
settles, then finishes it the same way — or, if the source failed or
changed in a way that disqualifies it, puts the run back in the queue.
To its owner a waiting run reads as the source reads to the source's
owner (running, or queued with the source's place in line).
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
from src.tiered_analysis.reuse import ReuseUnavailable, reuse_kit
from src.tiered_analysis.run_context import RunSettings
from src.tiered_analysis.run_queue import QueuedRun, RunQueue
from src.user_settings import (
    EncryptionNotConfigured,
    covers_model,
    model_label,
    run_settings_for,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_analysis(stock_code: str, depth: int = 1,
                  sizing_overrides: Optional[Dict[str, float]] = None,
                  hold_weeks: int = 2,
                  transcript: Optional[LlmTranscript] = None,
                  settings: Optional[RunSettings] = None,
                  **stand_ins: Any):
    """Indirection so tests can patch the multi-minute production run.
    ``stand_ins`` are a reused run's ``providers`` / ``quick_judge`` /
    ``tier2_stage`` (src/tiered_analysis/reuse.py); absent on a fresh run."""
    from src.tiered_analysis.integration import run_tiered_analysis

    return run_tiered_analysis(
        stock_code, depth=depth, sizing_overrides=sizing_overrides,
        hold_weeks=hold_weeks, transcript=transcript, settings=settings,
        **stand_ins,
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
        "stop_loss": levels.stop_loss,
        "take_profit": levels.take_profit,
    }


def _serialize_tier_section(report: Any) -> Optional[Dict[str, Any]]:
    """Tier 2 section: outlook + audit trail, no dimension duplication."""
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
        # The quick judge's 0-10 outlook (depth 1); None at depth 2, whose
        # judge detail sits under ``tier2``. Run reuse rebuilds a quick
        # outlook from it.
        "debate_detail": report.debate_detail,
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
    """The queue's runner: execute one run and record its outcome, then
    finish (or requeue) every run waiting on this one. Never raises — a
    failure lands on the run row."""
    try:
        settings = _settings_for_queued_run(run.owner_id)
        history.set_model(run.task_id, settings.llm_model)
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
    _settle_waiters(run.task_id)


#: The one queue this process runs; app startup calls ``resume`` on it.
run_queue = RunQueue(_execute_run)

#: Serializes the duplicate/reuse check with the row insert so two clicks
#: that arrive together cannot both pass the check, and so a source
#: cannot settle its waiters between a requester finding it and the
#: requester's row being written.
_submit_lock = threading.Lock()


def _source_serves(source: Dict[str, Any], requester: Dict[str, Any]) -> bool:
    """Whether a settled source still qualifies for a waiting requester:
    finished with a reusable result, at the requester's tier or deeper,
    with a model that covers the requester's (the source's owner may
    have changed models while it waited in the queue)."""
    from src.tiered_analysis.reuse import is_reusable_result

    if source["status"] != history.STATUS_DONE:
        return False
    if not is_reusable_result(source["result"]):
        return False
    source_tier = source["inputs"].get("tier")
    wanted_tier = requester["inputs"].get("tier") or 1
    if not isinstance(source_tier, int) or source_tier < int(wanted_tier):
        return False
    return covers_model(source["model"], requester["model"])


def _finish_from_source(requester: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Finish ``requester`` (a row already marked running) by running the
    pipeline with the source's data and outlook standing in for the
    shared stages. Only the requester's personal stages run — the plan
    levels, the plan review, sizing, the action — with their own key.
    A source that turns out unfit goes back in the queue as a fresh run;
    any other failure lands on the run row like a normal failure."""
    task_id = requester["task_id"]
    try:
        kit = reuse_kit(source["result"] or {})
    except ReuseUnavailable as exc:
        logger.warning("run %s cannot reuse %s (%s); running afresh",
                       task_id, source["task_id"], exc)
        history.requeue(task_id)
        return
    try:
        settings = _settings_for_queued_run(requester["owner_id"])
        inputs = requester["inputs"]
        outcome = _run_analysis(
            requester["stock_code"],
            depth=kit.depth,
            sizing_overrides=inputs.get("sizing_overrides") or None,
            hold_weeks=int(inputs.get("hold_weeks") or 2),
            transcript=LlmTranscript.for_run(task_id),
            settings=settings,
            providers=kit.providers,
            quick_judge=kit.quick_judge,
            tier2_stage=kit.tier2_stage,
        )
        result = _serialize_outcome(outcome)
        # What the report page tells the user: the outlook came from a
        # shared run at this tier by this model; only the trade plan is
        # theirs. Never who ran the source.
        result["reused"] = {
            "tier": kit.depth,
            "model": source["model"],
            "model_label": model_label(source["model"]),
        }
        history.set_model(task_id, source["model"])
        history.mark_done(task_id, result)
    except Exception as exc:
        logger.error("reused tiered analysis failed for %s: %s",
                     requester["stock_code"], exc, exc_info=True)
        history.mark_failed(task_id, str(exc))


def _reuse_finished_source(task_id: str, source_task_id: str) -> None:
    """Background thread for a run that reuses an already-finished
    source: finish it now, then let the queue fill any slot a requeue
    freed. Never raises."""
    try:
        requester = history.run_for_reuse(task_id)
        source = history.run_for_reuse(source_task_id)
        if requester is None or source is None or not _source_serves(source, requester):
            history.requeue(task_id)
        else:
            _finish_from_source(requester, source)
    except Exception:
        logger.exception("run %s could not be finished from %s", task_id, source_task_id)
        history.requeue(task_id)
    run_queue.dispatch()


def _settle_waiters(source_task_id: str) -> None:
    """After ``source_task_id`` settled: finish every run waiting on it,
    or put back in the queue those it can no longer serve. Runs in the
    source's worker thread (so the waiters' plan reviews take the slot
    the source held); the queue dispatches once they are done."""
    try:
        with _submit_lock:
            waiters = history.list_waiters(source_task_id)
        if not waiters:
            return
        source = history.run_for_reuse(source_task_id)
        for requester in waiters:
            if source is None or not _source_serves(source, requester):
                logger.info("run %s requeued: source %s cannot serve it",
                            requester["task_id"], source_task_id)
                history.requeue(requester["task_id"])
                continue
            history.mark_running(requester["task_id"])
            _finish_from_source(requester, source)
    except Exception:
        logger.exception("settling the runs waiting on %s failed", source_task_id)


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


def _bar_date_for(stock_code: str) -> Optional[str]:
    """The trading day a run started now analyses (the most recent
    completed session in the ticker's market), ISO; None for an unknown
    market — such runs are never matched for reuse."""
    from src.tiered_analysis.run_gate import expected_bar_date, market_for_symbol

    day = expected_bar_date(market_for_symbol(stock_code))
    return day.isoformat() if day is not None else None


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

    The response ``status`` is ``running`` when a slot was free (or the
    run is being finished from an already-finished matching run), else
    ``queued``. A run that will be finished from a matching run still
    in flight reports that run's status — to its owner it looks exactly
    as the source looks to the source's owner.
    """
    from src.tiered_analysis.run_gate import clock_gate

    # Refuse up front when the caller has no LLM key; the run itself
    # re-reads the settings when it leaves the queue. The model on file
    # now is what the reuse matching compares.
    settings = _settings_for_run(user)
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
    bar_date = _bar_date_for(request.stock_code)

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
        source = history.find_reusable_run(
            request.stock_code, bar_date, request.hold_weeks,
            request.depth, settings.llm_model,
        )
        task_id = uuid.uuid4().hex
        if source is None:
            history.create_run(task_id, request.stock_code, inputs=inputs,
                               owner_id=user["id"],
                               status=history.STATUS_QUEUED,
                               bar_date=bar_date, model=settings.llm_model)
        elif source["status"] == history.STATUS_DONE:
            history.create_run(task_id, request.stock_code, inputs=inputs,
                               owner_id=user["id"],
                               status=history.STATUS_RUNNING,
                               bar_date=bar_date, model=settings.llm_model,
                               source_task_id=source["task_id"])
        else:
            history.create_run(task_id, request.stock_code, inputs=inputs,
                               owner_id=user["id"],
                               status=history.STATUS_WAITING,
                               bar_date=bar_date, model=settings.llm_model,
                               source_task_id=source["task_id"])
    if source is None:
        status = run_queue.submit(task_id)
    elif source["status"] == history.STATUS_DONE:
        logger.info("tiered run %s reuses finished run %s for %s",
                    task_id, source["task_id"], request.stock_code)
        threading.Thread(
            target=_reuse_finished_source, args=(task_id, source["task_id"]),
            name=f"tiered-reuse-{request.stock_code}", daemon=True,
        ).start()
        status = history.STATUS_RUNNING
    else:
        logger.info("tiered run %s waits on %s run %s for %s",
                    task_id, source["status"], source["task_id"], request.stock_code)
        status = source["status"]
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
