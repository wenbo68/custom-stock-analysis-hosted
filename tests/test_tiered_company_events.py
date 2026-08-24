# -*- coding: utf-8 -*-
"""Offline tests for the company-news provider (the qualitative fifth
report, news-only since 2026-08-13): windowing, citation alignment,
date|publisher bullet fields, newest-first ordering, summary fallback,
drops, and the failure contract."""
from __future__ import annotations

import unittest
from datetime import date

from unittest import mock

from src.tiered_analysis.providers.base import Market, SourceKind
from src.tiered_analysis.providers import company_events
from src.tiered_analysis.providers.company_events import (
    CompanyEventsProvider,
    business_days_back,
    flatten_summary,
    mentions_company,
    name_to_terms,
    normalize_finnhub_entry,
    normalize_news_entry,
    relevance_terms,
)

TODAY = date(2026, 8, 13)


def passthrough_screener(symbol, entries, company):
    """Offline stand-in for the LLM screen: every article is its own
    kept event, in the order the provider handed them over."""
    passthrough_screener.calls.append(
        {"symbol": symbol, "entries": list(entries), "company": company}
    )
    return {
        "selected": [
            {"entry": entry, "verdict": None, "materiality": None, "group_size": 1}
            for entry in entries
        ],
        "mention_only": 0,
        "below_threshold": 0,
        "trimmed": 0,
        "warnings": [],
        "judgments": [],
        "from_cache": 0,
        "judged": len(entries),
    }


passthrough_screener.calls = []

LONG_SUMMARY = (
    "Apple introduced a set of AI features across its devices, expanding "
    "its assistant with real-time content deals, new on-device models, "
    "developer APIs, and a staged rollout plan that analysts said could "
    "reshape services revenue over the coming years while raising fresh "
    "questions about content licensing costs and regulatory attention in "
    "both the United States and the European Union."
)


def news_fixture():
    """Already-normalized news entries (the loader's output shape)."""
    return [
        {
            "title": "Apple unveils new AI features",
            "publisher": "Reuters",
            "url": "https://example.com/apple-ai",
            "date": "2026-08-12",
            "summary": LONG_SUMMARY,
        },
        {  # no summary shipped — the headline is the fallback bullet text
            "title": "Analysts weigh iPhone demand",
            "publisher": "Bloomberg",
            "url": "https://example.com/iphone-demand",
            "date": "2026-08-07",
            "summary": None,
        },
        {  # outside the business-day window
            "title": "Old story",
            "publisher": "CNBC",
            "url": "https://example.com/old",
            "date": "2026-07-01",
            "summary": None,
        },
        {  # no link — unverifiable, must be dropped with a warning
            "title": "No link story",
            "publisher": "Somewhere",
            "url": None,
            "date": "2026-08-12",
            "summary": None,
        },
    ]


def make_provider(news=None, screener=passthrough_screener):
    passthrough_screener.calls = []
    return CompanyEventsProvider(
        news_loader=lambda symbol: news if news is not None else news_fixture(),
        today=lambda: TODAY,
        # Offline: no yfinance name lookup; ticker + BRAND_ALIASES suffice.
        name_terms_loader=lambda symbol: [],
        # Offline: no LLM; the screen's own behavior is covered by
        # test_tiered_news_screen.py.
        screener=screener,
    )


