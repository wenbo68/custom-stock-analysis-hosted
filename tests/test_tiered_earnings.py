# -*- coding: utf-8 -*-
"""Offline tests for the warning-only next-earnings-date layer."""
from __future__ import annotations

import datetime as dt
import unittest

from src.tiered_analysis.earnings import (
    EARNINGS_WARNING_DAYS,
    EarningsInfo,
    earnings_warning,
    next_earnings_info,
)
from src.tiered_analysis.providers.base import Market

TODAY = dt.date(2026, 7, 20)


class TestNextEarningsInfo(unittest.TestCase):
    def test_picks_first_future_date(self):
        info = next_earnings_info(
            "AAPL", Market.US, today=TODAY,
            fetcher=lambda s: [dt.date(2026, 4, 30), dt.date(2026, 7, 29),
                               dt.date(2026, 10, 29)],
        )
        self.assertEqual(info.next_date, "2026-07-29")
        self.assertEqual(info.days_until, 9)
        self.assertFalse(info.is_near)

    def test_today_counts_as_upcoming(self):
        info = next_earnings_info(
            "AAPL", Market.US, today=TODAY, fetcher=lambda s: [TODAY]
        )
        self.assertEqual(info.days_until, 0)
        self.assertTrue(info.is_near)

    def test_within_window_is_near_with_warning(self):
        info = next_earnings_info(
            "AAPL", Market.US, today=TODAY,
            fetcher=lambda s: [TODAY + dt.timedelta(days=EARNINGS_WARNING_DAYS)],
        )
        self.assertTrue(info.is_near)
        warning = earnings_warning(info)
        self.assertIsNotNone(warning)
        self.assertIn("expect turbulence", warning)
        self.assertIn(info.next_date, warning)

    def test_outside_window_no_warning(self):
        info = next_earnings_info(
            "AAPL", Market.US, today=TODAY,
            fetcher=lambda s: [TODAY + dt.timedelta(days=30)],
        )
        self.assertFalse(info.is_near)
        self.assertIsNone(earnings_warning(info))

    def test_only_past_dates_yields_note(self):
        info = next_earnings_info(
            "AAPL", Market.US, today=TODAY,
            fetcher=lambda s: [dt.date(2026, 4, 30)],
        )
        self.assertIsNone(info.next_date)
        self.assertIn("no upcoming", info.note)

    def test_non_us_market_is_a_quiet_gap(self):
        info = next_earnings_info("600519", Market.CN, today=TODAY)
        self.assertIsNone(info.next_date)
        self.assertIn("not yet available", info.note)

    def test_fetch_failure_never_raises(self):
        def _boom(symbol):
            raise RuntimeError("api down")

        info = next_earnings_info("AAPL", Market.US, today=TODAY, fetcher=_boom)
        self.assertIsNone(info.next_date)
        self.assertIn("api down", info.note)

    def test_detail_is_json_ready(self):
        import json

        info = next_earnings_info(
            "AAPL", Market.US, today=TODAY,
            fetcher=lambda s: [TODAY + dt.timedelta(days=3)],
        )
        detail = info.to_detail()
        json.dumps(detail)
        self.assertEqual(detail["days_until"], 3)
        self.assertTrue(detail["is_near"])
        self.assertEqual(detail["warning_days"], EARNINGS_WARNING_DAYS)


class TestEarningsInfoDefaults(unittest.TestCase):
    def test_empty_info_is_not_near(self):
        self.assertFalse(EarningsInfo().is_near)
        self.assertIsNone(earnings_warning(EarningsInfo()))


if __name__ == "__main__":
    unittest.main()
