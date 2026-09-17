# -*- coding: utf-8 -*-
"""Offline tests for the tier-1 quick judge (the one-call outlook that
replaced the legacy DSA-blob delegate, 2026-08-10). No LLM, no network."""
from __future__ import annotations

import unittest

from src.tiered_analysis.debate import HOLD_MAX, SELL_BELOW
from src.tiered_analysis.llm_support import LlmConfigError
from src.tiered_analysis.providers.base import (
    DimensionResult,
    SourceKind,
)
from src.tiered_analysis.quick_judge import (
    MAX_ATTEMPTS,
    QUICK_DETAIL_FORMAT,
    QuickJudge,
    QuickResult,
    QuickOutlook,
)
from src.tiered_analysis.schema import Direction


def _dims():
    return [
        DimensionResult(
            dimension="technicals",
            kind=SourceKind.NUMERIC,
            payload={"rsi_14": 56.28},
        ),
        DimensionResult(
            dimension="macro_econ",
            kind=SourceKind.TEXTUAL,
            payload={"headline": "rates unchanged"},
        ),
    ]


def _run(summarizer, hold_weeks=3):
    return QuickJudge(summarizer=summarizer).run(
        "AAPL", _dims(), hold_weeks=hold_weeks
    )


class TestPrompt(unittest.TestCase):
    def test_prompt_carries_hold_time_and_evidence_but_no_plan_levels(self):
        prompts = []

        def summarizer(prompt):
            prompts.append(prompt)
            return '{"score": 7, "summary": "Looks constructive overall."}'

        _run(summarizer, hold_weeks=3)

        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        self.assertIn("3 weeks", prompt)
        self.assertIn("AAPL", prompt)
        # Plan levels are not the judge's business (2026-09-16).
        self.assertNotIn("plan levels", prompt)
        self.assertNotIn("entry=", prompt)
        self.assertIn("technicals", prompt)
        self.assertIn("56.28", prompt)
        self.assertIn("rates unchanged", prompt)

    def test_single_week_wording(self):
        prompts = []

        def summarizer(prompt):
            prompts.append(prompt)
            return '{"score": 5, "summary": "Mixed picture."}'

        _run(summarizer, hold_weeks=1)
        self.assertIn("1 week", prompts[0])
        self.assertNotIn("1 weeks", prompts[0])


class TestOutlook(unittest.TestCase):
    def test_score_maps_to_direction_with_debate_cutpoints(self):
        cases = [
            (7.4, Direction.BUY),
            (HOLD_MAX, Direction.HOLD),
            (5.0, Direction.HOLD),
            (SELL_BELOW - 0.1, Direction.SELL),
            (0.0, Direction.SELL),
            (10.0, Direction.BUY),
        ]
        for score, expected in cases:
            result = _run(
                lambda p, s=score: f'{{"score": {s}, "summary": "Reasoning."}}'
            )
            self.assertIsNotNone(result.outlook, score)
            self.assertEqual(result.outlook.direction, expected, score)
            self.assertEqual(result.outlook.final_score, round(score, 2))

    def test_score_rounds_to_two_decimals(self):
        result = _run(lambda p: '{"score": 6.666, "summary": "Close call."}')
        self.assertEqual(result.outlook.final_score, 6.67)

    def test_summary_is_stripped(self):
        result = _run(lambda p: '{"score": 7, "summary": "  Padded.  "}')
        self.assertEqual(result.outlook.summary, "Padded.")

    def test_fenced_json_is_accepted(self):
        result = _run(
            lambda p: '```json\n{"score": 7, "summary": "Fenced reply."}\n```'
        )
        self.assertIsNotNone(result.outlook)


class TestFailures(unittest.TestCase):
    def test_bad_reply_retries_with_the_problem_named(self):
        prompts = []

        def summarizer(prompt):
            prompts.append(prompt)
            if len(prompts) == 1:
                return "not json at all"
            return '{"score": 3, "summary": "Bearish on review."}'

        result = _run(summarizer)

        self.assertEqual(len(prompts), 2)
        self.assertIn("rejected", prompts[1])
        self.assertEqual(result.outlook.direction, Direction.SELL)
        self.assertTrue(any("rejected" in w for w in result.warnings))

    def test_out_of_range_or_missing_fields_are_rejected(self):
        for reply in (
            '{"score": 11, "summary": "Too high."}',
            '{"score": -1, "summary": "Too low."}',
            '{"score": "n/a", "summary": "Not a number."}',
            '{"summary": "No score."}',
            '{"score": 7, "summary": ""}',
            '{"score": 7}',
            "[]",
        ):
            result = _run(lambda p, r=reply: r)
            self.assertIsNone(result.outlook, reply)

    def test_all_attempts_bad_means_no_outlook_and_honest_warnings(self):
        calls = []

        def summarizer(prompt):
            calls.append(prompt)
            return "garbage"

        result = _run(summarizer)
        self.assertEqual(len(calls), MAX_ATTEMPTS)
        self.assertIsNone(result.outlook)
        self.assertTrue(any("no outlook" in w for w in result.warnings))

    def test_llm_config_error_stops_immediately(self):
        calls = []

        def summarizer(prompt):
            calls.append(prompt)
            raise LlmConfigError("LITELLM_MODEL is not set")

        result = _run(summarizer)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(result.outlook)
        self.assertTrue(any("LITELLM_MODEL" in w for w in result.warnings))

    def test_transient_llm_crash_is_retried_then_reported(self):
        calls = []

        def summarizer(prompt):
            calls.append(prompt)
            raise RuntimeError("socket closed")

        result = _run(summarizer)
        self.assertEqual(len(calls), MAX_ATTEMPTS)
        self.assertIsNone(result.outlook)
        self.assertTrue(any("socket closed" in w for w in result.warnings))


class TestDetail(unittest.TestCase):
    def test_detail_carries_format_and_outlook_score(self):
        detail = QuickResult(
            outlook=QuickOutlook(
                direction=Direction.BUY, final_score=7.25, summary="Up."
            )
        ).to_detail()
        self.assertEqual(detail["format"], QUICK_DETAIL_FORMAT)
        self.assertEqual(detail["outlook"]["final_score"], 7.25)
        self.assertEqual(detail["outlook"]["direction"], "buy")

    def test_failed_result_detail_has_no_outlook(self):
        detail = QuickResult(warnings=["boom"]).to_detail()
        self.assertEqual(detail["format"], QUICK_DETAIL_FORMAT)
        self.assertNotIn("outlook", detail)


if __name__ == "__main__":
    unittest.main()
