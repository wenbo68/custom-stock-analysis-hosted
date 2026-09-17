# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 evidence vote (v12 — graded sheet).

Fake-LLM tests covering: the vote choreography (two blind analyst GRADE
SHEETS in parallel — one grade per code-enumerated report field,
converted to bullets with a code citation check + fix loop → code merge
by field → check round on single-author bullets → deciding round on 1-1
ties → summary), the deterministic one-grade-per-field contract (a
reply that skips, invents or double-grades a field is rejected and
retried), the vote arithmetic (author = first valid vote; same field
graded the same direction by both = confirmed 2-0; majority of three
decides), the deterministic weighted score (every voter rates a
bullet's importance 1-5; a bullet's weight is the median of its voters'
ratings, mean when there are two; score = 10 × Σweight(bullish) /
Σweight(all); snapshots initial/final), the display-value citation
contract (the graded field's link is injected by code with the exact
display string; the claim must contain it), the vote citation contract
(reasons stating numbers must cite them; unfixable votes are
discarded), struck bullets from either analyst, the Pydantic
retry-once contract, and every failure rule — both sheets failing voids
the verdict (the run has no outlook; no tier-1 fallback), one sheet
failing proceeds with the other, a failed check round counts bullets on the author's
vote alone, a failed deciding round excludes ties as unresolved, and a
broken summary never voids a computed verdict.

The two sheet calls (and their fix loops) run in parallel threads, so
the fake LLM routes replies by prompt content, not call order.
"""
from __future__ import annotations

import json
import threading
import unittest

from src.tiered_analysis.debate import (
    DebateEngine,
    DebateResult,
    DebateVerdict,
    direction_from_final,
    gradable_field_refs,
    value_pattern,
)
from src.tiered_analysis.llm_support import (
    LlmUsageTracker,
    display_value,
    record_llm_usage,
)
from src.tiered_analysis.providers.base import (
    Citation,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.tiers import Tier2Stage, TierState


def _technicals():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        # "macd" is a grouping on purpose: the leaf-only ref rule must
        # reject "technicals.macd" but accept "technicals.macd.signal".
        # "sma_200" is blank on purpose: no grade-sheet row, and a grade
        # landing on it is dropped, not a sheet failure.
        # Gradable rows = 4 (rsi_14, close, score, macd.signal). Display
        # strings: rsi_14 "71.20", close "100", score "68", signal "1.20".
        payload={"rsi_14": 71.2, "close": 100.0, "score": 68,
                 "macd": {"signal": 1.2}, "sma_200": None},
    )


def _positioning():
    return DimensionResult(
        dimension="positioning",
        kind=SourceKind.NUMERIC,
        # Gradable rows = 4. Display strings: "61.55", "3.10", "1.80", "0.92".
        payload={
            "ownership": {"institutional_pct": 61.55},
            "short_interest": {"short_pct_of_float": 3.1, "days_to_cover": 1.8},
            "options": {"put_call_oi_ratio": 0.92},
        },
        citations=[Citation(source_name="FINRA short interest via Yahoo Finance")],
    )


def _dimensions():
    return [_technicals(), _positioning()]


#: The code-enumerated grade-sheet rows for the fixture, in report order.
T_REFS = [
    "technicals.rsi_14",
    "technicals.close",
    "technicals.score",
    "technicals.macd.signal",
]
P_REFS = [
    "positioning.ownership.institutional_pct",
    "positioning.short_interest.short_pct_of_float",
    "positioning.short_interest.days_to_cover",
    "positioning.options.put_call_oi_ratio",
]


def _tier1(direction=Direction.BUY, dimensions=()):
    return TierReport(
        tier=1,
        symbol="AAPL",
        market=Market.US,
        direction=direction,
        score=68,
        levels=SniperLevels(entry=96.0, stop_loss=90.0, take_profit=108.0),
        narrative="buy the pullback",
        dimensions=list(dimensions),
    )


# ---------------------------------------------------------------------------
# Reply builders — the default run:
#   sheet 1: rsi bullish (→ T1), close bearish (→ T2), inst bullish (→ P1),
#            short bearish (→ P2), everything else neutral
#   sheet 2: rsi/inst/short identical (→ covered, confirmed 2-0),
#            score bullish (→ its own T2, unmatched, renumbered T3),
#            days-to-cover bearish (→ its own P3, renumbered P3)
#   check round on T2/T3/P3: T2 voted invalid (→ tied), T3/P3 valid
#   deciding round on T2: valid → counted 2-1
#
# Score (flat counting): initial = final = 10 × 3 bullish / 6 = 5.00 → hold
# ---------------------------------------------------------------------------

RSI_CLAIM = "The 14-day RSI (71.20) is above 70, showing strong momentum."
CLOSE_CLAIM = "The closing price (100) is below the 105 resistance."
SCORE_CLAIM = "The technical score (68) is strong."
INST_CLAIM = "Institutional ownership (61.55) is a solid majority."
SHORT_CLAIM = "Short interest (3.10) rose against the float."
DAYS_CLAIM = "Days to cover (1.80) means shorts can exit quickly."

NEUTRAL = {"direction": "neutral"}


def _grade(direction, claim=None, links=(), weight=2, weight_reason=None):
    if direction == "neutral":
        return dict(NEUTRAL)
    return {"direction": direction, "claim": claim, "links": list(links),
            "weight": weight, "weight_reason": weight_reason}


def _vlink(ref, value):
    return {"ref": ref, "value": value}


SHEET_1 = {
    "technicals.rsi_14": _grade("bullish", RSI_CLAIM),
    "technicals.close": _grade("bearish", CLOSE_CLAIM),
    "technicals.score": NEUTRAL,
    "technicals.macd.signal": NEUTRAL,
    "positioning.ownership.institutional_pct": _grade("bullish", INST_CLAIM),
    "positioning.short_interest.short_pct_of_float": _grade("bearish", SHORT_CLAIM),
    "positioning.short_interest.days_to_cover": NEUTRAL,
    "positioning.options.put_call_oi_ratio": NEUTRAL,
}

SHEET_2 = {
    **SHEET_1,
    "technicals.close": NEUTRAL,
    "technicals.score": _grade("bullish", SCORE_CLAIM),
    "positioning.short_interest.days_to_cover": _grade("bearish", DAYS_CLAIM),
}

#: Sheet 1 with the close claim misquoting the value (report shows 100).
BROKEN_CLOSE_CLAIM = "The closing price (999) is below the 105 resistance."
SHEET_1_BROKEN_CLOSE = {
    **SHEET_1,
    "technicals.close": _grade("bearish", BROKEN_CLOSE_CLAIM),
}


def _item(item_id, dimension, direction, claim, links, weight=2,
          weight_reason=None):
    """A citation-fix reply bullet (the fix loop speaks the item shape)."""
    return {
        "id": item_id,
        "dimension": dimension,
        "direction": direction,
        "claim": claim,
        "links": links,
        "weight": weight,
        "weight_reason": weight_reason,
    }


#: The corrected close bullet a fix round can splice back in.
CLOSE_FIX_ITEM = _item("T2", "technicals", "bearish", CLOSE_CLAIM,
                       [_vlink("technicals.close", "100")])
#: A fix reply that stays broken (link value misquoted).
STILL_BROKEN_T2 = _item("T2", "technicals", "bearish", BROKEN_CLOSE_CLAIM,
                        [_vlink("technicals.close", "999")])


def _vote(verdict="valid", reason=None, links=(), weight=2,
          weight_reason=None):
    return {"verdict": verdict, "reason": reason, "links": list(links),
            "weight": weight, "weight_reason": weight_reason}


def _sheet_reply(grades):
    return json.dumps({"grades": grades})


def _fix(items):
    return json.dumps({"items": items})


def _vote_fix(votes):
    return json.dumps({"votes": votes})


def _check(votes=None):
    return json.dumps(
        {
            "votes": votes
            if votes is not None
            else {
                "T2": _vote("invalid",
                            "A single close below one level is not a trend."),
                "T3": _vote("valid", "The score reading is fair."),
                "P3": _vote("valid", "The 1.80 days-to-cover backs the point.",
                            [_vlink("positioning.short_interest.days_to_cover",
                                    "1.80")]),
            }
        }
    )


def _decider(votes=None):
    return json.dumps(
        {
            "votes": votes
            if votes is not None
            else {
                "T2": _vote("valid",
                            "The bearish reading of the close is defensible."),
            }
        }
    )


def _summary():
    # The fixed five-group outline; the fixture's data dimensions are
    # technicals + positioning, so only those groups carry bullets.
    return json.dumps({
        "summary": [
            {"text": "The evidence splits down the middle.", "children": []},
        ],
        "technicals": [
            {"text": "Trend and momentum point in opposite directions.",
             "children": [{"text": "RSI is neutral.", "links": []}]},
        ],
        "fundamentals": [],
        "positioning": [
            {"text": "Short interest is modest.", "children": []},
        ],
        "macro_econ": [],
    })


def _replies(**overrides):
    replies = {
        "lister1": _sheet_reply(SHEET_1),
        "lister2": _sheet_reply(SHEET_2),
        "check": _check(),
        "decider": _decider(),
        "summary": _summary(),
    }
    replies.update(overrides)
    return replies


# Marker → stage, checked in order — the fix markers must match before
# the generic role openers. The default reply set has no fix entries, so
# an unexpected fix round fails the test loudly.
MARKERS = [
    ("votes failed the code's citation check", "vote_fix"),
    ("bullets failed the code's citation check", "fix"),
    ("summary failed the code's citation check", "summary_fix"),
    ("You are the FIRST analyst", "lister1"),
    ("You are the SECOND analyst", "lister2"),
    ("cast the deciding vote", "decider"),
    ("cast the second vote", "check"),
    ("Write the user-facing report", "summary"),
]

RETRY_MARKER = "Your previous reply was invalid"


def stage_of(prompt):
    for marker, stage in MARKERS:
        if marker in prompt:
            return stage
    raise AssertionError(f"prompt matches no stage: {prompt[:120]}")


class RoutedSummarizer:
    """Routes replies by prompt content; thread-safe (the two sheets and
    their fix loops run in parallel). ``retry_replies`` serve the second
    attempt of a stage."""

    def __init__(self, replies, retry_replies=None):
        self.replies = replies
        self.retry_replies = retry_replies or {}
        self.prompts = []
        self._lock = threading.Lock()

    def __call__(self, prompt):
        with self._lock:
            self.prompts.append(prompt)
        stage = stage_of(prompt)
        if RETRY_MARKER in prompt and stage in self.retry_replies:
            return self.retry_replies[stage]
        reply = self.replies[stage]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def stages(self):
        return [stage_of(p) for p in self.prompts]


def _run(replies=None, retry_replies=None, dimensions=None):
    fake = RoutedSummarizer(replies or _replies(), retry_replies)
    engine = DebateEngine(summarizer=fake)
    dims = dimensions or _dimensions()
    result = engine.run("AAPL", _tier1(dimensions=dims), dims)
    return result, fake


def _item_by_id(result, item_id):
    return next(i for i in result.items if i["id"] == item_id)


# ---------------------------------------------------------------------------


class DirectionBandsTest(unittest.TestCase):
    def test_owner_spec_bands_on_the_two_decimal_score(self):
        self.assertEqual(direction_from_final(0.0), Direction.SELL)
        self.assertEqual(direction_from_final(3.99), Direction.SELL)
        self.assertEqual(direction_from_final(4.0), Direction.HOLD)
        self.assertEqual(direction_from_final(5.0), Direction.HOLD)
        self.assertEqual(direction_from_final(6.0), Direction.HOLD)
        self.assertEqual(direction_from_final(6.01), Direction.BUY)
        self.assertEqual(direction_from_final(10.0), Direction.BUY)


class DisplayValueTest(unittest.TestCase):
    """The Python port must mirror the frontend's formatValue exactly."""

    def test_whole_numbers_stay_whole(self):
        self.assertEqual(display_value(205.0), "205")
        self.assertEqual(display_value(68), "68")
        self.assertEqual(display_value(0), "0")

    def test_decimals_get_two_places(self):
        self.assertEqual(display_value(71.2), "71.20")
        self.assertEqual(display_value(202.23449935913087), "202.23")
        self.assertEqual(display_value(-0.9879906617313091), "-0.99")

    def test_big_numbers_are_worded(self):
        self.assertEqual(display_value(2_500_000), "2.50 million")
        self.assertEqual(display_value(3_200_000_000.0), "3.20 billion")
        self.assertEqual(display_value(1_500_000_000_000.0), "1.50 trillion")

    def test_text_passes_through(self):
        self.assertEqual(display_value("bullish"), "bullish")


