# -*- coding: utf-8 -*-
"""Offline tests for the tier stages and schema helpers.

The legacy Tier1Stage (delegate to the DSA analysis) is retired — tier 1
is the quick judge now (tests in test_tiered_quick_judge.py). No LLM, no
network.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.providers.base import Market
from src.tiered_analysis.schema import (
    Direction,
    SizingSlots,
    TierReport,
    coerce_price,
    extract_price,
)
from src.tiered_analysis.tiers import Tier2Stage, TierState


class TestCoercePrice(unittest.TestCase):
    def test_numeric_passthrough(self):
        self.assertEqual(coerce_price(180.5), 180.5)
        self.assertEqual(coerce_price(178), 178.0)

    def test_numeric_string(self):
        self.assertEqual(coerce_price("195"), 195.0)

    def test_na_and_garbage_return_none(self):
        self.assertIsNone(coerce_price("N/A"))
        self.assertIsNone(coerce_price(""))
        self.assertIsNone(coerce_price(None))
        self.assertIsNone(coerce_price("about 180"))


class TestExtractPrice(unittest.TestCase):
    """Prose fallback — the live AAPL run returned sniper levels as full
    Chinese sentences; the price must be extracted deterministically."""

    def test_strict_values_still_work(self):
        self.assertEqual(extract_price("195"), 195.0)
        self.assertEqual(extract_price(178), 178.0)
        self.assertIsNone(extract_price("N/A"))
        self.assertIsNone(extract_price(None))

    def test_real_live_run_sentences(self):
        cases = [
            ("理想买入点：303.80元（缩量回踩MA5获得支撑，且MA10上穿MA20）", 303.80),
            ("次优买入点：294.70元（回踩MA10获得支撑，且MA10上穿MA20）", 294.70),
            ("止损位：290.00元（跌破MA20或当前价位下方约7%）", 290.00),
            ("目标位：325.00元（心理关口，需配合放量突破）", 325.00),
        ]
        for text, expected in cases:
            self.assertEqual(extract_price(text), expected, text)

    def test_indicator_names_are_not_prices(self):
        # digits glued to letters (MA20, RSI14) must never parse as prices
        self.assertIsNone(extract_price("跌破MA20后止损"))
        self.assertIsNone(extract_price("RSI14 oversold"))

    def test_percentages_are_not_prices(self):
        self.assertIsNone(extract_price("当前价位下方约7%"))

    def test_english_prose(self):
        self.assertEqual(extract_price("$210.50 support zone"), 210.50)


class TestSchema(unittest.TestCase):
    def test_sizing_slots_default_empty(self):
        slots = SizingSlots()
        self.assertIsNone(slots.capital)
        self.assertIsNone(slots.risk_fraction)
        self.assertIsNone(slots.shares)
        self.assertTrue(slots.is_empty)

    def test_direction_from_decision_type(self):
        self.assertEqual(Direction.from_decision_type("buy"), Direction.BUY)
        self.assertEqual(Direction.from_decision_type("hold"), Direction.HOLD)
        self.assertEqual(Direction.from_decision_type("sell"), Direction.SELL)
        self.assertEqual(Direction.from_decision_type("nonsense"), Direction.UNKNOWN)
        self.assertEqual(Direction.from_decision_type(None), Direction.UNKNOWN)

    def test_tier_report_sizing_always_present_and_empty_in_v1(self):
        report = TierReport(
            tier=1,
            symbol="AAPL",
            market=Market.US,
            direction=Direction.BUY,
        )
        self.assertTrue(report.sizing.is_empty)


class TestTier2Failures(unittest.TestCase):
    def test_tier2_without_foundation_report_fails_unknown(self):
        report = Tier2Stage().run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.tier, 2)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("foundation" in w for w in report.warnings))

    def test_tier2_failure_never_falls_back_to_tier1_direction(self):
        # Outlook redesign: a failed vote is UNKNOWN, never the blob's call.
        state = TierState(symbol="AAPL", market=Market.US)
        state.reports[1] = TierReport(
            tier=1, symbol="AAPL", market=Market.US,
            direction=Direction.BUY,
        )
        report = Tier2Stage().run(state)  # no dimensions -> failure
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("re-run" in w for w in report.warnings))


if __name__ == "__main__":
    unittest.main()
