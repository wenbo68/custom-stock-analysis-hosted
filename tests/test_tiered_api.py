# -*- coding: utf-8 -*-
"""Offline tests for the tiered-analysis API endpoint.

The real run takes minutes (LLM + data fetch), so the endpoint runs it
in a background thread and persists status/result to the tiered_runs
table; the client polls the run list/detail. Tests patch the runner with
fast fakes and use the repo-standard isolated sqlite fixture.
"""
from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import tiered
from src.tiered_analysis.integration import TieredRunOutcome
from src.tiered_analysis.providers.base import (
    Citation,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.earnings import EarningsInfo
from src.tiered_analysis.schema import (
    Action,
    Direction,
    Outlook,
    SniperLevels,
    TierReport,
)
from src.tiered_analysis.signal_log import SignalLogResult
from src.tiered_analysis.tiers import TierState


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "tiered_api.db"
    os.environ["DATABASE_PATH"] = str(db_path)
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


@pytest.fixture(autouse=True)
def open_clock_gate(monkeypatch):
    """Neutralize the market-hours clock gate (2026-08-08) for the legacy
    endpoint tests — otherwise they pass or fail with the wall clock. The
    gate's own behavior is covered by TestClockGateEndpoint below and
    tests/test_tiered_run_gate.py."""
    from src.tiered_analysis import run_gate

    monkeypatch.setattr(
        run_gate,
        "clock_gate",
        lambda symbol, now=None, override=False: run_gate.ClockGateResult(
            False, "us", "test: gate open"
        ),
    )


@pytest.fixture()
def client(isolated_db):
    app = FastAPI()
    app.include_router(tiered.router, prefix="/tiered")
    return TestClient(app)


def _outcome(symbol="AAPL"):
    report = TierReport(
        tier=1,
        symbol=symbol,
        market=Market.US,
        direction=Direction.HOLD,
        score=56,
        levels=SniperLevels(entry=303.8, secondary_entry=294.7,
                            stop_loss=290.0, take_profit=325.0),
        narrative="Wait for a pullback.",
        dimensions=[
            DimensionResult(
                dimension="fundamentals", kind=SourceKind.NUMERIC,
                payload={"growth": {"revenue_yoy_pct": 6.4}},
            ),
            DimensionResult(
                dimension="sentiment", kind=SourceKind.TEXTUAL,
                narrative="Sentiment: mixed.",
                citations=[Citation(source_name="Reuters",
                                    url="https://reuters.example/x",
                                    title="Reuters", snippet="q")],
                warnings=["one page blocked"],
            ),
        ],
        warnings=[],
    )
    state = TierState(symbol=symbol, market=Market.US, reports={1: report})
    signal = SignalLogResult(logged=True, signal_id=7, created=True)
    return TieredRunOutcome(report=report, state=state, signal=signal)


def _deep_outcome(symbol="AAPL"):
    """Depth-2 outcome with a debate section and a sizing block."""
    base = _outcome(symbol)
    tier2 = TierReport(
        tier=2, symbol=symbol, market=Market.US,
        direction=Direction.BUY,
        confidence="0.70", levels=base.report.levels,
        narrative="bull case holds",
        debate_detail={"verdict": {"direction": "buy", "confidence": 0.7}},
    )
    state = TierState(
        symbol=symbol, market=Market.US,
        reports={1: base.report, 2: tier2},
    )
    sizing = {"enabled": True, "shares": 83,
              "reason_code": None, "refusal_reason": None, "notes": []}
    llm_usage = {"stages": {"tier2_debate": {"calls": 3, "prompt_tokens": 900,
                                             "completion_tokens": 300}},
                 "total": {"calls": 3, "prompt_tokens": 900,
                           "completion_tokens": 300},
                 "scope": "tiered-package LLM calls only"}
    return TieredRunOutcome(
        report=base.report, state=state, signal=base.signal,
        depth=2, final_report=tier2, sizing=sizing, llm_usage=llm_usage,
        outlook=Outlook.BULLISH, action=Action.ENTER,
        earnings=EarningsInfo(next_date="2026-07-24", days_until=4),
        risk_card=[{"id": "volatility", "status": "ok", "values": {}}],
    )


def _poll_until_done(client, task_id, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/tiered/runs/{task_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("run never finished")


class TestTieredAnalyzeEndpoint:
    def test_accepts_and_completes_run(self, client):
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            assert accepted.status_code == 202
            task_id = accepted.json()["task_id"]
            body = _poll_until_done(client, task_id)

        assert body["status"] == "done"
        result = body["result"]
        assert result["symbol"] == "AAPL"
        assert result["direction"] == "hold"
        assert result["score"] == 56
        # Coverage grades are retired (2026-08-19): the serialized run
        # carries no "coverage" key anywhere — degradation shows as
        # warnings/blank fields instead.
        assert "coverage" not in result
        assert result["levels"]["entry"] == 303.8
        assert result["signal"]["signal_id"] == 7
        dims = {d["dimension"]: d for d in result["dimensions"]}
        assert all("coverage" not in d for d in result["dimensions"])
        # is_actionable = numeric kind AND a payload present.
        assert dims["fundamentals"]["is_actionable"] is True
        assert dims["sentiment"]["is_actionable"] is False
        assert dims["fundamentals"]["payload"]["growth"]["revenue_yoy_pct"] == 6.4
        assert dims["sentiment"]["narrative"] == "Sentiment: mixed."
        assert dims["sentiment"]["citations"][0]["url"] == "https://reuters.example/x"

    def test_failed_run_reports_error(self, client):
        def boom(code, **kwargs):
            raise RuntimeError("upstream exploded")

        with patch.object(tiered, "_run_analysis", boom):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            body = _poll_until_done(client, accepted.json()["task_id"])

        assert body["status"] == "failed"
        assert "upstream exploded" in body["error"]

    def test_runs_list_is_history_newest_first(self, client):
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            first = client.post("/tiered/analyze",
                                json={"stock_code": "AAPL"}).json()["task_id"]
            _poll_until_done(client, first)
            second = client.post("/tiered/analyze",
                                 json={"stock_code": "NVDA"}).json()["task_id"]
            _poll_until_done(client, second)

        items = client.get("/tiered/runs").json()["items"]
        assert [item["stock_code"] for item in items[:2]] == ["NVDA", "AAPL"]
        assert all(item["status"] == "done" for item in items[:2])
        # summaries stay light — full reports come from the detail route
        assert all("result" not in item for item in items)

    def test_blank_stock_code_rejected(self, client):
        response = client.post("/tiered/analyze", json={"stock_code": "   "})
        assert response.status_code == 422

    def test_unknown_run_is_404(self, client):
        response = client.get("/tiered/runs/nope")
        assert response.status_code == 404

    def test_sizing_defaults_reflect_env_settings(self, client, monkeypatch):
        monkeypatch.setenv("TIERED_SIZING_CAPITAL", "100000")
        monkeypatch.setenv("TIERED_SIZING_RISK_FRACTION", "0.01")
        response = client.get("/tiered/sizing-defaults")
        assert response.status_code == 200
        assert response.json() == {
            "capital": 100000.0, "risk_fraction": 0.01, "reward_risk": 2.0}

    def test_sizing_defaults_null_when_unconfigured(self, client, monkeypatch):
        monkeypatch.delenv("TIERED_SIZING_CAPITAL", raising=False)
        monkeypatch.delenv("TIERED_SIZING_RISK_FRACTION", raising=False)
        response = client.get("/tiered/sizing-defaults")
        assert response.status_code == 200
        # reward_risk always has a default — the form needs a number.
        assert response.json() == {
            "capital": None, "risk_fraction": None, "reward_risk": 2.0}


class TestTieredDepthAndSizingApi:
    """v2 slice 6: depth parameter, sizing override, new response sections."""

    def test_depth_out_of_range_rejected(self, client):
        # Tier 3 is retired: depth 3 is an error, not a clamp (user
        # decision, 2026-07-20).
        for depth in (0, 3, 4):
            response = client.post(
                "/tiered/analyze", json={"stock_code": "AAPL", "depth": depth})
            assert response.status_code == 422

    def test_invalid_sizing_override_rejected(self, client):
        response = client.post("/tiered/analyze", json={
            "stock_code": "AAPL",
            "sizing": {"capital": -5, "risk_fraction": 0.01},
        })
        assert response.status_code == 422
        response = client.post("/tiered/analyze", json={
            "stock_code": "AAPL",
            "sizing": {"risk_fraction": 1.5},
        })
        assert response.status_code == 422
        response = client.post("/tiered/analyze", json={
            "stock_code": "AAPL",
            "sizing": {"ownership": -1},
        })
        assert response.status_code == 422

    def test_ownership_reaches_the_runner(self, client):
        captured = {}

        def fake_run(code, depth=1, sizing_overrides=None, hold_weeks=2):
            captured["sizing_overrides"] = sizing_overrides
            return _deep_outcome(code)

        with patch.object(tiered, "_run_analysis", fake_run):
            accepted = client.post("/tiered/analyze", json={
                "stock_code": "AAPL",
                "depth": 2,
                "sizing": {"ownership": 300},
            })
            assert accepted.status_code == 202
            _poll_until_done(client, accepted.json()["task_id"])

        assert captured["sizing_overrides"] == {"ownership": 300}

    def test_depth_and_sizing_reach_the_runner(self, client):
        captured = {}

        def fake_run(code, depth=1, sizing_overrides=None, hold_weeks=2):
            captured["code"] = code
            captured["depth"] = depth
            captured["sizing_overrides"] = sizing_overrides
            return _deep_outcome(code)

        with patch.object(tiered, "_run_analysis", fake_run):
            accepted = client.post("/tiered/analyze", json={
                "stock_code": "AAPL",
                "depth": 2,
                "sizing": {"capital": 50000, "risk_fraction": 0.02},
            })
            assert accepted.status_code == 202
            assert accepted.json()["depth"] == 2
            _poll_until_done(client, accepted.json()["task_id"])

        assert captured["depth"] == 2
        assert captured["sizing_overrides"] == {"capital": 50000.0,
                                                "risk_fraction": 0.02}

    def test_deep_run_response_contract(self, client):
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _deep_outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL", "depth": 2})
            body = _poll_until_done(client, accepted.json()["task_id"])

        result = body["result"]
        assert result["depth"] == 2
        # tier-1 fields keep their v1 shape for the existing UI
        assert result["direction"] == "hold"
        assert result["tier"] == 1
        # the deepest tier is what the user should act on
        assert result["final"]["tier"] == 2
        assert result["final"]["direction"] == "buy"
        assert result["final"]["outlook"] == "bullish"
        assert result["final"]["action"] == "enter"
        # No coverage grades anywhere in the serialized run (2026-08-19).
        assert "coverage" not in result["final"]
        assert "coverage" not in result["tier2"]
        assert result["tier2"]["debate_detail"]["verdict"]["direction"] == "buy"
        assert result["sizing"]["shares"] == 83
        assert result["llm_usage"]["total"]["calls"] == 3
        # outlook redesign additions
        assert result["outlook"] == "bullish"
        assert result["action"] == "enter"
        assert result["earnings"]["next_date"] == "2026-07-24"
        assert result["earnings"]["is_near"] is True
        assert result["risk_card"][0]["id"] == "volatility"

    def test_v1_shaped_outcome_serializes_with_defaults(self, client):
        # An outcome without the new fields (depth-1 run) must still
        # produce the additive keys, as explicit "not run" values.
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            body = _poll_until_done(client, accepted.json()["task_id"])

        result = body["result"]
        assert result["depth"] == 1
        assert result["final"]["tier"] == 1
        assert result["tier2"] is None
        assert result["sizing"] is None
        assert result["llm_usage"] is None
        assert result["outlook"] == "unknown"
        assert result["action"] == "unknown"
        assert result["earnings"] is None
        assert result["risk_card"] is None


class TestClockGateEndpoint:
    """The market-hours clock gate (owner decisions 2026-08-08)."""

    def _gate(self, blocked):
        from src.tiered_analysis import run_gate

        def fake(symbol, now=None, override=False):
            return run_gate.ClockGateResult(
                blocked and not override, "us", "test"
            )

        return fake

    def test_blocked_market_returns_409_with_code(self, client, monkeypatch):
        from src.tiered_analysis import run_gate

        monkeypatch.setattr(run_gate, "clock_gate", self._gate(blocked=True))
        response = client.post("/tiered/analyze", json={"stock_code": "AAPL"})
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "market_open"
        assert detail["market"] == "us"

    def test_blocked_409_carries_session_bounds_as_iso(
        self, client, monkeypatch
    ):
        """2026-08-11: the popup words the market's hours (market time +
        the user's time), so the 409 body ships the session bounds as
        ISO datetimes with the market's own UTC offset embedded."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.tiered_analysis import run_gate

        tz = ZoneInfo("America/New_York")

        def fake(symbol, now=None, override=False):
            return run_gate.ClockGateResult(
                not override, "us", "test",
                session_open=datetime(2026, 8, 11, 9, 30, tzinfo=tz),
                session_close=datetime(2026, 8, 11, 16, 0, tzinfo=tz),
            )

        monkeypatch.setattr(run_gate, "clock_gate", fake)
        response = client.post("/tiered/analyze", json={"stock_code": "AAPL"})
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["session_open"] == "2026-08-11T09:30:00-04:00"
        assert detail["session_close"] == "2026-08-11T16:00:00-04:00"

    def test_blocked_409_survives_the_global_error_handlers(
        self, isolated_db, monkeypatch
    ):
        """Regression (2026-08-11): the server registers add_error_handlers,
        which used to flatten any non-ErrorResponse dict detail into a
        Python-repr string — the web app then couldn't see detail.code and
        showed raw text instead of the run-anyway popup. Structured dict
        details must reach the client intact through the real handlers."""
        from api.middlewares.error_handler import add_error_handlers
        from src.tiered_analysis import run_gate

        app = FastAPI()
        add_error_handlers(app)
        app.include_router(tiered.router, prefix="/tiered")
        handled_client = TestClient(app)

        monkeypatch.setattr(run_gate, "clock_gate", self._gate(blocked=True))
        response = handled_client.post(
            "/tiered/analyze", json={"stock_code": "AAPL"}
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail == {"code": "market_open", "market": "us"}

    def test_run_anyway_overrides_the_gate(self, client, monkeypatch):
        from src.tiered_analysis import run_gate

        monkeypatch.setattr(run_gate, "clock_gate", self._gate(blocked=True))
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            response = client.post(
                "/tiered/analyze",
                json={"stock_code": "AAPL", "run_anyway": True},
            )
            assert response.status_code == 202
            _poll_until_done(client, response.json()["task_id"])

    def test_hold_weeks_reaches_the_runner_and_inputs(self, client):
        seen = {}

        def runner(code, **kwargs):
            seen.update(kwargs)
            return _outcome(code)

        with patch.object(tiered, "_run_analysis", runner):
            accepted = client.post(
                "/tiered/analyze",
                json={"stock_code": "AAPL", "hold_weeks": 3},
            )
            assert accepted.status_code == 202
            _poll_until_done(client, accepted.json()["task_id"])
        assert seen["hold_weeks"] == 3

    def test_hold_weeks_out_of_range_is_rejected(self, client):
        response = client.post(
            "/tiered/analyze", json={"stock_code": "AAPL", "hold_weeks": 5}
        )
        assert response.status_code == 422