class ValuePatternTest(unittest.TestCase):
    """Where a display value counts as "in the sentence"."""

    def test_digit_boundaries_stop_partial_matches(self):
        self.assertIsNone(value_pattern("205").search("price 1205 today"))
        self.assertIsNone(value_pattern("205").search("price 205.4 today"))
        self.assertIsNotNone(value_pattern("205").search("price (205) today"))
        self.assertIsNotNone(value_pattern("205").search("ends at 205."))

    def test_exact_display_string_is_required(self):
        self.assertIsNone(value_pattern("71.20").search("RSI is 71.2 now"))
        self.assertIsNotNone(value_pattern("71.20").search("RSI is 71.20 now"))
        self.assertIsNone(value_pattern("71.20").search("was 271.20 then"))

    def test_thousands_separators_are_tolerated(self):
        self.assertIsNotNone(value_pattern("1234").search("volume of 1,234 shares"))
        self.assertIsNotNone(value_pattern("1234").search("volume of 1234 shares"))

    def test_text_values_are_loose_on_case_and_underscores(self):
        self.assertIsNotNone(value_pattern("golden_cross").search("a Golden Cross formed"))


class GradeSheetRowsTest(unittest.TestCase):
    """Code enumerates the sheet: every citable leaf, in report order."""

    def test_rows_are_the_leaf_refs_in_report_order(self):
        refs = gradable_field_refs(_dimensions())
        self.assertEqual(refs["technicals"], T_REFS)
        self.assertEqual(refs["positioning"], P_REFS)

    def test_envelope_counts_as_one_row_not_three(self):
        # v2 metrics are {name, explanation, value}: one gradable fact.
        # Counting the prose keys would triple every sheet.
        dims = [
            DimensionResult(
                dimension="technicals",
                kind=SourceKind.NUMERIC,
                payload={
                    "price": {
                        "close": {"name": "n", "explanation": "e", "value": 1.0},
                        "high_1y": {"name": "n", "explanation": "e", "value": 2.0},
                    },
                    "daily": {
                        "rsi_14": {"name": "n", "explanation": "e", "value": 3.0},
                    },
                },
            )
        ]
        self.assertEqual(
            gradable_field_refs(dims)["technicals"],
            ["technicals.price.close", "technicals.price.high_1y",
             "technicals.daily.rsi_14"],
        )

    def test_blank_fields_get_no_row(self):
        # A blank field (value null) carries no evidence — code knows why
        # it is blank, so the AI is never asked to grade it.
        dims = [
            DimensionResult(
                dimension="technicals",
                kind=SourceKind.NUMERIC,
                payload={
                    "daily": {
                        "rsi_14": {"name": "n", "explanation": "e", "value": 56.28},
                        "sma_200": {"name": "n", "explanation": "e", "value": None},
                    },
                },
            )
        ]
        self.assertEqual(
            gradable_field_refs(dims)["technicals"], ["technicals.daily.rsi_14"]
        )


