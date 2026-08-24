# -*- coding: utf-8 -*-
"""Provider contract for tiered analysis (docs/tiered-analysis-design.md §5).

Core rule (§1): every tradeable number is produced by deterministic code
(NUMERIC); LLM+search output (TEXTUAL) carries citations and never feeds
numeric consumers such as position sizing. ``DimensionResult.is_actionable``
is the gate numeric consumers must check.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class Market(str, Enum):
    """Market family tags, mirroring data_provider.base._market_tag values."""

    CN = "cn"
    US = "us"
    HK = "hk"
    JP = "jp"
    KR = "kr"
    TW = "tw"
    UNKNOWN = "unknown"


class SourceKind(str, Enum):
    NUMERIC = "numeric"
    TEXTUAL = "textual"


@dataclass(frozen=True)
class Citation:
    """A verifiable reference.

    NUMERIC dimensions cite their data source; TEXTUAL dimensions cite
    articles. A citation URL must be the product of a real fetch performed
    by a tool, never a model-asserted URL.
    """

    source_name: str
    url: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    retrieved_at: Optional[str] = None


@dataclass(frozen=True)
class DimensionResult:
    """Unified return body for every dimension provider."""

    dimension: str
    kind: SourceKind
    payload: Optional[Dict[str, Any]] = None
    narrative: Optional[str] = None
    citations: List[Citation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    #: UI receipts for derived payload metrics, keyed "group.key":
    #: {"formula": words, "inputs": {var: number}} — the same shape the
    #: trade-plan levels ship. Deliberately OUTSIDE payload: the payload
    #: is dumped verbatim into LLM prompts and its envelope shape
    #: ({name, explanation, value}) is a contract; receipts are for the
    #: report page only.
    formulas: Optional[Dict[str, Any]] = None
    #: The same data notes as ``warnings``, keyed by the payload field
    #: ("group.key") each note is about — one note may sit on several
    #: fields. The report page shows a note next to its own field; a
    #: warning absent from this map has no field to live on and stays a
    #: card-level note. Same out-of-payload rationale as ``formulas``.
    field_notes: Optional[Dict[str, List[str]]] = None

    @property
    def is_actionable(self) -> bool:
        """True only for NUMERIC results carrying a payload.

        Numeric consumers (e.g. future position sizing) must gate on this —
        and on each field's value being non-null — so thin or degraded data
        can never silently flow into a share count. (Degradation is no
        longer a card-level grade, 2026-08-19: a failed source shows as
        blank fields with notes, so the field level is the only gate.)
        """
        return self.kind == SourceKind.NUMERIC and bool(self.payload)


def note_fields(
    warnings: List[str],
    field_notes: Dict[str, List[str]],
    message: str,
    paths: Sequence[str],
) -> None:
    """Record one data note: on the card-level warnings list AND on each
    payload field ("group.key") it affects, so the report page can show
    the note beside the field itself."""
    warnings.append(message)
    for path in paths:
        field_notes.setdefault(path, []).append(message)


class DimensionProvider(ABC):
    """One implementation per (dimension x market family)."""

    dimension: str
    kind: SourceKind

    @abstractmethod
    def supports(self, market: Market) -> bool:
        """Whether this provider covers the given market family."""

    @abstractmethod
    def collect(self, symbol: str) -> DimensionResult:
        """Collect this dimension for one symbol.

        Failures must surface as blank payload fields (value null) with
        warnings and field notes explaining why (fail-loud) — a total
        failure is every field blank, never a missing payload where one
        can be built without data. Never raised exceptions or silent
        blanks.
        """
