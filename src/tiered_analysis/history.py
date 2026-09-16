# -*- coding: utf-8 -*-
"""Persistent history of tiered-analysis runs (tiered_runs table).

The web tiered page shows these as a clickable run list: a run starts as
``queued`` (waiting for a free slot in the global run queue,
src/tiered_analysis/run_queue.py), becomes ``running``, then flips to
``done`` (with the full serialized report) or ``failed`` (with the
error), and stays in the list as history across page navigation and
server restarts. Queued rows outlive the process: the queue resumes them
at startup, whereas running rows die with their thread and are failed.

Storage is the product's existing sqlite database via DatabaseManager —
one small table, no separate infrastructure.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Collection, Dict, List, Optional

from .llm_support import TRANSCRIPT_MAX_AGE_DAYS

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 50

#: The error stored on runs that were still "running" when the server
#: came back up: the background thread died with the old process, so the
#: run can never finish. Worded for the history list.
STALE_RUN_ERROR = "server restarted while this run was in progress"

#: Run statuses. A run is "active" (queued or running) until it settles
#: as done or failed — the duplicate check only looks at active runs.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

#: The creation-time inputs that make two runs "the same run" (and that
#: the history row shows while a run is in flight).
INPUT_KEYS = ("tier", "capital", "risk_fraction", "reward_risk", "hold_weeks")


def _session():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


def create_run(
    task_id: str,
    stock_code: str,
    inputs: Optional[Dict[str, Any]] = None,
    owner_id: Optional[int] = None,
    status: str = STATUS_RUNNING,
) -> None:
    """``inputs`` are the run's effective settings (tier, capital,
    risk_fraction, reward_risk, hold_weeks) — recorded at creation so the
    history row shows them while the run is still in flight — plus, under
    ``sizing_overrides``, the raw per-run sizing the caller sent, which
    the queue hands to the engine when the run starts. ``owner_id`` is
    the signed-in user the run belongs to. The web endpoint creates runs
    ``queued``; the default keeps direct callers (tests, scripts) that
    start their own thread on ``running``."""
    from src.storage import TieredRunRecord

    with _session() as session:
        session.add(TieredRunRecord(
            task_id=task_id,
            stock_code=stock_code,
            status=status,
            inputs_json=json.dumps(inputs) if inputs else None,
            owner_user_id=owner_id,
        ))
        session.commit()


def _update_run(task_id: str, **fields: Any) -> None:
    from src.storage import TieredRunRecord

    with _session() as session:
        row = (
            session.query(TieredRunRecord)
            .filter_by(task_id=task_id)
            .one_or_none()
        )
        if row is None:
            logger.warning("tiered run %s vanished before update", task_id)
            return
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def mark_done(task_id: str, result: Dict[str, Any]) -> None:
    _update_run(task_id, status="done", result_json=json.dumps(result))


def mark_failed(task_id: str, error: str) -> None:
    _update_run(task_id, status=STATUS_FAILED, error=str(error))


def mark_running(task_id: str) -> None:
    """A queued run took a slot (the queue calls this as it starts the
    thread)."""
    _update_run(task_id, status=STATUS_RUNNING)


def next_queued_run(exclude: Collection[str] = ()) -> Optional[Dict[str, Any]]:
    """The oldest queued run not in ``exclude`` (task_id, stock_code,
    owner_id, inputs), or None when nothing is waiting. First come,
    first served: ordered by creation time, then id."""
    from src.storage import TieredRunRecord

    with _session() as session:
        query = (
            session.query(TieredRunRecord)
            .filter_by(status=STATUS_QUEUED)
            .order_by(TieredRunRecord.created_at.asc(), TieredRunRecord.id.asc())
        )
        skipped = [str(task_id) for task_id in exclude]
        if skipped:
            query = query.filter(TieredRunRecord.task_id.notin_(skipped))
        row = query.first()
        if row is None:
            return None
        return {
            "task_id": row.task_id,
            "stock_code": row.stock_code,
            "owner_id": row.owner_user_id,
            "inputs": _inputs_of(row),
        }


def find_active_duplicate(
    owner_id: int, stock_code: str, inputs: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """The owner's queued or running run for the same ticker with the
    same effective inputs (``INPUT_KEYS``), as {task_id, status}, or
    None. Ticker comparison ignores case. A finished or failed run is
    never a duplicate — re-running yesterday's analysis is legitimate."""
    from sqlalchemy import func

    from src.storage import TieredRunRecord

    wanted = _digest_inputs(inputs or {})
    with _session() as session:
        rows = (
            session.query(TieredRunRecord)
            .filter(TieredRunRecord.owner_user_id == int(owner_id))
            .filter(TieredRunRecord.status.in_(ACTIVE_STATUSES))
            .filter(func.upper(TieredRunRecord.stock_code) == stock_code.strip().upper())
            .order_by(TieredRunRecord.created_at.asc(), TieredRunRecord.id.asc())
            .all()
        )
        for row in rows:
            if _inputs_digest(row) == wanted:
                return {"task_id": row.task_id, "status": row.status}
    return None


