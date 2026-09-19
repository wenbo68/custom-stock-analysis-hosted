# -*- coding: utf-8 -*-
"""Persistent history of tiered-analysis runs (tiered_runs table).

The web tiered page shows these as a clickable run list: a run starts as
``queued`` (waiting for a free slot in the global run queue,
src/tiered_analysis/run_queue.py), becomes ``running``, then flips to
``done`` (with the full serialized report) or ``failed`` (with the
error), and stays in the list as history across page navigation and
server restarts. Queued rows outlive the process: the queue resumes them
at startup, whereas running rows die with their thread and are failed.

Run reuse (2026-09-17): a run may borrow another run's outlook instead
of paying for its own (src/tiered_analysis/reuse.py). ``find_reusable_run``
picks the source; a requester whose source is still in flight sits as
``waiting`` (with ``source_task_id`` set) until the source settles, and
is then finished from it or put back in the queue. ``waiting`` is a
storage status only: to its owner such a run reads exactly as the
source reads to the source's owner — ``running``, or ``queued`` with
the source's place in line (owner decision 2026-09-17).

Storage is the product's existing sqlite database via DatabaseManager —
one small table, no separate infrastructure.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple

from .llm_support import TRANSCRIPT_MAX_AGE_DAYS

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 50

#: The error stored on runs that were still "running" when the server
#: came back up: the background thread died with the old process, so the
#: run can never finish. Worded for the history list.
STALE_RUN_ERROR = "server restarted while this run was in progress"

#: Run statuses. A run is "active" (queued, running or waiting on
#: another run) until it settles as done or failed — the duplicate check
#: only looks at active runs.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_WAITING = "waiting"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_WAITING)
#: Statuses a run may be reused from, in preference order: a finished
#: run is instant; a running one finishes soonest; a queued one last.
REUSABLE_STATUSES = (STATUS_DONE, STATUS_RUNNING, STATUS_QUEUED)

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
    bar_date: Optional[str] = None,
    model: Optional[str] = None,
    source_task_id: Optional[str] = None,
) -> None:
    """``inputs`` are the run's effective settings (tier, capital,
    risk_fraction, reward_risk, hold_weeks) — recorded at creation so the
    history row shows them while the run is still in flight — plus, under
    ``sizing_overrides``, the raw per-run sizing the caller sent, which
    the queue hands to the engine when the run starts. ``owner_id`` is
    the signed-in user the run belongs to. The web endpoint creates runs
    ``queued``; the default keeps direct callers (tests, scripts) that
    start their own thread on ``running``. ``bar_date`` (ISO) is the
    trading day the run analyses and ``model`` the owner's main model —
    the run-reuse matching keys; ``source_task_id`` names the run this
    one borrows its outlook from."""
    from src.storage import TieredRunRecord

    with _session() as session:
        session.add(TieredRunRecord(
            task_id=task_id,
            stock_code=stock_code,
            status=status,
            inputs_json=json.dumps(inputs) if inputs else None,
            owner_user_id=owner_id,
            bar_date=bar_date,
            model=model,
            source_task_id=source_task_id,
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


def set_model(task_id: str, model: Optional[str]) -> None:
    """Record the main model a run actually uses (a queued run reads its
    owner's settings only when it starts; a reused run ends up with the
    source's model — the one that produced the outlook it shows)."""
    _update_run(task_id, model=model)


def attach_to_source(task_id: str, source_task_id: str) -> None:
    """Park a run as ``waiting``: it will be finished from
    ``source_task_id`` once that run settles."""
    _update_run(task_id, status=STATUS_WAITING, source_task_id=source_task_id)


def requeue(task_id: str) -> None:
    """A waiting run whose source cannot serve it goes back in the line
    as an ordinary queued run."""
    _update_run(task_id, status=STATUS_QUEUED, source_task_id=None)


def list_waiters(source_task_id: str) -> List[Dict[str, Any]]:
    """The runs waiting on ``source_task_id``, oldest first, each as
    {task_id, stock_code, owner_id, inputs, model}."""
    from src.storage import TieredRunRecord

    with _session() as session:
        rows = (
            session.query(TieredRunRecord)
            .filter_by(status=STATUS_WAITING, source_task_id=source_task_id)
            .order_by(TieredRunRecord.created_at.asc(), TieredRunRecord.id.asc())
            .all()
        )
        return [_run_for_reuse(row) for row in rows]


def run_for_reuse(task_id: str) -> Optional[Dict[str, Any]]:
    """A run as the reuse machinery sees it — status, model, inputs, the
    parsed result (None unless done and readable) — regardless of
    owner. Internal: never served to a client."""
    from src.storage import TieredRunRecord

    with _session() as session:
        row = (
            session.query(TieredRunRecord)
            .filter_by(task_id=task_id)
            .one_or_none()
        )
        return _run_for_reuse(row) if row is not None else None


def _run_for_reuse(row: Any) -> Dict[str, Any]:
    return {
        "task_id": row.task_id,
        "stock_code": row.stock_code,
        "status": row.status,
        "owner_id": row.owner_user_id,
        "model": row.model,
        "bar_date": row.bar_date,
        "source_task_id": row.source_task_id,
        "inputs": _inputs_of(row),
        "result": _parsed_result(row),
    }


def _parsed_result(row: Any) -> Optional[Dict[str, Any]]:
    if row.status != STATUS_DONE or not row.result_json:
        return None
    try:
        result = json.loads(row.result_json)
    except ValueError:
        return None
    return result if isinstance(result, dict) else None


def find_reusable_run(
    stock_code: str,
    bar_date: Optional[str],
    hold_weeks: int,
    tier: int,
    model: Optional[str],
) -> Optional[Dict[str, Any]]:
    """The best run (anyone's) whose outlook may stand in for a new run
    of ``stock_code`` on trading day ``bar_date`` with max hold
    ``hold_weeks``, tier ``tier`` and main model ``model``. Same ticker
    (case-insensitive), day and hold weeks; the same or a deeper tier;
    the same or a stronger model of the same provider
    (src.user_settings.covers_model). Finished runs come first (deeper
    tier, then stronger model, then newest), then running ones and
    queued ones, oldest first. Runs that are themselves waiting on
    another run are skipped — attach to the original instead. A finished
    run counts only when its stored result is fit to reuse. Returns
    {task_id, status, model, tier} or None."""
    from sqlalchemy import func

    from src.storage import TieredRunRecord
    from src.user_settings import covers_model, model_rank

    from .reuse import is_reusable_result

    if not bar_date:
        return None
    with _session() as session:
        rows = (
            session.query(TieredRunRecord)
            .filter(func.upper(TieredRunRecord.stock_code) == stock_code.strip().upper())
            .filter(TieredRunRecord.bar_date == bar_date)
            .filter(TieredRunRecord.status.in_(REUSABLE_STATUSES))
            .filter(TieredRunRecord.source_task_id.is_(None))
            .order_by(TieredRunRecord.created_at.asc(), TieredRunRecord.id.asc())
            .all()
        )
        candidates = []
        for row in rows:
            inputs = _inputs_of(row)
            if inputs.get("hold_weeks") != hold_weeks:
                continue
            row_tier = inputs.get("tier")
            if not isinstance(row_tier, int) or row_tier < tier:
                continue
            if not covers_model(row.model, model):
                continue
            if row.status == STATUS_DONE and not is_reusable_result(_parsed_result(row)):
                continue
            candidates.append({
                "task_id": row.task_id,
                "status": row.status,
                "model": row.model,
                "tier": row_tier,
                "_order": (
                    REUSABLE_STATUSES.index(row.status),
                    -row_tier if row.status == STATUS_DONE else 0,
                    model_rank(row.model) if row.status == STATUS_DONE else 0,
                    -(row.id or 0) if row.status == STATUS_DONE else (row.id or 0),
                ),
            })
    if not candidates:
        return None
    best = min(candidates, key=lambda c: c["_order"])
    return {key: value for key, value in best.items() if key != "_order"}


def requeue_orphaned_waiters() -> int:
    """Startup housekeeping: a waiting run whose source is no longer in
    flight (it finished or failed while nobody was there to settle the
    waiters, or vanished) goes back in the queue. Returns the count."""
    from src.storage import TieredRunRecord

    with _session() as session:
        waiting = (
            session.query(TieredRunRecord)
            .filter_by(status=STATUS_WAITING)
            .all()
        )
        changed = 0
        for row in waiting:
            source = (
                session.query(TieredRunRecord)
                .filter_by(task_id=row.source_task_id)
                .one_or_none()
                if row.source_task_id
                else None
            )
            if source is not None and source.status in (STATUS_QUEUED, STATUS_RUNNING):
                continue
            row.status = STATUS_QUEUED
            row.source_task_id = None
            changed += 1
        session.commit()
        return changed


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
    """The owner's queued, running or waiting run for the same ticker
    with the same effective inputs (``INPUT_KEYS``), as {task_id,
    status} (the status as shown to the owner), or None. Ticker
    comparison ignores case. A finished or failed run is never a
    duplicate — re-running yesterday's analysis is legitimate."""
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
                status, _ = _shown_status(row, _source_statuses(session, [row]), {})
                return {"task_id": row.task_id, "status": status}
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


def _transcript_query(session: Any, task_id: str, exclude_stages: Collection[str]):
    from src.storage import TieredRunTranscriptRecord

    query = session.query(TieredRunTranscriptRecord).filter_by(task_id=task_id)
    if exclude_stages:
        query = query.filter(
            TieredRunTranscriptRecord.stage.notin_(list(exclude_stages)))
    return query


def count_transcript(task_id: str, exclude_stages: Collection[str] = ()) -> int:
    """How many transcript rows the run holds, leaving out the given
    stages."""
    with _session() as session:
        return int(_transcript_query(session, task_id, exclude_stages).count())


def list_transcript(
    task_id: str, exclude_stages: Collection[str] = ()
) -> List[Dict[str, Any]]:
    """The run's LLM exchanges in call order (empty for unknown runs and
    runs that made no LLM call), leaving out the given stages."""
    from src.storage import TieredRunTranscriptRecord

    with _session() as session:
        rows = (
            _transcript_query(session, task_id, exclude_stages)
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


PAID_BY_YOU = "you"
PAID_BY_ANOTHER_USER = "another_user"


def transcript_for_run(task_id: str) -> List[Dict[str, Any]]:
    """The LLM exchanges a run's owner is concerned with, each marked
    ``paid_by`` (``you`` / ``another_user``) and numbered as one
    sequence. A run that did its own analysis shows its own rows. A
    reused run shows the shared rows of its source first — the source's
    transcript minus the personal stages the requester ran again for
    itself (reuse.PERSONAL_STAGES) — then its own; the shared rows are
    ``another_user``'s unless the source is the owner's own run. The
    source is never named. Owner checks are the caller's job."""
    from src.storage import TieredRunRecord

    from .reuse import PERSONAL_STAGES

    with _session() as session:
        row = session.query(TieredRunRecord).filter_by(task_id=task_id).one_or_none()
        if row is None:
            return []
        owner_id, source_task_id = row.owner_user_id, row.source_task_id
        source_owner_id = None
        if source_task_id:
            source = (
                session.query(TieredRunRecord)
                .filter_by(task_id=source_task_id)
                .one_or_none()
            )
            source_owner_id = source.owner_user_id if source is not None else None
    shared: List[Dict[str, Any]] = []
    if source_task_id:
        paid_by = PAID_BY_YOU if source_owner_id == owner_id else PAID_BY_ANOTHER_USER
        shared = [
            {**entry, "paid_by": paid_by}
            for entry in list_transcript(source_task_id, exclude_stages=PERSONAL_STAGES)
        ]
    own = [{**entry, "paid_by": PAID_BY_YOU} for entry in list_transcript(task_id)]
    return [
        {**entry, "seq": seq}
        for seq, entry in enumerate(shared + own, start=1)
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
    from src.user_settings import model_label

    return {
        "task_id": row.task_id,
        "stock_code": row.stock_code,
        "status": row.status,
        "error": row.error,
        # The main model behind the outlook (the source's, on a reused
        # run) and whether the outlook was borrowed from another run.
        "model": row.model,
        "model_label": model_label(row.model),
        "reused": row.source_task_id is not None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _result_digest(row: Any) -> Dict[str, Any]:
    """The report facts the run list shows per row — final direction,
    computed share count, and the tier the run went to — without shipping
    the full report. ``shares`` mirrors the report card: 0 when sizing ran
    but bought nothing, None (shown as a dash) when the run has no sizing
    block at all. ``tier`` is the requested depth.
    ``capital``/``risk_fraction`` are the sizing inputs the
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
    digest["outlook"] = result.get("outlook")
    sizing = result.get("sizing")
    if isinstance(sizing, dict):
        shares = sizing.get("shares")
        digest["shares"] = shares if shares is not None else 0
    if isinstance(result.get("depth"), int):
        digest["tier"] = result["depth"]
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


def _source_statuses(session: Any, rows: Sequence[Any]) -> Dict[str, str]:
    """source task_id -> status, for the waiting rows among ``rows``."""
    from src.storage import TieredRunRecord

    ids = {
        row.source_task_id for row in rows
        if row.status == STATUS_WAITING and row.source_task_id
    }
    if not ids:
        return {}
    pairs = (
        session.query(TieredRunRecord.task_id, TieredRunRecord.status)
        .filter(TieredRunRecord.task_id.in_(list(ids)))
        .all()
    )
    return {task_id: status for task_id, status in pairs}


def _shown_status(
    row: Any, sources: Dict[str, str], ahead: Dict[str, int]
) -> Tuple[str, Optional[int]]:
    """(status, queue_ahead) as the row's owner sees it. A waiting run
    shows as its source shows to the source's owner: ``queued`` with
    the source's place in line, else ``running`` (the source is running,
    or has just settled and this run is being finished from it)."""
    if row.status == STATUS_QUEUED:
        return STATUS_QUEUED, ahead.get(row.task_id)
    if row.status != STATUS_WAITING:
        return row.status, None
    if sources.get(row.source_task_id) == STATUS_QUEUED:
        return STATUS_QUEUED, ahead.get(row.source_task_id)
    return STATUS_RUNNING, None


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
            if any(row.status in (STATUS_QUEUED, STATUS_WAITING) for row in rows)
            else {}
        )
        sources = _source_statuses(session, rows)
        summaries = []
        for row in rows:
            status, queue_ahead = _shown_status(row, sources, ahead)
            summaries.append({
                **_row_summary(row),
                **_result_digest(row),
                "status": status,
                "queue_ahead": queue_ahead,
            })
        return summaries


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
        ahead = (
            _queue_ahead(session)
            if row.status in (STATUS_QUEUED, STATUS_WAITING)
            else {}
        )
        summary["status"], summary["queue_ahead"] = _shown_status(
            row, _source_statuses(session, [row]), ahead
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