class TestHelpers(unittest.TestCase):
    def test_business_days_back_counts_weekdays_only(self):
        # Thursday 2026-08-13, quota 7: Thu 13, Wed 12, Tue 11, Mon 10,
        # (weekend), Fri 7, Thu 6, Wed 5 — a 9-calendar-day span.
        self.assertEqual(
            business_days_back(date(2026, 8, 13), 7), date(2026, 8, 5)
        )
        # Monday 2026-08-17, quota 7: two weekends inside — an
        # 11-calendar-day span, same weekday depth.
        self.assertEqual(
            business_days_back(date(2026, 8, 17), 7), date(2026, 8, 7)
        )
        # A weekend run day does not count toward the quota.
        self.assertEqual(
            business_days_back(date(2026, 8, 16), 7), date(2026, 8, 6)
        )
        # Quota 1 from a weekday is that day itself.
        self.assertEqual(
            business_days_back(date(2026, 8, 13), 1), date(2026, 8, 13)
        )

    def test_flatten_summary_collapses_whitespace_without_truncating(self):
        self.assertEqual(flatten_summary("one\n two   three"), "one two three")
        long_text = "word " * 200
        self.assertEqual(flatten_summary(long_text), long_text.strip())

    def test_normalize_news_entry_new_nested_shape(self):
        entry = {
            "content": {
                "title": "Headline",
                "pubDate": "2026-08-12T14:30:00Z",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "https://example.com/story"},
                "summary": "What the article says.",
            }
        }
        self.assertEqual(
            normalize_news_entry(entry),
            {
                "title": "Headline",
                "publisher": "Reuters",
                "url": "https://example.com/story",
                "date": "2026-08-12",
                "summary": "What the article says.",
            },
        )

    def test_name_to_terms_strips_legal_suffixes(self):
        self.assertEqual(name_to_terms("Alphabet Inc. (Class A)"), ["alphabet"])
        self.assertEqual(
            name_to_terms("Berkshire Hathaway Inc"),
            ["berkshire hathaway", "berkshire"],
        )
        self.assertEqual(name_to_terms(""), [])

    def test_relevance_terms_combine_ticker_name_and_aliases(self):
        terms = relevance_terms("GOOGL", ["alphabet"])
        self.assertIn("googl", terms)
        self.assertIn("gemini", terms)  # brand alias
        self.assertEqual(terms.count("alphabet"), 1)  # deduplicated

    def test_mentions_company_respects_word_boundaries(self):
        terms = ["meta"]
        self.assertTrue(mentions_company({"title": "Meta beats estimates"}, terms))
        self.assertFalse(mentions_company({"title": "Precious metal rally"}, terms))
        # Match in the abstract alone also counts.
        self.assertTrue(
            mentions_company({"title": "Big Tech", "summary": "Meta led."}, terms)
        )

    def test_normalize_finnhub_entry_maps_fields_and_epoch_date(self):
        entry = {
            "headline": "Apple in talks with publishers",
            "source": "Reuters",
            "url": "https://example.com/story",
            "datetime": 1786600800,  # 2026-08-13 UTC
            "summary": "What the article says.",
        }
        self.assertEqual(
            normalize_finnhub_entry(entry),
            {
                "title": "Apple in talks with publishers",
                "publisher": "Reuters",
                "url": "https://example.com/story",
                "date": "2026-08-13",
                "summary": "What the article says.",
            },
        )

    def test_normalize_finnhub_entry_unescapes_html_entities(self):
        entry = {"headline": "Tesla hasn&#39;t advertised", "summary": "It won&amp;t."}
        normalized = normalize_finnhub_entry(entry)
        self.assertEqual(normalized["title"], "Tesla hasn't advertised")
        self.assertEqual(normalized["summary"], "It won&t.")

    def test_normalize_finnhub_entry_missing_fields_stay_none(self):
        self.assertEqual(
            normalize_finnhub_entry({}),
            {
                "title": None,
                "publisher": None,
                "url": None,
                "date": None,
                "summary": None,
            },
        )

    def test_default_loader_dispatches_on_finnhub_key(self):
        with mock.patch.object(
            company_events, "_finnhub_news_loader", return_value=["finnhub"]
        ) as finnhub, mock.patch.object(
            company_events, "_yahoo_news_loader", return_value=["yahoo"]
        ) as yahoo:
            with mock.patch.dict("os.environ", {"FINNHUB_API_KEY": "k"}):
                self.assertEqual(
                    company_events._default_news_loader("AAPL"), ["finnhub"]
                )
                finnhub.assert_called_once_with("AAPL", "k")
            with mock.patch.dict("os.environ", {"FINNHUB_API_KEY": ""}):
                self.assertEqual(
                    company_events._default_news_loader("AAPL"), ["yahoo"]
                )
                yahoo.assert_called_once_with("AAPL")

    def test_normalize_news_entry_old_flat_shape(self):
        entry = {
            "title": "Headline",
            "publisher": "CNBC",
            "link": "https://example.com/story",
            "providerPublishTime": 1786600800,  # 2026-08-13 UTC
            "summary": "Old-shape abstract.",
        }
        normalized = normalize_news_entry(entry)
        self.assertEqual(normalized["publisher"], "CNBC")
        self.assertEqual(normalized["url"], "https://example.com/story")
        self.assertEqual(normalized["date"], "2026-08-13")
        self.assertEqual(normalized["summary"], "Old-shape abstract.")


