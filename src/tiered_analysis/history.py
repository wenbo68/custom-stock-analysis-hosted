# -*- coding: utf-8 -*-
"""Persistent history of tiered-analysis runs (tiered_runs table).

The web tiered page shows these as a clickable run list: a run starts as
``running``, flips to ``done`` (with the full serialized report) or
``failed`` (with the error), and stays in the list as history across page
navigation and server restarts.

Storage is the product's existing sqlite database via DatabaseManager —
one small table, no separate infrastructure.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 50


def _session():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


def create_run(
    task_id: str,
    stock_code: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> None:
    """``inputs`` are the run's effective settings (tier, capital,
    risk_fraction, reward_risk, hold_weeks) — recorded at creation so the
    history row shows them while the run is still in flight."""
    from src.storage import TieredRunRecord

    with _session() as session:
        session.add(TieredRunRecord(
            task_id=task_id,
            stock_code=stock_code,
            status="running",
            inputs_json=json.dumps(inputs) if inputs else None,
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
    _update_run(task_id, status="failed", error=str(error))


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


def _inputs_digest(row: Any) -> Dict[str, Any]:
    """The creation-time inputs (tier/capital/risk_fraction/reward_risk/
    hold_weeks), or {} when absent/unreadable — old rows never break the
    list."""
    raw = getattr(row, "inputs_json", None)
    if not raw:
        return {}
    try:
        inputs = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(inputs, dict):
        return {}
    return {
        key: inputs[key]
        for key in ("tier", "capital", "risk_fraction", "reward_risk", "hold_weeks")
        if inputs.get(key) is not None
    }


def list_runs(limit: int = DEFAULT_LIST_LIMIT) -> List[Dict[str, Any]]:
    """Newest-first run summaries (no result payloads — keep the list light)."""
    from src.storage import TieredRunRecord

    safe_limit = max(1, min(int(limit), 200))
    with _session() as session:
        rows = (
            session.query(TieredRunRecord)
            .order_by(TieredRunRecord.created_at.desc(), TieredRunRecord.id.desc())
            .limit(safe_limit)
            .all()
        )
        return [{**_row_summary(row), **_result_digest(row)} for row in rows]


def get_run(task_id: str) -> Optional[Dict[str, Any]]:
    """One run with its full result (None result if still running/failed)."""
    from src.storage import TieredRunRecord

    with _session() as session:
        row = (
            session.query(TieredRunRecord)
            .filter_by(task_id=task_id)
            .one_or_none()
        )
        if row is None:
            return None
        summary = _row_summary(row)
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
