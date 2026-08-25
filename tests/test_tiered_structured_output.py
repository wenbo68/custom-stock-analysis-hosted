# -*- coding: utf-8 -*-
"""Offline tests for structured LLM output (owner request 2026-08-25).

Two guarantees, layered:

1. ENFORCEMENT — the real summarizers hand the expected reply shape to
   the provider (litellm ``response_format``): full schema mode when the
   model supports it, plain JSON mode as the step down, prompt-only as
   the unchanged last resort. A provider that rejects the enforcement
   request gets one plain call — enforcement must never break a call
   that worked before it.
2. CHECK + RETRY — ``request_structured`` validates every reply against
   its pydantic form and retries once with the problem shown; the last
   reply's parsed dict is returned even when invalid so the tolerant
   fail-soft paths still see it.

Injected plain ``(prompt)`` fakes must keep working untouched — the
schema is an upgrade on the seam, never a new requirement.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from types import SimpleNamespace
from typing import List
from unittest import mock

from pydantic import BaseModel

from src.tiered_analysis.llm_support import (
    JSON_REPLY,
    default_summarizer,
    deterministic_summarizer,
    request_structured,
    screen_summarizer,
    summarize_with_schema,
)


class _GroupsForm(BaseModel):
    groups: List[List[int]]


class TestSummarizeWithSchema(unittest.TestCase):
    def test_plain_fake_is_called_without_the_schema(self):
        seen = {}

        def fake(prompt):
            seen["args"] = (prompt,)
            return "ok"

        self.assertEqual(summarize_with_schema(fake, "p", _GroupsForm), "ok")
        self.assertEqual(seen["args"], ("p",))

    def test_schema_aware_summarizer_receives_the_schema(self):
        seen = {}

        def fake(prompt, schema=None):
            seen["schema"] = schema
            return "ok"

        summarize_with_schema(fake, "p", _GroupsForm)
        self.assertIs(seen["schema"], _GroupsForm)

    def test_var_keyword_summarizer_receives_the_schema(self):
        seen = {}

        def fake(prompt, **kwargs):
            seen.update(kwargs)
            return "ok"

        summarize_with_schema(fake, "p", JSON_REPLY)
        self.assertEqual(seen["schema"], JSON_REPLY)

    def test_real_summarizers_all_accept_a_schema(self):
        import inspect

        for summarizer in (
            default_summarizer, screen_summarizer, deterministic_summarizer,
        ):
            self.assertIn(
                "schema", inspect.signature(summarizer).parameters,
                summarizer.__name__,
            )


class TestRequestStructured(unittest.TestCase):
    def test_valid_first_reply_needs_one_call(self):
        calls = []

        def fake(prompt):
            calls.append(prompt)
            return '{"groups": [[1, 2]]}'

        reply = request_structured(fake, "the prompt", _GroupsForm)
        self.assertEqual(len(calls), 1)
        self.assertTrue(reply.valid)
        self.assertFalse(reply.retried)
        self.assertEqual(reply.parsed, {"groups": [[1, 2]]})
        self.assertIsNone(reply.problem)

    def test_invalid_json_retries_once_with_the_problem_shown(self):
        calls = []

        def fake(prompt):
            calls.append(prompt)
            return "no json here" if len(calls) == 1 else '{"groups": [[1]]}'

        reply = request_structured(fake, "the prompt", _GroupsForm)
        self.assertEqual(len(calls), 2)
        self.assertTrue(reply.valid)
        self.assertTrue(reply.retried)
        self.assertIn("the prompt", calls[1])
        self.assertIn("was not a JSON object", calls[1])

    def test_wrong_shape_retries_with_the_validation_problem(self):
        calls = []

        def fake(prompt):
            calls.append(prompt)
            return (
                '{"groups": "oops"}' if len(calls) == 1
                else '{"groups": [[1]]}'
            )

        reply = request_structured(fake, "the prompt", _GroupsForm)
        self.assertTrue(reply.valid)
        self.assertTrue(reply.retried)
        self.assertIn("groups", calls[1])

    def test_both_replies_invalid_still_hands_back_the_parsed_dict(self):
        reply = request_structured(
            lambda prompt: '{"groups": 7}', "p", _GroupsForm
        )
        self.assertFalse(reply.valid)
        self.assertTrue(reply.retried)
        # The tolerant fail-soft callers still get whatever came back.
        self.assertEqual(reply.parsed, {"groups": 7})
        self.assertIsNotNone(reply.problem)

    def test_no_json_at_all_ends_with_parsed_none(self):
        reply = request_structured(lambda prompt: "prose", "p", _GroupsForm)
        self.assertIsNone(reply.parsed)
        self.assertFalse(reply.valid)

    def test_call_exception_propagates_without_a_retry(self):
        calls = []

        def fake(prompt):
            calls.append(prompt)
            raise RuntimeError("transport down")

        with self.assertRaises(RuntimeError):
            request_structured(fake, "p", _GroupsForm)
        self.assertEqual(len(calls), 1)  # transport failures never retry


class _FakeLitellm:
    """Stands in for the litellm module inside ``_summarize``."""

    class BadRequestError(Exception):
        pass

    def __init__(
        self,
        reply='{"groups": [[1]]}',
        schema_support=True,
        response_format_param=True,
        reject_response_format=False,
        capability_error=None,
    ):
        self._reply = reply
        self._schema_support = schema_support
        self._response_format_param = response_format_param
        self._reject_response_format = reject_response_format
        self._capability_error = capability_error
        self.calls = []

    def supports_response_schema(self, model):
        if self._capability_error is not None:
            raise self._capability_error
        return self._schema_support

    def get_supported_openai_params(self, model):
        if self._capability_error is not None:
            raise self._capability_error
        return ["response_format"] if self._response_format_param else []

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        if self._reject_response_format and "response_format" in kwargs:
            raise self.BadRequestError("schema not accepted here")
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self._reply))
            ],
        )


def _summarize_with(fake, schema):
    with mock.patch.dict(sys.modules, {"litellm": fake}):
        with mock.patch.dict(os.environ, {"LITELLM_MODEL": "fake/model"}):
            return default_summarizer("the prompt", schema=schema)


class TestProviderEnforcement(unittest.TestCase):
    def test_schema_capable_model_gets_the_pydantic_form(self):
        fake = _FakeLitellm(schema_support=True)
        _summarize_with(fake, _GroupsForm)
        [call] = fake.calls
        self.assertIs(call["response_format"], _GroupsForm)

    def test_schema_incapable_model_steps_down_to_json_mode(self):
        fake = _FakeLitellm(schema_support=False, response_format_param=True)
        _summarize_with(fake, _GroupsForm)
        [call] = fake.calls
        self.assertEqual(call["response_format"], {"type": "json_object"})

    def test_json_reply_sentinel_requests_json_mode(self):
        fake = _FakeLitellm()
        _summarize_with(fake, JSON_REPLY)
        [call] = fake.calls
        self.assertEqual(call["response_format"], {"type": "json_object"})

    def test_no_enforcement_support_degrades_to_prompt_only(self):
        fake = _FakeLitellm(schema_support=False, response_format_param=False)
        _summarize_with(fake, _GroupsForm)
        [call] = fake.calls
        self.assertNotIn("response_format", call)

    def test_capability_lookup_error_degrades_to_prompt_only(self):
        fake = _FakeLitellm(capability_error=RuntimeError("unknown model"))
        _summarize_with(fake, _GroupsForm)
        [call] = fake.calls
        self.assertNotIn("response_format", call)

    def test_no_schema_keeps_the_old_call_shape(self):
        fake = _FakeLitellm()
        with mock.patch.dict(sys.modules, {"litellm": fake}):
            with mock.patch.dict(os.environ, {"LITELLM_MODEL": "fake/model"}):
                default_summarizer("the prompt")
        [call] = fake.calls
        self.assertNotIn("response_format", call)

    def test_provider_rejecting_the_schema_gets_one_plain_call(self):
        fake = _FakeLitellm(reject_response_format=True)
        raw = _summarize_with(fake, _GroupsForm)
        self.assertEqual(raw, '{"groups": [[1]]}')
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("response_format", fake.calls[0])
        self.assertNotIn("response_format", fake.calls[1])


class TestNewsScreenRetry(unittest.TestCase):
    """The screen's calls ride the shared retry: a bad first reply is
    re-asked once, and a successful retry is warned in the report."""

    def _entries(self, count=2):
        return [
            {
                "title": f"Story {index}",
                "publisher": "Wire",
                "url": f"https://example.com/{index}",
                "date": "2026-08-20",
                "summary": None,
            }
            for index in range(count)
        ]

    def test_grouping_recovers_on_the_retry_with_a_warning(self):
        from src.tiered_analysis.news_screen import llm_group_events

        replies = iter(["not json", json.dumps({"groups": [[1, 2]]})])
        result = llm_group_events(
            "GOOGL", self._entries(), summarize=lambda prompt: next(replies)
        )
        self.assertEqual(result["groups"], [[0, 1]])
        self.assertIn(
            "news grouping needed a retry — first reply was invalid",
            result["warnings"],
        )

    def test_judge_recovers_on_the_retry_with_a_warning(self):
        from src.tiered_analysis.news_screen import llm_judge_news

        replies = iter([
            "not json",
            json.dumps({"articles": [[1, 1, 4], [2, 0, 0]]}),
        ])
        result = llm_judge_news(
            "GOOGL", self._entries(), summarize=lambda prompt: next(replies)
        )
        self.assertTrue(result["judgments"][0]["about_company"])
        self.assertFalse(result["judgments"][1]["about_company"])
        self.assertIn(
            "news judge needed a retry — first reply was invalid",
            result["warnings"],
        )

    def test_still_invalid_after_retry_keeps_the_old_fallback_wording(self):
        from src.tiered_analysis.news_screen import llm_group_events

        result = llm_group_events(
            "GOOGL", self._entries(), summarize=lambda prompt: "never json"
        )
        self.assertEqual(result["groups"], [[0], [1]])
        self.assertEqual(
            result["warnings"],
            ["news grouping returned no usable JSON — no grouping"],
        )


if __name__ == "__main__":
    unittest.main()
