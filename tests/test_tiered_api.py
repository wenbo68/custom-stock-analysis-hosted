# -*- coding: utf-8 -*-
"""Offline tests for the tiered-analysis API endpoint.

The real run takes minutes (LLM + data fetch), so the endpoint runs it
in a background thread and persists status/result to the tiered_runs
table; the client polls the run list/detail. Tests patch the runner with
fast fakes and use the repo-standard isolated sqlite fixture.
"""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth.providers import Identity
from api.auth.session import current_user
from api.v1.endpoints import tiered
from src.tiered_analysis.integration import TieredRunOutcome
from src.user_settings import save_user_settings
from src.users import upsert_from_identity
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
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _signed_in_client(user):
    """A client whose every request is made by ``user`` (the sign-in
    dependency is overridden; sign-in itself is covered in test_auth)."""
    app = FastAPI()
    app.include_router(tiered.router, prefix="/tiered")
    app.dependency_overrides[current_user] = lambda: user
    return TestClient(app)


@pytest.fixture()
def user(isolated_db, encryption_key):
    """A signed-in user with a model and LLM key on file."""
    account = upsert_from_identity(Identity(provider="google", subject="u1",
                                            email="u1@example.com"))
    save_user_settings(account["id"], llm_model="gemini/gemini-3.8-flash",
                       llm_api_key="sk-user-one")
    return account


@pytest.fixture()
def client(user):
    return _signed_in_client(user)


