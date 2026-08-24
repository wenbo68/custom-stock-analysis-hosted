# -*- coding: utf-8 -*-
"""Offline tests for ATR stop suggestion + stop precedence (v2 slice 2).

The Tier-1 stop level is LLM-written prose parsed into a number, so before
sizing divides by (entry - stop) it must pass sanity checks; the fallback is
the deterministic entry - k*ATR stop. The chosen source is always labeled.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.stops import (
    DEFAULT_ATR_MULTIPLIER,
    MAX_STOP_DISTANCE_FRACTION,
    StopSource,
    resolve_stop,
    suggest_atr_stop,
)


class TestSuggestAtrStop(unittest.TestCase):
    def test_default_multiplier_is_two(self):
        self.assertEqual(DEFAULT_ATR_MULTIPLIER, 2.0)
        self.assertAlmostEqual(suggest_atr_stop(entry=100.0, atr=3.0), 94.0)

    def test_custom_multiplier(self):
        self.assertAlmostEqual(
            suggest_atr_stop(entry=100.0, atr=3.0, multiplier=1.5), 95.5
        )

    def test_missing_or_bad_inputs_return_none(self):
        self.assertIsNone(suggest_atr_stop(entry=None, atr=3.0))
        self.assertIsNone(suggest_atr_stop(entry=100.0, atr=None))
        self.assertIsNone(suggest_atr_stop(entry=100.0, atr=0.0))
        self.assertIsNone(suggest_atr_stop(entry=100.0, atr=-1.0))
        self.assertIsNone(suggest_atr_stop(entry=0.0, atr=3.0))
        self.assertIsNone(suggest_atr_stop(entry=100.0, atr=3.0, multiplier=0.0))

    def test_stop_that_would_go_nonpositive_returns_none(self):
        # entry 5, atr 3, k=2 -> stop -1: nonsense, refuse rather than clamp.
        self.assertIsNone(suggest_atr_stop(entry=5.0, atr=3.0))


class TestResolveStop(unittest.TestCase):
    def test_sane_level_stop_wins(self):
        resolution = resolve_stop(entry=100.0, level_stop=95.0, atr=3.0)
        self.assertEqual(resolution.source, StopSource.LEVELS)
        self.assertAlmostEqual(resolution.stop_loss, 95.0)
        self.assertEqual(resolution.warnings, [])

    def test_missing_level_stop_falls_back_to_atr(self):
        resolution = resolve_stop(entry=100.0, level_stop=None, atr=3.0)
        self.assertEqual(resolution.source, StopSource.ATR)
        self.assertAlmostEqual(resolution.stop_loss, 94.0)

    def test_level_stop_at_or_above_entry_is_rejected_with_warning(self):
        for bad_stop in (100.0, 105.0):
            resolution = resolve_stop(entry=100.0, level_stop=bad_stop, atr=3.0)
            self.assertEqual(resolution.source, StopSource.ATR)
            self.assertAlmostEqual(resolution.stop_loss, 94.0)
            self.assertTrue(resolution.warnings)

    def test_level_stop_too_far_below_entry_is_rejected_with_warning(self):
        # 25% max distance: a stop at 70 on a 100 entry fails the sanity check.
        self.assertEqual(MAX_STOP_DISTANCE_FRACTION, 0.25)
        resolution = resolve_stop(entry=100.0, level_stop=70.0, atr=3.0)
        self.assertEqual(resolution.source, StopSource.ATR)
        self.assertTrue(any("far" in w.lower() for w in resolution.warnings))

    def test_nonpositive_level_stop_is_rejected_with_warning(self):
        resolution = resolve_stop(entry=100.0, level_stop=-3.0, atr=3.0)
        self.assertEqual(resolution.source, StopSource.ATR)
        self.assertTrue(resolution.warnings)

    def test_no_level_and_no_atr_yields_none_with_warning(self):
        resolution = resolve_stop(entry=100.0, level_stop=None, atr=None)
        self.assertEqual(resolution.source, StopSource.NONE)
        self.assertIsNone(resolution.stop_loss)
        self.assertTrue(resolution.warnings)

    def test_insane_level_and_no_atr_reports_both_problems(self):
        resolution = resolve_stop(entry=100.0, level_stop=120.0, atr=None)
        self.assertEqual(resolution.source, StopSource.NONE)
        self.assertIsNone(resolution.stop_loss)
        self.assertGreaterEqual(len(resolution.warnings), 2)

    def test_missing_entry_yields_none(self):
        resolution = resolve_stop(entry=None, level_stop=95.0, atr=3.0)
        self.assertEqual(resolution.source, StopSource.NONE)
        self.assertIsNone(resolution.stop_loss)
        self.assertTrue(resolution.warnings)

    def test_boundary_stop_exactly_at_max_distance_is_accepted(self):
        resolution = resolve_stop(entry=100.0, level_stop=75.0, atr=3.0)
        self.assertEqual(resolution.source, StopSource.LEVELS)
        self.assertAlmostEqual(resolution.stop_loss, 75.0)


if __name__ == "__main__":
    unittest.main()