class EnvelopeRefResolutionTest(unittest.TestCase):
    """v2 refs land on the envelope path and resolve to its value."""

    def _dims(self, value):
        return [
            DimensionResult(
                dimension="technicals",
                kind=SourceKind.NUMERIC,
                payload={
                    "daily": {
                        "rsi_14": {
                            "name": "RSI (14d)",
                            "explanation": "momentum",
                            "value": value,
                        },
                    },
                },
            )
        ]

    def test_envelope_path_resolves_to_the_value(self):
        from src.tiered_analysis.debate import _payload_value

        resolves, value = _payload_value(
            "technicals.daily.rsi_14", self._dims(56.28)
        )
        self.assertTrue(resolves)
        self.assertEqual(value, 56.28)

    def test_envelope_with_null_value_does_not_resolve(self):
        from src.tiered_analysis.debate import _payload_value

        resolves, _ = _payload_value(
            "technicals.daily.rsi_14", self._dims(None)
        )
        self.assertFalse(resolves)

    def test_group_path_still_rejected(self):
        from src.tiered_analysis.debate import _payload_value

        resolves, _ = _payload_value("technicals.daily", self._dims(56.28))
        self.assertFalse(resolves)


class GradeSheetContractTest(unittest.TestCase):
    """The deterministic one-grade-per-field rule: exact key coverage,
    enforced by code with a retry, not by prompt wording."""

    def test_a_missing_grade_is_rejected_then_retried(self):
        incomplete = {ref: grade for ref, grade in SHEET_1.items()
                      if ref != "technicals.close"}
        result, fake = _run(
            _replies(lister1=_sheet_reply(incomplete)),
            retry_replies={"lister1": _sheet_reply(SHEET_1)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn("missing grade for: technicals.close", retry_prompt)

    def test_an_invented_field_key_is_rejected_then_retried(self):
        invented = {**SHEET_1, "technicals.bogus": _grade("bullish", "Made up.")}
        result, fake = _run(
            _replies(lister1=_sheet_reply(invented)),
            retry_replies={"lister1": _sheet_reply(SHEET_1)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn("unknown grade keys: technicals.bogus", retry_prompt)

    def test_a_grade_on_a_blank_field_is_dropped_not_failed(self):
        # The report text still shows blank fields (value null) and the
        # AIs keep grading them — such grades are dropped silently
        # instead of failing the sheet (owner decision 2026-08-05: this
        # was voiding whole runs).
        with_blank = {
            **SHEET_1,
            "technicals.sma_200": _grade("bullish", "Graded a blank field."),
        }
        result, fake = _run(_replies(lister1=_sheet_reply(with_blank)))
        self.assertIsNotNone(result.verdict)
        self.assertFalse(any(RETRY_MARKER in p for p in fake.prompts))
        self.assertFalse(
            any(i.get("field") == "technicals.sma_200" for i in result.items)
        )

    def test_a_directional_grade_without_a_claim_is_rejected(self):
        claimless = {**SHEET_1, "technicals.score": {"direction": "bullish"}}
        result, fake = _run(
            _replies(lister1=_sheet_reply(claimless)),
            retry_replies={"lister1": _sheet_reply(SHEET_1)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn("has no claim sentence", retry_prompt)

    def test_the_graded_field_link_is_injected_by_code(self):
        # The AI never writes its own field's citation — code attaches
        # {ref, exact display value}, so the ref can never be misquoted.
        result, _ = _run()
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["field"], "technicals.rsi_14")
        self.assertEqual(t1["links"][0],
                         {"ref": "technicals.rsi_14", "value": "71.20"})


class ChoreographyTest(unittest.TestCase):
    def test_full_run_five_calls_and_the_computed_verdict(self):
        result, fake = _run()
        self.assertEqual(
            sorted(fake.stages()),
            sorted(["lister1", "lister2", "check", "decider", "summary"]),
        )
        verdict = result.verdict
        self.assertIsNotNone(verdict)
        # flat counting: 3 bullish of 6 bullets → 5.0
        self.assertEqual(verdict.initial_score, 5.0)
        self.assertEqual(verdict.final_score, 5.0)
        self.assertEqual(verdict.direction, Direction.HOLD)
        # The flat text renders the outline one line per non-empty group;
        # the outline itself rides in summary_structure.
        self.assertEqual(
            verdict.summary,
            "Summary: The evidence splits down the middle.\n"
            "Technicals: Trend and momentum point in opposite directions. "
            "RSI is neutral.\n"
            "Positioning: Short interest is modest.",
        )
        self.assertEqual(
            verdict.summary_structure["summary"],
            [{"text": "The evidence splits down the middle.",
              "links": [], "children": []}],
        )
        self.assertEqual(verdict.summary_structure["fundamentals"], [])
        self.assertEqual(
            verdict.pools["initial"]["dimensions"]["technicals"],
            {"bullish": 2, "bearish": 1, "total": 3,
             "bullish_weight": 4, "bearish_weight": 2, "total_weight": 6},
        )
        self.assertEqual(verdict.pools["final"]["bullish"], 3)
        self.assertEqual(verdict.pools["final"]["bearish"], 3)

    def test_the_two_sheets_run_before_everything_else(self):
        _, fake = _run()
        stages = fake.stages()
        self.assertEqual(sorted(stages[:2]), ["lister1", "lister2"])
        self.assertEqual(stages[2:], ["check", "decider", "summary"])

    def test_same_field_same_direction_is_confirmed_without_any_vote(self):
        result, _ = _run()
        for item_id in ("T1", "P1", "P2"):
            item = _item_by_id(result, item_id)
            self.assertEqual(item["authors"], 2)
            self.assertEqual(item["votes"], [])
            self.assertEqual(item["final_status"], "counted")

    def test_the_unmatched_second_sheet_bullet_is_renumbered_in(self):
        result, _ = _run()
        t3 = _item_by_id(result, "T3")
        self.assertEqual(t3["authors"], 1)
        self.assertEqual(t3["claim"], SCORE_CLAIM)
        self.assertEqual(t3["field"], "technicals.score")
        self.assertEqual(t3["final_status"], "counted")

    def test_a_tied_bullet_carries_both_votes_and_the_majority_wins(self):
        result, _ = _run()
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["authors"], 1)
        self.assertEqual(
            [(v["role"], v["verdict"]) for v in t2["votes"]],
            [("checker", "invalid"), ("decider", "valid")],
        )
        self.assertEqual(t2["final_status"], "counted")  # 2-1

    def test_identical_sheets_skip_both_vote_rounds(self):
        result, fake = _run(_replies(lister2=_sheet_reply(SHEET_1)))
        self.assertEqual(
            sorted(fake.stages()),
            sorted(["lister1", "lister2", "summary"]),
        )
        self.assertTrue(
            any("check round skipped" in w for w in result.warnings)
        )
        for item in result.items:
            self.assertEqual(item["authors"], 2)
            self.assertEqual(item["final_status"], "counted")

    def test_no_ties_skips_the_deciding_round(self):
        votes = {
            "T2": _vote("valid", "Fair reading."),
            "T3": _vote("valid", "Fair reading."),
            "P3": _vote("valid", "Fair reading."),
        }
        result, fake = _run(_replies(check=_check(votes)))
        self.assertNotIn("decider", fake.stages())
        self.assertEqual(len(fake.prompts), 4)
        for item in result.items:
            self.assertEqual(item["final_status"], "counted")

    def test_an_opposite_direction_grade_is_a_dispute_both_face_the_votes(self):
        # The second analyst reads the same RSI field as bearish. Code
        # matches by (field, direction), so the clash never merges — both
        # versions join the list and the votes settle it.
        disputed = {
            **SHEET_2,
            "technicals.rsi_14": _grade(
                "bearish", "The 14-day RSI (71.20) is overbought territory."
            ),
        }
        votes = {
            item_id: _vote("valid", "Fair reading.")
            for item_id in ("T1", "T2", "T3", "T4", "P3")
        }
        result, _ = _run(
            _replies(lister2=_sheet_reply(disputed), check=_check(votes))
        )
        self.assertIsNotNone(result.verdict)
        t1 = _item_by_id(result, "T1")  # the first analyst's bullish RSI
        self.assertEqual(t1["direction"], "bullish")
        self.assertEqual(t1["authors"], 1)
        t3 = _item_by_id(result, "T3")  # the bearish RSI, renumbered in
        self.assertEqual(t3["direction"], "bearish")
        self.assertEqual(t3["field"], "technicals.rsi_14")
        self.assertEqual(t3["final_status"], "counted")


class VoteOutcomeTest(unittest.TestCase):
    """Majority of at most three votes; the author is always valid."""

    def test_outvoted_bullet_is_excluded(self):
        result, _ = _run(
            _replies(decider=_decider({"T2": _vote("invalid", "The objection holds.")}))
        )
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["final_status"], "excluded")  # 1-2
        self.assertEqual(t2["exclusion_reason"], "outvoted")
        # final: 3 bullish of the 5 remaining bullets → 6.0 hold
        self.assertEqual(result.verdict.final_score, 6.0)
        self.assertEqual(result.verdict.direction, Direction.HOLD)

    def test_failed_deciding_round_excludes_ties_as_unresolved(self):
        result, _ = _run(_replies(decider="not json"))
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["final_status"], "excluded")
        self.assertEqual(t2["exclusion_reason"], "unresolved")
        self.assertTrue(
            any("deciding round invalid after retry — tied bullets excluded" in w
                for w in result.warnings)
        )
        self.assertTrue(
            any("no deciding vote for T2" in w for w in result.warnings)
        )

    def test_failed_check_round_counts_bullets_on_the_author_alone(self):
        result, fake = _run(_replies(check="not json"))
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("check round invalid after retry — bullets counted on" in w
                for w in result.warnings)
        )
        self.assertNotIn("decider", fake.stages())
        for item in result.items:
            self.assertEqual(item["final_status"], "counted")

    def test_empty_final_pool_defaults_to_neutral_five(self):
        # Kill the second sheet, then vote every surviving bullet down,
        # ties resolved against — nothing survives to be weighed.
        votes = {
            item_id: _vote("invalid", "Flawed.")
            for item_id in ("T1", "T2", "P1", "P2")
        }
        deciders = {
            item_id: _vote("invalid", "The objection holds.")
            for item_id in ("T1", "T2", "P1", "P2")
        }
        result, _ = _run(
            _replies(
                lister2="not json",
                check=_check(votes),
                decider=_decider(deciders),
            )
        )
        verdict = result.verdict
        self.assertEqual(verdict.pools["final"]["total"], 0)
        self.assertEqual(verdict.final_score, 5.0)
        self.assertEqual(verdict.direction, Direction.HOLD)
        self.assertTrue(any("no surviving evidence to weigh" in w for w in result.warnings))
        self.assertTrue(
            any("the final score rests on a thin base" in w for w in result.warnings)
        )


class WeightTest(unittest.TestCase):
    """v11: every voter rates a bullet 1-5; the bullet's weight is the
    median of its voters' ratings (mean when there are two) and the
    score is 10 × Σweight(bullish) / Σweight(all)."""

    HEAVY_RSI = _grade("bullish", RSI_CLAIM, weight=5,
                       weight_reason="Momentum this strong drives the thesis.")

    def test_a_heavy_bullet_moves_the_weighted_score(self):
        # Both authors rate the bullish RSI a 5 → its weight is 5 while
        # everything else stays 2. Bullish weight 5+2+2=9 of 15 total.
        first = {**SHEET_1, "technicals.rsi_14": self.HEAVY_RSI}
        second = {**SHEET_2, "technicals.rsi_14": self.HEAVY_RSI}
        result, _ = _run(
            _replies(lister1=_sheet_reply(first), lister2=_sheet_reply(second))
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["author_weights"], [5, 5])
        self.assertEqual(t1["weight"], 5)
        self.assertEqual(result.verdict.pools["final"]["bullish_weight"], 9)
        self.assertEqual(result.verdict.pools["final"]["total_weight"], 15)
        self.assertEqual(result.verdict.final_score, round(10 * 9 / 15, 2))

    def test_three_voters_take_the_median(self):
        # T2: author 2, checker invalid 3, decider valid 3 → median 3.
        votes = {
            "T2": _vote("invalid", "A single close below one level is not a trend.",
                        weight=3),
            "T3": _vote("valid", "The score reading is fair."),
            "P3": _vote("valid", "Fair reading."),
        }
        decider = {"T2": _vote("valid", "The bearish reading is defensible.",
                               weight=3)}
        result, _ = _run(_replies(check=_check(votes), decider=_decider(decider)))
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["author_weights"], [2])
        self.assertEqual([v["weight"] for v in t2["votes"]], [3, 3])
        self.assertEqual(t2["weight"], 3)
        # bearish weight 3+2+2=7 of 13 → 10×6/13 bullish.
        self.assertEqual(result.verdict.final_score, round(10 * 6 / 13, 2))

    def test_two_voters_take_the_mean_so_halves_happen(self):
        # T3: its single author rated it 3; the checker rates it 2 → 2.5.
        second = {
            **SHEET_2,
            "technicals.score": _grade("bullish", SCORE_CLAIM, weight=3),
        }
        result, _ = _run(_replies(lister2=_sheet_reply(second)))
        t3 = _item_by_id(result, "T3")
        self.assertEqual(t3["author_weights"], [3])
        self.assertEqual(t3["weight"], 2.5)
        self.assertEqual(result.verdict.pools["final"]["total_weight"], 12.5)

    def test_both_author_ratings_ride_in_on_the_field_match(self):
        # First analyst rates the RSI a 1, the second a 5 → mean 3.
        light = _grade("bullish", RSI_CLAIM, weight=1)
        first = {**SHEET_1, "technicals.rsi_14": light}
        second = {**SHEET_2, "technicals.rsi_14": self.HEAVY_RSI}
        result, _ = _run(
            _replies(lister1=_sheet_reply(first), lister2=_sheet_reply(second))
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["author_weights"], [1, 5])
        self.assertEqual(t1["weight"], 3)

    def test_an_omitted_weight_defaults_to_the_neutral_3(self):
        # Replies without any "weight" keys reproduce flat counting: every
        # weight lands on the 1-5 middle, so the sums cancel out.
        def stripped(sheet):
            return {
                ref: {key: value for key, value in grade.items()
                      if key not in ("weight", "weight_reason")}
                for ref, grade in sheet.items()
            }

        bare = {key: {"verdict": vote["verdict"], "reason": vote["reason"],
                      "links": vote["links"]}
                for key, vote in json.loads(_check())["votes"].items()}
        bare_decider = {key: {"verdict": vote["verdict"],
                              "reason": vote["reason"], "links": vote["links"]}
                        for key, vote in json.loads(_decider())["votes"].items()}
        result, _ = _run(
            _replies(
                lister1=_sheet_reply(stripped(SHEET_1)),
                lister2=_sheet_reply(stripped(SHEET_2)),
                check=_check(bare),
                decider=_decider(bare_decider),
            )
        )
        self.assertIsNotNone(result.verdict)
        self.assertEqual(_item_by_id(result, "T1")["author_weights"], [3, 3])
        self.assertEqual(result.verdict.final_score, 5.0)

    def test_the_author_rating_survives_a_citation_fix(self):
        # The fix reply comes back without the original rating or its
        # reason — code freezes both so they cannot silently reset.
        heavy_broken = {
            **SHEET_1,
            "technicals.close": _grade("bearish", BROKEN_CLOSE_CLAIM,
                                       weight=5, weight_reason="Key level."),
        }
        result, _ = _run(
            _replies(
                lister1=_sheet_reply(heavy_broken),
                fix=_fix([CLOSE_FIX_ITEM]),  # the fixed bullet says weight 2
            )
        )
        t2 = _item_by_id(result, "T2")
        self.assertFalse(t2["struck"])
        self.assertEqual(t2["author_weights"], [5])
        self.assertEqual(t2["author_votes"][0]["weight_reason"], "Key level.")

    def test_author_votes_carry_the_lister_number_and_the_reason(self):
        # v11 attribution: a both-graded field keeps each lister's own
        # rating and reason; a second-sheet extra is lister 2's.
        first = {
            **SHEET_1,
            "technicals.rsi_14": _grade(
                "bullish", RSI_CLAIM, weight=4,
                weight_reason="Strong but not decisive.",
            ),
        }
        second = {**SHEET_2, "technicals.rsi_14": self.HEAVY_RSI}
        result, _ = _run(
            _replies(lister1=_sheet_reply(first), lister2=_sheet_reply(second))
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(
            t1["author_votes"],
            [
                {"lister": 1, "weight": 4,
                 "weight_reason": "Strong but not decisive."},
                {"lister": 2, "weight": 5,
                 "weight_reason": "Momentum this strong drives the thesis."},
            ],
        )
        t2 = _item_by_id(result, "T2")  # single-author, from the first sheet
        self.assertEqual([v["lister"] for v in t2["author_votes"]], [1])
        t3 = _item_by_id(result, "T3")  # renumbered second-sheet extra
        self.assertEqual([v["lister"] for v in t3["author_votes"]], [2])

    def test_vote_score_reasons_are_stored_with_the_votes(self):
        votes = {
            "T2": _vote("invalid",
                        "A single close below one level is not a trend.",
                        weight=4, weight_reason="Levels drive the plan."),
            "T3": _vote("valid", "The score reading is fair."),
            "P3": _vote("valid", "Fair reading."),
        }
        result, _ = _run(_replies(check=_check(votes)))
        t2 = _item_by_id(result, "T2")
        checker = next(v for v in t2["votes"] if v["role"] == "checker")
        self.assertEqual(checker["weight"], 4)
        self.assertEqual(checker["weight_reason"], "Levels drive the plan.")


class StruckBulletTest(unittest.TestCase):
    """Bullets whose citations code cannot fix are struck — crossed out,
    never voted on, in no pool — from either analyst."""

    def test_an_unfixable_first_sheet_bullet_is_struck_and_sits_out(self):
        result, fake = _run(
            _replies(
                lister1=_sheet_reply(SHEET_1_BROKEN_CLOSE),
                fix=_fix([STILL_BROKEN_T2]),
                check=_check({
                    "T3": _vote("valid", "Fair reading."),
                    "P3": _vote("valid", "Fair reading."),
                }),
            )
        )
        self.assertEqual(fake.stages().count("fix"), 3)
        t2 = _item_by_id(result, "T2")
        self.assertTrue(t2["struck"])
        self.assertIsNone(t2["weight"])  # in no pool, so no final weight
        self.assertEqual(t2["final_status"], "excluded")
        self.assertEqual(t2["exclusion_reason"], "citation_failed")
        self.assertTrue(any("must be copied exactly" in p for p in t2["problems"]))
        self.assertTrue(
            any("struck from the list" in w for w in result.warnings)
        )
        # The struck bullet never reaches the votes…
        check_prompt = next(p for p in fake.prompts if stage_of(p) == "check")
        self.assertNotIn("999", check_prompt)
        # …and never enters a pool: initial = T1, P1, P2, T3, P3.
        self.assertEqual(result.verdict.pools["initial"]["total"], 5)
        # flat counting: 3 bullish of the 5 surviving bullets → 6.0
        self.assertEqual(result.verdict.initial_score, 6.0)

    def test_an_unfixable_second_sheet_bullet_is_struck_too(self):
        broken_days = {
            **SHEET_2,
            "positioning.short_interest.days_to_cover": _grade(
                "bearish", "Days to cover (9.99) means shorts can exit quickly."
            ),
        }
        broken_p3_item = _item(
            "P3", "positioning", "bearish",
            "Days to cover (9.99) means shorts can exit quickly.",
            [_vlink("positioning.short_interest.days_to_cover", "9.99")],
        )
        result, fake = _run(
            _replies(
                lister2=_sheet_reply(broken_days),
                fix=_fix([broken_p3_item]),
                check=_check({
                    "T2": _vote("valid", "Fair reading."),
                    "T3": _vote("valid", "Fair reading."),
                }),
            )
        )
        self.assertEqual(fake.stages().count("fix"), 3)
        p3 = _item_by_id(result, "P3")  # renumbered into the tree, struck
        self.assertTrue(p3["struck"])
        self.assertEqual(p3["exclusion_reason"], "citation_failed")
        self.assertEqual(p3["votes"], [])
        self.assertEqual(result.verdict.pools["initial"]["total"], 5)

    def test_a_fixed_bullet_rejoins_without_a_trace(self):
        result, fake = _run(
            _replies(
                lister1=_sheet_reply(SHEET_1_BROKEN_CLOSE),
                fix=_fix([CLOSE_FIX_ITEM]),
            )
        )
        self.assertEqual(fake.stages().count("fix"), 1)
        t2 = _item_by_id(result, "T2")
        self.assertFalse(t2["struck"])
        self.assertEqual(t2["links"][0]["value"], "100")
        self.assertEqual(t2["final_status"], "counted")
        self.assertFalse(any("struck" in w for w in result.warnings))

    def test_the_fix_prompt_carries_only_the_broken_bullets_and_errors(self):
        _, fake = _run(
            _replies(
                lister1=_sheet_reply(SHEET_1_BROKEN_CLOSE),
                fix=_fix([CLOSE_FIX_ITEM]),
            )
        )
        fix_prompt = next(p for p in fake.prompts if stage_of(p) == "fix")
        self.assertIn('"T2"', fix_prompt)
        self.assertIn("999", fix_prompt)
        self.assertNotIn("The 14-day RSI", fix_prompt)  # healthy bullets stay out
        # The claim misquotes the value; the injected link is correct, so
        # the error is "the value must appear in the sentence".
        self.assertIn("must appear in the", fix_prompt)
        self.assertIn("'100'", fix_prompt)  # the correct display string is shown


class VoteCitationTest(unittest.TestCase):
    """Vote reasons follow the same code-checked citation contract."""

    def test_a_numeric_reason_without_links_is_sent_back_to_fix(self):
        votes = {
            "T2": _vote("invalid", "The close of 100.00 tells nothing."),
            "T3": _vote("valid", "Fair reading."),
            "P3": _vote("valid", "Fair reading."),
        }
        fixed = {
            "T2": _vote("invalid",
                        "The close of 100 tells nothing on its own.",
                        [_vlink("technicals.close", "100")]),
        }
        result, fake = _run(
            _replies(check=_check(votes), vote_fix=_vote_fix(fixed))
        )
        self.assertEqual(fake.stages().count("vote_fix"), 1)
        vote_fix_prompt = next(p for p in fake.prompts if stage_of(p) == "vote_fix")
        self.assertIn("states a number — cite it with a link", vote_fix_prompt)
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["votes"][0]["links"][0]["ref"], "technicals.close")
        self.assertEqual(t2["final_status"], "counted")  # decider still saves it

    def test_a_vote_with_an_unfixable_citation_is_discarded(self):
        bad_vote = _vote("invalid", "The close is 999.00 which is wrong.",
                         [_vlink("technicals.close", "999")])
        votes = {
            "T2": bad_vote,
            "T3": _vote("valid", "Fair reading."),
            "P3": _vote("valid", "Fair reading."),
        }
        result, fake = _run(
            _replies(check=_check(votes), vote_fix=_vote_fix({"T2": bad_vote}))
        )
        self.assertEqual(fake.stages().count("vote_fix"), 3)
        self.assertTrue(
            any("vote on T2 discarded — citations unfixable" in w
                for w in result.warnings)
        )
        t2 = _item_by_id(result, "T2")
        # The discarded objection carries no weight: author unopposed.
        self.assertEqual(t2["votes"], [])
        self.assertEqual(t2["final_status"], "counted")
        self.assertNotIn("decider", fake.stages())

    def test_a_vote_link_value_must_match_the_display_string(self):
        votes = {
            "T2": _vote("invalid", "The close of 100 is neutral.",
                        [_vlink("technicals.close", "100.0")]),
            "T3": _vote("valid", "Fair reading."),
            "P3": _vote("valid", "Fair reading."),
        }
        fixed = {
            "T2": _vote("invalid", "The close of 100 is neutral.",
                        [_vlink("technicals.close", "100")]),
        }
        _, fake = _run(_replies(check=_check(votes), vote_fix=_vote_fix(fixed)))
        vote_fix_prompt = next(p for p in fake.prompts if stage_of(p) == "vote_fix")
        self.assertIn("must be copied exactly", vote_fix_prompt)


