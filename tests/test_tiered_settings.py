# -*- coding: utf-8 -*-
"""Offline tests for the sizing settings loader (v2 slice 6).

Sizing is opt-in: absent settings keep it off; malformed values are
dropped with a warning, never silently coerced.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.settings import (
    DEFAULT_REWARD_RISK,
    ENV_CAPITAL,
    ENV_REWARD_RISK,
    ENV_RISK_FRACTION,
    SizingSettings,
    load_sizing_settings,
    merge_overrides,
)


class TestLoadSizingSettings(unittest.TestCase):
    def test_absent_env_means_sizing_off_with_defaults(self):
        settings = load_sizing_settings(env={})
        self.assertFalse(settings.is_enabled)
        self.assertIsNone(settings.capital)
        self.assertIsNone(settings.risk_fraction)
        self.assertEqual(settings.reward_risk, DEFAULT_REWARD_RISK)
        self.assertEqual(settings.warnings, ())

    def test_full_valid_env_parses(self):
        settings = load_sizing_settings(env={
            ENV_CAPITAL: "120000",
            ENV_RISK_FRACTION: "0.01",
            ENV_REWARD_RISK: "2.5",
        })
        self.assertTrue(settings.is_enabled)
        self.assertEqual(settings.capital, 120000.0)
        self.assertEqual(settings.risk_fraction, 0.01)
        self.assertEqual(settings.reward_risk, 2.5)
        self.assertEqual(settings.warnings, ())

    def test_capital_alone_is_not_enabled(self):
        settings = load_sizing_settings(env={ENV_CAPITAL: "50000"})
        self.assertFalse(settings.is_enabled)

    def test_garbage_value_dropped_with_warning(self):
        settings = load_sizing_settings(env={
            ENV_CAPITAL: "lots of money",
            ENV_RISK_FRACTION: "0.01",
        })
        self.assertFalse(settings.is_enabled)
        self.assertIsNone(settings.capital)
        self.assertTrue(any(ENV_CAPITAL in w for w in settings.warnings))

    def test_garbage_optional_value_falls_back_to_default(self):
        settings = load_sizing_settings(env={
            ENV_CAPITAL: "50000",
            ENV_RISK_FRACTION: "0.01",
            ENV_REWARD_RISK: "plenty",
        })
        self.assertTrue(settings.is_enabled)
        self.assertEqual(settings.reward_risk, DEFAULT_REWARD_RISK)
        self.assertTrue(any(ENV_REWARD_RISK in w for w in settings.warnings))

    def test_blank_strings_treated_as_absent(self):
        settings = load_sizing_settings(env={
            ENV_CAPITAL: "  ",
            ENV_RISK_FRACTION: "",
        })
        self.assertFalse(settings.is_enabled)
        self.assertEqual(settings.warnings, ())


class TestMergeOverrides(unittest.TestCase):
    def test_overrides_apply_without_mutating_original(self):
        saved = SizingSettings(capital=100000.0, risk_fraction=0.01)
        merged = merge_overrides(saved, capital=25000.0)
        self.assertEqual(merged.capital, 25000.0)
        self.assertEqual(merged.risk_fraction, 0.01)
        self.assertEqual(saved.capital, 100000.0)  # unchanged

    def test_override_can_enable_sizing_for_one_run(self):
        merged = merge_overrides(
            SizingSettings(), capital=30000.0, risk_fraction=0.02
        )
        self.assertTrue(merged.is_enabled)

    def test_no_overrides_returns_equivalent_settings(self):
        saved = SizingSettings(capital=100000.0, risk_fraction=0.01)
        self.assertEqual(merge_overrides(saved), saved)

    def test_ownership_override_is_per_run_and_defaults_to_zero(self):
        saved = SizingSettings()
        self.assertEqual(saved.ownership, 0)
        merged = merge_overrides(saved, ownership=300)
        self.assertEqual(merged.ownership, 300)
        self.assertEqual(saved.ownership, 0)  # unchanged
        # A negative value can never sneak in as a holding.
        self.assertEqual(merge_overrides(saved, ownership=-5).ownership, 0)


if __name__ == "__main__":
    unittest.main()
