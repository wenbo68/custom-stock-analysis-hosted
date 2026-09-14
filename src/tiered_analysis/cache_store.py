# -*- coding: utf-8 -*-
"""Key-value store for the fetched-data caches (macro series, the world
news pool, crowd-opinion lists, per-article news judgments).

These caches used to be JSON files under ``data/``. On a public host the
server's disk is wiped on every restart, and losing the world-news cache
several times a day would burn through AlphaVantage's 25-calls-a-day
budget by mid-morning. So the copies live in the database instead.

The store is deliberately dumb: a string key, a JSON value, and the rule
every cache in this package follows — a cache must never fail a run.
``read`` returns None on any trouble (missing, corrupt, database down)
and ``write`` swallows errors and logs them.

``MemoryCacheStore`` is the test double; ``DbCacheStore`` is production.
Providers take a ``cache`` argument and fall back to
``default_cache_store()`` so production wiring needs no plumbing.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import timedelta
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

#: Rows untouched for this long are deleted at startup. The longest-lived
#: cache is the per-symbol news judgment (35-day article window, rewritten
#: on every use), so 60 days keeps everything that can still matter.
CACHE_MAX_AGE_DAYS = 60


class CacheStore(Protocol):
    def read(self, key: str) -> Optional[Any]: ...

    def write(self, key: str, value: Any) -> None: ...


class MemoryCacheStore:
    """In-memory store for tests. Values are kept as JSON text so a test
    can plant a corrupt entry (``store.data[key] = "{not json"``) exactly
    the way a corrupt row would look."""

    def __init__(self) -> None:
        self.data: Dict[str, str] = {}

    def read(self, key: str) -> Optional[Any]:
        raw = self.data.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def write(self, key: str, value: Any) -> None:
        self.data[key] = json.dumps(value, ensure_ascii=False)

    def keys(self) -> List[str]:
        return sorted(self.data)


class DbCacheStore:
    """The ``tiered_cache`` table via the app's DatabaseManager."""

    def read(self, key: str) -> Optional[Any]:
        try:
            from src.storage import DatabaseManager, TieredCacheRecord

            with DatabaseManager.get_instance().get_session() as session:
                row = session.get(TieredCacheRecord, key)
                if row is None or not row.value_json:
                    return None
                return json.loads(row.value_json)
        except Exception as exc:  # corrupt row, database down: cold cache
            logger.warning("cache read failed for %s: %s", key, exc)
            return None

    def write(self, key: str, value: Any) -> None:
        try:
            from src.storage import DatabaseManager, TieredCacheRecord, utc_naive_now

            payload = json.dumps(value, ensure_ascii=False)
            with DatabaseManager.get_instance().get_session() as session:
                session.merge(TieredCacheRecord(
                    key=key, value_json=payload, updated_at=utc_naive_now(),
                ))
                session.commit()
        except Exception as exc:  # a cold cache tomorrow beats a failed run
            logger.warning("cache write failed for %s: %s", key, exc)


_default: Optional[DbCacheStore] = None
_default_lock = threading.Lock()


def default_cache_store() -> CacheStore:
    """The production store (one shared instance; it holds no state)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = DbCacheStore()
        return _default


def prune_cache(max_age_days: int = CACHE_MAX_AGE_DAYS) -> int:
    """Delete rows untouched for ``max_age_days``; returns the count."""
    from src.storage import DatabaseManager, TieredCacheRecord, utc_naive_now

    cutoff = utc_naive_now() - timedelta(days=max_age_days)
    with DatabaseManager.get_instance().get_session() as session:
        deleted = (
            session.query(TieredCacheRecord)
            .filter(TieredCacheRecord.updated_at < cutoff)
            .delete(synchronize_session=False)
        )
        session.commit()
        return int(deleted or 0)