class RetryContractTest(unittest.TestCase):
    def test_an_invalid_first_reply_is_retried_with_the_errors_shown(self):
        incomplete = {ref: grade for ref, grade in SHEET_1.items()
                      if not ref.startswith("positioning.")}
        result, fake = _run(
            _replies(lister1=_sheet_reply(incomplete)),
            retry_replies={"lister1": _sheet_reply(SHEET_1)},
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("first analyst grade sheet needed a retry" in w
                for w in result.warnings)
        )
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn("missing grade for:", retry_prompt)

    def test_a_link_without_a_value_is_rejected_by_the_form(self):
        crossref = {
            **SHEET_1,
            "technicals.rsi_14": {
                "direction": "bullish",
                "claim": "The 14-day RSI (71.20) is hot while the close (100) holds.",
                "links": [{"ref": "technicals.close"}],  # value missing
                "weight": 2,
            },
        }
        result, fake = _run(
            _replies(lister1=_sheet_reply(crossref)),
            retry_replies={"lister1": _sheet_reply(SHEET_1)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn('must carry "value"', retry_prompt)


class FailureRulesTest(unittest.TestCase):
    def test_both_sheets_invalid_twice_voids(self):
        result, _ = _run(_replies(lister1="not json", lister2="not json"))
        self.assertIsNone(result.verdict)
        self.assertEqual(result.items, [])
        self.assertTrue(
            any("both analyst grade sheets invalid after retry — tier-2 "
                "verdict voided" in w for w in result.warnings)
        )

    def test_one_sheet_invalid_twice_proceeds_with_the_other(self):
        votes = {
            item_id: _vote("valid", "Fair reading.")
            for item_id in ("T1", "T2", "P1", "P2", "P3")
        }
        result, fake = _run(
            _replies(lister1="not json", check=_check(votes))
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("first analyst grade sheet invalid after retry — "
                "proceeding with the other sheet only" in w
                for w in result.warnings)
        )
        # The surviving sheet's bullets are all single-author.
        self.assertEqual(len(result.items), 5)
        for item in result.items:
            self.assertEqual(item["authors"], 1)

    def test_no_gradable_fields_voids_without_any_llm_call(self):
        blank_dims = [
            DimensionResult(
                dimension="technicals",
                kind=SourceKind.NUMERIC,
                payload={
                    "daily": {
                        "rsi_14": {"name": "n", "explanation": "e", "value": None},
                    },
                },
            )
        ]
        result, fake = _run(dimensions=blank_dims)
        self.assertIsNone(result.verdict)
        self.assertEqual(fake.prompts, [])
        self.assertTrue(
            any("no gradable report fields collected" in w
                for w in result.warnings)
        )

    def test_broken_summary_never_voids_a_computed_verdict(self):
        result, _ = _run(_replies(summary="not json"))
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.summary, "")
        self.assertTrue(
            any("judge summary unparseable — computed verdict stands" in w
                for w in result.warnings)
        )

    def test_summary_llm_failure_never_voids_a_computed_verdict(self):
        result, _ = _run(_replies(summary=RuntimeError("llm down")))
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("summary LLM call failed" in w and "computed verdict stands" in w
                for w in result.warnings)
        )

    def test_llm_failure_mid_debate_fails_loud_without_a_verdict(self):
        result, _ = _run(_replies(check=RuntimeError("llm down")))
        self.assertIsNone(result.verdict)
        self.assertTrue(any("debate LLM call failed" in w for w in result.warnings))

    def test_summary_number_without_a_link_goes_through_the_fix_loop(self):
        # First summary states 71.20 with no link → the code check fails →
        # one fix round returns the same sentence properly linked.
        broken = json.dumps({
            "summary": [{"text": "The outlook is neutral.", "links": [],
                         "children": []}],
            "technicals": [{"text": "The 14-day RSI (71.20) runs hot.",
                            "links": [], "children": []}],
            "fundamentals": [],
            "positioning": [{"text": "Short interest is modest.",
                             "links": [], "children": []}],
            "macro_econ": [],
        })
        fixed = json.dumps({
            "summary": [{"text": "The outlook is neutral.", "links": [],
                         "children": []}],
            "technicals": [{"text": "The 14-day RSI (71.20) runs hot.",
                            "links": [{"ref": "technicals.rsi_14",
                                       "value": "71.20"}],
                            "children": []}],
            "fundamentals": [],
            "positioning": [{"text": "Short interest is modest.",
                             "links": [], "children": []}],
            "macro_econ": [],
        })
        result, fake = _run(_replies(summary=broken, summary_fix=fixed))
        self.assertIn("summary_fix", fake.stages())
        bullet = result.verdict.summary_structure["technicals"][0]
        self.assertEqual(bullet["links"],
                         [{"ref": "technicals.rsi_14", "value": "71.20"}])
        self.assertFalse(
            any("summary citations unfixable" in w for w in result.warnings)
        )

    def test_unfixable_summary_links_are_dropped_not_voiding(self):
        # A link pointing at a grouping path never verifies; after the fix
        # rounds it is dropped, the sentence stays, and the verdict stands.
        broken = json.dumps({
            "summary": [{"text": "The outlook is neutral.", "links": [],
                         "children": []}],
            "technicals": [{"text": "MACD looks fine.",
                            "links": [{"ref": "technicals.macd",
                                       "value": "1.20"}],
                            "children": []}],
            "fundamentals": [],
            "positioning": [{"text": "Short interest is modest.",
                             "links": [], "children": []}],
            "macro_econ": [],
        })
        result, _ = _run(_replies(summary=broken, summary_fix=broken))
        self.assertIsNotNone(result.verdict)
        self.assertEqual(
            result.verdict.summary_structure["technicals"][0]["links"], []
        )
        self.assertTrue(
            any("summary citations unfixable" in w for w in result.warnings)
        )


