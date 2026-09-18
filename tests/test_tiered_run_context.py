# -*- coding: utf-8 -*-
"""Offline tests for per-run settings (hosted-app work, 2026-09-14):
a run's own model and keys beat the environment, reach litellm
explicitly, ride into worker threads with the tracker, and never touch
the process environment."""
from __future__ import annotations

import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from src.tiered_analysis.llm_support import (
    LlmUsageTracker,
    default_summarizer,
    screen_summarizer,
)
from src.tiered_analysis.run_context import (
    RunSettings,
    active_run_settings,
    data_key,
    llm_api_key,
    llm_model,
)


class _FakeLitellm:
    def __init__(self):
        self.calls = []

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )


class TestFallbacks(unittest.TestCase):
    def test_outside_a_run_everything_comes_from_the_environment(self):
        with mock.patch.dict(os.environ, {"LITELLM_MODEL": "env/model",
                                          "FRED_API_KEY": "env-fred"}, clear=False):
            self.assertEqual(active_run_settings(), RunSettings())
            self.assertEqual(llm_model(), "env/model")
            self.assertIsNone(llm_api_key())
            self.assertEqual(data_key("fred"), "env-fred")

    def test_missing_values_are_none_not_empty_strings(self):
        with mock.patch.dict(os.environ, {"LITELLM_MODEL": "  ", "FINNHUB_API_KEY": ""}):
            self.assertIsNone(llm_model())
            self.assertIsNone(data_key("finnhub"))

    def test_unknown_data_key_name_is_a_programming_error(self):
        with self.assertRaises(KeyError):
            data_key("bloomberg")


class TestActiveRun(unittest.TestCase):
    def setUp(self):
        self.settings = RunSettings(
            llm_model="openai/gpt-5.6-luna", llm_api_key="sk-user",
            data_keys={"finnhub": "user-finnhub"},
        )
        self.tracker = LlmUsageTracker(settings=self.settings)

    def test_run_settings_beat_the_environment(self):
        with mock.patch.dict(os.environ, {"LITELLM_MODEL": "env/model",
                                          "FINNHUB_API_KEY": "env-finnhub",
                                          "FRED_API_KEY": "env-fred"}):
            with self.tracker.activate():
                self.assertEqual(llm_model(), "openai/gpt-5.6-luna")
                self.assertEqual(llm_api_key(), "sk-user")
                self.assertEqual(data_key("finnhub"), "user-finnhub")
                # a key the user did not bring falls back to the server's
                self.assertEqual(data_key("fred"), "env-fred")
            # and nothing leaked into the process environment
            self.assertEqual(os.environ["LITELLM_MODEL"], "env/model")
            self.assertEqual(os.environ["FINNHUB_API_KEY"], "env-finnhub")

    def test_summarizer_sends_the_run_key_and_model_to_litellm(self):
        fake = _FakeLitellm()
        with mock.patch.dict(sys.modules, {"litellm": fake}):
            with mock.patch.dict(os.environ, {"LITELLM_MODEL": "env/model"}):
                with self.tracker.activate():
                    default_summarizer("p")
                    screen_summarizer("q")
        for call in fake.calls:
            self.assertEqual(call["model"], "openai/gpt-5.6-luna")
            self.assertEqual(call["api_key"], "sk-user")

    def test_screening_uses_the_run_sub_model_when_it_has_one(self):
        fake = _FakeLitellm()
        tracker = LlmUsageTracker(settings=RunSettings(
            llm_model="openai/gpt-5.6-sol", llm_sub_model="openai/gpt-5.6-luna",
            llm_api_key="sk-user",
        ))
        with mock.patch.dict(sys.modules, {"litellm": fake}):
            with mock.patch.dict(os.environ, {"NEWS_SCREEN_MODEL": "env/screen"}):
                with tracker.activate():
                    default_summarizer("p")
                    screen_summarizer("q")
        self.assertEqual(fake.calls[0]["model"], "openai/gpt-5.6-sol")
        self.assertEqual(fake.calls[1]["model"], "openai/gpt-5.6-luna")
        self.assertEqual(fake.calls[1]["api_key"], "sk-user")

    def test_without_run_settings_no_key_is_passed(self):
        fake = _FakeLitellm()
        with mock.patch.dict(sys.modules, {"litellm": fake}):
            with mock.patch.dict(os.environ, {"LITELLM_MODEL": "env/model",
                                              "NEWS_SCREEN_MODEL": "env/screen"}):
                default_summarizer("p")
                screen_summarizer("q")
        self.assertNotIn("api_key", fake.calls[0])
        self.assertEqual(fake.calls[0]["model"], "env/model")
        self.assertEqual(fake.calls[1]["model"], "env/screen")

    def test_worker_threads_see_the_settings_once_they_activate_the_tracker(self):
        seen = {}

        def worker():
            with self.tracker.activate():
                seen["model"] = llm_model()
                seen["key"] = data_key("finnhub")

        with self.tracker.activate():
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
        self.assertEqual(seen, {"model": "openai/gpt-5.6-luna", "key": "user-finnhub"})

    def test_concurrent_runs_keep_their_own_settings(self):
        other = LlmUsageTracker(settings=RunSettings(llm_model="deepseek/deepseek-flash",
                                                     llm_api_key="sk-other"))
        seen = {}
        barrier = threading.Barrier(2)

        def run(name, tracker):
            with tracker.activate():
                barrier.wait()
                seen[name] = (llm_model(), llm_api_key())

        threads = [threading.Thread(target=run, args=("a", self.tracker)),
                   threading.Thread(target=run, args=("b", other))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(seen["a"], ("openai/gpt-5.6-luna", "sk-user"))
        self.assertEqual(seen["b"], ("deepseek/deepseek-flash", "sk-other"))


if __name__ == "__main__":
    unittest.main()
