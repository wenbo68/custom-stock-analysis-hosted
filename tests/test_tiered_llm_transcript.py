# -*- coding: utf-8 -*-
"""Offline tests for the per-run LLM transcript (owner request 2026-08-25).

Every real LLM exchange of a run — prompt, raw reply, stage, model, and
the error when the call itself raised — is handed to the transcript's
writer (the run's database rows in production), so a "returned no
usable JSON" warning is diagnosable from stored evidence instead of a
re-run. Recording is fail-soft: a broken writer never fails an analysis.
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from src.tiered_analysis.llm_support import (
    LlmTranscript,
    LlmUsageTracker,
    default_summarizer,
)


def _capturing_transcript(run_id="task-1"):
    entries = []
    return LlmTranscript(run_id, writer=entries.append), entries


class TestLlmTranscript(unittest.TestCase):
    def test_nothing_written_until_first_record(self):
        transcript, entries = _capturing_transcript()
        self.assertEqual(entries, [])
        self.assertEqual(transcript.entries, 0)

    def test_record_hands_one_entry_per_call_to_the_writer(self):
        transcript, entries = _capturing_transcript()
        transcript.record(
            stage="world_events",
            model="gemini/x",
            temperature=0.0,
            prompt="the prompt",
            reply='{"groups": [[1]]}',
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=120,
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["task_id"], "task-1")
        self.assertEqual(entry["seq"], 1)
        self.assertEqual(entry["stage"], "world_events")
        self.assertEqual(entry["model"], "gemini/x")
        self.assertEqual(entry["prompt"], "the prompt")
        self.assertEqual(entry["reply"], '{"groups": [[1]]}')
        self.assertEqual(entry["prompt_tokens"], 10)
        self.assertIsNone(entry["error"])
        self.assertEqual(transcript.entries, 1)

    def test_entries_are_numbered_in_call_order(self):
        transcript, entries = _capturing_transcript()
        for _ in range(3):
            transcript.record(
                stage="s", model="m", temperature=0.0, prompt="p", reply="r"
            )
        self.assertEqual([e["seq"] for e in entries], [1, 2, 3])

    def test_broken_writer_disables_quietly(self):
        def broken(entry):
            raise RuntimeError("database down")

        transcript = LlmTranscript("task-1", writer=broken)
        transcript.record(  # must not raise — a transcript never fails a run
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        transcript.record(
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        self.assertEqual(transcript.entries, 0)

    def test_discard_counts_but_stores_nothing(self):
        transcript = LlmTranscript.discard()
        transcript.record(
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        self.assertEqual(transcript.entries, 1)

    def test_to_detail_counts_entries_only_when_there_are_some(self):
        transcript, _ = _capturing_transcript()
        tracker = LlmUsageTracker(transcript=transcript)
        self.assertNotIn("transcript_entries", tracker.to_detail())

        transcript.record(
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        self.assertEqual(tracker.to_detail()["transcript_entries"], 1)

    def test_tracker_without_transcript_stays_unchanged(self):
        self.assertNotIn("transcript_entries", LlmUsageTracker().to_detail())


class _FakeLitellm:
    """Stands in for the litellm module inside ``_summarize``."""

    def __init__(self, reply="ok", error=None):
        self._reply = reply
        self._error = error
        self.calls = []

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._reply)
                )
            ],
        )


class TestSummarizerTranscript(unittest.TestCase):
    def setUp(self):
        self.transcript, self.entries = _capturing_transcript()
        self.tracker = LlmUsageTracker(transcript=self.transcript)

    def _summarize_with(self, fake):
        with mock.patch.dict(sys.modules, {"litellm": fake}):
            with mock.patch.dict(os.environ, {"LITELLM_MODEL": "fake/model"}):
                return default_summarizer("the prompt")

    def test_successful_call_lands_in_the_transcript_with_its_stage(self):
        fake = _FakeLitellm(reply='{"order": [1]}')
        with self.tracker.activate():
            with self.tracker.stage("world_events"):
                reply = self._summarize_with(fake)

        self.assertEqual(reply, '{"order": [1]}')
        [entry] = self.entries
        self.assertEqual(entry["stage"], "world_events")
        self.assertEqual(entry["model"], "fake/model")
        self.assertEqual(entry["reply"], '{"order": [1]}')
        self.assertEqual(entry["prompt_tokens"], 7)
        self.assertIsNone(entry["error"])

    def test_crashed_call_records_the_error_and_still_raises(self):
        fake = _FakeLitellm(error=RuntimeError("boom"))
        with self.tracker.activate():
            with self.assertRaises(RuntimeError):
                self._summarize_with(fake)

        [entry] = self.entries
        self.assertIsNone(entry["reply"])
        self.assertIn("boom", entry["error"])
        self.assertEqual(entry["stage"], "unattributed")

    def test_no_tracker_means_no_transcript_and_no_error(self):
        fake = _FakeLitellm()
        self._summarize_with(fake)  # outside any activation
        self.assertEqual(self.entries, [])


if __name__ == "__main__":
    unittest.main()