class UsageTrackingTest(unittest.TestCase):
    def test_parallel_sheet_calls_report_into_the_active_tracker(self):
        routed = RoutedSummarizer(_replies())

        def fake(prompt):
            record_llm_usage(10, 5)
            return routed(prompt)

        engine = DebateEngine(summarizer=fake)
        tracker = LlmUsageTracker()
        dims = _dimensions()
        with tracker.activate():
            with tracker.stage("tier2_debate"):
                result = engine.run("AAPL", _tier1(dimensions=dims), dims)
        self.assertIsNotNone(result.verdict)
        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["tier2_debate"]["calls"], 5)
        self.assertEqual(detail["stages"]["tier2_debate"]["prompt_tokens"], 50)

    def test_fix_round_calls_are_counted_too(self):
        routed = RoutedSummarizer(
            _replies(
                lister1=_sheet_reply(SHEET_1_BROKEN_CLOSE),
                fix=_fix([CLOSE_FIX_ITEM]),
            )
        )

        def fake(prompt):
            record_llm_usage(10, 5)
            return routed(prompt)

        engine = DebateEngine(summarizer=fake)
        tracker = LlmUsageTracker()
        dims = _dimensions()
        with tracker.activate():
            with tracker.stage("tier2_debate"):
                result = engine.run("AAPL", _tier1(dimensions=dims), dims)
        self.assertIsNotNone(result.verdict)
        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["tier2_debate"]["calls"], 6)