def fail_stale_running_runs(error: str = STALE_RUN_ERROR) -> int:
    """Startup housekeeping: every run still marked ``running`` belongs
    to a process that no longer exists (runs execute in-process threads),
    so mark them failed rather than leave a spinner forever. Returns the
    number of rows changed."""
    from src.storage import TieredRunRecord

    with _session() as session:
        changed = (
            session.query(TieredRunRecord)
            .filter_by(status=STATUS_RUNNING)
            .update({"status": STATUS_FAILED, "error": error},
                    synchronize_session=False)
        )
        session.commit()
        return int(changed or 0)


def list_transcript(task_id: str) -> List[Dict[str, Any]]:
    """The run's LLM exchanges in call order (empty for unknown runs and
    runs that made no LLM call)."""
    from src.storage import TieredRunTranscriptRecord

    with _session() as session:
        rows = (
            session.query(TieredRunTranscriptRecord)
            .filter_by(task_id=task_id)
            .order_by(TieredRunTranscriptRecord.seq.asc())
            .all()
        )
        return [
            {
                "seq": row.seq,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "stage": row.stage,
                "model": row.model,
                "temperature": row.temperature,
                "duration_ms": row.duration_ms,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "structured": row.structured,
                "error": row.error,
                "prompt": row.prompt,
                "reply": row.reply,
            }
            for row in rows
        ]


