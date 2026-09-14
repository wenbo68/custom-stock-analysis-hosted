# -*- coding: utf-8 -*-
"""Offline tests for the reformed macro-economic provider (TODO.md truth
2026-08-04): envelope payload, trends, diffs, events, per-day cache.

FRED responses are canned observation lists; caching uses temp dirs. The
live check is the network-marked test at the bottom (needs FRED_API_KEY).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pytest

from src.tiered_analysis.cache_store import MemoryCacheStore
from src.tiered_analysis.providers.base import Market, SourceKind
from src.tiered_analysis.providers.macro_econ import (
    CPI_RELEASE_ID,
    JOBS_RELEASE_ID,
    MacroConfigError,
    MacroEconProvider,
    SERIES_IDS,
    _REQUIRED_FIELDS,
    cpi_yoy_pct,
    next_date_after,
    observations_as_of,
    pct_trend_label,
    trend_label,
)
from src.tiered_analysis.providers.technicals import is_envelope, metric_value

TODAY = date(2026, 7, 7)

# Monthly CPI index, 2025-03 .. 2026-06. YoY now: 320/310 -> +3.23%.
# YoY at the 3-month baseline (<= 2026-03-02 cutoff -> 2026-03 point):
# 318/306 -> +3.92%, so the trend reads "down" (-0.69 beyond the 0.2 band).
CPI_OBS = [
    ("2025-03-01", 306.0), ("2025-04-01", 307.0), ("2025-05-01", 308.0),
    ("2025-06-01", 310.0), ("2025-07-01", 311.0), ("2025-08-01", 312.0),
    ("2025-09-01", 313.0), ("2025-10-01", 314.0), ("2025-11-01", 315.0),
    ("2025-12-01", 316.0), ("2026-01-01", 317.0), ("2026-02-01", 317.5),
    ("2026-03-01", 318.0), ("2026-04-01", 319.0), ("2026-05-01", 319.5),
    ("2026-06-01", 320.0),
]

# (3-months-ago value, latest value) per daily/monthly series.
SERIES_NOW_THEN = {
    "DFF": (4.33, 4.33),          # official rate, unchanged
    "DGS10": (4.00, 4.40),        # +0.40 -> trend up (band 0.25)
    "DGS2": (4.20, 4.00),         # diff vs official: 4.00 - 4.33 = -0.33
    "T10Y2Y": (0.60, 0.40),       # -0.20 -> trend down (band 0.15)
    "BAMLH0A0HYM2": (3.00, 3.10),  # +0.10 -> flat (band 0.25)
    "VIXCLS": (15.00, 17.50),
    "DCOILWTICO": (60.00, 68.20),  # +13.7% -> up (band 5%)
    "DTWEXBGS": (121.00, 120.00),  # -0.83% -> flat (band 2%)
}

RELEASE_DATES = {
    CPI_RELEASE_ID: ["2026-06-10", "2026-07-15", "2026-08-12"],
    JOBS_RELEASE_ID: ["2026-07-02", "2026-08-07"],
}


def _fake_fetcher(calls=None):
    def fetch(series_id):
        if calls is not None:
            calls.append(series_id)
        if series_id == "CPIAUCSL":
            return list(CPI_OBS)
        if series_id == "UNRATE":
            return [("2026-03-01", 4.0), ("2026-06-01", 4.1)]  # +0.1 -> flat
        if series_id in SERIES_NOW_THEN:
            then, now = SERIES_NOW_THEN[series_id]
            return [("2026-04-01", then), ("2026-07-03", now)]
        raise KeyError(series_id)

    return fetch


def _fake_release_dates(release_id):
    return list(RELEASE_DATES[release_id])


class TestPureHelpers(unittest.TestCase):
    def test_yoy_from_monthly_index(self):
        self.assertAlmostEqual(cpi_yoy_pct(CPI_OBS), (320.0 / 310.0 - 1) * 100.0)

    def test_missing_year_ago_month_returns_none(self):
        self.assertIsNone(cpi_yoy_pct([("2026-06-01", 320.0)]))

    def test_empty_returns_none(self):
        self.assertIsNone(cpi_yoy_pct([]))

    def test_observations_as_of_truncates_to_three_months_back(self):
        truncated = observations_as_of(CPI_OBS)
        self.assertEqual(truncated[-1][0], "2026-03-01")

    def test_trend_label_dead_band(self):
        self.assertEqual(trend_label(4.4, 4.0, 0.25), "up")
        self.assertEqual(trend_label(4.0, 4.4, 0.25), "down")
        self.assertEqual(trend_label(4.1, 4.0, 0.25), "flat")
        self.assertIsNone(trend_label(None, 4.0, 0.25))

    def test_trend_label_exactly_on_the_band_is_flat(self):
        # Regression (run 67, 2026-08-09): 4.1 − 4.3 computes as
        # −0.20000000000000018 in floats, which mislabeled an
        # exactly-at-the-band unemployment change as "down".
        self.assertEqual(trend_label(4.1, 4.3, 0.2), "flat")
        self.assertEqual(trend_label(4.3, 4.1, 0.2), "flat")

    def test_pct_trend_label(self):
        self.assertEqual(pct_trend_label(68.2, 60.0, 5.0), "up")
        self.assertEqual(pct_trend_label(50.0, 60.0, 5.0), "down")
        self.assertEqual(pct_trend_label(120.0, 121.0, 2.0), "flat")
        self.assertIsNone(pct_trend_label(120.0, 0.0, 2.0))

    def test_next_date_after_picks_first_future_date(self):
        self.assertEqual(
            next_date_after(["2026-06-10", "2026-08-12", "2026-07-15"], TODAY),
            "2026-07-15",
        )
        self.assertIsNone(next_date_after(["2026-06-10"], TODAY))


class TestMacroEconProvider(unittest.TestCase):
    def setUp(self):
        self.cache = MemoryCacheStore()

    def _provider(self, fetcher=None, today=None, release_dates=None):
        return MacroEconProvider(
            series_fetcher=fetcher or _fake_fetcher(),
            cache=self.cache,
            today=today or (lambda: TODAY),
            release_dates_fetcher=release_dates or _fake_release_dates,
        )

    def test_supports_every_market(self):
        provider = self._provider()
        for market in Market:
            self.assertTrue(provider.supports(market))

    def test_full_payload_values_and_trends(self):
        result = self._provider().collect("AAPL")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        payload = result.payload

        def value(group, key):
            return metric_value(payload[group][key])

        self.assertEqual(value("meta", "region"), "us")
        self.assertEqual(value("meta", "inflation_data_up_to"), "2026-06-01")
        self.assertEqual(value("meta", "employment_data_up_to"), "2026-06-01")
        self.assertAlmostEqual(value("inflation", "cpi_yoy_pct"), 3.23)
        self.assertEqual(value("inflation", "cpi_yoy_trend"), "down")
        self.assertAlmostEqual(value("employment", "unemployment_rate_pct"), 4.1)
        self.assertEqual(value("employment", "unemployment_trend"), "flat")
        self.assertAlmostEqual(value("interest_rates", "official_rate_pct"), 4.33)
        self.assertAlmostEqual(
            value("interest_rates", "diff_2y_vs_official_pp"), -0.33
        )
        self.assertAlmostEqual(value("bonds", "gov10y_yield_pct"), 4.40)
        self.assertEqual(value("bonds", "gov10y_trend"), "up")
        self.assertAlmostEqual(value("bonds", "yield_diff_10y_2y_pp"), 0.40)
        self.assertEqual(value("bonds", "yield_diff_10y_2y_trend"), "down")
        self.assertAlmostEqual(value("bonds", "yield_diff_hy_gov_pp"), 3.10)
        self.assertEqual(value("bonds", "yield_diff_hy_gov_trend"), "flat")
        self.assertAlmostEqual(value("markets", "vix"), 17.50)
        self.assertAlmostEqual(value("markets", "wti_oil_usd"), 68.20)
        self.assertEqual(value("markets", "oil_trend"), "up")
        self.assertEqual(value("markets", "dollar_trend"), "flat")
        self.assertEqual(value("events", "next_cpi_release_date"), "2026-07-15")
        self.assertEqual(value("events", "next_jobs_release_date"), "2026-08-07")
        self.assertEqual(
            value("events", "next_rate_decision_date"), "2026-07-29"
        )
        self.assertTrue(result.citations)

    def test_every_published_metric_is_an_envelope(self):
        payload = self._provider().collect("AAPL").payload
        for group, metrics in payload.items():
            self.assertIsInstance(metrics, dict, group)
            for key, node in metrics.items():
                self.assertTrue(is_envelope(node), f"{group}.{key}")

    def test_formula_receipts_cover_diffs_and_trends(self):
        result = self._provider().collect("AAPL")
        formulas = result.formulas or {}
        diff = formulas["interest_rates.diff_2y_vs_official_pp"]
        self.assertEqual(
            diff["formula"], "gov_bond_yield_2y − official_interest_rate"
        )
        self.assertAlmostEqual(diff["inputs"]["gov_bond_yield_2y"], 4.00)
        self.assertAlmostEqual(diff["inputs"]["official_interest_rate"], 4.33)
        curve = formulas["bonds.yield_diff_10y_2y_pp"]
        self.assertAlmostEqual(curve["inputs"]["gov_bond_yield_10y"], 4.40)
        trend = formulas["bonds.gov10y_trend"]
        self.assertAlmostEqual(trend["inputs"]["value_now"], 4.40)
        self.assertAlmostEqual(trend["inputs"]["value_3m_ago"], 4.00)
        self.assertEqual(
            [branch["label"] for branch in trend["branches"]],
            ["up", "down", "flat"],
        )
        oil = formulas["markets.oil_trend"]
        self.assertAlmostEqual(oil["inputs"]["change_3m_pct"], 13.67)

    def test_one_series_failing_blanks_its_fields_with_notes(self):
        base = _fake_fetcher()

        def flaky(series_id):
            if series_id == "VIXCLS":
                raise RuntimeError("FRED 500")
            return base(series_id)

        result = self._provider(fetcher=flaky).collect("AAPL")
        self.assertIsNone(metric_value(result.payload["markets"]["vix"]))
        # Unaffected fields still carry their values.
        self.assertAlmostEqual(
            metric_value(result.payload["markets"]["wti_oil_usd"]), 68.20
        )
        self.assertTrue(any("VIXCLS" in w for w in result.warnings))
        # The note also sits on the blanked field itself.
        self.assertTrue(
            any(
                "VIXCLS" in note
                for note in (result.field_notes or {}).get("markets.vix", [])
            )
        )

    def test_calendar_outage_blanks_release_dates_with_warning(self):
        def broken_calendar(release_id):
            raise RuntimeError("FRED release API down")

        result = self._provider(release_dates=broken_calendar).collect("AAPL")
        # The series-fed fields are untouched by a calendar outage.
        self.assertAlmostEqual(
            metric_value(result.payload["markets"]["vix"]), 17.50
        )
        self.assertIsNone(
            metric_value(result.payload["events"]["next_cpi_release_date"])
        )
        # The static FOMC table needs no network, so it still resolves.
        self.assertEqual(
            metric_value(result.payload["events"]["next_rate_decision_date"]),
            "2026-07-29",
        )
        self.assertTrue(any("release calendar" in w for w in result.warnings))

    def test_fomc_table_exhausted_warns_instead_of_guessing(self):
        result = self._provider(today=lambda: date(2028, 1, 1)).collect("AAPL")
        self.assertIsNone(
            metric_value(result.payload["events"]["next_rate_decision_date"])
        )
        self.assertTrue(any("FOMC" in w for w in result.warnings))

    def test_all_series_failing_ships_all_blank_payload(self):
        def broken(series_id):
            raise RuntimeError("network down")

        result = self._provider(fetcher=broken).collect("AAPL")
        # The full payload shape still ships: every required field is
        # blank and carries a note saying why.
        self.assertIsNotNone(result.payload)
        for group, key in _REQUIRED_FIELDS:
            self.assertIsNone(
                metric_value(result.payload[group][key]), f"{group}.{key}"
            )
            self.assertIn(f"{group}.{key}", result.field_notes or {})
        self.assertTrue(
            any("macro fields lacking data" in w for w in result.warnings)
        )
        # A NUMERIC card with a payload stays actionable — gating moved
        # to the field level (each blank value is its own gate).
        self.assertTrue(result.is_actionable)
        # A total failure is never day-cached: the next run must retry.
        self.assertEqual(self.cache.keys(), [])

    def test_missing_api_key_ships_blank_payload_with_one_config_warning(self):
        def unconfigured(series_id):
            raise MacroConfigError("FRED_API_KEY is not set")

        result = self._provider(fetcher=unconfigured).collect("AAPL")
        # One clear config warning, no per-series noise; the aggregate
        # missing-fields note is the only other warning.
        self.assertIn("FRED_API_KEY", result.warnings[0])
        self.assertEqual(
            len([w for w in result.warnings if "FRED_API_KEY" in w]), 1
        )
        self.assertFalse(any("FRED series" in w for w in result.warnings))
        # The payload still ships its shape, all series-fed fields blank.
        self.assertIsNotNone(result.payload)
        self.assertIsNone(metric_value(result.payload["markets"]["vix"]))
        # Not-configured is a total failure: never day-cached.
        self.assertEqual(self.cache.keys(), [])

    def test_cached_once_per_day_never_per_ticker(self):
        calls = []
        provider = self._provider(fetcher=_fake_fetcher(calls))
        first = provider.collect("AAPL")
        second = provider.collect("600519")  # different ticker, same day
        self.assertEqual(len(calls), len(SERIES_IDS))  # one fetch round only
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.warnings, second.warnings)

    def test_cache_round_trips_formulas(self):
        provider = self._provider()
        provider.collect("AAPL")
        cached = self._provider().collect("MSFT")
        self.assertIn("interest_rates.diff_2y_vs_official_pp", cached.formulas)

    def test_cache_is_per_day(self):
        calls = []
        fetcher = _fake_fetcher(calls)
        day = [TODAY]
        provider = self._provider(fetcher=fetcher, today=lambda: day[0])
        provider.collect("AAPL")
        day[0] = date(2026, 7, 8)
        provider.collect("AAPL")
        self.assertEqual(len(calls), 2 * len(SERIES_IDS))

    def test_old_format_same_day_cache_is_ignored(self):
        # A cache entry written by the pre-reform provider (no version tag
        # in its key) must not be misread as the new payload shape.
        self.cache.data[f"macro_econ_us_{TODAY.isoformat()}"] = (
            '{"payload": {"region": "us"}}'
        )
        calls = []
        result = self._provider(fetcher=_fake_fetcher(calls)).collect("AAPL")
        self.assertEqual(len(calls), len(SERIES_IDS))  # refetched
        self.assertIn("meta", result.payload)

    def test_same_day_cache_missing_payload_is_refetched(self):
        # The reader requires "payload"; a v2-keyed entry without it is
        # ignored and the data refetched, never misread.
        self.cache.data[f"macro_econ_us_v2_{TODAY.isoformat()}"] = '{"warnings": []}'
        calls = []
        result = self._provider(fetcher=_fake_fetcher(calls)).collect("AAPL")
        self.assertEqual(len(calls), len(SERIES_IDS))  # refetched
        self.assertIn("meta", result.payload)

    def test_corrupt_cache_entry_triggers_refetch(self):
        calls = []
        provider = self._provider(fetcher=_fake_fetcher(calls))
        provider.collect("AAPL")
        key = next(k for k in self.cache.keys() if "_v2_" in k)
        self.cache.data[key] = "{not json"
        fresh = self._provider(fetcher=_fake_fetcher(calls))
        result = fresh.collect("AAPL")
        self.assertIn("meta", result.payload)
        self.assertEqual(len(calls), 2 * len(SERIES_IDS))

    def test_degraded_results_are_cached_too(self):
        base = _fake_fetcher()
        calls = []

        def counting_flaky(series_id):
            calls.append(series_id)
            if series_id == "VIXCLS":
                raise RuntimeError("FRED 500")
            return base(series_id)

        provider = self._provider(fetcher=counting_flaky)
        provider.collect("AAPL")
        second = provider.collect("AAPL")
        self.assertEqual(len(calls), len(SERIES_IDS))
        # The cached read keeps the blank field and its warning.
        self.assertIsNone(metric_value(second.payload["markets"]["vix"]))
        self.assertTrue(any("VIXCLS" in w for w in second.warnings))


class TestRegistryIncludesMacro(unittest.TestCase):
    def test_macro_routed_for_all_markets(self):
        from src.tiered_analysis.providers.registry import get_providers

        for market in (Market.US, Market.CN, Market.KR):
            dimensions = [p.dimension for p in get_providers(market)]
            self.assertIn("macro_econ", dimensions)


@pytest.mark.network
@pytest.mark.skipif(not os.getenv("FRED_API_KEY"), reason="FRED_API_KEY not set")
class TestLiveFredSanity(unittest.TestCase):
    def test_live_us_macro_is_plausible(self):
        provider = MacroEconProvider(cache=MemoryCacheStore())
        result = provider.collect("AAPL")
        self.assertTrue(result.payload)
        gov10y = metric_value(result.payload["bonds"]["gov10y_yield_pct"])
        self.assertGreater(gov10y or 0, 0.5)
        self.assertLess(gov10y or 99, 15.0)
        inflation = metric_value(result.payload["inflation"]["cpi_yoy_pct"])
        self.assertIsNotNone(inflation)
        self.assertGreater(inflation, -5.0)
        self.assertLess(inflation, 15.0)


if __name__ == "__main__":
    unittest.main()
