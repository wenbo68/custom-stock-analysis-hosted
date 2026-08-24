# -*- coding: utf-8 -*-
"""Offline tests for the per-run LLM usage tracker (v2 slice 6).

The tracker gives cost visibility: how many LLM calls (and tokens) each
pipeline stage of a tiered run made. Recording is ambient (thread-local)
so engines don't need plumbing; with no active tracker it is a no-op.
"""
from __future__ import annotations

import threading
import unittest

from src.tiered_analysis.llm_support import (
    LlmUsageTracker,
    record_llm_usage,
)


class TestLlmUsageTracker(unittest.TestCase):
    def test_records_into_current_stage(self):
        tracker = LlmUsageTracker()
        with tracker.activate():
            with tracker.stage("tier2_debate"):
                record_llm_usage(100, 20)
                record_llm_usage(50, 10)
            with tracker.stage("tier3_risk"):
                record_llm_usage(200, 40)

        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["tier2_debate"],
                         {"calls": 2, "prompt_tokens": 150,
                          "completion_tokens": 30})
        self.assertEqual(detail["stages"]["tier3_risk"]["calls"], 1)
        self.assertEqual(detail["total"],
                         {"calls": 3, "prompt_tokens": 350,
                          "completion_tokens": 70})

    def test_scope_note_present(self):
        # Readers of a stored run must know tier 1's synthesis (inside the
        # DSA pipeline) is not part of these numbers.
        detail = LlmUsageTracker().to_detail()
        self.assertIn("tier-1", detail["scope"])

    def test_no_active_tracker_is_a_noop(self):
        record_llm_usage(999, 999)  # must not raise or leak anywhere
        tracker = LlmUsageTracker()
        self.assertEqual(tracker.to_detail()["total"]["calls"], 0)

    def test_call_outside_any_stage_is_kept_not_lost(self):
        tracker = LlmUsageTracker()
        with tracker.activate():
            record_llm_usage(10, 5)
        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["unattributed"]["calls"], 1)

    def test_missing_token_counts_still_count_the_call(self):
        tracker = LlmUsageTracker()
        with tracker.activate():
            with tracker.stage("level_adjuster"):
                record_llm_usage(None, None)
        stage = tracker.to_detail()["stages"]["level_adjuster"]
        self.assertEqual(stage, {"calls": 1, "prompt_tokens": 0,
                                 "completion_tokens": 0})

    def test_activation_restores_previous_tracker(self):
        outer, inner = LlmUsageTracker(), LlmUsageTracker()
        with outer.activate():
            with inner.activate():
                record_llm_usage(1, 1)
            record_llm_usage(2, 2)
        self.assertEqual(inner.to_detail()["total"]["calls"], 1)
        self.assertEqual(outer.to_detail()["total"]["calls"], 1)
        self.assertEqual(outer.to_detail()["total"]["prompt_tokens"], 2)

    def test_trackers_are_thread_local(self):
        tracker = LlmUsageTracker()
        recorded_in_other_thread = []

        def other_thread():
            record_llm_usage(500, 500)  # no tracker active on THIS thread
            recorded_in_other_thread.append(True)

        with tracker.activate():
            worker = threading.Thread(target=other_thread)
            worker.start()
            worker.join()
        self.assertTrue(recorded_in_other_thread)
        self.assertEqual(tracker.to_detail()["total"]["calls"], 0)

    def test_nested_stages_restore_outer_stage(self):
        tracker = LlmUsageTracker()
        with tracker.activate():
            with tracker.stage("outer"):
                with tracker.stage("inner"):
                    record_llm_usage(1, 1)
                record_llm_usage(2, 2)
        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["inner"]["calls"], 1)
        self.assertEqual(detail["stages"]["outer"]["calls"], 1)


if __name__ == "__main__":
    unittest.main()
