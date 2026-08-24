# -*- coding: utf-8 -*-
"""Offline tests for the opinion provider (the analyst + crowd
sentiment card, numeric): envelope values and formulas computed from
the fixtures, the rating-action window cut, blank-with-note semantics
per failed or silent source (including everything-down), and the
debate's leaf-ref enumeration of the numeric payload.

No network: every loader is an injected fake.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.tiered_analysis.debate import gradable_field_refs
from src.tiered_analysis.providers.base import Market, SourceKind
from src.tiered_analysis.providers.opinion import (
    OpinionProvider,
    _cached_crowd_list,
    normalize_apewisdom_row,
    normalize_tradestie_row,
)
from src.tiered_analysis.providers.technicals import metric_value

TODAY = date(2026, 8, 18)  # a Tuesday


def analyst_fixture():
    return {
        "source": "yahoo",
        "actions": [
            {
                "date": "2026-08-14",
                "firm": "Jefferies",
                "to_grade": "Underperform",
                "from_grade": "Hold",
                "action": "down",
                "pt_current": 263.66,
                "pt_prior": 285.56,
            },
            {  # outside the 7-business-day window (starts 2026-08-10)
                "date": "2026-08-07",
                "firm": "Old Firm",
                "to_grade": "Buy",
                "from_grade": "Hold",
                "action": "up",
                "pt_current": None,
                "pt_prior": None,
            },
            {
                "date": "2026-08-17",
                "firm": "Baird",
                "to_grade": "Neutral",
                "from_grade": None,
                "action": "init",
                "pt_current": 250.0,
                "pt_prior": None,
            },
        ],
        "consensus": [
            {
                "period": "0m",
                "strong_buy": 6, "buy": 21, "hold": 14,
                "sell": 3, "strong_sell": 2,
            },
            {
                "period": "-1m",
                "strong_buy": 6, "buy": 22, "hold": 14,
                "sell": 2, "strong_sell": 2,
            },
        ],
        "targets": {
            "current": 300.0, "mean": 321.0, "high": 400.0, "low": 215.0,
        },
    }


APEWISDOM_ROW = {
    "rank": 4,
    "ticker": "AAPL",
    "mentions": 146,
    "upvotes": 832,
    "rank_24h_ago": 29,
    "mentions_24h_ago": 9,
}

TRADESTIE_ROW = {
    "ticker": "AAPL",
    "sentiment": "Bullish",
    "sentiment_score": 0.168,
    "no_of_comments": 43,
}


def values(group):
    """Envelope group -> {key: plain value}."""
    return {key: metric_value(node) for key, node in group.items()}


class TestNormalizers(unittest.TestCase):
    def test_apewisdom_row_maps_published_stats(self):
        self.assertEqual(
            normalize_apewisdom_row(APEWISDOM_ROW),
            {
                "mentions": 146,
                "mentions_24h_ago": 9,
                "upvotes": 832,
                "rank": 4,
                "rank_24h_ago": 29,
            },
        )

    def test_junk_stats_stay_none_never_fake_zeros(self):
        normalized = normalize_apewisdom_row({"mentions": "n/a", "rank": None})
        self.assertIsNone(normalized["mentions"])
        self.assertIsNone(normalized["rank"])
        wsb = normalize_tradestie_row({"sentiment_score": "x"})
        self.assertIsNone(wsb["sentiment_score"])
        self.assertIsNone(wsb["comments"])

    def test_tradestie_row_maps_published_stats(self):
        self.assertEqual(
            normalize_tradestie_row(TRADESTIE_ROW),
            {"sentiment_score": 0.168, "comments": 43},
        )


class TestOpinionProvider(unittest.TestCase):
    def make_provider(
        self,
        analyst=None,
        analyst_loader=None,
        apewisdom_loader=None,
        tradestie_loader=None,
    ):
        def default_analyst_loader(symbol):
            return (analyst if analyst is not None else analyst_fixture(), [])

        return OpinionProvider(
            analyst_loader=analyst_loader or default_analyst_loader,
            apewisdom_loader=apewisdom_loader
            or (lambda symbol: normalize_apewisdom_row(APEWISDOM_ROW)),
            tradestie_loader=tradestie_loader
            or (lambda symbol: normalize_tradestie_row(TRADESTIE_ROW)),
            today=lambda: TODAY,
        )

    def test_supports_us_only(self):
        provider = self.make_provider()
        self.assertTrue(provider.supports(Market.US))
        self.assertFalse(provider.supports(Market.CN))
        self.assertFalse(provider.supports(Market.HK))

    def test_full_payload_values_and_formulas(self):
        result = self.make_provider().collect("AAPL")
        self.assertEqual(result.dimension, "opinion")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        self.assertEqual(list(result.payload), ["analyst", "crowd"])

        analyst = values(result.payload["analyst"])
        self.assertEqual(analyst["firms_total"], 46)
        self.assertEqual(analyst["strong_buy_firms"], 6)
        self.assertEqual(analyst["buy_firms"], 21)
        self.assertEqual(analyst["hold_firms"], 14)
        self.assertEqual(analyst["sell_firms"], 3)
        self.assertEqual(analyst["strong_sell_firms"], 2)
        self.assertEqual(analyst["buy_rating_pct"], 58.7)  # 27/46
        self.assertEqual(analyst["buy_rating_change_1m_pp"], -2.2)  # vs 60.9
        self.assertEqual(analyst["price_target_mean"], 321.0)
        self.assertEqual(analyst["price_target_high"], 400.0)
        self.assertEqual(analyst["price_target_low"], 215.0)
        self.assertEqual(analyst["target_vs_price_pct"], 7.0)
        # Window cut: the 2026-08-07 upgrade sits outside the window
        # starting 2026-08-10 — counted zero, a real zero.
        self.assertEqual(analyst["upgrades_count"], 0)
        self.assertEqual(analyst["downgrades_count"], 1)
        self.assertEqual(analyst["initiations_count"], 1)

        crowd = values(result.payload["crowd"])
        self.assertEqual(crowd["reddit_mentions"], 146)
        self.assertEqual(crowd["reddit_mentions_24h_ago"], 9)
        self.assertEqual(crowd["reddit_upvotes"], 832)
        self.assertEqual(crowd["reddit_rank"], 4)
        self.assertEqual(crowd["reddit_rank_24h_ago"], 29)
        self.assertEqual(crowd["wsb_sentiment_score"], 0.168)
        self.assertEqual(crowd["wsb_comments"], 43)

        # Computed fields carry UI formula receipts.
        self.assertIn("analyst.buy_rating_pct", result.formulas)
        self.assertEqual(
            result.formulas["analyst.buy_rating_pct"]["inputs"]["firms_total"],
            46,
        )
        self.assertIn("analyst.target_vs_price_pct", result.formulas)
        self.assertIn("analyst.upgrades_count", result.formulas)

        # One citation per delivered source, Yahoo's a clickable page.
        names = [citation.source_name for citation in result.citations]
        self.assertEqual(len(names), 3)
        self.assertEqual(
            result.citations[0].url,
            "https://finance.yahoo.com/quote/AAPL/analysis",
        )
        self.assertTrue(any("ApeWisdom" in name for name in names))
        self.assertTrue(any("Tradestie" in name for name in names))
        self.assertIsNone(result.field_notes)

    def test_unranked_ticker_is_checked_and_none_not_a_failure(self):
        result = self.make_provider(
            apewisdom_loader=lambda symbol: None,
            tradestie_loader=lambda symbol: None,
        ).collect("AAPL")
        crowd = values(result.payload["crowd"])
        self.assertTrue(all(value is None for value in crowd.values()))
        self.assertTrue(
            any("not on ApeWisdom" in note for note in result.warnings)
        )
        self.assertIn(
            "crowd.reddit_mentions", result.field_notes
        )
        self.assertIn("crowd.wsb_comments", result.field_notes)

    def test_failed_crowd_source_blanks_its_fields_with_notes(self):
        def failing(symbol):
            raise RuntimeError("apewisdom down")

        result = self.make_provider(apewisdom_loader=failing).collect("AAPL")
        crowd = values(result.payload["crowd"])
        self.assertIsNone(crowd["reddit_mentions"])
        self.assertEqual(crowd["wsb_comments"], 43)  # the other source held
        self.assertTrue(
            any("apewisdom down" in note for note in result.warnings)
        )
        self.assertIn("crowd.reddit_rank", result.field_notes)

    def test_failed_analyst_blanks_its_half_with_crowd_intact(self):
        def failing_analyst(symbol):
            raise RuntimeError("yahoo down")

        result = self.make_provider(
            analyst_loader=failing_analyst
        ).collect("AAPL")
        analyst = values(result.payload["analyst"])
        self.assertTrue(all(value is None for value in analyst.values()))
        self.assertEqual(values(result.payload["crowd"])["reddit_rank"], 4)
        self.assertTrue(
            any("yahoo down" in note for note in result.warnings)
        )
        self.assertIn("analyst.firms_total", result.field_notes)
        # No Yahoo citation when the analyst source failed.
        names = [citation.source_name for citation in result.citations]
        self.assertFalse(any("Yahoo" in name for name in names))

    def test_everything_down_ships_all_blank_payload_with_notes(self):
        def failing(symbol):
            raise RuntimeError("down")

        result = self.make_provider(
            analyst_loader=failing,
            apewisdom_loader=failing,
            tradestie_loader=failing,
        ).collect("AAPL")
        self.assertEqual(list(result.payload), ["analyst", "crowd"])
        for group in ("analyst", "crowd"):
            blanks = values(result.payload[group])
            self.assertTrue(all(value is None for value in blanks.values()))
        # Every field carries its source's failure note.
        self.assertIn("analyst.firms_total", result.field_notes)
        self.assertIn("crowd.reddit_mentions", result.field_notes)
        self.assertIn("crowd.wsb_comments", result.field_notes)
        self.assertEqual(result.citations, [])

    def test_finnhub_backup_blanks_targets_and_actions_with_notes(self):
        note = (
            "analyst opinions: Yahoo failed (boom); Finnhub consensus"
            " only — no price targets or rating-action counts"
        )

        def finnhub_loader(symbol):
            return (
                {
                    "source": "finnhub",
                    "actions": None,
                    "targets": None,
                    "consensus": analyst_fixture()["consensus"],
                },
                [note],
            )

        result = self.make_provider(analyst_loader=finnhub_loader).collect(
            "AAPL"
        )
        analyst = values(result.payload["analyst"])
        self.assertEqual(analyst["firms_total"], 46)
        self.assertIsNone(analyst["price_target_mean"])
        self.assertIsNone(analyst["upgrades_count"])
        self.assertIn(note, result.field_notes["analyst.price_target_mean"])
        self.assertIn(note, result.field_notes["analyst.upgrades_count"])
        self.assertNotIn("analyst.firms_total", result.field_notes)
        finnhub = result.citations[0]
        self.assertEqual(finnhub.source_name, "Finnhub analyst consensus")
        self.assertIsNone(finnhub.url)

    def test_fetched_empty_actions_are_real_zeros(self):
        data = analyst_fixture()
        data["actions"] = []
        result = self.make_provider(analyst=data).collect("AAPL")
        analyst = values(result.payload["analyst"])
        self.assertEqual(analyst["upgrades_count"], 0)
        self.assertEqual(analyst["downgrades_count"], 0)
        self.assertEqual(analyst["initiations_count"], 0)


class TestCrowdDayCache(unittest.TestCase):
    """The crowd lists are symbol-independent: fetched once per day,
    served from disk after that, and never cached on failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_second_call_reads_the_cache_not_the_network(self):
        calls = []

        def fetch():
            calls.append(1)
            return [{"ticker": "AAPL", "mentions": 5}]

        for _ in range(2):
            rows = _cached_crowd_list(
                "apewisdom", fetch,
                cache_dir=self.cache_dir, today=lambda: TODAY,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(rows, [{"ticker": "AAPL", "mentions": 5}])

    def test_failed_fetch_is_not_cached_so_the_next_ticker_retries(self):
        def failing():
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            _cached_crowd_list(
                "tradestie", failing,
                cache_dir=self.cache_dir, today=lambda: TODAY,
            )
        self.assertEqual(list(self.cache_dir.iterdir()), [])

    def test_corrupt_cache_refetches_instead_of_failing(self):
        rows = [{"ticker": "TSLA"}]
        _cached_crowd_list(
            "apewisdom", lambda: rows,
            cache_dir=self.cache_dir, today=lambda: TODAY,
        )
        cache_file = next(self.cache_dir.iterdir())
        cache_file.write_text("{not json", encoding="utf-8")
        result = _cached_crowd_list(
            "apewisdom", lambda: rows,
            cache_dir=self.cache_dir, today=lambda: TODAY,
        )
        self.assertEqual(result, rows)


class TestDebateEnumeration(unittest.TestCase):
    def test_opinion_rows_are_numeric_leaf_refs_skipping_blanks(self):
        provider = OpinionProvider(
            analyst_loader=lambda symbol: (analyst_fixture(), []),
            apewisdom_loader=lambda symbol: None,  # crowd half blank
            tradestie_loader=lambda symbol: normalize_tradestie_row(
                TRADESTIE_ROW
            ),
            today=lambda: TODAY,
        )
        refs = gradable_field_refs([provider.collect("AAPL")])
        self.assertIn("opinion.analyst.buy_rating_pct", refs["opinion"])
        self.assertIn("opinion.crowd.wsb_sentiment_score", refs["opinion"])
        # Blank fields (the unranked ApeWisdom half) get no rows.
        self.assertNotIn("opinion.crowd.reddit_mentions", refs["opinion"])
        # Envelope prose keys are never rows of their own.
        self.assertFalse(
            any(ref.endswith(".value") or ref.endswith(".name") for ref in refs["opinion"])
        )


if __name__ == "__main__":
    unittest.main()