class PromptContentTest(unittest.TestCase):
    def test_grade_prompts_enumerate_every_field_and_carry_the_rules(self):
        _, fake = _run()
        first = next(p for p in fake.prompts if "You are the FIRST analyst" in p)
        for ref in T_REFS + P_REFS:
            self.assertIn(f"- {ref}", first)
        self.assertIn("EXACTLY one grade per field key", first)
        self.assertIn("invents a field key, or grades a", first)
        self.assertIn("Link rules", first)
        self.assertIn("copied EXACTLY", first)
        self.assertIn("do not wrap them in quotation marks", first)
        self.assertIn("You give no score", first)
        second = next(p for p in fake.prompts if "You are the SECOND analyst" in p)
        self.assertIn("you have NOT seen their work", second)

    def test_the_evidence_block_shows_display_values(self):
        _, fake = _run()
        first = next(p for p in fake.prompts if "You are the FIRST analyst" in p)
        # The model never sees the raw floats — only the display strings.
        self.assertIn('"rsi_14": "71.20"', first)
        self.assertIn('"close": "100"', first)
        self.assertIn('"signal": "1.20"', first)

    def test_check_prompt_names_the_single_author_bullets_only(self):
        _, fake = _run()
        check = next(p for p in fake.prompts if "cast the second vote" in p)
        self.assertIn("T2, T3, P3", check)
        self.assertIn("already code-verified", check)
        self.assertIn("listed by BOTH analysts", check)  # the tree shows authorship
        self.assertIn("Vote rules", check)

    def test_decider_prompt_shows_the_claim_and_the_objection(self):
        _, fake = _run()
        decider = next(p for p in fake.prompts if "cast the deciding vote" in p)
        self.assertIn('"votes" must cover exactly these bullet ids: T2', decider)
        self.assertIn("objection: A single close below one level", decider)
        self.assertIn(CLOSE_CLAIM, decider)

    def test_summary_prompt_carries_the_computed_pool_scores(self):
        _, fake = _run()
        summary = next(p for p in fake.prompts if "Write the user-facing report" in p)
        self.assertNotIn("initial score", summary)
        self.assertIn("final score 5.00", summary)
        self.assertIn("3 bullish vs 3", summary)
        self.assertIn("bearish of 6", summary)
        # The builders rate everything a 2: bullish weight 6 of 12 total.
        self.assertIn("bullish weight 6", summary)
        self.assertIn("of 12 total", summary)
        self.assertIn("outlook: neutral", summary)
        self.assertNotIn("verdict:", summary)

    def test_grade_and_vote_prompts_carry_the_weight_rubric(self):
        _, fake = _run()
        first = next(p for p in fake.prompts if "You are the FIRST analyst" in p)
        self.assertIn("5 (very important", first)
        self.assertIn('"weight": 3', first)  # the grade shape shows it
        self.assertIn('"weight_reason"', first)
        check = next(p for p in fake.prompts if "cast the second vote" in p)
        self.assertIn("regardless of your", check)
        self.assertIn("median of all voters' weights", check)
        self.assertIn('"weight_reason"', check)


