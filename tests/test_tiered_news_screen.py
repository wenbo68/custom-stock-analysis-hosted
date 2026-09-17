# -*- coding: utf-8 -*-
"""Offline tests for the LLM news screen: judge prompt/parsing, the
per-URL judgment+summary cache, headline grouping, selection, finalist
ranking, card summaries, and the fail-soft keep-everything contract at
every stage."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from unittest import mock

from src.tiered_analysis.cache_store import MemoryCacheStore
from src.tiered_analysis import news_screen
from src.tiered_analysis.news_screen import (
    NewsJudgmentCache,
    build_group_prompt,
    build_judge_prompt,
    build_rank_prompt,
    build_summarize_prompt,
    judge_news_cached,
    llm_group_events,
    llm_judge_news,
    llm_rank_events,
    llm_summarize_articles,
    screen_news,
    select_events,
    summarize_articles_cached,
)


def entries():
    return [
        {
            "title": "Alphabet sells $25 billion in bonds",
            "publisher": "Reuters",
            "url": "https://example.com/bonds",
            "date": "2026-08-07",
            "summary": "Second major debt sale this year.",
        },
        {
            "title": "Micron outlook improves",
            "publisher": "Zacks",
            "url": "https://example.com/micron",
            "date": "2026-08-12",
            "summary": "Chipmakers sell to hyperscalers like Alphabet.",
        },
        {
            "title": "3 reasons to hold Alphabet",
            "publisher": "Motley Fool",
            "url": "https://example.com/hold",
            "date": "2026-08-13",
            "summary": None,
        },
    ]


def canned(response):
    """A fake summarizer that returns a fixed response and records the
    prompts it was handed."""
    calls = []

    def summarize(prompt):
        calls.append(prompt)
        return response

    summarize.calls = calls
    return summarize


class TestPrompts(unittest.TestCase):
    def test_judge_prompt_numbers_articles_with_date_outlet_and_abstract(self):
        prompt = build_judge_prompt("GOOGL", entries(), company="Alphabet")
        self.assertIn("GOOGL (Alphabet)", prompt)
        self.assertIn(
            "[1] (2026-08-07, Reuters) Alphabet sells $25 billion in bonds"
            " — Second major debt sale this year.",
            prompt,
        )
        # No abstract -> the headline stands alone, never "None".
        self.assertIn("[3] (2026-08-13, Motley Fool) 3 reasons to hold Alphabet", prompt)
        self.assertNotIn("None", prompt.split("Articles:")[1])

    def test_judge_prompt_asks_for_compact_arrays_unless_reasons_requested(self):
        compact = build_judge_prompt("GOOGL", entries())
        self.assertIn("[n, about_company, materiality]", compact)
        self.assertNotIn('"reason"', compact)
        reasoned = build_judge_prompt("GOOGL", entries(), include_reasons=True)
        self.assertIn('"reason"', reasoned)

    def test_group_prompt_shows_headlines_without_abstracts(self):
        prompt = build_group_prompt("GOOGL", entries(), company="Alphabet")
        self.assertIn('{"groups": [[1, 4, 9], [2], [3]]}', prompt)
        self.assertIn("[1] (2026-08-07, Reuters) Alphabet sells", prompt)
        self.assertNotIn("Second major debt sale", prompt)

    def test_rank_prompt_shows_headlines_without_abstracts(self):
        prompt = build_rank_prompt("GOOGL", entries(), company="Alphabet")
        self.assertIn('{"order": [n, n, ...]}', prompt)
        self.assertIn("[1] (2026-08-07, Reuters) Alphabet sells", prompt)
        self.assertNotIn("Second major debt sale", prompt)

    def test_summarize_prompt_carries_abstracts_and_the_word_cap(self):
        prompt = build_summarize_prompt("GOOGL", entries(), company="Alphabet")
        self.assertIn('{"summaries": [[n, "one-sentence summary"], ...]}', prompt)
        self.assertIn("Second major debt sale this year.", prompt)
        self.assertIn(f"at most {news_screen.SUMMARY_MAX_WORDS} words", prompt)


class TestJudge(unittest.TestCase):
    def test_compact_array_judgments_parse_with_zero_one_flags(self):
        response = json.dumps({"articles": [[1, 1, 5], [2, 0, 0], [3, 1, 1]]})
        result = llm_judge_news("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(result["warnings"], [])
        self.assertEqual([j["index"] for j in result["judgments"]], [0, 1, 2])
        self.assertTrue(result["judgments"][0]["about_company"])
        self.assertFalse(result["judgments"][1]["about_company"])
        self.assertEqual(result["judgments"][0]["materiality"], 5)
        self.assertTrue(all(j["from_model"] for j in result["judgments"]))

    def test_fourth_array_element_is_the_reason(self):
        response = json.dumps(
            {"articles": [[1, 1, 5, "debt sale"], [2, 0, 0, ""], [3, 1, 1]]}
        )
        result = llm_judge_news("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(result["judgments"][0]["reason"], "debt sale")
        self.assertIsNone(result["judgments"][1]["reason"])

    def test_labeled_dict_shape_still_parses(self):
        response = json.dumps(
            {
                "articles": [
                    {"n": 1, "about_company": True, "materiality": 9},
                    {"n": 2, "about_company": False, "materiality": 0},
                    {"n": 3, "about_company": True, "materiality": 1},
                ]
            }
        )
        result = llm_judge_news("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(result["judgments"][0]["materiality"], 5)  # 9 clamped
        self.assertFalse(result["judgments"][1]["about_company"])

    def test_fenced_json_is_accepted(self):
        response = (
            "```json\n"
            + json.dumps({"articles": [[1, 1, 3], [2, 1, 3], [3, 1, 3]]})
            + "\n```"
        )
        result = llm_judge_news("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(len(result["judgments"]), 3)
        self.assertEqual(result["warnings"], [])

    def test_missing_judgments_default_to_keep_with_warning(self):
        response = json.dumps({"articles": [[1, 0, 0]]})
        result = llm_judge_news("GOOGL", entries(), summarize=canned(response))
        self.assertFalse(result["judgments"][0]["about_company"])
        self.assertTrue(result["judgments"][1]["about_company"])
        self.assertIsNone(result["judgments"][1]["materiality"])
        self.assertFalse(result["judgments"][1]["from_model"])
        self.assertTrue(any("gave no judgment for 2" in w for w in result["warnings"]))

    def test_garbage_json_keeps_everything_with_warning(self):
        result = llm_judge_news("GOOGL", entries(), summarize=canned("not json"))
        self.assertEqual(len(result["judgments"]), 3)
        self.assertTrue(all(j["about_company"] for j in result["judgments"]))
        self.assertTrue(any("no usable JSON" in w for w in result["warnings"]))

    def test_llm_exception_keeps_everything_with_warning(self):
        def broken(prompt):
            raise RuntimeError("model down")

        result = llm_judge_news("GOOGL", entries(), summarize=broken)
        self.assertEqual(len(result["judgments"]), 3)
        self.assertTrue(all(j["about_company"] for j in result["judgments"]))
        self.assertTrue(any("model down" in w for w in result["warnings"]))

    def test_out_of_range_and_malformed_judgments_are_ignored(self):
        response = json.dumps(
            {
                "articles": [
                    [0, 1, 3],       # out of range
                    [99, 1, 3],      # out of range
                    "gibberish",     # not a list
                    [1, "yes", 3],   # about not a bool/0/1
                    [2, 1, "hi"],    # bad materiality degrades to None
                ]
            }
        )
        result = llm_judge_news("GOOGL", entries(), summarize=canned(response))
        self.assertTrue(result["judgments"][1]["about_company"])
        self.assertIsNone(result["judgments"][1]["materiality"])
        self.assertTrue(any("gave no judgment for 2" in w for w in result["warnings"]))

    def test_empty_input_makes_no_llm_call(self):
        summarize = canned("{}")
        result = llm_judge_news("GOOGL", [], summarize=summarize)
        self.assertEqual(result, {"judgments": [], "warnings": []})
        self.assertEqual(summarize.calls, [])


class TestCache(unittest.TestCase):
    def setUp(self):
        self.store = MemoryCacheStore()

    def make_cache(self, today=date(2026, 8, 15)):
        return NewsJudgmentCache("GOOGL", cache=self.store,
                                 today=lambda: today)

    def test_roundtrip_survives_reload(self):
        cache = self.make_cache()
        cache.put("https://example.com/a", True, 4, "2026-08-13")
        cache.save()
        again = self.make_cache()
        self.assertEqual(
            again.get("https://example.com/a"),
            {"about": True, "materiality": 4, "date": "2026-08-13"},
        )

    def test_articles_older_than_any_window_are_pruned_on_load(self):
        cache = self.make_cache()
        cache.put("https://example.com/old", True, 4, "2026-07-01")
        cache.put("https://example.com/new", True, 4, "2026-08-13")
        cache.save()
        again = self.make_cache()
        self.assertIsNone(again.get("https://example.com/old"))
        self.assertIsNotNone(again.get("https://example.com/new"))

    def test_corrupt_entry_degrades_to_cold_cache(self):
        self.store.data["news_screen_GOOGL"] = "not json"
        cache = self.make_cache()
        self.assertIsNone(cache.get("https://example.com/a"))

    def test_summary_roundtrip_and_prune(self):
        cache = self.make_cache()
        cache.put_summary("https://example.com/old", "Old news.", "2026-07-01")
        cache.put_summary("https://example.com/new", "New news.", "2026-08-13")
        cache.save()
        again = self.make_cache()
        self.assertIsNone(again.get_summary("https://example.com/old"))
        self.assertEqual(again.get_summary("https://example.com/new"), "New news.")

    def test_pre_summary_cache_entry_still_loads(self):
        # Cache entries written before summaries existed have no
        # "summaries" key — judgments must still load (additive schema).
        self.store.write(
            "news_screen_GOOGL",
            {
                "version": 1,
                "articles": {
                    "https://example.com/a": {
                        "about": True, "materiality": 4, "date": "2026-08-13",
                    }
                },
            },
        )
        cache = self.make_cache()
        self.assertIsNotNone(cache.get("https://example.com/a"))
        self.assertIsNone(cache.get_summary("https://example.com/a"))

    def test_a_summary_never_masquerades_as_a_judgment(self):
        cache = self.make_cache()
        cache.put_summary("https://example.com/a", "Summary only.", "2026-08-13")
        self.assertIsNone(cache.get("https://example.com/a"))


class TestJudgeCached(unittest.TestCase):
    def setUp(self):
        self.cache = NewsJudgmentCache(
            "GOOGL", cache=MemoryCacheStore(),
            today=lambda: date(2026, 8, 15),
        )

    def test_cached_articles_skip_the_llm_entirely(self):
        for entry in entries():
            self.cache.put(entry["url"], True, 3, entry["date"])
        summarize = canned("{}")
        result = judge_news_cached(
            "GOOGL", entries(), summarize=summarize, cache=self.cache
        )
        self.assertEqual(summarize.calls, [])
        self.assertEqual(result["from_cache"], 3)
        self.assertEqual(result["judged"], 0)
        self.assertTrue(all(j["about_company"] for j in result["judgments"]))

    def test_only_new_articles_are_judged_and_then_cached(self):
        self.cache.put("https://example.com/bonds", True, 5, "2026-08-07")
        summarize = canned(json.dumps({"articles": [[1, 0, 0], [2, 1, 1]]}))
        result = judge_news_cached(
            "GOOGL", entries(), summarize=summarize, cache=self.cache
        )
        self.assertEqual(len(summarize.calls), 1)
        # The single LLM prompt carries only the two uncached articles.
        self.assertIn("Micron outlook improves", summarize.calls[0])
        self.assertNotIn("$25 billion", summarize.calls[0])
        self.assertEqual(result["from_cache"], 1)
        self.assertEqual(result["judged"], 2)
        # Judgments land on the right global positions.
        self.assertEqual(result["judgments"][0]["materiality"], 5)   # cache hit
        self.assertFalse(result["judgments"][1]["about_company"])    # judged
        # And the fresh judgments are now cached for tomorrow.
        self.assertEqual(self.cache.get("https://example.com/micron")["about"], False)

    def test_fail_soft_fallbacks_are_never_cached(self):
        result = judge_news_cached(
            "GOOGL", entries(), summarize=canned("not json"), cache=self.cache
        )
        self.assertEqual(result["judged"], 3)
        for entry in entries():
            self.assertIsNone(self.cache.get(entry["url"]))

    def test_large_batches_split_and_all_positions_come_back(self):
        many = [
            {
                "title": f"Alphabet story {index}",
                "publisher": "Wire",
                "url": f"https://example.com/{index}",
                "date": "2026-08-13",
                "summary": None,
            }
            for index in range(5)
        ]

        def summarize(prompt):
            summarize.calls.append(prompt)
            count = prompt.split("Articles:")[1].count("\n[")
            return json.dumps({"articles": [[i, 1, 2] for i in range(1, count + 1)]})

        summarize.calls = []
        with mock.patch.object(news_screen, "JUDGE_BATCH_SIZE", 2):
            result = judge_news_cached("GOOGL", many, summarize=summarize)
        self.assertEqual(len(summarize.calls), 3)  # 2 + 2 + 1
        self.assertEqual([j["index"] for j in result["judgments"]], [0, 1, 2, 3, 4])
        self.assertTrue(all(j["materiality"] == 2 for j in result["judgments"]))


class TestGroup(unittest.TestCase):
    def test_groups_come_back_zero_based_and_complete(self):
        response = json.dumps({"groups": [[1, 3], [2]]})
        result = llm_group_events("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(result["groups"], [[0, 2], [1]])
        self.assertEqual(result["warnings"], [])

    def test_forgotten_articles_become_their_own_events_with_warning(self):
        response = json.dumps({"groups": [[1]]})
        result = llm_group_events("GOOGL", entries(), summarize=canned(response))
        self.assertIn([1], result["groups"])
        self.assertIn([2], result["groups"])
        self.assertTrue(any("ungrouped" in w for w in result["warnings"]))

    def test_garbage_json_degrades_to_singletons_with_warning(self):
        result = llm_group_events("GOOGL", entries(), summarize=canned("not json"))
        self.assertEqual(result["groups"], [[0], [1], [2]])
        self.assertTrue(any("no usable JSON" in w for w in result["warnings"]))

    def test_single_article_needs_no_llm_call(self):
        summarize = canned("{}")
        result = llm_group_events("GOOGL", entries()[:1], summarize=summarize)
        self.assertEqual(result["groups"], [[0]])
        self.assertEqual(summarize.calls, [])


class TestRank(unittest.TestCase):
    def test_order_comes_back_zero_based(self):
        response = json.dumps({"order": [2, 3, 1]})
        result = llm_rank_events("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(result["order"], [1, 2, 0])
        self.assertEqual(result["warnings"], [])

    def test_forgotten_events_append_in_input_order_with_warning(self):
        response = json.dumps({"order": [2]})
        result = llm_rank_events("GOOGL", entries(), summarize=canned(response))
        self.assertEqual(result["order"], [1, 0, 2])
        self.assertTrue(any("unranked" in w for w in result["warnings"]))

    def test_garbage_json_keeps_input_order_with_warning(self):
        result = llm_rank_events("GOOGL", entries(), summarize=canned("not json"))
        self.assertEqual(result["order"], [0, 1, 2])
        self.assertTrue(any("no usable JSON" in w for w in result["warnings"]))

    def test_llm_exception_keeps_input_order_with_warning(self):
        def broken(prompt):
            raise RuntimeError("model down")

        result = llm_rank_events("GOOGL", entries(), summarize=broken)
        self.assertEqual(result["order"], [0, 1, 2])
        self.assertTrue(any("model down" in w for w in result["warnings"]))

    def test_single_event_needs_no_llm_call(self):
        summarize = canned("{}")
        result = llm_rank_events("GOOGL", entries()[:1], summarize=summarize)
        self.assertEqual(result["order"], [0])
        self.assertEqual(summarize.calls, [])


class TestSummarize(unittest.TestCase):
    def test_summaries_land_on_their_positions_whitespace_flattened(self):
        response = json.dumps(
            {"summaries": [[1, "Bond sale."], [3, "  Hold\n thesis. "]]}
        )
        result = llm_summarize_articles(
            "GOOGL", entries(), summarize=canned(response)
        )
        self.assertEqual(
            result["summaries"], ["Bond sale.", None, "Hold thesis."]
        )
        self.assertTrue(any("missing for 1" in w for w in result["warnings"]))

    def test_garbage_json_degrades_to_verbatim_with_warning(self):
        result = llm_summarize_articles(
            "GOOGL", entries(), summarize=canned("not json")
        )
        self.assertEqual(result["summaries"], [None, None, None])
        self.assertTrue(any("no usable JSON" in w for w in result["warnings"]))

    def test_llm_exception_degrades_to_verbatim_with_warning(self):
        def broken(prompt):
            raise RuntimeError("model down")

        result = llm_summarize_articles("GOOGL", entries(), summarize=broken)
        self.assertEqual(result["summaries"], [None, None, None])
        self.assertTrue(any("model down" in w for w in result["warnings"]))

    def test_empty_input_makes_no_llm_call(self):
        summarize = canned("{}")
        result = llm_summarize_articles("GOOGL", [], summarize=summarize)
        self.assertEqual(result, {"summaries": [], "warnings": []})
        self.assertEqual(summarize.calls, [])


class TestSummarizeCached(unittest.TestCase):
    def setUp(self):
        self.store = MemoryCacheStore()

    def make_cache(self):
        return NewsJudgmentCache(
            "GOOGL", cache=self.store, today=lambda: date(2026, 8, 15)
        )

    def test_cached_summaries_skip_the_llm_entirely(self):
        cache = self.make_cache()
        for entry in entries():
            cache.put_summary(entry["url"], "Cached sentence.", entry["date"])
        summarize = canned("{}")
        result = summarize_articles_cached(
            "GOOGL", entries(), summarize=summarize, cache=cache
        )
        self.assertEqual(summarize.calls, [])
        self.assertEqual(result["from_cache"], 3)
        self.assertEqual(result["summarized"], 0)
        self.assertEqual(result["summaries"], ["Cached sentence."] * 3)

    def test_new_summaries_are_written_back(self):
        cache = self.make_cache()
        cache.put_summary(
            "https://example.com/bonds", "Old cached bond sentence.", "2026-08-07"
        )
        response = json.dumps({"summaries": [[1, "Micron."], [2, "Hold."]]})
        summarize = canned(response)
        result = summarize_articles_cached(
            "GOOGL", entries(), summarize=summarize, cache=cache
        )
        # The single LLM prompt carries only the two uncached articles.
        self.assertEqual(len(summarize.calls), 1)
        self.assertNotIn("$25 billion", summarize.calls[0])
        self.assertEqual(
            result["summaries"], ["Old cached bond sentence.", "Micron.", "Hold."]
        )
        # And the fresh summaries survive a reload.
        again = self.make_cache()
        self.assertEqual(again.get_summary("https://example.com/micron"), "Micron.")

    def test_failed_summaries_are_never_cached(self):
        cache = self.make_cache()
        result = summarize_articles_cached(
            "GOOGL", entries(), summarize=canned("not json"), cache=cache
        )
        self.assertEqual(result["summaries"], [None, None, None])
        for entry in entries():
            self.assertIsNone(cache.get_summary(entry["url"]))


class TestSelectEvents(unittest.TestCase):
    def judgment(self, index, about=True, materiality=3, event=None):
        return {
            "index": index,
            "about_company": about,
            "materiality": materiality,
            "event": index if event is None else event,
            "reason": None,
        }

    def entry(self, title, date_="2026-08-13", summary=None):
        return {"title": title, "date": date_, "summary": summary, "publisher": "X"}

    def test_event_group_collapses_to_its_most_important_article(self):
        items = [
            self.entry("routine rewrite", summary="A rewrite."),
            self.entry("the big original", summary="What happened."),
        ]
        judgments = [
            self.judgment(0, materiality=4, event=0),
            self.judgment(1, materiality=5, event=0),
        ]
        result = select_events(items, judgments)
        self.assertEqual(len(result["selected"]), 1)
        chosen = result["selected"][0]
        # The highest-scored member represents the group (owner decision
        # 2026-08-15: most important article, not merely best-formatted).
        self.assertEqual(chosen["entry"]["title"], "the big original")
        self.assertEqual(chosen["materiality"], 5)
        self.assertEqual(chosen["group_size"], 2)

    def test_equal_scores_break_ties_toward_an_abstract(self):
        items = [
            self.entry("bare headline rewrite"),
            self.entry("original with abstract", summary="What happened."),
        ]
        judgments = [
            self.judgment(0, materiality=4, event=0),
            self.judgment(1, materiality=4, event=0),
        ]
        result = select_events(items, judgments)
        self.assertEqual(
            result["selected"][0]["entry"]["title"], "original with abstract"
        )

    def test_threshold_cuts_low_scores_and_counts_them(self):
        items = [self.entry("big"), self.entry("listicle")]
        judgments = [
            self.judgment(0, materiality=4),
            self.judgment(1, materiality=1),
        ]
        result = select_events(items, judgments, threshold=3)
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["below_threshold"], 1)

    def test_mention_only_articles_never_form_events(self):
        items = [self.entry("about us"), self.entry("about someone else")]
        judgments = [
            self.judgment(0, materiality=4),
            self.judgment(1, about=False, materiality=0),
        ]
        result = select_events(items, judgments)
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["mention_only"], 1)

    def test_unknown_materiality_passes_selection(self):
        # Fail-soft upstream: a judgment the LLM never delivered must not
        # vanish here.
        items = [self.entry("unjudged story")]
        judgments = [self.judgment(0, materiality=None)]
        result = select_events(items, judgments, threshold=3)
        self.assertEqual(len(result["selected"]), 1)
        self.assertIsNone(result["selected"][0]["materiality"])


class TestScreenNews(unittest.TestCase):
    """End-to-end: judge (cached) -> group -> select -> rank-trim ->
    summarize, with one fake summarizer answering all four prompt
    kinds (told apart by phrases unique to each prompt template)."""

    def summarizer(
        self,
        judge_response,
        group_response,
        rank_response="not json",
        summary_response="not json",
    ):
        calls = {"judge": [], "group": [], "rank": [], "summary": []}

        def summarize(prompt):
            if "Group together" in prompt:
                calls["group"].append(prompt)
                return group_response
            if "Rank them" in prompt:
                calls["rank"].append(prompt)
                return rank_response
            if "card bullets" in prompt:
                calls["summary"].append(prompt)
                return summary_response
            calls["judge"].append(prompt)
            return judge_response

        summarize.calls = calls
        return summarize

    def test_full_flow_groups_and_selects_across_the_window(self):
        items = [
            {
                "title": "Alphabet sells $25 billion in bonds",
                "publisher": "Reuters",
                "url": "https://example.com/bonds",
                "date": "2026-08-07",
                "summary": "Second major debt sale this year.",
            },
            {  # same story, different outlet, other end of the window
                "title": "Alphabet lines up $25B bond offering",
                "publisher": "Barron's",
                "url": "https://example.com/bonds2",
                "date": "2026-08-14",
                "summary": None,
            },
            {  # mention-only
                "title": "Micron outlook improves",
                "publisher": "Zacks",
                "url": "https://example.com/micron",
                "date": "2026-08-12",
                "summary": "Chipmakers sell to hyperscalers like Alphabet.",
            },
            {  # below threshold
                "title": "3 reasons to hold Alphabet",
                "publisher": "Motley Fool",
                "url": "https://example.com/hold",
                "date": "2026-08-13",
                "summary": None,
            },
        ]
        judge = json.dumps(
            {"articles": [[1, 1, 5], [2, 1, 4], [3, 0, 0], [4, 1, 1]]}
        )
        # Only the two bond articles survive to grouping (listicle is
        # below threshold, Micron is mention-only) -> local numbers 1, 2.
        group = json.dumps({"groups": [[1, 2]]})
        summary = json.dumps(
            {"summaries": [[1, "Alphabet raised $25 billion in bonds."]]}
        )
        summarize = self.summarizer(judge, group, summary_response=summary)
        result = screen_news("GOOGL", items, summarize=summarize, threshold=3)

        self.assertEqual(len(summarize.calls["judge"]), 1)
        self.assertEqual(len(summarize.calls["group"]), 1)
        # The grouping prompt carries only the two candidates.
        self.assertIn("bond", summarize.calls["group"][0])
        self.assertNotIn("Micron", summarize.calls["group"][0])
        # One event, far under the ceiling -> ranking never runs.
        self.assertEqual(summarize.calls["rank"], [])
        # The summary prompt carries only the winning representative.
        self.assertEqual(len(summarize.calls["summary"]), 1)
        self.assertIn("$25 billion", summarize.calls["summary"][0])
        self.assertNotIn("Micron", summarize.calls["summary"][0])

        self.assertEqual(len(result["selected"]), 1)
        chosen = result["selected"][0]
        self.assertEqual(chosen["entry"]["url"], "https://example.com/bonds")
        self.assertEqual(chosen["materiality"], 5)
        self.assertEqual(chosen["group_size"], 2)
        self.assertEqual(chosen["card_text"], "Alphabet raised $25 billion in bonds.")
        self.assertEqual(result["mention_only"], 1)
        self.assertEqual(result["below_threshold"], 1)
        self.assertEqual(result["trimmed"], 0)

    def test_over_ceiling_events_are_ranked_and_trimmed(self):
        items = [
            {
                "title": f"Alphabet development {index}",
                "publisher": "Wire",
                "url": f"https://example.com/{index}",
                "date": f"2026-08-{10 + index}",
                "summary": None,
            }
            for index in range(3)
        ]
        judge = json.dumps({"articles": [[1, 1, 4], [2, 1, 4], [3, 1, 4]]})
        group = json.dumps({"groups": [[1], [2], [3]]})
        # The rank prompt sees events in score/date order (newest
        # first: urls 2, 1, 0) and the model ranks the OLDEST story
        # most important — proving the cut follows the ranking, not
        # the score/date order.
        rank = json.dumps({"order": [3, 1, 2]})
        summarize = self.summarizer(judge, group, rank_response=rank)
        result = screen_news(
            "GOOGL", items, summarize=summarize, threshold=3, max_events=2
        )

        self.assertEqual(len(summarize.calls["rank"]), 1)
        self.assertEqual(result["trimmed"], 1)
        self.assertEqual(
            [event["entry"]["url"] for event in result["selected"]],
            ["https://example.com/0", "https://example.com/2"],
        )
        self.assertTrue(any("busy news window" in w for w in result["warnings"]))
        # Only the two survivors get summarized. (The fake's default
        # summary reply is invalid, which since 2026-08-25 costs one
        # retry — so assert on every ask, not on the call count.)
        self.assertTrue(summarize.calls["summary"])
        for prompt in summarize.calls["summary"]:
            self.assertNotIn("development 1", prompt)

    def test_failed_ranking_falls_back_to_score_order_for_the_cut(self):
        items = [
            {
                "title": f"Alphabet development {index}",
                "publisher": "Wire",
                "url": f"https://example.com/{index}",
                "date": f"2026-08-{10 + index}",
                "summary": None,
            }
            for index in range(3)
        ]
        judge = json.dumps({"articles": [[1, 1, 3], [2, 1, 5], [3, 1, 4]]})
        group = json.dumps({"groups": [[1], [2], [3]]})
        summarize = self.summarizer(judge, group, rank_response="not json")
        result = screen_news(
            "GOOGL", items, summarize=summarize, threshold=3, max_events=2
        )
        # Highest scores survive; the score-3 story is the one trimmed.
        self.assertEqual(
            sorted(event["materiality"] for event in result["selected"]), [4, 5]
        )
        self.assertTrue(any("no usable JSON" in w for w in result["warnings"]))
        self.assertTrue(any("busy news window" in w for w in result["warnings"]))

    def test_second_run_judges_and_summarizes_nothing_new(self):
        store = MemoryCacheStore()
        if True:  # one shared store across the two "runs"
            cache = NewsJudgmentCache(
                "GOOGL", cache=store, today=lambda: date(2026, 8, 15)
            )
            judge = json.dumps({"articles": [[1, 1, 5], [2, 0, 0], [3, 1, 1]]})
            group = json.dumps({"groups": [[1]]})
            summary = json.dumps({"summaries": [[1, "Bond sale sentence."]]})
            first = screen_news(
                "GOOGL", entries(),
                summarize=self.summarizer(judge, group, summary_response=summary),
                cache=cache,
            )
            self.assertEqual(first["judged"], 3)
            self.assertEqual(first["selected"][0]["card_text"], "Bond sale sentence.")

            fresh_cache = NewsJudgmentCache(
                "GOOGL", cache=store, today=lambda: date(2026, 8, 15)
            )
            summarize = self.summarizer("never used", group)
            second = screen_news(
                "GOOGL", entries(), summarize=summarize, cache=fresh_cache
            )
            self.assertEqual(second["judged"], 0)
            self.assertEqual(second["from_cache"], 3)
            self.assertEqual(summarize.calls["judge"], [])
            # The winner's summary comes straight from cache too.
            self.assertEqual(summarize.calls["summary"], [])
            self.assertEqual(
                second["selected"][0]["entry"]["url"], "https://example.com/bonds"
            )
            self.assertEqual(
                second["selected"][0]["card_text"], "Bond sale sentence."
            )


if __name__ == "__main__":
    unittest.main()