class TestCollect(unittest.TestCase):
    def test_full_run_windows_citations_and_fallback_bullets(self):
        result = make_provider().collect("AAPL")

        self.assertEqual(result.dimension, "company_events")
        self.assertEqual(result.kind, SourceKind.TEXTUAL)
        self.assertIsNotNone(result.payload)  # no card-level grade anymore
        self.assertFalse(result.is_actionable)  # textual never feeds sizing

        news = result.payload["news_coverage"]
        # The window is a business-day quota with a varying calendar
        # length, so no window_days promise rides in the payload — the
        # card title shows the actual span instead (owner format
        # 2026-08-17, matching the world card). TODAY is Thursday
        # 2026-08-13; 7 business days back lands on Wednesday
        # 2026-08-05 (one weekend inside the span).
        self.assertNotIn("window_days", news)
        self.assertEqual(news["oldest"], "2026-08-05")
        self.assertEqual(news["newest"], "2026-08-13")
        self.assertEqual(
            [item["text"] for item in news["items"]],
            [
                # No card_text from the (passthrough) screen -> the feed's
                # own abstract, never clipped; headline only as fallback
                # when no abstract shipped.
                LONG_SUMMARY,
                "Analysts weigh iPhone demand",
            ],
        )
        # date/publisher ride as separate fields (owner format
        # 2026-08-16) for the card's "2026/08/12 | Reuters" header line.
        self.assertEqual(
            [(item["date"], item["publisher"]) for item in news["items"]],
            [("2026-08-12", "Reuters"), ("2026-08-07", "Bloomberg")],
        )

        # Every bullet's 1-based citation index points at a real URL.
        self.assertEqual([item["citation"] for item in news["items"]], [1, 2])
        self.assertEqual(len(result.citations), 2)
        self.assertTrue(all(citation.url for citation in result.citations))
        self.assertEqual(result.citations[0].url, "https://example.com/apple-ai")

        # The linkless news item was dropped loudly, not silently.
        self.assertTrue(
            any("skipped" in warning for warning in result.warnings), result.warnings
        )

    def test_duplicate_urls_collapse_to_one_bullet(self):
        twice = [
            {
                "title": "Apple same story",
                "publisher": "Wire",
                "url": "https://example.com/same",
                "date": "2026-08-12",
                "summary": None,
            }
        ] * 2
        result = make_provider(news=twice).collect("AAPL")
        self.assertEqual(len(result.payload["news_coverage"]["items"]), 1)

    def test_relevance_filter_cuts_articles_not_naming_the_company(self):
        mixed = [
            {
                "title": "Apple unveils new AI features",
                "publisher": "Reuters",
                "url": "https://example.com/1",
                "date": "2026-08-12",
                "summary": None,
            },
            {  # wrong-company article tagged to the ticker (the junk case)
                "title": "Tesla robotaxi fleet stays stuck",
                "publisher": "Stocktwits",
                "url": "https://example.com/2",
                "date": "2026-08-12",
                "summary": "Gary Black questions the strategy.",
            },
            {  # brand alias in the abstract counts as naming the company
                "title": "Voice assistants compared",
                "publisher": "CNBC",
                "url": "https://example.com/3",
                "date": "2026-08-12",
                "summary": "Siri lags rivals in daily usage.",
            },
        ]
        result = make_provider(news=mixed).collect("AAPL")
        news = result.payload["news_coverage"]
        self.assertEqual(len(news["items"]), 2)
        self.assertEqual(news["filtered_out"], 1)
        self.assertNotIn("Tesla", " ".join(item["text"] for item in news["items"]))

    def test_identical_body_text_collapses_to_one_bullet(self):
        boilerplate = "Fund X released its Q2 2026 letter. A copy is available."
        twice = [
            {
                "title": "Apple story one",
                "publisher": "Insider Monkey",
                "url": "https://example.com/a",
                "date": "2026-08-12",
                "summary": boilerplate,
            },
            {
                "title": "Apple story two",
                "publisher": "Insider Monkey",
                "url": "https://example.com/b",
                "date": "2026-08-12",
                "summary": boilerplate,
            },
        ]
        result = make_provider(news=twice).collect("AAPL")
        self.assertEqual(len(result.payload["news_coverage"]["items"]), 1)

    def test_all_articles_irrelevant_warns_loudly(self):
        junk = [
            {
                "title": "Tesla robotaxi update",
                "publisher": "Wire",
                "url": "https://example.com/t",
                "date": "2026-08-12",
                "summary": None,
            }
        ]
        result = make_provider(news=junk).collect("AAPL")
        self.assertEqual(result.payload["news_coverage"]["items"], [])
        self.assertTrue(
            any("none mention the company" in w for w in result.warnings),
            result.warnings,
        )

    def test_empty_window_keeps_payload_present_with_empty_items(self):
        result = make_provider(news=[]).collect("AAPL")
        self.assertIsNotNone(result.payload)
        self.assertEqual(result.payload["news_coverage"]["items"], [])

    def test_failed_loader_ships_empty_timeline_with_warning(self):
        # Degradation lives on the card notes now, never on a card-level
        # grade: a failed fetch still ships the card's payload shape (an
        # empty timeline over the real window) plus the warning saying why.
        def broken(symbol):
            raise RuntimeError("Yahoo down")

        provider = CompanyEventsProvider(news_loader=broken, today=lambda: TODAY)
        result = provider.collect("AAPL")
        news = result.payload["news_coverage"]
        self.assertEqual(news["items"], [])
        # The window bounds are real dates, so the empty card still shows
        # the span it covers (7 business days back from Thursday 08-13).
        self.assertEqual(news["oldest"], "2026-08-05")
        self.assertEqual(news["newest"], "2026-08-13")
        self.assertEqual(news["filtered_out"], 0)
        self.assertEqual(news["mention_only"], 0)
        self.assertEqual(news["below_bar"], 0)
        self.assertTrue(
            any(
                "news headlines unavailable" in warning and "Yahoo down" in warning
                for warning in result.warnings
            ),
            result.warnings,
        )

    def test_screener_gets_the_filtered_deduped_newest_first_entries(self):
        result = make_provider().collect("AAPL")
        self.assertIsNotNone(result.payload)
        call = passthrough_screener.calls[0]
        self.assertEqual(call["symbol"], "AAPL")
        # No registered name available offline -> company is None.
        self.assertIsNone(call["company"])
        # Windowed, link-verified, newest first.
        self.assertEqual(
            [entry["date"] for entry in call["entries"]],
            ["2026-08-12", "2026-08-07"],
        )

    def test_screener_warnings_and_event_extras_reach_the_result(self):
        def screener(symbol, entries, company):
            return {
                "selected": [
                    {
                        "entry": entries[0],
                        "verdict": None,
                        "materiality": 5,
                        "group_size": 16,
                        "card_text": "Apple shipped its AI overhaul.",
                    }
                ],
                "mention_only": 3,
                "below_threshold": 7,
                "trimmed": 2,
                "warnings": ["busy news window: 2 event(s) trimmed"],
                "judgments": [],
                "from_cache": 0,
                "judged": 1,
            }

        result = make_provider(screener=screener).collect("AAPL")
        news = result.payload["news_coverage"]
        self.assertEqual(len(news["items"]), 1)
        # The screen's one-sentence summary IS the bullet — the feed
        # abstract only backs it up when no summary was written.
        self.assertEqual(news["items"][0]["text"], "Apple shipped its AI overhaul.")
        self.assertEqual(news["items"][0]["importance"], 5)
        self.assertEqual(news["items"][0]["articles_covering_event"], 16)
        self.assertEqual(news["mention_only"], 3)
        self.assertEqual(news["below_bar"], 7)
        self.assertTrue(any("busy news window" in w for w in result.warnings))
        # One citation per selected event, aligned with the bullet.
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(news["items"][0]["citation"], 1)

    def test_bullets_display_newest_first_even_when_ranked_otherwise(self):
        def screener(symbol, entries, company):
            # The screen returns rank order (oldest event ranked most
            # important); the card must still read as a timeline.
            return {
                "selected": [
                    {
                        "entry": entries[1],  # 2026-08-07
                        "verdict": None,
                        "materiality": 5,
                        "group_size": 1,
                        "card_text": "The big old event.",
                    },
                    {
                        "entry": entries[0],  # 2026-08-12
                        "verdict": None,
                        "materiality": 4,
                        "group_size": 1,
                        "card_text": "The newer event.",
                    },
                ],
                "mention_only": 0,
                "below_threshold": 0,
                "trimmed": 0,
                "warnings": [],
                "judgments": [],
                "from_cache": 0,
                "judged": 2,
            }

        result = make_provider(screener=screener).collect("AAPL")
        news = result.payload["news_coverage"]
        self.assertEqual(
            [item["date"] for item in news["items"]],
            ["2026-08-12", "2026-08-07"],
        )
        # Citations stay aligned after the re-sort: bullet [1] is the
        # newer article.
        self.assertEqual(news["items"][0]["text"], "The newer event.")
        self.assertEqual(
            result.citations[0].url, "https://example.com/apple-ai"
        )

    def test_supports_us_only(self):
        provider = make_provider()
        self.assertTrue(provider.supports(Market.US))
        for market in (Market.CN, Market.HK, Market.JP, Market.KR, Market.TW):
            self.assertFalse(provider.supports(market))


if __name__ == "__main__":
    unittest.main()