class DetailShapeTest(unittest.TestCase):
    def test_to_detail_is_json_ready_with_the_v11_marker(self):
        result, _ = _run()
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        self.assertEqual(detail["format"], 11)
        self.assertNotIn("turns", detail)  # pre-v5 key, removed 2026-09-16
        self.assertEqual(len(detail["items"]), 6)
        # v12 addition: every bullet names the field it grades.
        self.assertEqual(detail["items"][0]["field"], "technicals.rsi_14")
        verdict = detail["verdict"]
        self.assertEqual(verdict["direction"], "hold")
        self.assertEqual(verdict["final_score"], 5.0)
        self.assertEqual(verdict["initial_score"], 5.0)
        self.assertIn("final", verdict["pools"])
        self.assertNotIn("adjusted", verdict["pools"])
        self.assertEqual(verdict["pools"]["final"]["total"], 6)
        # The inert pre-v8 keys are gone (2026-09-16).
        for legacy in ("adjusted_score", "confidence", "scoring", "weight",
                       "reasons_for", "final_score_rounded"):
            self.assertNotIn(legacy, verdict)

    def test_voided_run_still_serializes(self):
        result, _ = _run(_replies(lister1="not json", lister2="not json"))
        detail = result.to_detail()
        json.dumps(detail)
        self.assertIsNone(detail["verdict"])
        self.assertEqual(detail["items"], [])


class _FakeEngine:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def run(self, symbol, tier1, dimensions, hold_weeks=2):
        self.calls.append((symbol, len(list(dimensions))))
        return self._result