def _outcome(symbol="AAPL"):
    report = TierReport(
        tier=1,
        symbol=symbol,
        market=Market.US,
        direction=Direction.HOLD,
        score=56,
        levels=SniperLevels(entry=303.8,
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
    return TieredRunOutcome(report=report, state=state)


def _quick_outcome(symbol="AAPL"):
    """Depth-1 outcome with a neutral outlook and the quick judge's detail."""
    base = _outcome(symbol)
    from dataclasses import replace

    report = replace(base.report, debate_detail={
        "format": "quick_v1", "outlook": {"direction": "hold", "final_score": 5.5}})
    return TieredRunOutcome(
        report=report, state=TierState(symbol=symbol, market=Market.US,
                                       reports={1: report}),
        outlook=Outlook.NEUTRAL, action=Action.NO_TRADE,
    )


def _deep_outcome(symbol="AAPL"):
    """Depth-2 outcome with a debate section and a sizing block."""
    base = _outcome(symbol)
    tier2 = TierReport(
        tier=2, symbol=symbol, market=Market.US,
        direction=Direction.BUY,
        confidence="0.70", levels=base.report.levels,
        narrative="bull case holds",
        debate_detail={"outlook": {"direction": "buy", "confidence": 0.7}},
    )
    state = TierState(
        symbol=symbol, market=Market.US,
        reports={1: base.report, 2: tier2},
    )
    sizing = {"enabled": True, "shares": 83,
              "reason_code": None, "refusal_reason": None, "notes": []}
    llm_usage = {"stages": {"tier2_analysis": {"calls": 3, "prompt_tokens": 900,
                                             "completion_tokens": 300}},
                 "total": {"calls": 3, "prompt_tokens": 900,
                           "completion_tokens": 300},
                 "scope": "tiered-package LLM calls only"}
    return TieredRunOutcome(
        report=base.report, state=state,
        depth=2, final_report=tier2, sizing=sizing, llm_usage=llm_usage,
        outlook=Outlook.BULLISH, action=Action.ENTER,
        earnings=EarningsInfo(next_date="2026-07-24", days_until=4),
    )


def _poll_until_done(client, task_id, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/tiered/runs/{task_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] not in ("queued", "running"):
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
        assert "signal" not in result
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

    def test_depth_and_sizing_reach_the_runner(self, client):
        captured = {}

        def fake_run(code, depth=1, sizing_overrides=None, hold_weeks=2,
                     **kwargs):
            captured["code"] = code
            captured["depth"] = depth
            captured["sizing_overrides"] = sizing_overrides
            captured["settings"] = kwargs.get("settings")
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
        # The run carries the caller's own model and key (never the env).
        assert captured["settings"].llm_model == "gemini/gemini-3.8-flash"
        assert captured["settings"].llm_api_key == "sk-user-one"

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
        assert result["tier2"]["debate_detail"]["outlook"]["direction"] == "buy"
        assert result["sizing"]["shares"] == 83
        assert result["llm_usage"]["total"]["calls"] == 3
        # outlook redesign additions
        assert result["outlook"] == "bullish"
        assert result["action"] == "enter"
        assert result["earnings"]["next_date"] == "2026-07-24"
        assert result["earnings"]["is_near"] is True
        assert "risk_card" not in result

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
        self, user, monkeypatch
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
        app.dependency_overrides[current_user] = lambda: user
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


class TestAccessControl:
    """Public server: sign-in required, runs belong to their owner, and a
    run without an LLM key is refused up front."""

    def test_signed_out_requests_are_401(self, isolated_db):
        from starlette.middleware.sessions import SessionMiddleware

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="t")
        app.include_router(tiered.router, prefix="/tiered")
        anonymous = TestClient(app)
        assert anonymous.post("/tiered/analyze", json={"stock_code": "AAPL"}).status_code == 401
        assert anonymous.get("/tiered/runs").status_code == 401
        assert anonymous.get("/tiered/runs/x").status_code == 401
        assert anonymous.get("/tiered/runs/x/transcript").status_code == 401
        # the sizing defaults are server config, not user data
        assert anonymous.get("/tiered/sizing-defaults").status_code == 200

    def test_runs_are_private_to_their_owner(self, client, isolated_db, encryption_key):
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            accepted = client.post("/tiered/analyze", json={"stock_code": "AAPL"})
            task_id = accepted.json()["task_id"]
            _poll_until_done(client, task_id)
        assert [r["task_id"] for r in client.get("/tiered/runs").json()["items"]] == [task_id]

        other = upsert_from_identity(Identity(provider="discord", subject="u2"))
        save_user_settings(other["id"], llm_model="openai/gpt-5.6-luna", llm_api_key="k")
        stranger = _signed_in_client(other)
        assert stranger.get("/tiered/runs").json() == {"items": []}
        assert stranger.get(f"/tiered/runs/{task_id}").status_code == 404
        assert stranger.get(f"/tiered/runs/{task_id}/transcript").status_code == 404

    def test_run_without_an_llm_key_is_refused_before_starting(self, isolated_db, encryption_key):
        account = upsert_from_identity(Identity(provider="google", subject="nokey"))
        bare = _signed_in_client(account)
        response = bare.post("/tiered/analyze", json={"stock_code": "AAPL"})
        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "llm_not_configured"
        assert bare.get("/tiered/runs").json() == {"items": []}

    def test_missing_encryption_key_is_a_clear_503(self, user, monkeypatch):
        monkeypatch.delenv("API_KEY_ENCRYPTION_KEY")
        response = _signed_in_client(user).post("/tiered/analyze", json={"stock_code": "AAPL"})
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "encryption_not_configured"


class TestRunQueueEndpoint:
    """The global run queue (2026-09-15): a run past the concurrency cap
    waits as ``queued`` and starts by itself; an exact duplicate of the
    caller's own unfinished run is refused with a 409."""

    @staticmethod
    def _gated_runner():
        release = threading.Event()

        def runner(code, **kwargs):
            release.wait(timeout=5)
            return _outcome(code)

        return runner, release

    def test_second_run_past_the_cap_waits_then_runs(self, client, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release = self._gated_runner()
        with patch.object(tiered, "_run_analysis", runner):
            first = client.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            second = client.post("/tiered/analyze", json={"stock_code": "MSFT"}).json()
            assert first["status"] == "running"
            assert second["status"] == "queued"

            items = {r["task_id"]: r for r in client.get("/tiered/runs").json()["items"]}
            assert items[first["task_id"]]["status"] == "running"
            assert items[second["task_id"]]["status"] == "queued"
            assert items[second["task_id"]]["queue_ahead"] == 0
            # queued rows already show the inputs they were made with
            assert items[second["task_id"]]["tier"] == 1

            release.set()
            assert _poll_until_done(client, first["task_id"])["status"] == "done"
            assert _poll_until_done(client, second["task_id"])["status"] == "done"

    def test_exact_duplicate_of_an_unfinished_run_is_409(self, client, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release = self._gated_runner()
        body = {"stock_code": "AAPL", "depth": 2, "hold_weeks": 3,
                "sizing": {"capital": 50000, "risk_fraction": 0.02, "reward_risk": 2}}
        with patch.object(tiered, "_run_analysis", runner):
            accepted = client.post("/tiered/analyze", json=body)
            assert accepted.status_code == 202
            task_id = accepted.json()["task_id"]

            again = client.post("/tiered/analyze", json={**body, "stock_code": "aapl"})
            assert again.status_code == 409
            assert again.json()["detail"] == {
                "code": "duplicate_run", "task_id": task_id, "status": "running",
            }
            # one input changed: a different run, so it joins the line
            other = client.post("/tiered/analyze", json={**body, "hold_weeks": 4})
            assert other.status_code == 202
            assert other.json()["status"] == "queued"
            # and the queued one is a duplicate too
            assert client.post("/tiered/analyze",
                               json={**body, "hold_weeks": 4}).status_code == 409

            release.set()
            _poll_until_done(client, task_id)
            _poll_until_done(client, other.json()["task_id"])

        # finished runs never block a re-run
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            assert client.post("/tiered/analyze", json=body).status_code == 202

    def test_duplicates_are_per_user(self, client, user, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release = self._gated_runner()
        other = upsert_from_identity(Identity(provider="discord", subject="u2"))
        save_user_settings(other["id"], llm_model="openai/gpt-5.6-luna", llm_api_key="k")
        with patch.object(tiered, "_run_analysis", runner):
            mine = client.post("/tiered/analyze", json={"stock_code": "AAPL"})
            theirs = _signed_in_client(other).post("/tiered/analyze",
                                                   json={"stock_code": "AAPL"})
            assert mine.status_code == 202
            assert theirs.status_code == 202
            release.set()
            _poll_until_done(client, mine.json()["task_id"])
            _poll_until_done(_signed_in_client(other), theirs.json()["task_id"])

    def test_a_queued_run_reads_the_owners_key_when_it_starts(self, client, user, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release = self._gated_runner()
        seen = {}

        def capturing(code, **kwargs):
            seen[code] = kwargs.get("settings")
            return runner(code, **kwargs)

        with patch.object(tiered, "_run_analysis", capturing):
            client.post("/tiered/analyze", json={"stock_code": "AAPL"})
            queued = client.post("/tiered/analyze", json={"stock_code": "MSFT"}).json()
            assert queued["status"] == "queued"
            save_user_settings(user["id"], llm_api_key="sk-rotated")
            release.set()
            _poll_until_done(client, queued["task_id"])
        assert seen["MSFT"].llm_api_key == "sk-rotated"

    def test_a_queued_run_whose_owner_lost_their_key_fails_cleanly(
        self, client, user, monkeypatch
    ):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release = self._gated_runner()
        with patch.object(tiered, "_run_analysis", runner):
            client.post("/tiered/analyze", json={"stock_code": "AAPL"})
            queued = client.post("/tiered/analyze", json={"stock_code": "MSFT"}).json()
            save_user_settings(user["id"], llm_api_key="")
            release.set()
            body = _poll_until_done(client, queued["task_id"])
        assert body["status"] == "failed"
        assert "no LLM model and API key" in body["error"]


class TestRunReuseEndpoint:
    """Run reuse (2026-09-17): a run of the same ticker, trading day and
    max hold time by the same-or-stronger model of the same provider at
    the same-or-deeper tier lends its outlook; only the requester's
    trade-plan stages run."""

    @staticmethod
    def _other_user(model="gemini/gemini-3.8-flash"):
        other = upsert_from_identity(Identity(provider="discord", subject="u2"))
        save_user_settings(other["id"], llm_model=model, llm_api_key="k2")
        return _signed_in_client(other)

    @staticmethod
    def _gated_runner(outcome=_deep_outcome):
        release = threading.Event()
        calls = []

        def runner(code, **kwargs):
            calls.append(kwargs)
            if "providers" not in kwargs:
                release.wait(timeout=5)
            return outcome(code)

        return runner, release, calls

    def test_a_finished_run_finishes_the_new_run_from_it(self, client, user):
        runner, release, calls = self._gated_runner()
        release.set()
        with patch.object(tiered, "_run_analysis", runner):
            first = client.post("/tiered/analyze",
                                json={"stock_code": "AAPL", "depth": 2}).json()
            _poll_until_done(client, first["task_id"])

            other = self._other_user()
            second = other.post("/tiered/analyze", json={
                "stock_code": "aapl", "depth": 1,
                "sizing": {"capital": 5000, "risk_fraction": 0.01, "reward_risk": 3},
            }).json()
            assert second["status"] == "running"
            body = _poll_until_done(other, second["task_id"])

        assert body["status"] == "done"
        assert body["reused"] is True
        assert body["model"] == "gemini/gemini-3.8-flash"
        assert body["result"]["reused"] == {
            "tier": 2, "model": "gemini/gemini-3.8-flash",
            "model_label": "Gemini 3.8 Flash",
        }
        # the second run went through the pipeline with the stand-ins,
        # at the source's depth, with the requester's own sizing and key
        reused_call = calls[-1]
        assert reused_call["depth"] == 2
        assert reused_call["tier2_stage"] is not None
        assert reused_call["quick_judge"] is None
        assert [p.dimension for p in reused_call["providers"]] == ["fundamentals", "sentiment"]
        assert reused_call["sizing_overrides"] == {
            "capital": 5000, "risk_fraction": 0.01, "reward_risk": 3}
        assert reused_call["settings"].llm_api_key == "k2"
        # the history row says tier 2 and marks the outlook as shared
        row = {r["task_id"]: r for r in other.get("/tiered/runs").json()["items"]}
        assert row[second["task_id"]]["tier"] == 2
        assert row[second["task_id"]]["reused"] is True
        assert row[second["task_id"]]["model_label"] == "Gemini 3.8 Flash"
        # the source's own row is untouched
        mine = {r["task_id"]: r for r in client.get("/tiered/runs").json()["items"]}
        assert mine[first["task_id"]]["reused"] is False

    def test_a_running_run_parks_the_new_run_as_waiting_then_finishes_it(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release, calls = self._gated_runner()
        with patch.object(tiered, "_run_analysis", runner):
            first = client.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            other = self._other_user()
            second = other.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            # to its owner the new run reads as the source reads to its owner
            assert second["status"] == "running"
            listed = other.get("/tiered/runs").json()["items"][0]
            assert listed["status"] == "running"
            assert listed["queue_ahead"] is None
            assert listed["reused"] is True
            # a third user behind a queued source sees the source's place in line
            third_owner = upsert_from_identity(Identity(provider="google", subject="u3"))
            save_user_settings(third_owner["id"], llm_model="gemini/gemini-3.8-flash",
                               llm_api_key="k3")
            third = _signed_in_client(third_owner)
            queued_src = client.post("/tiered/analyze", json={"stock_code": "MSFT"}).json()
            assert queued_src["status"] == "queued"
            behind = third.post("/tiered/analyze", json={"stock_code": "MSFT"}).json()
            assert behind["status"] == "queued"
            behind_row = third.get("/tiered/runs").json()["items"][0]
            assert behind_row["status"] == "queued"
            assert behind_row["queue_ahead"] == 0
            assert third.get(f"/tiered/runs/{behind['task_id']}").json()["status"] == "queued"
            release.set()
            _poll_until_done(client, queued_src["task_id"])
            _poll_until_done(third, behind["task_id"])
            _poll_until_done(client, first["task_id"])
            body = _poll_until_done(other, second["task_id"])
        assert body["status"] == "done"
        assert body["result"]["reused"]["tier"] == 2
        # two fresh runs (AAPL, MSFT), two finished from them
        assert sum("providers" in call for call in calls) == 2
        assert sum("providers" not in call for call in calls) == 2

    def test_a_failed_source_sends_the_waiting_run_back_to_the_queue(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        release = threading.Event()
        calls = []

        def runner(code, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                release.wait(timeout=5)
                raise RuntimeError("LLM exploded")
            return _deep_outcome(code)

        with patch.object(tiered, "_run_analysis", runner):
            first = client.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            other = self._other_user()
            second = other.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            assert second["status"] == "running"
            release.set()
            assert _poll_until_done(client, first["task_id"])["status"] == "failed"
            body = _poll_until_done(other, second["task_id"])
        assert body["status"] == "done"
        assert "reused" not in body["result"]
        assert body["reused"] is False
        assert len(calls) == 2 and "providers" not in calls[-1]

    @pytest.mark.parametrize("payload, model", [
        # weaker model of the same provider asks for more than the source gave
        ({"stock_code": "AAPL"}, "gemini/gemini-3.1-pro-preview"),
        # another provider
        ({"stock_code": "AAPL"}, "openai/gpt-6-astra"),
        # another max hold time
        ({"stock_code": "AAPL", "hold_weeks": 3}, "gemini/gemini-3.8-flash"),
        # a deeper tier than the source ran
        ({"stock_code": "AAPL", "depth": 2}, "gemini/gemini-3.8-flash"),
    ])
    def test_mismatches_run_afresh(self, client, payload, model):
        runner, release, calls = self._gated_runner(_outcome)
        release.set()
        quick = lambda code, **kw: _quick_outcome(code)  # noqa: E731
        with patch.object(tiered, "_run_analysis", quick):
            first = client.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            _poll_until_done(client, first["task_id"])
        with patch.object(tiered, "_run_analysis", runner):
            other = self._other_user(model)
            second = other.post("/tiered/analyze", json=payload).json()
            assert second["status"] == "running"
            body = _poll_until_done(other, second["task_id"])
        assert body["reused"] is False
        assert "providers" not in calls[-1]

    def test_a_stronger_model_and_ones_own_run_are_reused(self, client, user):
        runner, release, calls = self._gated_runner()
        release.set()
        with patch.object(tiered, "_run_analysis", runner):
            first = client.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            _poll_until_done(client, first["task_id"])
            # the same user, a different capital: their own run lends its outlook
            again = client.post("/tiered/analyze", json={
                "stock_code": "AAPL", "sizing": {"capital": 123}}).json()
            assert again["status"] == "running"
            assert _poll_until_done(client, again["task_id"])["reused"] is True
            # a weaker model of the same provider gets the stronger run's outlook
            other = self._other_user("gemini/gemini-3.5-flash-lite")
            weaker = other.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            body = _poll_until_done(other, weaker["task_id"])
        assert body["result"]["reused"]["model"] == "gemini/gemini-3.8-flash"

    def test_a_run_without_an_outlook_is_never_reused(self, client):
        with patch.object(tiered, "_run_analysis", lambda code, **kw: _outcome(code)):
            first = client.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            assert _poll_until_done(client, first["task_id"])["status"] == "done"
        runner, release, calls = self._gated_runner()
        release.set()
        with patch.object(tiered, "_run_analysis", runner):
            other = self._other_user()
            second = other.post("/tiered/analyze", json={"stock_code": "AAPL"}).json()
            body = _poll_until_done(other, second["task_id"])
        assert body["reused"] is False
        assert "providers" not in calls[-1]

    def test_an_exact_duplicate_of_ones_own_waiting_run_is_still_refused(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
        runner, release, calls = self._gated_runner()
        with patch.object(tiered, "_run_analysis", runner):
            client.post("/tiered/analyze", json={"stock_code": "AAPL"})
            other = self._other_user()
            waiting = other.post("/tiered/analyze", json={"stock_code": "AAPL"})
            assert waiting.json()["status"] == "running"
            again = other.post("/tiered/analyze", json={"stock_code": "AAPL"})
            assert again.status_code == 409
            assert again.json()["detail"]["status"] == "running"
            release.set()
            _poll_until_done(other, waiting.json()["task_id"])

    def test_a_source_that_became_unfit_requeues_the_requester(self, client, user):
        """The reuse path re-checks the source when it actually finishes
        the run — e.g. the source owner switched to another provider's
        model while it waited in the queue."""
        from src.tiered_analysis import history

        history.create_run("src", "AAPL", inputs={"tier": 1, "hold_weeks": 2},
                           owner_id=user["id"], status="done",
                           bar_date="2026-09-16", model="openai/gpt-6-astra")
        history.mark_done("src", {"outlook": "unknown"})
        history.create_run("req", "AAPL", inputs={"tier": 1, "hold_weeks": 2},
                           owner_id=user["id"], status="running",
                           bar_date="2026-09-16", model="gemini/gemini-3.8-flash",
                           source_task_id="src")
        with patch.object(tiered, "_run_analysis", lambda code, **kw: _deep_outcome(code)):
            tiered._reuse_finished_source("req", "src")
            body = _poll_until_done(client, "req")
        assert body["status"] == "done"
        assert body["reused"] is False
