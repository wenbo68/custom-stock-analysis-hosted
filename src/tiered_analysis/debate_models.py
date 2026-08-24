# -*- coding: utf-8 -*-
"""Pydantic forms the tier-2 debate (v8) forces its LLM calls to fill.

Every stage of the debate (two analyst lists, the merge match-map, the
check round, the deciding round, citation fixes) is a strict typed form,
not free prose: the engine hands the model the exact JSON shape,
validates the reply against these models, retries once with the
validation errors shown, and degrades/voids per the failure rules if the
retry is still invalid.

v12 (owner spec 2026-07-31): the opening stage is a GRADE SHEET, not a
free-form list. Code enumerates every gradable report field; each
analyst must return exactly one grade per field (bullish / bearish /
neutral) — ``check_grade_sheet`` rejects a reply that skips a field,
invents one, or grades one twice, so "each field is used once" is
enforced structurally, not by prompt. Code converts non-neutral grades
into evidence bullets (ids assigned by code in field order) and matches
the two analysts' sheets by field — no merge LLM call. Every bullet's
author is its first valid vote (a field both analysts graded the same
direction is confirmed 2-0 on the spot); a check round casts the second
vote on single-author bullets; a deciding round breaks 1-1 ties.
Citations are code's job alone — links are ``{ref, value}`` and every
link, including the ones inside vote reasons, is verified mechanically
with a fix loop. Structural rules that depend on run-time data live in
the validator helpers at the bottom — they raise ``ValueError`` with
retry-friendly messages.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Tree order for the debated dimension groups; also the id-prefix map.
#: company_events joined 2026-08-16 (owner decision): each card news
#: event is a gradable row like any numeric field — debate.py enumerates
#: one ref per news bullet and relaxes the value-copy rule for them
#: (a 40-word summary is anchored by its ref, not by verbatim copying).
#: world_events joined the same day: the macro/world news card, graded
#: through the same news-row contract. opinion joined 2026-08-18: the
#: analyst + crowd sentiment card — numeric metric envelopes (analyst
#: consensus/targets/action counts, Reddit-chatter measures), graded
#: like any other numeric field; moved between macro_econ and the news
#: cards 2026-08-19 (owner display order).
DIMENSIONS: Tuple[str, ...] = (
    "technicals", "fundamentals", "positioning", "macro_econ",
    "opinion", "company_events", "world_events",
)
DIMENSION_PREFIX: Dict[str, str] = {
    "technicals": "T",
    "fundamentals": "F",
    "positioning": "P",
    "macro_econ": "E",
    "company_events": "N",
    "world_events": "W",
    "opinion": "O",
}

Dimension = Literal[
    "technicals", "fundamentals", "macro_econ", "positioning",
    "opinion", "company_events", "world_events",
]
ItemDirection = Literal["bullish", "bearish"]
#: A grade adds "neutral": the field carries no lean (metadata, dates,
#: a genuinely mixed reading) and produces no evidence bullet.
GradeDirection = Literal["bullish", "bearish", "neutral"]

#: Importance weight of one bullet, rated by each voter (owner spec
#: 2026-07-20, widened to 1-5 the same day): 1 = very minor, 3 = normal
#: evidence, 5 = very important (could change the whole thesis).
#: Schema-validated — an out-of-range weight fails the form and triggers
#: the normal retry; an OMITTED weight degrades to 3 (the neutral
#: middle), which reproduces the old flat counting exactly.
Weight = Literal[1, 2, 3, 4, 5]
DEFAULT_WEIGHT = 3


class _StageModel(BaseModel):
    # Tolerate extra keys (models love adding commentary fields); never
    # let them through to storage though — only declared fields survive.
    model_config = ConfigDict(extra="ignore")


class LinkModel(_StageModel):
    """One citation: a payload ref carrying "value" — the value copied
    exactly as the report displays it (code verifies the copy AND that
    the sentence contains it)."""

    ref: str = Field(min_length=1)
    value: Optional[Union[float, str]] = None

    @model_validator(mode="after")
    def _payload_needs_value(self) -> "LinkModel":
        ref = self.ref.strip()
        if self.value is None or (
            isinstance(self.value, str) and not self.value.strip()
        ):
            raise ValueError(
                f'link {ref!r} must carry "value" — the value copied exactly '
                "as the report displays it"
            )
        return self


class EvidenceItemModel(_StageModel):
    """One evidence bullet: an atomic claim with a direction tag whose
    cited values carry code-verified links."""

    id: str = Field(min_length=1)
    dimension: Dimension
    direction: ItemDirection
    claim: str = Field(min_length=1)
    links: List[LinkModel] = Field(min_length=1)
    #: The author's own importance rating of this bullet (1-5).
    weight: Weight = DEFAULT_WEIGHT
    #: One short plain sentence saying why the rating is what it is —
    #: shown in the UI when the user clicks the author's check mark.
    weight_reason: Optional[str] = None


class FieldGradeModel(_StageModel):
    """One field's grade on the sheet. Neutral needs nothing else and
    produces no bullet; a bullish/bearish grade carries the claim
    sentence (cited values checked by code) and the author's own
    importance rating."""

    direction: GradeDirection
    claim: Optional[str] = None
    links: List[LinkModel] = Field(default_factory=list)
    weight: Weight = DEFAULT_WEIGHT
    weight_reason: Optional[str] = None


class GradeSheetModel(_StageModel):
    """Step 1 (v12): one analyst's completed grade sheet — exactly one
    grade per code-enumerated report field (``check_grade_sheet``
    enforces the key set). No score — the position scores are computed
    by code from the direction tags."""

    grades: Dict[str, FieldGradeModel] = Field(default_factory=dict)


class CitationFixModel(_StageModel):
    """A bullet citation-fix round's reply: corrected bullets, same ids."""

    items: List[EvidenceItemModel] = Field(min_length=1)