class TestTier2Stage(unittest.TestCase):
    def _state(self, tier1=None, dimensions=None):
        state = TierState(symbol="AAPL", market=Market.US)
        if tier1 is not None:
            state.reports[1] = tier1
        if dimensions is not None:
            state.dimensions = dimensions
        return state

    def _verdict_result(self, direction=Direction.HOLD):
        return DebateResult(
            items=[],
            verdict=DebateVerdict(
                direction=direction,
                final_score=6.0,
                summary="ruling",
                initial_score=7.5,
                pools={},
            ),
        )

    def test_verdict_updates_direction_and_keeps_levels(self):
        engine = _FakeEngine(self._verdict_result())
        state = self._state(_tier1(Direction.BUY), dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.tier, 2)
        self.assertEqual(report.warnings, [])  # a clean success carries none
        self.assertEqual(report.direction, Direction.HOLD)  # formula overruled
        self.assertIsNone(report.confidence)  # no judge confidence since v3
        self.assertAlmostEqual(report.levels.entry, 96.0)
        self.assertEqual(report.narrative, "ruling")
        self.assertIsNotNone(report.debate_detail)
        self.assertEqual(report.debate_detail["format"], 11)

    def test_no_verdict_is_unknown_never_tier1_fallback(self):
        # Outlook redesign: a failed vote fails honestly — no silently
        # substituting the one-blob judge's direction.
        engine = _FakeEngine(DebateResult(warnings=["judge exploded"]))
        state = self._state(_tier1(Direction.BUY), dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("re-run" in w for w in report.warnings))

    def test_missing_tier1_report_fails_unknown(self):
        report = Tier2Stage(engine=_FakeEngine(None)).run(self._state())
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("foundation" in w for w in report.warnings))

    def test_no_evidence_skips_engine_entirely(self):
        engine = _FakeEngine(self._verdict_result())
        state = self._state(_tier1(Direction.BUY))  # no dimensions anywhere
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("no collected evidence" in w for w in report.warnings))
        self.assertEqual(engine.calls, [])

    def test_dimensions_fall_back_to_tier1_report(self):
        engine = _FakeEngine(self._verdict_result())
        tier1 = _tier1(Direction.BUY, dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(self._state(tier1))
        self.assertEqual(report.direction, Direction.HOLD)  # verdict landed
        self.assertEqual(engine.calls, [("AAPL", 1)])


# ---------------------------------------------------------------------------
# The company-news dimension (owner decision 2026-08-16): every card
# news event is a gradable row; the value-copy rule is relaxed for news
# refs (the ref anchors the claim), everything else is standard.
# ---------------------------------------------------------------------------

BOND_TEXT = (
    "Alphabet announced a $25 billion bond offering to fund AI expansion."
)
SUIT_TEXT = "A new antitrust lawsuit seeks damages after an adverse ruling."

N_REFS = [
    "company_events.news_coverage.items.0.text",
    "company_events.news_coverage.items.1.text",
]


def _news():
    return DimensionResult(
        dimension="company_events",
        kind=SourceKind.TEXTUAL,
        payload={
            "news_coverage": {
                "window_days": 14,
                "filtered_out": 3,
                "mention_only": 1,
                "score_bar": 4,
                "items": [
                    {"text": BOND_TEXT, "date": "2026-08-07",
                     "publisher": "Yahoo", "citation": 1, "importance": 5},
                    {"text": SUIT_TEXT, "date": "2026-08-03",
                     "publisher": "CNBC", "citation": 2, "importance": 4},
                ],
            }
        },
    )


#: News claims in the analyst's OWN words — they do not contain the
#: item text, which the relaxed contract must accept without a fix round
#: (an unexpected fix round fails the routed fake loudly).
BOND_CLAIM = "Fresh debt funding supports the AI growth story into the hold."
SUIT_CLAIM = "The lawsuit adds legal risk that could weigh on the price."

NEWS_GRADES = {
    N_REFS[0]: _grade("bullish", BOND_CLAIM),
    N_REFS[1]: _grade("bearish", SUIT_CLAIM),
}


def _news_summary():
    # Same outline as _summary() plus the company-news group the extra
    # data dimension requires.
    parsed = json.loads(_summary())
    parsed["company_events"] = [
        {"text": "News flow is mixed: financing support against legal risk.",
         "links": [{"ref": N_REFS[0], "value": "bond offering"}],
         "children": []},
    ]
    return json.dumps(parsed)


class NewsDimensionTest(unittest.TestCase):
    """The company-news card as a debated dimension."""

    def dims(self):
        return [_technicals(), _positioning(), _news()]

    def test_news_rows_are_one_per_event_never_the_counters(self):
        refs = gradable_field_refs(self.dims())
        self.assertEqual(refs["company_events"], N_REFS)
        flat = [ref for rows in refs.values() for ref in rows]
        self.assertNotIn("company_events.news_coverage.window_days", flat)
        self.assertNotIn("company_events.news_coverage.filtered_out", flat)

    def test_item_text_ref_resolves_and_list_paths_do_not(self):
        from src.tiered_analysis.debate import _payload_value

        resolves, value = _payload_value(N_REFS[0], self.dims())
        self.assertTrue(resolves)
        self.assertEqual(value, BOND_TEXT)
        # The bare list is not a leaf; an out-of-range index is nothing.
        self.assertFalse(
            _payload_value("company_events.news_coverage.items", self.dims())[0]
        )
        self.assertFalse(
            _payload_value(
                "company_events.news_coverage.items.9.text", self.dims()
            )[0]
        )

    def test_news_grades_ride_the_full_vote_without_value_copying(self):
        sheet1 = {**SHEET_1, **NEWS_GRADES}
        sheet2 = {**SHEET_2, **NEWS_GRADES}
        replies = _replies(
            lister1=_sheet_reply(sheet1),
            lister2=_sheet_reply(sheet2),
            summary=_news_summary(),
        )
        fake = RoutedSummarizer(replies)
        engine = DebateEngine(summarizer=fake)
        dims = self.dims()
        result = engine.run("AAPL", _tier1(dimensions=dims), dims)

        # Both analysts graded both news rows the same way → confirmed
        # 2-0 at birth, no check votes needed, no fix rounds (the routed
        # fake would fail loudly on an unexpected fix prompt).
        bond = _item_by_id(result, "N1")
        self.assertEqual(bond["dimension"], "company_events")
        self.assertEqual(bond["field"], N_REFS[0])
        self.assertEqual(bond["direction"], "bullish")
        self.assertEqual(bond["claim"], BOND_CLAIM)
        self.assertEqual(bond["authors"], 2)
        self.assertEqual(bond["final_status"], "counted")
        # Code injected the event's own citation: the ref plus the full
        # summary sentence as its value.
        self.assertEqual(bond["links"][0]["ref"], N_REFS[0])
        self.assertEqual(bond["links"][0]["value"], BOND_TEXT)

        suit = _item_by_id(result, "N2")
        self.assertEqual(suit["direction"], "bearish")
        self.assertEqual(suit["final_status"], "counted")

        # News bullets join the pools like any other dimension.
        news_pool = result.verdict.pools["final"]["dimensions"]["company_events"]
        self.assertEqual(news_pool["total"], 2)
        self.assertEqual(news_pool["bullish"], 1)
        self.assertEqual(news_pool["bearish"], 1)
        # And the summary carries the company-news group.
        self.assertTrue(result.verdict.summary_structure["company_events"])
        self.assertIn("Company news:", result.verdict.summary)

    def test_summary_news_links_need_no_value(self):
        # What the prompt asks for and what real models send: the news
        # bullet cites the event by ref alone (or with a null value).
        # Until 2026-09-16 the link model demanded a value here, so every
        # summary that cited a news event was rejected twice and the deep
        # analysis card showed no summary at all.
        parsed = json.loads(_news_summary())
        parsed["company_events"] = [
            {"text": "Financing support: the bond offering.",
             "links": [{"ref": N_REFS[0]}], "children": []},
            {"text": "Legal risk: the antitrust suit.",
             "links": [{"ref": N_REFS[1], "value": None}], "children": []},
        ]
        replies = _replies(
            lister1=_sheet_reply({**SHEET_1, **NEWS_GRADES}),
            lister2=_sheet_reply({**SHEET_2, **NEWS_GRADES}),
            summary=json.dumps(parsed),
        )
        engine = DebateEngine(summarizer=RoutedSummarizer(replies))
        dims = self.dims()
        result = engine.run("AAPL", _tier1(dimensions=dims), dims)

        self.assertFalse(
            any("judge summary unparseable" in w for w in result.warnings),
            result.warnings,
        )
        news_bullets = result.verdict.summary_structure["company_events"]
        self.assertEqual(len(news_bullets), 2)
        self.assertEqual(news_bullets[0]["links"][0]["ref"], N_REFS[0])
        self.assertEqual(news_bullets[1]["links"][0]["ref"], N_REFS[1])

    def test_link_model_still_demands_a_value_for_report_numbers(self):
        from pydantic import ValidationError

        from src.tiered_analysis.debate_models import LinkModel, is_news_item_ref

        self.assertTrue(is_news_item_ref(N_REFS[0]))
        self.assertFalse(is_news_item_ref("technicals.daily.rsi_14"))
        LinkModel(ref=N_REFS[0])  # a news anchor needs no value
        with self.assertRaises(ValidationError):
            LinkModel(ref="technicals.daily.rsi_14")
        with self.assertRaises(ValidationError):
            LinkModel(ref="technicals.daily.rsi_14", value="  ")

    def test_grade_sheet_lists_the_news_rows(self):
        sheet1 = {**SHEET_1, **NEWS_GRADES}
        sheet2 = {**SHEET_2, **NEWS_GRADES}
        replies = _replies(
            lister1=_sheet_reply(sheet1),
            lister2=_sheet_reply(sheet2),
            summary=_news_summary(),
        )
        fake = RoutedSummarizer(replies)
        engine = DebateEngine(summarizer=fake)
        dims = self.dims()
        engine.run("AAPL", _tier1(dimensions=dims), dims)
        lister_prompt = next(
            p for p in fake.prompts if "You are the FIRST analyst" in p
        )
        for ref in N_REFS:
            self.assertIn(f"- {ref}", lister_prompt)
        # The news guidance rides along.
        self.assertIn("NEWS EVENTS", lister_prompt)

    def test_missing_news_grade_fails_the_sheet_shape(self):
        # A sheet that skips a news row is invalid: retried, and with the
        # retry also short it is dropped (the other sheet proceeds).
        short1 = {**SHEET_1, N_REFS[0]: _grade("bullish", BOND_CLAIM)}
        sheet2 = {**SHEET_2, **NEWS_GRADES}
        replies = _replies(
            lister1=_sheet_reply(short1),
            lister2=_sheet_reply(sheet2),
            summary=_news_summary(),
        )
        fake = RoutedSummarizer(
            replies, retry_replies={"lister1": _sheet_reply(short1)}
        )
        engine = DebateEngine(summarizer=fake)
        dims = self.dims()
        result = engine.run("AAPL", _tier1(dimensions=dims), dims)
        self.assertTrue(
            any("first analyst grade sheet invalid" in w
                for w in result.warnings),
            result.warnings,
        )


if __name__ == "__main__":
    unittest.main()
