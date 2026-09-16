# -*- coding: utf-8 -*-
"""Offline tests for the global run queue (2026-09-15).

At most TIERED_MAX_CONCURRENT_RUNS runs execute at once; the rest wait
as ``queued`` rows and start first come, first served. The line lives in
the database so a restart resumes it. Uses the repo-standard isolated
sqlite fixture; runners are fakes gated on threading events.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from src.tiered_analysis import history
from src.tiered_analysis.run_queue import (
    DEFAULT_MAX_CONCURRENT_RUNS,
    MAX_CONCURRENT_RUNS_ENV,
    QueuedRun,
    RunQueue,
    max_concurrent_runs,
)


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "run_queue.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _wait_until(predicate, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition never became true")


class _GatedRunner:
    """A runner that records what it was handed and blocks each run until
    the test releases it, so the test controls how many are in flight."""

    def __init__(self) -> None:
        self.started: list = []
        self.finished: list = []
        self.release = threading.Event()

    def __call__(self, run: QueuedRun) -> None:
        self.started.append(run)
        self.release.wait(timeout=5)
        history.mark_done(run.task_id, {"symbol": run.stock_code})
        self.finished.append(run.task_id)


class TestMaxConcurrentRuns:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv(MAX_CONCURRENT_RUNS_ENV, raising=False)
        assert max_concurrent_runs() == DEFAULT_MAX_CONCURRENT_RUNS

    def test_env_value_wins(self, monkeypatch):
        monkeypatch.setenv(MAX_CONCURRENT_RUNS_ENV, " 3 ")
        assert max_concurrent_runs() == 3

    @pytest.mark.parametrize("raw", ["0", "-1", "two", "1.5"])
    def test_bad_values_fall_back_to_the_default(self, monkeypatch, raw):
        monkeypatch.setenv(MAX_CONCURRENT_RUNS_ENV, raw)
        assert max_concurrent_runs() == DEFAULT_MAX_CONCURRENT_RUNS


class TestRunQueue:
    def test_runs_start_in_order_up_to_the_cap(self, isolated_db, monkeypatch):
        monkeypatch.setenv(MAX_CONCURRENT_RUNS_ENV, "1")
        runner = _GatedRunner()
        queue = RunQueue(runner)
        history.create_run("first", "AAPL", owner_id=1, status=history.STATUS_QUEUED,
                           inputs={"tier": 2, "hold_weeks": 3})
        history.create_run("second", "MSFT", owner_id=1, status=history.STATUS_QUEUED)

        assert queue.submit("first") == "running"
        assert queue.submit("second") == "queued"
        _wait_until(lambda: len(runner.started) == 1)
        assert runner.started[0] == QueuedRun(
            task_id="first", stock_code="AAPL", owner_id=1,
            inputs={"tier": 2, "hold_weeks": 3},
        )
        assert history.get_run("first")["status"] == "running"
        assert history.get_run("second")["status"] == "queued"
        assert queue.active_count == 1

        runner.release.set()
        _wait_until(lambda: runner.finished == ["first", "second"])
        assert history.get_run("second")["status"] == "done"
        assert queue.active_count == 0

    def test_two_slots_run_two_at_once(self, isolated_db, monkeypatch):
        monkeypatch.setenv(MAX_CONCURRENT_RUNS_ENV, "2")
        runner = _GatedRunner()
        queue = RunQueue(runner)
        for task_id in ("a", "b", "c"):
            history.create_run(task_id, "AAPL", owner_id=1, status=history.STATUS_QUEUED)

        assert queue.dispatch() == ["a", "b"]
        _wait_until(lambda: len(runner.started) == 2)
        assert history.get_run("c")["status"] == "queued"
        assert history.get_run("c")["queue_ahead"] == 0

        runner.release.set()
        _wait_until(lambda: len(runner.finished) == 3)

    def test_resume_picks_up_rows_left_by_a_previous_process(self, isolated_db):
        runner = _GatedRunner()
        runner.release.set()
        history.create_run("left-over", "AAPL", owner_id=1, status=history.STATUS_QUEUED)
        history.create_run("finished", "MSFT", owner_id=1)
        history.mark_done("finished", {})

        assert RunQueue(runner).resume() == ["left-over"]
        _wait_until(lambda: runner.finished == ["left-over"])
        assert RunQueue(runner).resume() == []

    def test_a_runner_that_raises_frees_its_slot(self, isolated_db, monkeypatch):
        monkeypatch.setenv(MAX_CONCURRENT_RUNS_ENV, "1")
        seen = []

        def bad_runner(run: QueuedRun) -> None:
            seen.append(run.task_id)
            raise RuntimeError("boom")

        queue = RunQueue(bad_runner)
        history.create_run("x", "AAPL", owner_id=1, status=history.STATUS_QUEUED)
        history.create_run("y", "AAPL", owner_id=1, status=history.STATUS_QUEUED)
        queue.dispatch()
        _wait_until(lambda: seen == ["x", "y"])
        _wait_until(lambda: queue.active_count == 0)

    def test_queue_ahead_counts_everyones_earlier_rows(self, isolated_db):
        history.create_run("p", "AAPL", owner_id=1, status=history.STATUS_QUEUED)
        history.create_run("q", "MSFT", owner_id=2, status=history.STATUS_QUEUED)
        history.create_run("r", "NVDA", owner_id=1, status=history.STATUS_QUEUED)
        by_id = {row["task_id"]: row for row in history.list_runs(owner_id=1)}
        assert by_id["p"]["queue_ahead"] == 0
        assert by_id["r"]["queue_ahead"] == 2
        assert history.get_run("q")["queue_ahead"] == 1
        history.mark_done("p", {})
        assert history.get_run("p")["queue_ahead"] is None


class TestActiveDuplicate:
    INPUTS = {"tier": 1, "capital": 100000.0, "risk_fraction": 0.01,
              "reward_risk": 2.0, "hold_weeks": 2}

    def test_same_owner_ticker_and_inputs_is_a_duplicate(self, isolated_db):
        history.create_run("t1", "AAPL", owner_id=1, status=history.STATUS_QUEUED,
                           inputs={**self.INPUTS, "sizing_overrides": {"capital": 100000}})
        found = history.find_active_duplicate(1, "aapl ", self.INPUTS)
        assert found == {"task_id": "t1", "status": "queued"}
        history.mark_running("t1")
        assert history.find_active_duplicate(1, "AAPL", self.INPUTS)["status"] == "running"

    def test_finished_failed_other_owner_or_other_inputs_are_not(self, isolated_db):
        history.create_run("done", "AAPL", owner_id=1, inputs=self.INPUTS)
        history.mark_done("done", {})
        history.create_run("failed", "AAPL", owner_id=1, inputs=self.INPUTS)
        history.mark_failed("failed", "x")
        history.create_run("theirs", "AAPL", owner_id=2, inputs=self.INPUTS)
        history.create_run("deeper", "AAPL", owner_id=1,
                           inputs={**self.INPUTS, "tier": 2})
        history.create_run("other", "MSFT", owner_id=1, inputs=self.INPUTS)
        assert history.find_active_duplicate(1, "AAPL", self.INPUTS) is None