class VoteModel(_StageModel):
    """One vote on a bullet: valid/invalid with a short reason — required
    either way, because the UI shows the reason when the user clicks the
    vote's mark. Numbers inside the reason must be cited with the same
    code-checked links the bullets use."""

    verdict: Literal["valid", "invalid"]
    reason: Optional[str] = None
    links: List[LinkModel] = Field(default_factory=list)
    #: The voter's own importance rating of the bullet (1-5), cast
    #: regardless of the verdict — it joins the bullet's weight median.
    weight: Weight = DEFAULT_WEIGHT
    #: One short plain sentence explaining the rating (see the item's
    #: field of the same name).
    weight_reason: Optional[str] = None

    @model_validator(mode="after")
    def _needs_reason(self) -> "VoteModel":
        if not (self.reason or "").strip():
            raise ValueError("every vote must carry a short non-empty reason")
        return self


class VoteRoundModel(_StageModel):
    """Steps 3 and 4: one vote per requested bullet id."""

    votes: Dict[str, VoteModel] = Field(default_factory=dict)


class SummaryChildModel(_StageModel):
    """One sub-bullet: same citation contract as its parent — any report
    number in the sentence carries a code-verified {ref, value} link."""

    text: str = Field(min_length=1)
    links: List[LinkModel] = Field(default_factory=list)


class SummaryBulletModel(_StageModel):
    """One report bullet: a short plain sentence whose cited report
    values carry code-verified links, with optional sub-bullets one
    level deep."""

    text: str = Field(min_length=1)
    links: List[LinkModel] = Field(default_factory=list)
    children: List[SummaryChildModel] = Field(default_factory=list)


class StructuredSummaryModel(_StageModel):
    """Step 5: the user-facing report as a fixed outline (owner decision
    2026-07-24) — the group set and order never change run to run; the
    AI only fills the bullets. ``summary`` states the outlook and the
    decisive reasons; each dimension group covers what its surviving
    evidence says."""

    summary: List[SummaryBulletModel] = Field(min_length=1)
    technicals: List[SummaryBulletModel] = Field(default_factory=list)
    fundamentals: List[SummaryBulletModel] = Field(default_factory=list)
    positioning: List[SummaryBulletModel] = Field(default_factory=list)
    macro_econ: List[SummaryBulletModel] = Field(default_factory=list)
    opinion: List[SummaryBulletModel] = Field(default_factory=list)
    company_events: List[SummaryBulletModel] = Field(default_factory=list)
    world_events: List[SummaryBulletModel] = Field(default_factory=list)


class VoteFixModel(_StageModel):
    """A vote citation-fix round's reply: corrected votes, same keys."""

    votes: Dict[str, VoteModel] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run-time structural validators (retry-friendly ValueErrors)
# ---------------------------------------------------------------------------


def check_grade_sheet(
    grades: Dict[str, FieldGradeModel], required_refs: Sequence[str]
) -> None:
    """The deterministic one-grade-per-field contract: the sheet must
    cover exactly the code-enumerated field refs — no field skipped, no
    field invented, and (because ``grades`` is a JSON object keyed by
    ref) no field graded twice. Non-neutral grades must carry a claim
    sentence."""
    check_exact_keys(list(grades), list(required_refs), "grade")
    errors: List[str] = []
    for ref, grade in grades.items():
        if grade.direction != "neutral" and not (grade.claim or "").strip():
            errors.append(
                f"grade {ref!r} is {grade.direction} but has no claim "
                "sentence — state the evidence or grade it neutral"
            )
    if errors:
        raise ValueError("; ".join(errors))


def check_summary_groups(
    model: StructuredSummaryModel, data_dimensions: Sequence[str]
) -> None:
    """Every dimension that contributed evidence must get bullets; a
    dimension with no collected data must stay empty (nothing to report
    means nothing to invent)."""
    errors: List[str] = []
    for dimension in DIMENSIONS:
        bullets = getattr(model, dimension)
        if dimension in data_dimensions and not bullets:
            errors.append(
                f'"{dimension}" has evidence above but no bullets — write at least one'
            )
        if dimension not in data_dimensions and bullets:
            errors.append(
                f'"{dimension}" has no collected data — its group must be []'
            )
    if errors:
        raise ValueError("; ".join(errors))


def check_exact_keys(given: Sequence[str], required: Sequence[str], what: str) -> None:
    """The stage must cover exactly ``required`` — no gaps, no inventions."""
    missing = [key for key in required if key not in given]
    extra = [key for key in given if key not in required]
    errors: List[str] = []
    if missing:
        errors.append(f"missing {what} for: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown {what} keys: {', '.join(extra)}")
    if errors:
        raise ValueError("; ".join(errors))