def prune_transcripts(max_age_days: int = TRANSCRIPT_MAX_AGE_DAYS) -> int:
    """Delete transcript rows older than ``max_age_days``; returns the count."""
    from src.storage import TieredRunTranscriptRecord, utc_naive_now

    cutoff = utc_naive_now() - timedelta(days=max_age_days)
    with _session() as session:
        deleted = (
            session.query(TieredRunTranscriptRecord)
            .filter(TieredRunTranscriptRecord.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        session.commit()
        return int(deleted or 0)


def _row_summary(row: Any) -> Dict[str, Any]:
    return {
        "task_id": row.task_id,
        "stock_code": row.stock_code,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _result_digest(row: Any) -> Dict[str, Any]:
    """The report facts the run list shows per row — final direction,
    computed share count, and the tier the run went to — without shipping
    the full report. ``shares`` mirrors the report card: 0 when sizing ran
    but bought nothing, None (shown as a dash) when the run has no sizing
    block at all. ``tier`` is the requested depth; old runs stored before
    depth existed fall back to the deepest tier that reported (v1 runs were
    tier 1 only). ``capital``/``risk_fraction`` are the sizing inputs the
    run used, for the row's capital and risk columns. Anything unreadable
    degrades to None rather than breaking the list."""
    digest: Dict[str, Any] = {
        "direction": None,
        "outlook": None,
        "shares": None,
        "tier": None,
        "capital": None,
        "risk_fraction": None,
        "reward_risk": None,
        "hold_weeks": None,
    }
    # The inputs recorded at creation show while the run is in flight (and
    # stand as fallback on failed runs); a finished report's own values
    # overwrite them below.
    digest.update(_inputs_digest(row))
    if row.status != "done" or not row.result_json:
        return digest
    try:
        result = json.loads(row.result_json)
    except ValueError:
        return digest
    if not isinstance(result, dict):
        return digest
    final = result.get("final")
    direction = final.get("direction") if isinstance(final, dict) else None
    digest["direction"] = direction or result.get("direction")
    # Outlook redesign: new runs store it; old runs map buy/hold/sell.
    legacy_outlook = {"buy": "bullish", "hold": "neutral", "sell": "bearish"}
    digest["outlook"] = result.get("outlook") or legacy_outlook.get(
        digest["direction"]
    )
    sizing = result.get("sizing")
    if isinstance(sizing, dict):
        shares = sizing.get("shares")
        digest["shares"] = shares if shares is not None else 0
    for tier_source in (
        result.get("depth"),
        final.get("tier") if isinstance(final, dict) else None,
        result.get("tier"),
    ):
        if isinstance(tier_source, int):
            digest["tier"] = tier_source
            break
    if isinstance(sizing, dict) and isinstance(sizing.get("inputs"), dict):
        inputs = sizing["inputs"]
        for key in ("capital", "risk_fraction", "reward_risk"):
            # The report's own values win, but never None-overwrite the
            # inputs recorded at creation.
            if inputs.get(key) is not None:
                digest[key] = inputs[key]
    if result.get("hold_weeks") is not None:
        digest["hold_weeks"] = result["hold_weeks"]
    return digest


def _inputs_of(row: Any) -> Dict[str, Any]:
    """The row's stored inputs as a dict, {} when absent/unreadable — old
    rows never break the list."""
    raw = getattr(row, "inputs_json", None)
    if not raw:
        return {}
    try:
        inputs = json.loads(raw)
    except ValueError:
        return {}
    return inputs if isinstance(inputs, dict) else {}


def _digest_inputs(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Just the ``INPUT_KEYS`` that are set — what the history row shows
    and what the duplicate check compares."""
    return {key: inputs[key] for key in INPUT_KEYS if inputs.get(key) is not None}


def _inputs_digest(row: Any) -> Dict[str, Any]:
    """The creation-time inputs (tier/capital/risk_fraction/reward_risk/
    hold_weeks) of a row."""
    return _digest_inputs(_inputs_of(row))


def _queue_ahead(session: Any) -> Dict[str, int]:
    """task_id -> how many queued runs (anyone's) are ahead of it in the
    line, for the "Queued (2 ahead)" wording."""
    from src.storage import TieredRunRecord

    waiting = (
        session.query(TieredRunRecord.task_id)
        .filter_by(status=STATUS_QUEUED)
        .order_by(TieredRunRecord.created_at.asc(), TieredRunRecord.id.asc())
        .all()
    )
    return {task_id: position for position, (task_id,) in enumerate(waiting)}


def list_runs(
    limit: int = DEFAULT_LIST_LIMIT, owner_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Newest-first run summaries (no result payloads — keep the list
    light). With ``owner_id``, only that user's runs."""
    from src.storage import TieredRunRecord

    safe_limit = max(1, min(int(limit), 200))
    with _session() as session:
        query = session.query(TieredRunRecord)
        if owner_id is not None:
            query = query.filter_by(owner_user_id=int(owner_id))
        rows = (
            query
            .order_by(TieredRunRecord.created_at.desc(), TieredRunRecord.id.desc())
            .limit(safe_limit)
            .all()
        )
        ahead = (
            _queue_ahead(session)
            if any(row.status == STATUS_QUEUED for row in rows)
            else {}
        )
        return [
            {
                **_row_summary(row),
                **_result_digest(row),
                "queue_ahead": ahead.get(row.task_id),
            }
            for row in rows
        ]


def get_run(task_id: str, owner_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """One run with its full result (None result if still running/failed).
    With ``owner_id``, another user's run reads as not found."""
    from src.storage import TieredRunRecord

    with _session() as session:
        row = (
            session.query(TieredRunRecord)
            .filter_by(task_id=task_id)
            .one_or_none()
        )
        if row is None:
            return None
        if owner_id is not None and row.owner_user_id != int(owner_id):
            return None
        summary = _row_summary(row)
        summary["queue_ahead"] = (
            _queue_ahead(session).get(row.task_id)
            if row.status == STATUS_QUEUED
            else None
        )
        summary["result"] = None
        if row.result_json:
            try:
                summary["result"] = json.loads(row.result_json)
            except ValueError:
                summary["error"] = (
                    (summary["error"] or "")
                    + " stored result unreadable (corrupt JSON)"
                ).strip()
        return summary
