# -*- coding: utf-8 -*-
"""Tier 2: the evidence vote (v12 — graded sheet).

v12 revision (owner spec 2026-07-31, replacing the v8-v11 free-form
lists): the opening stage is a GRADE SHEET. Code enumerates every
gradable report field (each non-blank leaf, in report order) and each
of the two blind ANALYSTS must return exactly one grade per field —
bullish, bearish or neutral. The one-grade-per-field rule is enforced
structurally (``check_grade_sheet`` rejects a reply that skips, invents
or double-grades a field; JSON object keys make a double grade
impossible to express), not by prompt wording. One tolerance (owner
decision 2026-08-05): a grade on a field that exists in the report but
is blank is silently dropped, never a sheet failure — the report text
shows blank fields and the AIs kept grading them, voiding whole runs. Code converts the
non-neutral grades into evidence bullets — ids assigned by code in
field order, the graded field's citation injected by code with the
exact display value — and MATCHES the two sheets by field in pure code
(same field + same direction = the same bullet; an opposite-direction
clash is a dispute and stays unmatched). The old merge LLM call is
gone. Membership is a majority vote with at most three votes per
bullet:

- A bullet's author is automatically its first valid vote, so a bullet
  BOTH analysts listed independently starts 2-0 — confirmed, no checking.
- A CHECK round casts the second vote on every single-author bullet:
  2-0 confirmed or 1-1 tied.
- A DECIDING round breaks the ties: 2-1 in or 1-2 out. Three votes,
  so a tie is impossible.

Citations are code's job alone (carried over from v7): links are
``{ref, value}`` with the value copied exactly as the report pages
display it (``display_value``).
Code verifies every link — including the links inside vote reasons —
and sends failures back to the same AI in up to ``MAX_FIX_ROUNDS``
focused fix calls; bullets that cannot be fixed are STRUCK (crossed
out, never voted on, in no pool) and unfixable votes are discarded.

NO AI authors any number, but every voter RATES each bullet's
importance 1-5 (v11 owner spec, 2026-07-20: 1 = very minor, 3 = normal
evidence, 5 = very important — thesis-changing) and gives one short
plain sentence saying why (``weight_reason``, shown in the UI's check
modals). Listers rate their own bullets in the same call; check/decider
votes carry a weight alongside the validity. A bullet's final weight is
the MEDIAN of its voters' weights (two voters → their mean, so halves
happen). The outlook score is computed by code from the direction tags
and the weights:
``10 × Σweight(bullish) / Σweight(all)`` over the whole pool
(per-dimension counts and weight sums are stored for the section
headers). Two snapshots: initial (the merged list before voting,
weighted by the authors' own ratings, stored for the audit trail only)
and final (the bullets the votes left standing, weighted by the full
voter median — the displayed score). Outlook on the 2-decimal final:
< 4 sell, 4-6 hold, > 6 buy. Empty final pool → 5.00, hold, warning.

4-5 base LLM calls (two grade sheets parallel with their fix loops →
code merge → check round → deciding round only when there are ties →
summary), all temperature 0. Every stage fills a strict Pydantic form;
an invalid reply gets ONE retry with the errors shown, then: both
sheets failing voids the tier-2 outlook — the run has no outlook and
says re-run (no fallback: depth 2 never runs the tier-1 one-blob
outlook, so there is nothing to fall back to); one
sheet failing proceeds with the other; a failed check round counts
bullets on their author's vote alone; a failed deciding round excludes
the tied bullets as unresolved; the summary's failure never voids
anything.

2026-08-16 (owner decision): the news cards joined the sheet — every
card news event is one gradable row
(``company_events.news_coverage.items.{i}.text``, id prefix N;
``world_events.…``, id prefix W — both keyed by TEXTUAL kind, not by
name). News rows relax the value-copy rule only (the ref anchors the
claim to the event; a 40-word summary has no short display value to
copy) — everything else (votes, weights, pools, the summary group)
treats them like any other field.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from .debate_models import (
    CitationFixModel,
    DIMENSION_PREFIX,
    DIMENSIONS,
    EvidenceItemModel,
    GradeSheetModel,
    LinkModel,
    StructuredSummaryModel,
    VoteFixModel,
    VoteModel,
    VoteRoundModel,
    check_exact_keys,
    check_grade_sheet,
    check_summary_groups,
)
from .llm_support import (
    JSON_REPLY,
    active_tracker,
    deterministic_summarizer,
    display_value,
    evidence_block,
    parse_llm_json,
    summarize_with_schema,
)
from .providers.base import DimensionResult, SourceKind
from .providers.technicals import is_envelope
from .schema import (
    DEFAULT_HOLD_WEEKS,
    Direction,
    TierReport,
    hold_weeks_text,
)

#: Outlook bands on the 2-decimal final score (owner spec).
SELL_BELOW = 4.0
HOLD_MAX = 6.0

#: How many focused fix calls a broken citation gets before its bullet is
#: struck (or its vote discarded).
MAX_FIX_ROUNDS = 3

#: Stored-detail version marker — the frontend picks its renderer by this.
#: 11 = 1-5 weights with per-voter score reasons and author attribution
#: (``author_votes``: which lister authored the bullet, their rating and
#: why); 10 = 1-3 weights, ratings only; stored format-9 runs are the
#: same shapes minus the weight keys, with flat counting. The v12 graded
#: opening (2026-07-31) only ADDS the per-bullet ``field`` key, so the
#: stored shape stays format 11.
DETAIL_FORMAT = 11

#: A vote reason that states a report-style number (a decimal or a
#: percentage) must cite it — bare integers like "above 50" are usually
#: thresholds, not report fields, so they are not forced.
_NUMERIC_REASON_RE = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?\s?%")


def direction_from_final(final: float) -> Direction:
    """The fixed mapping from the 0-10 final score to an outlook."""
    if final < SELL_BELOW:
        return Direction.SELL
    if final <= HOLD_MAX:
        return Direction.HOLD
    return Direction.BUY


@dataclass(frozen=True)
class AnchoredReason:
    """A claim tied to evidence refs — still used by the tier-3 risk stage."""

    claim: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DebateOutlook:
    direction: Direction
    #: The final pool's weighted score: 10 × Σweight(bullish) / Σweight(all).
    final_score: float
    summary: str
    #: The same formula over the merged list before any voting, weighted
    #: by the authors' own ratings.
    initial_score: float
    #: Per-pool audit: {initial|final: {dimensions, bullish, bearish,
    #: total, score}}.
    pools: Dict[str, Any] = field(default_factory=dict)
    #: The report as the fixed outline (StructuredSummaryModel dump);
    #: ``summary`` above is its flat-text rendering (the tier-2 report's
    #: narrative). None when the summary stage failed.
    summary_structure: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class DebateResult:
    #: The evidence list, one dict per bullet (see _base_item for the shape).
    items: List[Dict[str, Any]] = field(default_factory=list)
    outlook: Optional[DebateOutlook] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready audit trail for storage and the debate-tree UI."""
        outlook: Optional[Dict[str, Any]] = None
        if self.outlook is not None:
            v = self.outlook
            outlook = {
                "direction": v.direction.value,
                "final_score": v.final_score,
                "summary": v.summary,
                "summary_structure": v.summary_structure,
                "initial_score": v.initial_score,
                "pools": v.pools,
            }
        return {
            "format": DETAIL_FORMAT,
            "items": [dict(item) for item in self.items],
            "outlook": outlook,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Payload helpers (leaf counting, value lookup, display-string matching)
# ---------------------------------------------------------------------------


def _leaf_refs(dim: DimensionResult) -> List[str]:
    """Every payload leaf ref of one dimension, in report order — an
    envelope {name, explanation[, interpretation], value} is one leaf."""
    rows: List[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict) and not is_envelope(node):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
            return
        rows.append(path)

    for key, value in (dim.payload or {}).items():
        walk(value, f"{dim.dimension}.{key}")
    return rows


def _news_item_refs(dim: DimensionResult) -> List[str]:
    """One gradable ref per bullet of a textual card: the item's
    summary sentence (``items.{i}.text``), enumerated from EVERY
    payload group that carries an items list (the news cards' single
    ``news_coverage`` group today, payload order). The groups' other
    keys (window/date-span, screen counters) are bookkeeping, not
    evidence, and get no rows — the EVENT is the gradable fact."""
    refs: List[str] = []
    for group_key, group in (dim.payload or {}).items():
        items = group.get("items") if isinstance(group, dict) else None
        if not isinstance(items, list):
            continue
        refs.extend(
            f"{dim.dimension}.{group_key}.items.{index}.text"
            for index, item in enumerate(items)
            if isinstance(item, dict) and item.get("text")
        )
    return refs


def gradable_field_refs(
    dimensions: Sequence[DimensionResult],
) -> Dict[str, List[str]]:
    """The grade sheet's row set: every citable leaf ref per dimension,
    in report order. An envelope {name, explanation[, interpretation],
    value} is ONE gradable fact (its prose keys are documentation);
    blank fields (value null) carry no evidence and get no row — code
    already knows why they are blank. News cards are textual (kind, not
    name — company_events and world_events alike): their rows are the
    news EVENTS (one per bullet, ``_news_item_refs``), never their
    bookkeeping counters."""
    refs: Dict[str, List[str]] = {}
    for dim in dimensions:
        if dim.dimension not in DIMENSIONS or not dim.payload:
            continue
        if dim.kind == SourceKind.TEXTUAL:
            rows = _news_item_refs(dim)
        else:
            rows = [
                path for path in _leaf_refs(dim) if _payload_value(path, [dim])[0]
            ]
        if rows:
            refs[dim.dimension] = rows
    return refs


def blank_field_refs(dimensions: Sequence[DimensionResult]) -> set:
    """Payload leaves that exist but are blank (value null). They get no
    grade-sheet row, but the report text the analysts read still shows
    them, and the AIs keep grading them anyway — so a grade landing on
    one is DROPPED (it would have been an invisible neutral at best),
    never a reason to fail the whole sheet (owner decision 2026-08-05:
    a voided outlook over meaningless grades is the worse outcome)."""
    refs: set = set()
    for dim in dimensions:
        if dim.dimension not in DIMENSIONS or not dim.payload:
            continue
        if dim.kind == SourceKind.TEXTUAL:
            continue  # news rows are enumerated non-blank by construction
        refs.update(
            path
            for path in _leaf_refs(dim)
            if not _payload_value(path, [dim])[0]
        )
    return refs


def _payload_value(ref: str, dimensions: Sequence[DimensionResult]) -> Tuple[bool, Any]:
    """(resolves-to-a-leaf, value) for a ``dimension.key[.subkey…]`` ref.

    A ref that lands on a {name, explanation[, interpretation], value}
    envelope resolves to its ``value`` — the envelope path IS the citable
    leaf; its prose keys are documentation, not separately citable facts.
    A numeric segment indexes a list (``news_coverage.items.3.text`` —
    how the company-news rows resolve); lists themselves are never
    leaves.
    """
    parts = ref.split(".")
    if len(parts) < 2:
        return False, None
    dimension_name, path = parts[0], parts[1:]
    for dim in dimensions:
        if dim.dimension != dimension_name or not dim.payload:
            continue
        node: Any = dim.payload
        for segment in path:
            if isinstance(node, dict) and segment in node:
                node = node[segment]
            elif (
                isinstance(node, list)
                and segment.isdigit()
                and int(segment) < len(node)
            ):
                node = node[int(segment)]
            else:
                node = None
                break
        if is_envelope(node):
            node = node.get("value")
        if node is not None and not isinstance(node, (dict, list)):
            return True, node
    return False, None


def _is_textual_ref(ref: str, dimensions: Sequence[DimensionResult]) -> bool:
    """Whether a ref points into a TEXTUAL dimension (the company-news
    card). Textual refs anchor a claim to a news event — there is no
    short display value to copy verbatim, so the value-copy and
    value-in-sentence rules do not apply; the ref resolving is the
    check. Everything numeric keeps the strict contract."""
    name = ref.split(".", 1)[0]
    return any(
        dim.dimension == name and dim.kind == SourceKind.TEXTUAL
        for dim in dimensions
    )


def _link_value_text(value: Any) -> str:
    """The link's claimed value as a display string (numbers a model sends
    as JSON numbers are normalized through the same formatter)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value).strip()
    return display_value(value)


def _norm_text_value(text: str) -> str:
    """Loose comparison form for TEXT values only ("Golden_Cross" ↔
    "golden cross") — numbers never come through here."""
    return re.sub(r"[_\s]+", " ", text).strip().lower()


def _values_equal(claimed: str, expected: str) -> bool:
    if claimed == expected:
        return True
    if any(char.isdigit() for char in expected):
        return False  # numeric display strings must be copied exactly
    return _norm_text_value(claimed) == _norm_text_value(expected)


def value_pattern(value_text: str) -> "re.Pattern[str]":
    """Where a display value may appear in a sentence: the exact string,
    tolerating thousands separators ("1,234" for "1234") and — for text
    values — case/underscore looseness. Digit boundaries stop "205" from
    matching inside "1205" or "205.4". The frontend underliner builds the
    same pattern to highlight exactly the cited value."""
    parts: List[str] = []
    for index, char in enumerate(value_text):
        parts.append("[_ ]" if char == "_" else re.escape(char))
        if (
            char.isdigit()
            and index + 1 < len(value_text)
            and value_text[index + 1].isdigit()
        ):
            parts.append(",?")
    pattern = "".join(parts)
    if value_text[:1].isdigit() or (
        value_text[:1] == "-" and value_text[1:2].isdigit()
    ):
        pattern = r"(?<![\d.])" + pattern
    if value_text[-1:].isdigit():
        pattern += r"(?!\.?\d)"
    flags = 0 if any(char.isdigit() for char in value_text) else re.IGNORECASE
    return re.compile(pattern, flags)


def _value_in_text(value_text: str, sentence: str) -> bool:
    return bool(value_pattern(value_text).search(sentence))


# ---------------------------------------------------------------------------
# Prompts — one marker phrase per stage so tests can route replies.
# ---------------------------------------------------------------------------

_CONTEXT_TEMPLATE = """Stock under debate: {symbol}
This is a SWING TRADE held for up to {hold_text} (the user's chosen max
hold time). Judge every piece of evidence against that horizon — use
your own judgment about what matters at this timescale (owner decision
2026-08-08: the same number drives the report and the forward test).

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_LINK_RULES = """Link rules (all checked mechanically by code):
- Every bullet carries "links": one entry per report field the sentence
  uses, each {{"ref": the leaf field, "value": the value copied EXACTLY
  as the report above displays it}}.
- The claim sentence must contain each linked value verbatim — "The
  14-day RSI (56.28) is above 50", never "RSI is high". Copy the
  displayed string exactly: if the report shows 56.28, write 56.28,
  never 56.3 or 56.280. Write values as plain numbers in the sentence —
  do not wrap them in quotation marks.
- A "ref" must point at ONE exact value, like "technicals.daily.rsi_14"
  — grouping paths ("technicals.daily" when it holds sub-fields) are
  rejected; cite the field ("technicals.daily.rsi_14"). A report field
  may be an envelope {"name", "explanation", "interpretation", "value"}:
  cite the FIELD path, never ".value"/".name" — the ref resolves to the
  value automatically.
- Code verifies every link and sends failures back to you to fix;
  bullets that cannot be fixed are struck from the list.
- Exception: a ref into a textual card (company_events or
  world_events) points at an item's summary sentence — cite the item's
  text field (like "company_events.news_coverage.items.3.text" or
  "world_events.news_coverage.items.1.text") and you do NOT copy that
  sentence into your own; the ref itself is the anchor.
- Use only the evidence above; never invent facts or numbers."""

_VOTE_RULES = """Vote rules (checked mechanically by code):
- Every vote: "validity" is "valid" or "invalid", plus a short plain
  "reason" — REQUIRED either way; a vote without a reason is rejected.
- Every vote also carries "weight": your own importance rating of the
  bullet for the trade decision, 1 to 5 — 1 (very minor), 2 (minor),
  3 (normal evidence), 4 (important), 5 (very important — could change
  the whole thesis alone). Rate it regardless of your validity call; code
  takes the median of all voters' weights.
- Every vote also carries "weight_reason": ONE short plain sentence
  saying why you rated it that important. Plain words only — report
  numbers belong in the vote reason with links, never here.
- If your reason states a number from the reports, cite it with a link
  {{"ref": the leaf field, "value": the value copied EXACTLY as the
  report displays it}} and write that exact value in your reason.
- The reason is a plain sentence for a human reader — never paste refs
  or link JSON into it; refs belong in "links" only.
- Code verifies every link and sends failures back to you to fix; votes
  that cannot be fixed are discarded."""

_GRADE_RULES = """Grade-sheet rules (all checked mechanically by code):
- Reply with EXACTLY one grade per field key listed above — code
  rejects a reply that skips a field, invents a field key, or grades a
  field twice.
- Fields shown blank/null in the report are NOT on the sheet — do not
  grade them (code ignores any grade on a blank field).
- Each grade: "direction" is "bullish", "bearish" or "neutral" for
  this swing trade. Neutral = the field carries no lean either way
  (metadata like dates and bar counts, or a genuinely mixed reading);
  a neutral grade needs no other keys and produces no evidence.
- A bullish/bearish grade carries "claim": ONE plain sentence stating
  the evidence, containing the field's value copied EXACTLY as the
  report above displays it. Code attaches the graded field's citation
  itself; only if the sentence ALSO states another field's value, cite
  that other field in "links" (link rules below).
- A bullish/bearish grade carries "weight": your importance rating of
  the evidence for the trade decision, 1 to 5 — 1 (very minor),
  2 (minor), 3 (normal evidence), 4 (important), 5 (very important —
  could change the whole thesis alone). Most are a 3; reserve 5 for
  evidence that would change the whole thesis on its own, and 1 for
  footnotes. Code weighs the score by these ratings.
- A bullish/bearish grade carries "weight_reason": ONE short plain
  sentence saying why you rated it that important. Plain words only —
  report numbers belong in the claim sentence, never here.
- If fundamentals.quarterly_report.next_earnings_date shows a report
  within roughly a week of the report's as-of date, grade that field
  bearish — an imminent earnings report can gap the price past any
  plan level, which argues for waiting.
- company_events and world_events rows are NEWS EVENTS, not numbers:
  each ref points at one news summary in the report. Grade the event's
  likely effect on THIS stock over the hold time — bullish, bearish, or
  neutral when it has no clear lean (routine coverage, already-priced-in
  noise). world_events items are market-wide backdrop news: judge what
  the event means for this particular stock (a rate story hits a bank
  and a miner differently); when it has no read-through to this name,
  grade it neutral. The claim states the event and why it leans that
  way IN YOUR OWN WORDS — the value-copy rule does not apply to news
  rows (code attaches the event citation itself); any NUMBER your claim
  quotes from the news text still appears exactly as the report shows
  it.
- The direction tags ARE the score — code counts them; nobody writes
  a score."""

# Substituted into the templates as a VALUE (never format()ed itself),
# so the braces are literal.
_GRADE_SHAPE = """{"grades": {
  "technicals.daily.rsi_14": {"direction": "bullish",
    "claim": "The 14-day RSI (56.28) is above 50, showing bullish momentum.",
    "links": [],
    "weight": 3, "weight_reason": "Momentum backs the trend but rarely drives it alone."},
  "technicals.meta.as_of": {"direction": "neutral"},
  "company_events.news_coverage.items.0.text": {"direction": "bearish",
    "claim": "The new antitrust lawsuit adds legal risk that could weigh on the stock during the hold.",
    "links": [],
    "weight": 4, "weight_reason": "Litigation news can move the price on its own."},
  ...one entry for EVERY field key listed above...}}"""

_GRADER1_TEMPLATE = """{context}
You are the FIRST analyst. Another analyst is grading the same sheet
separately; neither of you sees the other's work. Take no side: grade
EVERY field on the sheet below — bullish, bearish or neutral — walking
it top to bottom so nothing is skipped. You give no score; code
computes the outlook score from your direction tags.

The grade sheet (one grade per field key, exactly these keys):
{field_rows}

{grade_rules}

{link_rules}

Reply with JSON only:
{shape}"""

_GRADER2_TEMPLATE = """{context}
You are the SECOND analyst. Another analyst is grading the same sheet
separately; you have NOT seen their work. Take no side: grade EVERY
field on the sheet below — bullish, bearish or neutral. Think theme by
theme — momentum, trend, profitability, valuation, balance sheet,
macro pressures — then make sure every field key has exactly one
grade. You give no score; code computes the outlook score from your
direction tags.

The grade sheet (one grade per field key, exactly these keys):
{field_rows}

{grade_rules}

{link_rules}

Reply with JSON only:
{shape}"""

_CITATION_FIX_TEMPLATE = """Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

Some of your evidence bullets failed the code's citation check. Fix each
bullet listed below: point the ref at the right leaf field, copy the
value exactly as the report above displays it, and make sure the claim
sentence contains that exact value. Keep each bullet's "id" and
"dimension" unchanged; you may rewrite the claim, the links, and the
direction tag.

{link_rules}

The bullets to fix:
{bullets}

The code's error list:
{errors}

Reply with JSON only:
{{"items": [ ...every bullet above, corrected, same ids... ]}}"""

_VOTE_FIX_TEMPLATE = """Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

Some of your votes failed the code's citation check. Fix each vote
listed below: cite every number your reason states, copying the value
exactly as the report above displays it. Keep the same keys; you may
rewrite the reason and links, and reconsider the validity with the
correct numbers in hand.

{vote_rules}

The votes to fix:
{votes}

The code's error list:
{errors}

Reply with JSON only:
{{"votes": {{ ...every vote above, corrected, same keys... }}}}"""

_CHECK_TEMPLATE = """{context}
The merged evidence list (every bullet's numbers already code-verified):
{tree}

Each bullet named below was listed by only ONE of the two analysts, so
it has one vote so far (its author's). You cast the second vote on each:
- "valid" — the sentence says something TRUE about the verified values
  AND the bullish/bearish tag actually follows from the fact.
- "invalid" — the statement is wrong about the values, or the tag does
  not follow. Say why.
Vote on the bullet in front of you, not on the stock.

{vote_rules}

Reply with JSON only:
{{"votes": {{"T2": {{"validity": "invalid", "reason": "why it is flawed", "links": [{{"ref": "technicals.price.close", "value": "100"}}], "weight": 3, "weight_reason": "why it matters this much"}}}}}}
"votes" must cover exactly these bullet ids: {check_ids}."""

_DECIDER_TEMPLATE = """{context}
The merged evidence list (every bullet's numbers already code-verified):
{tree}

The bullets below are TIED — one analyst listed each, and the check
vote went against it. You cast the deciding vote. For each bullet you
see the claim and the objection; weigh both and rule:
- "valid" — the bullet stands and counts in the score.
- "invalid" — the objection is right and the bullet is out.

{disputes}

{vote_rules}

Reply with JSON only:
{{"votes": {{"T2": {{"validity": "valid", "reason": "why the bullet stands", "links": [], "weight": 3, "weight_reason": "why it matters this much"}}}}}}
"votes" must cover exactly these bullet ids: {tied_ids}."""

# The summary speaks in outlook words (user-facing tier-2 prose) — the
# internal Direction enum never leaks its buy/hold/sell vocabulary there.
_OUTLOOK_WORD = {
    Direction.BUY: "bullish",
    Direction.HOLD: "neutral",
    Direction.SELL: "bearish",
}

_SUMMARY_TEMPLATE = """{context}
The voted evidence list:
{tree}

Computed result (fixed formula, already decided by code — the score is
10 × the total importance weight of the bullish bullets / the total
weight of all bullets, over the pool the votes left standing; each
bullet's weight is the median of its voters' 1-5 ratings):
- final score {final} ({final_bullish} bullish vs {final_bearish}
  bearish of {final_total} bullets; bullish weight {final_bullish_weight}
  of {final_total_weight} total)
- outlook: {outlook} (below 4 bearish, 4-6 neutral, above 6 bullish)

Write the user-facing report as a fixed bullet outline. Reply with JSON
only. Never write the words "outlook", "buy", "hold" or "sell" — say
bullish, neutral or bearish:
{{"summary": [{{"text": "one short plain sentence", "links": [], "children": []}}],
 "technicals": [{{"text": "The 14-day RSI (56.28) is above 50.",
   "links": [{{"ref": "technicals.daily.rsi_14", "value": "56.28"}}],
   "children": [{{"text": "optional supporting detail", "links": []}}]}}],
 "fundamentals": [], "positioning": [], "macro_econ": [],
 "company_events": [], "world_events": []}}

Rules:
- "summary": 2-4 bullets stating the outlook and the decisive reasons.
- Fill exactly these dimension groups (the others stay []): {fill_groups}.
  Each filled group: 1-4 bullets on what its surviving evidence says.
- "children" holds supporting detail one level deep; keep it [] when a
  bullet needs none.
- Every "text" and every child is one short plain sentence.
- If a sentence states a number from the reports, write the value copied
  EXACTLY as the report above displays it and cite it in that bullet's
  "links" as {{"ref": the leaf field, "value": that exact value}} — the
  same link rules as the evidence list, checked mechanically by code.
  Code sends failures back to you to fix; links that cannot be fixed
  are dropped from the report.
- "company_events" and "world_events" bullets talk about the news
  events; cite each item by its ref
  ("company_events.news_coverage.items.3.text",
  "world_events.news_coverage.items.1.text") — for these refs there
  is no value to copy into the sentence.
- Support the computed outlook; if little evidence survived, say plainly
  that the case is weak.
- Use only the evidence above; do not invent facts."""

#: Flat-text group titles for the legacy narrative rendering.
_SUMMARY_GROUP_TITLES = {
    "summary": "Summary",
    "technicals": "Technicals",
    "fundamentals": "Fundamentals",
    "positioning": "Positioning",
    "macro_econ": "Macro economy",
    "company_events": "Company news",
    "world_events": "World news",
}


def _flatten_summary(model: StructuredSummaryModel) -> str:
    """The outline as plain text, one line per non-empty group — what the
    legacy narrative consumers (main page, stored summaries) keep."""
    lines: List[str] = []
    for group in ("summary",) + DIMENSIONS:
        bullets = getattr(model, group)
        if not bullets:
            continue
        sentences: List[str] = []
        for bullet in bullets:
            sentences.append(bullet.text.strip())
            sentences.extend(child.text.strip() for child in bullet.children)
        lines.append(f"{_SUMMARY_GROUP_TITLES[group]}: " + " ".join(sentences))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_StageParse = Callable[[dict], Any]

#: One analyst sheet after conversion + citation fixes: (bullets, still
#: broken bullet id → errors, bullet id → the field ref it grades).
_SheetResult = Tuple[List[EvidenceItemModel], Dict[str, List[str]], Dict[str, str]]


class DebateEngine:
    """Runs the v8 evidence vote. Never raises out of run()."""

    # The fix loops are shared with the tier-3 risk engine (a subclass);
    # these hooks let it swap in its own item form and prompt wording
    # while the loop mechanics stay identical.
    FIX_ITEMS_MODEL: Any = CitationFixModel
    CITATION_FIX_TEMPLATE = _CITATION_FIX_TEMPLATE
    LINK_RULES = _LINK_RULES
    VOTE_FIX_TEMPLATE = _VOTE_FIX_TEMPLATE
    VOTE_RULES = _VOTE_RULES

    def __init__(self, summarizer: Optional[Callable[[str], str]] = None) -> None:
        # Temperature 0 by default: the same evidence rules the same way.
        self._summarize = summarizer or deterministic_summarizer

    # -- public entry ------------------------------------------------------

    def run(
        self,
        symbol: str,
        tier1: TierReport,
        dimensions: Sequence[DimensionResult],
        hold_weeks: int = DEFAULT_HOLD_WEEKS,
    ) -> DebateResult:
        context = _CONTEXT_TEMPLATE.format(
            symbol=symbol,
            hold_text=hold_weeks_text(hold_weeks),
            # The plan levels are deliberately NOT in the context (owner
            # decision 2026-09-16): the debate judges the outlook from
            # citable evidence, and the levels are neither.
            # Display-formatted numbers: the model must cite what the
            # report pages show, so it only ever sees those strings.
            evidence_block=evidence_block(dimensions, display=True),
        )
        data_dimensions = [
            d.dimension
            for d in dimensions
            if d.dimension in DIMENSIONS
            and (d.payload or d.narrative or d.citations)
        ]
        warnings: List[str] = []
        items: List[Dict[str, Any]] = []
        try:
            return self._run_stages(
                context, dimensions, data_dimensions, warnings, items
            )
        except Exception as exc:  # fail-loud as a structured result
            return DebateResult(
                items=items, warnings=warnings + [f"debate LLM call failed: {exc}"]
            )

    # -- the steps ---------------------------------------------------------

    def _run_stages(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        data_dimensions: List[str],
        warnings: List[str],
        items: List[Dict[str, Any]],
    ) -> DebateResult:
        refs = gradable_field_refs(dimensions)
        if not refs:
            warnings.append(
                "no gradable report fields collected — tier-2 outlook voided"
            )
            return DebateResult(items=items, warnings=warnings)

        # Step 1 — the two analyst grade sheets, in parallel (blind),
        # each converted to bullets with its own citation-fix loop.
        first, second = self._listers(context, dimensions, refs, warnings)
        if first is None and second is None:
            warnings.append(
                "both analyst grade sheets invalid after retry — tier-2 "
                "outlook voided"
            )
            return DebateResult(items=items, warnings=warnings)
        if first is None or second is None:
            which = "first" if first is None else "second"
            warnings.append(
                f"{which} analyst grade sheet invalid after retry — "
                "proceeding with the other sheet only"
            )

        # Step 2 — code merge by graded field. Same field + same
        # direction = listed independently by both (2-0 confirmed);
        # everything else on the second sheet joins the list.
        items.extend(self._assemble(first, second))
        for item in items:
            if item["struck"]:
                warnings.append(
                    f"analyst {item['id']}: citations unfixable after "
                    f"{MAX_FIX_ROUNDS} fix attempts — struck from the list"
                )

        # Step 3 — the check round: the second vote on single-author
        # bullets. Bullets both analysts listed are already 2-0.
        check_ids = [
            item["id"] for item in items if not item["struck"] and item["authors"] < 2
        ]
        if check_ids:
            votes = self._vote_round(
                _CHECK_TEMPLATE.format(
                    context=context,
                    tree=_tree_text(items),
                    vote_rules=_VOTE_RULES,
                    check_ids=", ".join(check_ids),
                ),
                check_ids,
                dimensions,
                "check round",
                warnings,
            )
            if votes is None:
                warnings.append(
                    "check round invalid after retry — bullets counted on "
                    "their author's vote alone"
                )
            else:
                self._attach_votes(items, votes, "checker")
        else:
            warnings.append(
                "every bullet was listed by both analysts — check round skipped"
            )

        # Step 4 — the deciding round, only for 1-1 ties.
        tied_ids = [item["id"] for item in items if self._is_tied(item)]
        if tied_ids:
            by_id = {item["id"]: item for item in items}
            votes = self._vote_round(
                _DECIDER_TEMPLATE.format(
                    context=context,
                    tree=_tree_text(items),
                    disputes=_disputes_text([by_id[i] for i in tied_ids]),
                    vote_rules=_VOTE_RULES,
                    tied_ids=", ".join(tied_ids),
                ),
                tied_ids,
                dimensions,
                "deciding round",
                warnings,
            )
            if votes is None:
                warnings.append(
                    "deciding round invalid after retry — tied bullets "
                    "excluded as unresolved"
                )
            else:
                self._attach_votes(items, votes, "decider")

        # Outcomes — pure counting of the votes — then each surviving
        # bullet's final weight: the median of every voter's 1-5 rating.
        self._apply_outcomes(items, warnings)
        for item in items:
            if not item["struck"]:
                item["weight"] = _median_weight(
                    item["author_weights"]
                    + [vote["weight"] for vote in item["votes"]]
                )

        pools = {
            # The initial pool is the merged list BEFORE voting, so it is
            # weighted by the authors' own ratings alone.
            "initial": _pool_detail(
                (i for i in items if not i["struck"]),
                lambda item: _median_weight(item["author_weights"]),
            ),
            "final": _pool_detail(
                (i for i in items if i["final_status"] == "counted"),
                lambda item: item["weight"],
            ),
        }
        initial_score = pools["initial"]["score"] if pools["initial"]["total"] else 5.0
        if pools["final"]["total"]:
            final = pools["final"]["score"]
        else:
            final = 5.0
            warnings.append(
                "no surviving evidence to weigh — final score is neutral 5 by default"
            )
        merged = [i for i in items if not i["struck"]]
        survivors = sum(1 for i in merged if i["final_status"] == "counted")
        if merged and survivors * 2 < len(merged):
            warnings.append(
                "most of the merged evidence did not survive the votes — "
                "the final score rests on a thin base"
            )
        direction = direction_from_final(final)

        # Step 5 — the user-facing report; its failure never voids anything.
        summary, summary_structure = self._summary(
            context, items, final, pools, direction, data_dimensions,
            dimensions, warnings,
        )

        outlook = DebateOutlook(
            direction=direction,
            final_score=final,
            summary=summary,
            initial_score=initial_score,
            pools=pools,
            summary_structure=summary_structure,
        )
        return DebateResult(items=items, outlook=outlook, warnings=warnings)

    # -- step 1: the two lists ---------------------------------------------

    def _listers(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        refs: Dict[str, List[str]],
        warnings: List[str],
    ) -> Tuple[Optional["_SheetResult"], Optional["_SheetResult"]]:
        """Each entry: (bullets with fixes applied, still-broken map,
        bullet id → graded field ref), or None when the sheet never
        validated."""
        all_refs = [ref for dimension in refs for ref in refs[dimension]]
        blank_refs = blank_field_refs(dimensions)
        field_rows = "\n".join(f"- {ref}" for ref in all_refs)
        prompts = [
            template.format(
                context=context,
                field_rows=field_rows,
                grade_rules=_GRADE_RULES,
                link_rules=_LINK_RULES,
                shape=_GRADE_SHAPE,
            )
            for template in (_GRADER1_TEMPLATE, _GRADER2_TEMPLATE)
        ]

        def parse(parsed: dict) -> GradeSheetModel:
            model = GradeSheetModel.model_validate(parsed)
            # Grades on blank-but-real report fields are dropped, not
            # failed (see blank_field_refs); truly invented keys still
            # fail the exact-coverage check below.
            grades = {
                ref: grade
                for ref, grade in model.grades.items()
                if ref not in blank_refs
            }
            check_grade_sheet(grades, all_refs)
            return model.model_copy(update={"grades": grades})

        # The usage tracker is thread-local; hand it to the workers so
        # their calls still count toward the run's AI-calls number.
        tracker = active_tracker()

        def run_stage(prompt: str, stage: str):
            def job():
                model, stage_warnings = self._call_validated(prompt, parse, stage)
                if model is None:
                    return None, stage_warnings
                sheet_items, ref_by_id = self._sheet_items(
                    model, refs, dimensions
                )
                fixed_items, broken = self._fix_citations(
                    sheet_items, dimensions, stage, stage_warnings
                )
                return (fixed_items, broken, ref_by_id), stage_warnings

            if tracker is None:
                return job()
            with tracker.activate():
                return job()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(run_stage, prompts[0], "first analyst grade sheet"),
                pool.submit(run_stage, prompts[1], "second analyst grade sheet"),
            ]
            (first, first_warnings), (second, second_warnings) = (
                futures[0].result(),
                futures[1].result(),
            )
        warnings.extend(first_warnings)
        warnings.extend(second_warnings)
        return first, second

    @staticmethod
    def _sheet_items(
        sheet: GradeSheetModel,
        refs: Dict[str, List[str]],
        dimensions: Sequence[DimensionResult],
    ) -> Tuple[List[EvidenceItemModel], Dict[str, str]]:
        """Non-neutral grades as evidence bullets. Ids are assigned by
        code in field order; the graded field's own citation is injected
        by code with the exact display value (the AI cannot misquote its
        own field), so the fix loop only polices the claim wording and
        any extra cross-field links."""
        items: List[EvidenceItemModel] = []
        ref_by_id: Dict[str, str] = {}
        counters: Dict[str, int] = {}
        for dimension, dim_refs in refs.items():
            prefix = DIMENSION_PREFIX[dimension]
            for ref in dim_refs:
                grade = sheet.grades[ref]
                if grade.direction == "neutral":
                    continue
                counters[prefix] = counters.get(prefix, 0) + 1
                item_id = f"{prefix}{counters[prefix]}"
                _resolves, value = _payload_value(ref, dimensions)
                own_link = LinkModel(ref=ref, value=display_value(value))
                extra_links = [
                    link for link in grade.links if link.ref.strip() != ref
                ]
                items.append(
                    EvidenceItemModel(
                        id=item_id,
                        dimension=dimension,
                        direction=grade.direction,
                        claim=(grade.claim or "").strip(),
                        links=[own_link, *extra_links],
                        weight=grade.weight,
                        weight_reason=grade.weight_reason,
                    )
                )
                ref_by_id[item_id] = ref
        return items, ref_by_id

    # -- step 2: the code merge --------------------------------------------

    def _assemble(
        self,
        first: Optional["_SheetResult"],
        second: Optional["_SheetResult"],
    ) -> List[Dict[str, Any]]:
        """The merged bullet list, matched by graded field in pure code:
        the first sheet's bullets (authors=2 where the second analyst
        graded the same field the same direction), the second sheet's
        unmatched bullets renumbered in (a different field, or the same
        field graded the OPPOSITE direction — a genuine dispute the
        votes settle), and both sheets' struck bullets kept for the
        audit trail."""
        lead_author = 1
        if first is None:
            first, second = second, None  # the surviving sheet leads
            lead_author = 2
        first_items, first_broken, first_refs = first

        # covered: first-sheet id → the SECOND author's bullet for the
        # same field (how their rating and its reason ride in).
        covered: Dict[str, EvidenceItemModel] = {}
        extra_models: List[EvidenceItemModel] = []
        extra_refs: Dict[str, str] = {}
        extra_broken: Dict[str, List[str]] = {}
        if second is not None:
            second_items, second_broken, second_refs = second
            first_id_by_key = {
                (first_refs[m.id], m.direction): m.id
                for m in first_items
                if m.id not in first_broken
            }
            for model in second_items:
                if model.id in second_broken:
                    extra_models.append(model)
                    extra_refs[model.id] = second_refs[model.id]
                    extra_broken[model.id] = second_broken[model.id]
                    continue
                target = first_id_by_key.get(
                    (second_refs[model.id], model.direction)
                )
                if target is not None:
                    covered[target] = model
                else:
                    extra_models.append(model)
                    extra_refs[model.id] = second_refs[model.id]

        # Renumber second-sheet bullets to continue the first sheet's ids.
        next_number: Dict[str, int] = {}
        for model in first_items:
            prefix = DIMENSION_PREFIX[model.dimension]
            next_number[prefix] = max(
                next_number.get(prefix, 0), int(model.id[len(prefix):])
            )
        items: List[Dict[str, Any]] = []
        for model in first_items:
            second_model = covered.get(model.id)
            items.append(
                self._base_item(
                    model,
                    first_broken.get(model.id),
                    authors=2 if second_model is not None else 1,
                    author_no=lead_author,
                    second_model=second_model,
                    field=first_refs.get(model.id),
                )
            )
        for model in extra_models:
            prefix = DIMENSION_PREFIX[model.dimension]
            next_number[prefix] = next_number.get(prefix, 0) + 1
            renumbered = model.model_copy(update={"id": f"{prefix}{next_number[prefix]}"})
            items.append(
                self._base_item(
                    renumbered,
                    extra_broken.get(model.id),
                    authors=1,
                    author_no=2,
                    field=extra_refs.get(model.id),
                )
            )
        return items

    # -- citation verification + the fix loops -----------------------------

    def _text_link_errors(
        self,
        links: Sequence[Any],
        sentence: str,
        where_prefix: str,
        dimensions: Sequence[DimensionResult],
    ) -> List[str]:
        """Everything code checks about one sentence's links, phrased for
        the fix prompt. Empty list → the citations are good."""
        errors: List[str] = []
        for link in links:
            ref = link.ref.strip()
            where = f"{where_prefix} link {ref!r}"
            resolves, actual = _payload_value(ref, dimensions)
            if not resolves:
                errors.append(f"{where}: does not resolve to a single report value")
                continue
            if _is_textual_ref(ref, dimensions):
                continue  # a news-event anchor; no display value to copy
            expected = display_value(actual)
            claimed = _link_value_text(link.value)
            if not _values_equal(claimed, expected):
                errors.append(
                    f"{where}: claimed value {claimed!r} must be copied exactly "
                    f"as the report displays it: {expected!r}"
                )
                continue
            if not _value_in_text(expected, sentence):
                errors.append(
                    f"{where}: the value {expected!r} must appear in the "
                    "sentence exactly as the report displays it"
                )
        return errors

    def _link_errors(
        self, item: EvidenceItemModel, dimensions: Sequence[DimensionResult]
    ) -> List[str]:
        return self._text_link_errors(
            item.links, item.claim, f"item {item.id}", dimensions
        )

    def _vote_errors(
        self, key: str, vote: VoteModel, dimensions: Sequence[DimensionResult]
    ) -> List[str]:
        reason = vote.reason or ""
        errors = self._text_link_errors(
            vote.links, reason, f"vote {key}", dimensions
        )
        if _NUMERIC_REASON_RE.search(reason) and not vote.links:
            errors.append(
                f"vote {key}: the reason states a number — cite it with a link"
            )
        return errors

    def _fix_citations(
        self,
        items: Sequence[EvidenceItemModel],
        dimensions: Sequence[DimensionResult],
        stage: str,
        warnings: List[str],
    ) -> Tuple[List[EvidenceItemModel], Dict[str, List[str]]]:
        """Run the code citation check, send broken bullets back to the
        same AI (only the broken ones), splice fixes in, repeat up to
        MAX_FIX_ROUNDS. Returns (items with fixes applied, still-broken
        id → errors). Successful fixes leave no trace — the UI shows only
        the end state."""
        fixed = list(items)
        index_by_id = {item.id: index for index, item in enumerate(fixed)}
        broken: Dict[str, List[str]] = {}
        for item in fixed:
            errors = self._link_errors(item, dimensions)
            if errors:
                broken[item.id] = errors
        rounds = 0
        while broken and rounds < MAX_FIX_ROUNDS:
            rounds += 1
            prompt = self.CITATION_FIX_TEMPLATE.format(
                evidence=evidence_block(dimensions, display=True),
                link_rules=self.LINK_RULES,
                bullets=_items_json([fixed[index_by_id[i]] for i in broken]),
                errors="\n".join(
                    f"- {item_id}: {'; '.join(errors)}"
                    for item_id, errors in broken.items()
                ),
            )
            raw = summarize_with_schema(
                self._summarize, prompt, self.FIX_ITEMS_MODEL
            )
            parsed = parse_llm_json(raw)
            if parsed is None:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            try:
                reply = self.FIX_ITEMS_MODEL.model_validate(parsed)
            except ValidationError:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            for candidate in reply.items:
                if candidate.id not in broken:
                    continue  # untouched bullets must not be churned
                original = fixed[index_by_id[candidate.id]]
                if candidate.dimension != original.dimension:
                    continue  # id and dimension are frozen
                # The author's importance rating is frozen too — a fix
                # round is about citations, and a reply that omits
                # "weight" must not silently reset a 5 to the default.
                candidate = candidate.model_copy(
                    update={
                        "weight": original.weight,
                        "weight_reason": original.weight_reason,
                    }
                )
                fixed[index_by_id[candidate.id]] = candidate
                errors = self._link_errors(candidate, dimensions)
                if errors:
                    broken[candidate.id] = errors
                else:
                    del broken[candidate.id]
        return fixed, broken

    def _fix_votes(
        self,
        votes: Dict[str, VoteModel],
        dimensions: Sequence[DimensionResult],
        stage: str,
        warnings: List[str],
    ) -> Dict[str, VoteModel]:
        """The same fix loop for vote reasons. Votes still broken after
        the rounds are DISCARDED (with a warning) — an objection that
        cannot back its numbers carries no weight."""
        fixed = dict(votes)
        broken: Dict[str, List[str]] = {}
        for key, vote in fixed.items():
            errors = self._vote_errors(key, vote, dimensions)
            if errors:
                broken[key] = errors
        rounds = 0
        while broken and rounds < MAX_FIX_ROUNDS:
            rounds += 1
            prompt = self.VOTE_FIX_TEMPLATE.format(
                evidence=evidence_block(dimensions, display=True),
                vote_rules=self.VOTE_RULES,
                votes=json.dumps(
                    {key: fixed[key].model_dump(exclude_none=True) for key in broken},
                    ensure_ascii=False,
                    indent=1,
                ),
                errors="\n".join(
                    f"- {key}: {'; '.join(errors)}" for key, errors in broken.items()
                ),
            )
            # Votes key on run-time bullet ids — JSON mode, not schema.
            raw = summarize_with_schema(self._summarize, prompt, JSON_REPLY)
            parsed = parse_llm_json(raw)
            if parsed is None:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            try:
                reply = VoteFixModel.model_validate(parsed)
            except ValidationError:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            for key, candidate in reply.votes.items():
                if key not in broken:
                    continue
                # The voter's importance rating is frozen through fixes
                # (same reason as bullet weights: no silent resets).
                fixed[key] = candidate.model_copy(
                    update={
                        "weight": fixed[key].weight,
                        "weight_reason": fixed[key].weight_reason,
                    }
                )
                errors = self._vote_errors(key, candidate, dimensions)
                if errors:
                    broken[key] = errors
                else:
                    del broken[key]
        for key in broken:
            warnings.append(
                f"vote on {key} discarded — citations unfixable after "
                f"{MAX_FIX_ROUNDS} fix attempts"
            )
            del fixed[key]
        return fixed

    # -- steps 3-4: the vote rounds ----------------------------------------

    def _vote_round(
        self,
        prompt: str,
        required_ids: List[str],
        dimensions: Sequence[DimensionResult],
        stage: str,
        warnings: List[str],
    ) -> Optional[Dict[str, VoteModel]]:
        def parse(parsed: dict) -> VoteRoundModel:
            model = VoteRoundModel.model_validate(parsed)
            check_exact_keys(list(model.votes), required_ids, "votes")
            return model

        model, stage_warnings = self._call_validated(prompt, parse, stage)
        warnings.extend(stage_warnings)
        if model is None:
            return None
        return self._fix_votes(model.votes, dimensions, stage, warnings)

    @staticmethod
    def _attach_votes(
        items: List[Dict[str, Any]], votes: Dict[str, VoteModel], role: str
    ) -> None:
        by_id = {item["id"]: item for item in items}
        for key, vote in votes.items():
            reason = (vote.reason or "").strip()
            by_id[key]["votes"].append(
                {
                    "role": role,
                    "validity": vote.validity,
                    "reason": reason or None,
                    "weight": vote.weight,
                    "weight_reason": vote.weight_reason,
                    "links": [
                        _link_detail(link) for link in vote.links
                    ],
                }
            )

    @staticmethod
    def _vote_by_role(item: Dict[str, Any], role: str) -> Optional[Dict[str, Any]]:
        return next((v for v in item["votes"] if v["role"] == role), None)

    def _is_tied(self, item: Dict[str, Any]) -> bool:
        """1-1: the author's implicit valid vote vs an invalid check vote."""
        if item["struck"] or item["authors"] >= 2:
            return False
        checker = self._vote_by_role(item, "checker")
        return checker is not None and checker["validity"] == "invalid"

    def _apply_outcomes(
        self, items: List[Dict[str, Any]], warnings: List[str]
    ) -> None:
        """Majority of votes decides; the author is always a valid vote."""
        for item in items:
            if item["struck"]:
                continue  # excluded by code before any voting
            if item["authors"] >= 2:
                item["final_status"] = "counted"  # 2-0 at birth
                continue
            checker = self._vote_by_role(item, "checker")
            if checker is None or checker["validity"] == "valid":
                # No second vote cast (degraded/discarded) → the author's
                # vote stands unopposed; a valid check vote → 2-0.
                item["final_status"] = "counted"
                continue
            decider = self._vote_by_role(item, "decider")
            if decider is None:
                item["final_status"] = "excluded"
                item["exclusion_reason"] = "unresolved"
                warnings.append(
                    f"no deciding vote for {item['id']} — excluded as unresolved"
                )
            elif decider["validity"] == "valid":
                item["final_status"] = "counted"  # 2-1
            else:
                item["final_status"] = "excluded"  # 1-2
                item["exclusion_reason"] = "outvoted"

    # -- step 5 ------------------------------------------------------------

    def _summary_link_errors(
        self,
        model: StructuredSummaryModel,
        dimensions: Sequence[DimensionResult],
    ) -> Dict[str, List[str]]:
        """The evidence-list citation contract, applied to every report
        sentence: links verify mechanically, and a sentence that states a
        report-style number must carry one."""
        errors: Dict[str, List[str]] = {}

        def check(where: str, text: str, links: Sequence[LinkModel]) -> None:
            sentence_errors = self._text_link_errors(links, text, where, dimensions)
            if _NUMERIC_REASON_RE.search(text) and not links:
                sentence_errors.append(
                    f"{where}: the sentence states a number — cite it with a link"
                )
            if sentence_errors:
                errors[where] = sentence_errors

        for group in ("summary",) + DIMENSIONS:
            for index, bullet in enumerate(getattr(model, group)):
                where = f"{group}[{index}]"
                check(where, bullet.text, bullet.links)
                for child_index, child in enumerate(bullet.children):
                    check(f"{where}.child[{child_index}]", child.text, child.links)
        return errors

    @staticmethod
    def _prune_summary_links(
        model: StructuredSummaryModel,
        keep: Callable[[str, Sequence[LinkModel]], List[LinkModel]],
    ) -> StructuredSummaryModel:
        """A copy with each sentence's links filtered through ``keep``."""
        update: Dict[str, Any] = {}
        for group in ("summary",) + DIMENSIONS:
            bullets = []
            for bullet in getattr(model, group):
                bullets.append(
                    bullet.model_copy(
                        update={
                            "links": keep(bullet.text, bullet.links),
                            "children": [
                                child.model_copy(
                                    update={"links": keep(child.text, child.links)}
                                )
                                for child in bullet.children
                            ],
                        }
                    )
                )
            update[group] = bullets
        return model.model_copy(update=update)

    def _summary(
        self,
        context: str,
        items: Sequence[Dict[str, Any]],
        final: float,
        pools: Dict[str, Any],
        direction: Direction,
        data_dimensions: Sequence[str],
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """(flat text for legacy consumers, fixed-outline dump) — both
        empty/None when the stage failed; the computed outlook stands."""
        prompt = _SUMMARY_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            final=f"{final:.2f}",
            final_bullish=pools["final"]["bullish"],
            final_bearish=pools["final"]["bearish"],
            final_total=pools["final"]["total"],
            final_bullish_weight=pools["final"]["bullish_weight"],
            final_total_weight=pools["final"]["total_weight"],
            outlook=_OUTLOOK_WORD.get(direction, "neutral"),
            fill_groups=", ".join(
                dim for dim in DIMENSIONS if dim in data_dimensions
            ) or "none",
        )

        def parse(parsed: dict) -> StructuredSummaryModel:
            # A group the model left out counts as empty; whether it was
            # allowed to be empty is check_summary_groups' call.
            filled = {**{group: [] for group in DIMENSIONS}, **parsed}
            model = StructuredSummaryModel.model_validate(filled)
            check_summary_groups(model, data_dimensions)
            return model

        try:
            model, stage_warnings = self._call_validated(
                prompt, parse, "report outline",
                schema=StructuredSummaryModel,  # fixed outline: enforceable
            )
            if model is None:
                # Keep the long-standing wording (and its friendly gloss)
                # instead of the stage's voided-sounding warnings — a
                # summary failure never voids the computed outlook.
                warnings.append("judge summary unparseable — computed outlook stands")
                return "", None
            warnings.extend(stage_warnings)

            # The citation fix loop, same mechanics as bullets and votes:
            # broken links go back to the AI; links still broken after
            # the rounds are dropped (the sentence stays, unlinked).
            errors = self._summary_link_errors(model, dimensions)
            rounds = 0
            while errors and rounds < MAX_FIX_ROUNDS:
                rounds += 1
                fix_prompt = (
                    f"{prompt}\n\nYour previous summary failed the code's "
                    "citation check:\n"
                    + "\n".join(
                        f"- {where}: {'; '.join(sentence_errors)}"
                        for where, sentence_errors in errors.items()
                    )
                    + "\nReply again with the FULL corrected JSON, same shape. "
                    "JSON only."
                )
                parsed = parse_llm_json(summarize_with_schema(
                    self._summarize, fix_prompt, StructuredSummaryModel
                ))
                if parsed is None:
                    warnings.append(
                        "summary citation-fix reply invalid — fix round lost"
                    )
                    continue
                try:
                    model = parse(parsed)
                except (ValidationError, ValueError):
                    warnings.append(
                        "summary citation-fix reply invalid — fix round lost"
                    )
                    continue
                errors = self._summary_link_errors(model, dimensions)
            if errors:
                model = self._prune_summary_links(
                    model,
                    lambda text, links: [
                        link
                        for link in links
                        if not self._text_link_errors([link], text, "x", dimensions)
                    ],
                )
                warnings.append(
                    "summary citations unfixable — those values are shown "
                    "without links"
                )
        except Exception as exc:
            warnings.append(f"summary LLM call failed: {exc} — computed outlook stands")
            return "", None
        return _flatten_summary(model), model.model_dump()

    # -- shared plumbing ---------------------------------------------------

    def _call_validated(
        self, prompt: str, parse: _StageParse, stage: str,
        schema: Any = JSON_REPLY,
    ) -> Tuple[Optional[Any], List[str]]:
        """One LLM call against a Pydantic form, with ONE retry that shows
        the model its validation errors. Returns (model|None, warnings).

        ``schema`` is handed to the provider for decode-time enforcement
        (2026-08-25): the default ``JSON_REPLY`` guarantees valid JSON —
        most debate forms key on run-time ids (one grade per field ref,
        one vote per bullet id), which no decode-time schema can name —
        and fixed-shape stages pass their pydantic form for full
        enforcement."""
        error = None
        raw = summarize_with_schema(self._summarize, prompt, schema)
        parsed = parse_llm_json(raw)
        if parsed is None:
            error = "the reply was not a JSON object"
        else:
            try:
                return parse(parsed), []
            except (ValidationError, ValueError) as exc:
                error = _validation_text(exc)

        retry_prompt = (
            f"{prompt}\n\nYour previous reply was invalid: {error}\n"
            "Reply again, following the JSON shape exactly. JSON only."
        )
        raw = summarize_with_schema(self._summarize, retry_prompt, schema)
        parsed = parse_llm_json(raw)
        if parsed is None:
            return None, [f"{stage} was not JSON even after a retry"]
        try:
            return (
                parse(parsed),
                [f"{stage} needed a retry — first reply was invalid"],
            )
        except (ValidationError, ValueError) as exc:
            return None, [f"{stage} invalid after retry: {_validation_text(exc)}"]

    @staticmethod
    def _base_item(
        model: EvidenceItemModel,
        problems: Optional[List[str]],
        authors: int,
        author_no: int = 1,
        second_model: Optional[EvidenceItemModel] = None,
        field: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One list bullet. ``problems`` non-empty → the bullet is struck:
        code could not fix its citations, so it renders crossed out and
        never enters a pool. ``authors`` = how many analysts listed it
        independently (2 = confirmed at birth); ``author_no`` = which
        lister wrote it (1 or 2); ``second_model`` is the second lister's
        own bullet for the same evidence when both listed it; ``field``
        is the report field ref the bullet grades (v12)."""
        struck = bool(problems)
        author_votes = [
            {
                "lister": author_no,
                "weight": model.weight,
                "weight_reason": model.weight_reason,
            }
        ]
        if second_model is not None:
            author_votes.append(
                {
                    "lister": 2,
                    "weight": second_model.weight,
                    "weight_reason": second_model.weight_reason,
                }
            )
        author_weights = [vote["weight"] for vote in author_votes]
        return {
            "id": model.id,
            "dimension": model.dimension,
            "field": field,
            "direction": model.direction,
            "claim": model.claim.strip(),
            "links": [_link_detail(link) for link in model.links],
            "struck": struck,
            "problems": list(problems or []),
            "authors": authors,
            # Per-lister rating detail (v11) and the bare weight list the
            # pools consume (kept alongside, same order).
            "author_votes": author_votes,
            "author_weights": author_weights,
            # The final median of every voter's rating — filled once all
            # the votes are in (None while struck: no pool, no weight).
            "weight": None,
            "votes": [],
            "final_status": "excluded" if struck else None,
            "exclusion_reason": "citation_failed" if struck else None,
        }


# ---------------------------------------------------------------------------
# Pool counting
# ---------------------------------------------------------------------------


def _median_weight(weights: Sequence[float]) -> Optional[float]:
    """The median of the voters' 1-5 ratings; an even count takes the
    mean of the middle two, so halves (2.5) happen. Whole results come
    back as ints so the stored JSON stays clean."""
    if not weights:
        return None
    ordered = sorted(weights)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        value = float(ordered[middle])
    else:
        value = (ordered[middle - 1] + ordered[middle]) / 2.0
    return int(value) if value.is_integer() else value


def _pool_detail(items, weight_of) -> Dict[str, Any]:
    """Weighted counting: 10 × Σweight(bullish) / Σweight(all) over the
    whole pool, ``weight_of`` supplying each bullet's weight. The
    per-dimension counts and weight sums feed the section headers
    (`Technicals: ↑3 ↓4`)."""
    per_dimension: Dict[str, Dict[str, Any]] = {}
    for item in items:
        stats = per_dimension.setdefault(
            item["dimension"],
            {"bullish": 0, "bearish": 0, "total": 0,
             "bullish_weight": 0, "bearish_weight": 0, "total_weight": 0},
        )
        side = "bullish" if item["direction"] == "bullish" else "bearish"
        weight = weight_of(item)
        stats["total"] += 1
        stats[side] += 1
        stats["total_weight"] += weight
        stats[f"{side}_weight"] += weight
    bullish = bearish = total = 0
    bullish_weight = bearish_weight = total_weight = 0
    for dimension in DIMENSIONS:
        stats = per_dimension.get(dimension)
        if not stats:
            continue
        for key in ("total_weight", "bullish_weight", "bearish_weight"):
            stats[key] = _int_when_whole(stats[key])
        bullish += stats["bullish"]
        bearish += stats["bearish"]
        total += stats["total"]
        bullish_weight += stats["bullish_weight"]
        bearish_weight += stats["bearish_weight"]
        total_weight += stats["total_weight"]
    return {
        "dimensions": per_dimension,
        "bullish": bullish,
        "bearish": bearish,
        "total": total,
        "bullish_weight": _int_when_whole(bullish_weight),
        "bearish_weight": _int_when_whole(bearish_weight),
        "total_weight": _int_when_whole(total_weight),
        "score": round(10 * bullish_weight / total_weight, 2)
        if total_weight
        else None,
    }


def _int_when_whole(value: float) -> float:
    return int(value) if float(value).is_integer() else value


# ---------------------------------------------------------------------------
# Prompt-side rendering helpers
# ---------------------------------------------------------------------------


def _validation_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return "; ".join(parts) or str(exc)
    return str(exc)


def _link_detail(link) -> Dict[str, Any]:
    """The stored link shape: the ref plus its display-string value."""
    return {"ref": link.ref.strip(), "value": _link_value_text(link.value)}


def _items_json(items: Sequence[EvidenceItemModel]) -> str:
    return json.dumps(
        [item.model_dump(exclude_none=True) for item in items],
        ensure_ascii=False,
        indent=1,
    )


def _links_text(links: Sequence[Dict[str, Any]]) -> str:
    parts = []
    for link in links:
        if link.get("value") is not None:
            parts.append(f"{link['ref']} = {link['value']}")
        else:
            parts.append(link["ref"])
    return "; ".join(parts)


def _vote_text(vote: Dict[str, Any]) -> str:
    text = vote["validity"]
    if vote["reason"]:
        text += f" — {vote['reason']}"
    if vote["links"]:
        text += f" [{_links_text(vote['links'])}]"
    return text


def _tree_text(items: Sequence[Dict[str, Any]]) -> str:
    """The merged list as indented text for the vote/summary prompts.
    Struck bullets sit out and are omitted."""
    lines: List[str] = []
    for dimension in DIMENSIONS:
        group = [
            i for i in items if i["dimension"] == dimension and not i["struck"]
        ]
        if not group:
            continue
        lines.append(f"- {dimension}")
        for item in group:
            source = (
                "listed by BOTH analysts" if item["authors"] >= 2 else "one analyst"
            )
            lines.append(
                f"  - [{item['id']}] ({item['direction']}, {source}) {item['claim']}"
            )
            if item["links"]:
                lines.append(f"    links: {_links_text(item['links'])}")
            for vote in item["votes"]:
                lines.append(f"    - {vote['role']} vote: {_vote_text(vote)}")
    return "\n".join(lines) if lines else "(no evidence was listed)"


def _disputes_text(tied_items: Sequence[Dict[str, Any]]) -> str:
    """Claim + objection for every tied bullet, for the deciding prompt."""
    lines: List[str] = []
    for item in tied_items:
        checker = next(v for v in item["votes"] if v["role"] == "checker")
        lines.append(
            f"- [{item['id']}] claim ({item['direction']}): {item['claim']}\n"
            f"  objection: {checker['reason'] or '(no reason given)'}"
        )
    return "\n".join(lines) if lines else "(none)"
