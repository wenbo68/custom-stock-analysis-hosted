# -*- coding: utf-8 -*-
"""Offline tests for the per-run LLM transcript (owner request 2026-08-25).

Every real LLM exchange of a run — prompt, raw reply, stage, model, and
the error when the call itself raised — lands in one JSONL file, so a
"returned no usable JSON" warning is diagnosable from stored evidence
instead of a re-run. Writing is lazy (fake-summarizer runs leave no
file) and fail-soft (filesystem trouble never fails an analysis).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.tiered_analysis.llm_support import (
    TRANSCRIPT_MAX_AGE_DAYS,
    LlmTranscript,
    LlmUsageTracker,
    default_summarizer,
)


def _read_lines(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


class TestLlmTranscript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_no_file_until_first_record(self):
        transcript = LlmTranscript.for_run("AAPL", directory=self.dir)
        self.assertEqual(list(self.dir.glob("*.jsonl")), [])
        self.assertEqual(transcript.entries, 0)

    def test_record_writes_one_jsonl_line_per_call(self):
        transcript = LlmTranscript.for_run("AAPL", directory=self.dir)
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
        entries = _read_lines(self.dir / transcript.filename)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["stage"], "world_events")
        self.assertEqual(entry["model"], "gemini/x")
        self.assertEqual(entry["prompt"], "the prompt")
        self.assertEqual(entry["reply"], '{"groups": [[1]]}')
        self.assertEqual(entry["prompt_tokens"], 10)
        self.assertIsNone(entry["error"])
        self.assertEqual(transcript.entries, 1)

    def test_filename_carries_the_symbol(self):
        transcript = LlmTranscript.for_run("aapl", directory=self.dir)
        self.assertIn("AAPL", transcript.filename)
        self.assertTrue(transcript.filename.endswith(".jsonl"))

    def test_first_write_prunes_expired_files_and_keeps_fresh_ones(self):
        self.dir.mkdir(exist_ok=True)
        expired = self.dir / "old_run.jsonl"
        fresh = self.dir / "recent_run.jsonl"
        expired.write_text("{}\n", encoding="utf-8")
        fresh.write_text("{}\n", encoding="utf-8")
        too_old = time.time() - (TRANSCRIPT_MAX_AGE_DAYS + 1) * 86400
        os.utime(expired, (too_old, too_old))

        transcript = LlmTranscript.for_run("MSFT", directory=self.dir)
        transcript.record(
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        self.assertFalse(expired.exists())
        self.assertTrue(fresh.exists())

    def test_unwritable_directory_disables_quietly(self):
        blocker = self.dir / "not_a_dir"
        blocker.write_text("", encoding="utf-8")
        transcript = LlmTranscript.for_run(
            "AAPL", directory=blocker / "sub"
        )
        transcript.record(  # must not raise — a transcript never fails a run
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        self.assertEqual(transcript.entries, 0)

    def test_to_detail_names_the_file_only_when_it_holds_entries(self):
        transcript = LlmTranscript.for_run("AAPL", directory=self.dir)
        tracker = LlmUsageTracker(transcript=transcript)
        self.assertNotIn("transcript_file", tracker.to_detail())

        transcript.record(
            stage="s", model="m", temperature=0.0, prompt="p", reply="r"
        )
        self.assertEqual(
            tracker.to_detail()["transcript_file"], transcript.filename
        )

    def test_tracker_without_transcript_stays_unchanged(self):
        self.assertNotIn("transcript_file", LlmUsageTracker().to_detail())


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
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.transcript = LlmTranscript.for_run("AAPL", directory=self.dir)
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
        [entry] = _read_lines(self.dir / self.transcript.filename)
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

        [entry] = _read_lines(self.dir / self.transcript.filename)
        self.assertIsNone(entry["reply"])
        self.assertIn("boom", entry["error"])
        self.assertEqual(entry["stage"], "unattributed")

    def test_no_tracker_means_no_transcript_and_no_error(self):
        fake = _FakeLitellm()
        self._summarize_with(fake)  # outside any activation
        self.assertEqual(list(self.dir.glob("*.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
