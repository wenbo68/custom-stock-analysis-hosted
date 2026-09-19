# -*- coding: utf-8 -*-
"""Offline tests for run reuse (2026-09-17): one run borrowing another
run's outlook. Covers the model rule (src.user_settings.covers_model),
the stored-result → pipeline pieces conversion (src/tiered_analysis/
reuse.py) and the history matching query (find_reusable_run)."""
from __future__ import annotations

import os

import pytest

from src.tiered_analysis import history
from src.tiered_analysis.providers.base import Market, SourceKind
from src.tiered_analysis.llm_support import LlmTranscript
from src.tiered_analysis.reuse import (
    ReuseUnavailable,
    dimensions_from_result,
    is_reusable_result,
    merged_llm_usage,
    reuse_kit,
    shared_llm_stages,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.tiers import TierState
from src.user_settings import covers_model, model_label, model_rank


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "tiered_reuse.db")
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


PRO = "gemini/gemini-3.1-pro-preview"
FLASH = "gemini/gemini-3.8-flash"
FLASH_LITE = "gemini/gemini-3.5-flash-lite"
GPT = "openai/gpt-6-astra"


class TestModelRule:
    def test_rank_follows_catalog_order(self):
        assert model_rank(PRO) == 0
        assert model_rank(FLASH) == 1
        assert model_rank("gemini/retired-model") is None
        assert model_label(FLASH) == "Gemini 3.8 Flash"
        assert model_label(None) is None

    def test_same_or_stronger_model_of_the_same_provider_covers(self):
        assert covers_model(FLASH, FLASH)
        assert covers_model(PRO, FLASH)
        assert covers_model(FLASH, FLASH_LITE)
        assert not covers_model(FLASH_LITE, FLASH)

    def test_other_provider_or_unknown_model_never_covers(self):
        assert not covers_model(GPT, FLASH)
        assert not covers_model("gemini/retired-model", FLASH)
        assert not covers_model(FLASH, None)


def _dimension(name="technicals", kind="numeric", **extra):
    return {
        "dimension": name, "kind": kind, "is_actionable": True,
        "payload": {"trend": {"close": 100.0}}, "formulas": None,
        "narrative": None, "warnings": ["one note"], "field_notes": None,
        "citations": [{"source_name": "Yahoo", "url": "https://y/x",
                       "title": "t", "snippet": "s"}],
        **extra,
    }


def _deep_result(outlook="bullish"):
    return {
        "symbol": "AAPL", "market": "us", "depth": 2, "outlook": outlook,
        "direction": "unknown", "narrative": None, "debate_detail": None,
        "final": {"tier": 2, "direction": "buy"},
        "dimensions": [_dimension(), _dimension("company_news", "textual")],
        "tier2": {"tier": 2, "direction": "buy", "narrative": "bull case holds",
                  "warnings": ["a debate note"],
                  "debate_detail": {"format": 11, "outlook": {"direction": "buy"}}},
    }


def _quick_result(outlook="neutral"):
    return {
        "symbol": "AAPL", "market": "us", "depth": 1, "outlook": outlook,
        "direction": "hold", "narrative": "Wait for a pullback.",
        "debate_detail": {"format": "quick_v1",
                          "outlook": {"direction": "hold", "final_score": 5.5}},
        "final": {"tier": 1, "direction": "hold"},
        "dimensions": [_dimension()],
        "tier2": None,
    }


class TestReusableResult:
    def test_deep_and_quick_results_with_an_outlook_are_reusable(self):
        assert is_reusable_result(_deep_result())
        assert is_reusable_result(_quick_result())

    @pytest.mark.parametrize("outlook", ["unknown", None])
    def test_no_outlook_is_never_reusable(self, outlook):
        assert not is_reusable_result(_deep_result(outlook))
        assert not is_reusable_result(_quick_result(outlook))

    def test_missing_pieces_are_not_reusable(self):
        assert not is_reusable_result({**_deep_result(), "dimensions": []})
        assert not is_reusable_result({**_deep_result(), "tier2": None})
        assert not is_reusable_result({**_quick_result(), "debate_detail": None})
        assert not is_reusable_result("not a dict")


class TestDimensionsRoundTrip:
    def test_stored_dimensions_become_dataclasses(self):
        dims = dimensions_from_result(_deep_result())
        assert [d.dimension for d in dims] == ["technicals", "company_news"]
        assert dims[0].kind is SourceKind.NUMERIC
        assert dims[0].payload == {"trend": {"close": 100.0}}
        assert dims[0].warnings == ["one note"]
        assert dims[0].citations[0].url == "https://y/x"
        assert dims[1].kind is SourceKind.TEXTUAL
        assert dims[0].is_actionable

    def test_unknown_kind_or_no_dimensions_refuse(self):
        with pytest.raises(ReuseUnavailable):
            dimensions_from_result({"dimensions": [_dimension(kind="odd")]})
        with pytest.raises(ReuseUnavailable):
            dimensions_from_result({"dimensions": []})


class TestReuseKit:
    def test_deep_result_yields_a_tier2_stand_in(self):
        kit = reuse_kit(_deep_result())
        assert kit.depth == 2 and kit.quick_judge is None
        assert [p.dimension for p in kit.providers] == ["technicals", "company_news"]
        foundation = TierReport(
            tier=1, symbol="AAPL", market=Market.US, direction=Direction.UNKNOWN,
            levels=SniperLevels(entry=100.0, stop_loss=95.0, take_profit=110.0),
        )
        state = TierState(symbol="AAPL", market=Market.US, reports={1: foundation})
        report = kit.tier2_stage.run(state)
        assert report.tier == 2
        assert report.direction is Direction.BUY
        assert report.narrative == "bull case holds"
        assert report.warnings == ["a debate note"]
        assert report.debate_detail == {"format": 11, "outlook": {"direction": "buy"}}
        assert report.levels == foundation.levels

    def test_quick_result_yields_a_quick_judge_stand_in(self):
        kit = reuse_kit(_quick_result())
        assert kit.depth == 1 and kit.tier2_stage is None
        quick = kit.quick_judge.run("AAPL", [], hold_weeks=2)
        assert quick.outlook.direction is Direction.HOLD
        assert quick.outlook.final_score == 5.5
        assert quick.outlook.summary == "Wait for a pullback."
        assert quick.warnings == []

    def test_unfit_result_refuses(self):
        with pytest.raises(ReuseUnavailable):
            reuse_kit(_deep_result("unknown"))


def _inputs(tier=1, hold_weeks=2):
    return {"tier": tier, "capital": 10000, "risk_fraction": 0.01,
            "reward_risk": 2, "hold_weeks": hold_weeks}


def _create(task_id, status="done", tier=1, hold_weeks=2, model=FLASH,
            bar_date="2026-09-16", stock_code="AAPL", result=None,
            source_task_id=None, owner_id=1):
    history.create_run(task_id, stock_code, inputs=_inputs(tier, hold_weeks),
                       owner_id=owner_id, status=status, bar_date=bar_date,
                       model=model, source_task_id=source_task_id)
    if status == "done":
        history.mark_done(task_id, result if result is not None else
                          (_deep_result() if tier == 2 else _quick_result()))


def _find(tier=1, hold_weeks=2, model=FLASH, bar_date="2026-09-16", code="aapl"):
    found = history.find_reusable_run(code, bar_date, hold_weeks, tier, model)
    return found["task_id"] if found else None


class TestFindReusableRun:
    def test_matches_ticker_day_and_hold_weeks(self, isolated_db):
        _create("s1")
        assert _find() == "s1"
        assert _find(bar_date="2026-09-15") is None
        assert _find(hold_weeks=3) is None
        assert _find(code="MSFT") is None
        assert history.find_reusable_run("AAPL", None, 2, 1, FLASH) is None

    def test_tier_must_be_the_same_or_deeper(self, isolated_db):
        _create("quick", tier=1)
        assert _find(tier=2) is None
        _create("deep", tier=2)
        assert _find(tier=2) == "deep"
        # a tier-1 request prefers the deeper finished run
        assert _find(tier=1) == "deep"

    def test_model_must_be_the_same_or_stronger_of_the_same_provider(self, isolated_db):
        _create("lite", model=FLASH_LITE)
        assert _find(model=FLASH) is None
        assert _find(model=FLASH_LITE) == "lite"
        _create("gpt", model=GPT)
        assert _find(model=FLASH) is None
        _create("pro", model=PRO)
        assert _find(model=FLASH) == "pro"

    def test_finished_runs_need_a_usable_result(self, isolated_db):
        _create("bad", result=_quick_result("unknown"))
        assert _find() is None
        _create("failed", status="failed")
        assert _find() is None

    def test_finished_beats_running_beats_queued_and_waiters_are_skipped(self, isolated_db):
        _create("queued", status="queued")
        _create("running", status="running")
        assert _find() == "running"
        _create("waiting", status="waiting", source_task_id="running")
        assert _find() == "running"
        _create("done", status="done")
        assert _find() == "done"

    def test_finished_prefers_deeper_then_stronger_then_newest(self, isolated_db):
        _create("flash-old", model=FLASH)
        _create("flash-new", model=FLASH)
        assert _find() == "flash-new"
        _create("pro", model=PRO)
        assert _find() == "pro"
        _create("deep-flash", tier=2, model=FLASH)
        assert _find() == "deep-flash"

    def test_running_sources_are_served_oldest_first(self, isolated_db):
        _create("first", status="queued")
        _create("second", status="queued")
        assert _find() == "first"

    def test_summary_carries_model_and_reused_flag(self, isolated_db):
        _create("s1", model=PRO)
        _create("copy", model=FLASH, source_task_id="s1")
        rows = {r["task_id"]: r for r in history.list_runs()}
        assert rows["s1"]["model"] == PRO
        assert rows["s1"]["model_label"] == "Gemini 3.1 Pro (preview)"
        assert rows["s1"]["reused"] is False
        assert rows["copy"]["reused"] is True


class TestWaitingRuns:
    def test_attach_list_and_requeue(self, isolated_db):
        _create("src", status="running")
        _create("w1", status="queued")
        history.attach_to_source("w1", "src")
        waiters = history.list_waiters("src")
        assert [w["task_id"] for w in waiters] == ["w1"]
        assert waiters[0]["model"] == FLASH
        assert waiters[0]["inputs"]["hold_weeks"] == 2
        assert history.get_run("w1")["status"] == "running"  # as the source reads
        assert history.list_waiters("src")[0]["status"] == "waiting"  # stored
        history.requeue("w1")
        assert history.get_run("w1")["status"] == "queued"
        assert history.list_waiters("src") == []
        assert history.next_queued_run()["task_id"] == "w1"

    def test_waiting_rows_are_never_dispatched(self, isolated_db):
        _create("src", status="running")
        _create("w1", status="waiting", source_task_id="src")
        assert history.next_queued_run() is None

    def test_waiting_counts_as_active_for_the_duplicate_check(self, isolated_db):
        _create("src", status="queued")
        _create("w1", status="waiting", source_task_id="src")
        assert history.find_active_duplicate(1, "AAPL", _inputs())["status"] == "queued"

    def test_a_waiting_run_reads_as_its_source_reads(self, isolated_db):
        _create("ahead", status="queued", stock_code="MSFT")
        _create("src-queued", status="queued")
        _create("src-running", status="running")
        _create("w-queued", status="waiting", source_task_id="src-queued")
        _create("w-running", status="waiting", source_task_id="src-running")
        rows = {r["task_id"]: r for r in history.list_runs()}
        assert (rows["w-queued"]["status"], rows["w-queued"]["queue_ahead"]) == ("queued", 1)
        assert (rows["src-queued"]["status"], rows["src-queued"]["queue_ahead"]) == ("queued", 1)
        assert (rows["w-running"]["status"], rows["w-running"]["queue_ahead"]) == ("running", None)
        one = history.get_run("w-queued")
        assert (one["status"], one["queue_ahead"]) == ("queued", 1)

    def test_startup_requeues_waiters_whose_source_is_gone(self, isolated_db):
        _create("alive", status="queued")
        _create("dead", status="failed")
        _create("w-alive", status="waiting", source_task_id="alive")
        _create("w-dead", status="waiting", source_task_id="dead")
        _create("w-missing", status="waiting", source_task_id="nope")
        assert history.requeue_orphaned_waiters() == 2
        assert history.run_for_reuse("w-alive")["status"] == "waiting"
        assert history.get_run("w-dead")["status"] == "queued"
        assert history.get_run("w-missing")["status"] == "queued"

    def test_run_for_reuse_exposes_the_parsed_result(self, isolated_db):
        _create("s1", tier=2)
        run = history.run_for_reuse("s1")
        assert run["result"]["depth"] == 2
        assert run["bar_date"] == "2026-09-16"
        assert history.run_for_reuse("nope") is None


# ---------- round trip through the real pipeline ----------

def _env(value):
    return {"name": "n", "explanation": "e", "value": value}


def _technicals_payload():
    """Bases: entry 96, stop 90, target = entry + goal × 6."""
    return {
        "price": {"close": _env(100.0), "high_1y": _env(None)},
        "daily": {"sma_50": _env(96.0), "sma_200": _env(90.0)},
        "volatility": {"atr_14": _env(3.0)},
        "volume": {"avg_vol_60d": _env(None)},
        "levels": {"support_1": _env(94.0), "resistance_1": _env(None)},
    }


class _StubProvider:
    kind = SourceKind.NUMERIC

    def __init__(self, result):
        self.dimension = result.dimension
        self._result = result

    def supports(self, market):
        return True

    def collect(self, symbol):
        return self._result


class _FakeDebateEngine:
    def __init__(self, direction=Direction.BUY):
        from src.tiered_analysis.debate import DebateOutlook

        self.calls = 0
        self._outlook = DebateOutlook(
            direction=direction, final_score=7.4, summary="the vote settled it",
            initial_score=7.4, pools={"bullish_weight": 3.0, "total_weight": 4.0},
        )

    def run(self, symbol, tier1, dimensions, hold_weeks=2):
        from src.tiered_analysis.debate import DebateResult

        self.calls += 1
        return DebateResult(outlook=self._outlook, warnings=["a debate note"])


class _FakeQuickJudge:
    def __init__(self):
        from src.tiered_analysis.quick_judge import QuickOutlook, QuickResult

        self.calls = 0
        self._result = QuickResult(outlook=QuickOutlook(
            direction=Direction.HOLD, final_score=5.0, summary="wait"))

    def run(self, symbol, dimensions, hold_weeks):
        self.calls += 1
        return self._result


def _no_earnings(symbol, market):
    from src.tiered_analysis.earnings import EarningsInfo

    return EarningsInfo(next_date=None, days_until=None)


class TestPipelineRoundTrip:
    """A reused run through the REAL orchestrator: the source's stored
    result stands in for the data layer and the judge, the personal
    stages run again with the requester's reward goal."""

    @staticmethod
    def _run(depth, reward_risk, providers=None, engine=None, judge=None,
             stand_ins=None):
        from src.tiered_analysis.integration import run_tiered_analysis
        from src.tiered_analysis.providers.base import DimensionResult
        from src.tiered_analysis.settings import SizingSettings
        from src.tiered_analysis.tiers import Tier2Stage

        technicals = DimensionResult(
            dimension="technicals", kind=SourceKind.NUMERIC,
            payload=_technicals_payload(), warnings=["a data note"],
        )
        kwargs = dict(
            providers=[_StubProvider(technicals)],
            quick_judge=judge,
            tier2_stage=Tier2Stage(engine=engine) if engine else None,
        )
        if stand_ins:
            kwargs = stand_ins
        return run_tiered_analysis(
            "AAPL", market=Market.US, depth=depth,
            sizing_settings=SizingSettings(capital=10000.0, risk_fraction=0.01,
                                           reward_risk=reward_risk),
            earnings_lookup=_no_earnings,
            plan_summarizer=lambda prompt: '{"adjustments": []}',
            **kwargs,
        )

    def test_deep_run_reused_with_another_reward_goal(self):
        from api.v1.endpoints.tiered import _serialize_outcome

        engine = _FakeDebateEngine()
        source = _serialize_outcome(self._run(2, 2.0, engine=engine))
        assert engine.calls == 1
        assert source["outlook"] == "bullish"
        assert source["levels"]["take_profit"] == 108.0

        kit = reuse_kit(source)
        copy = _serialize_outcome(self._run(2, 3.0, stand_ins=dict(
            providers=kit.providers, quick_judge=kit.quick_judge,
            tier2_stage=kit.tier2_stage)))
        assert engine.calls == 1  # the debate did not run again
        # shared: the data cards and the judge's call
        assert copy["dimensions"] == source["dimensions"]
        assert copy["tier2"]["debate_detail"] == source["tier2"]["debate_detail"]
        assert copy["tier2"]["narrative"] == "the vote settled it"
        assert copy["tier2"]["warnings"] == ["a debate note"]
        assert copy["outlook"] == "bullish" and copy["depth"] == 2
        # personal: the target follows the requester's goal
        assert copy["levels"]["take_profit"] == 114.0
        assert copy["sizing"]["inputs"]["reward_risk"] == 3.0

    def test_quick_run_reused(self):
        from api.v1.endpoints.tiered import _serialize_outcome

        judge = _FakeQuickJudge()
        source = _serialize_outcome(self._run(1, 2.0, judge=judge))
        assert source["outlook"] == "neutral"
        assert source["debate_detail"]["outlook"]["final_score"] == 5.0

        kit = reuse_kit(source)
        copy = _serialize_outcome(self._run(1, 2.0, stand_ins=dict(
            providers=kit.providers, quick_judge=kit.quick_judge,
            tier2_stage=kit.tier2_stage)))
        assert judge.calls == 1
        assert copy["outlook"] == "neutral"
        assert copy["narrative"] == "wait"
        assert copy["debate_detail"] == source["debate_detail"]
        assert copy["dimensions"] == source["dimensions"]


def _usage(stages):
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for usage in stages.values():
        for key in total:
            total[key] += usage[key]
    return {"stages": stages, "total": total, "scope": "tiered"}


def _stage(calls, prompt_tokens, completion_tokens):
    return {"calls": calls, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens}


class TestMergedUsage:
    """The usage a reused run reports (2026-09-19): the source's shared
    calls plus the requester's own, with the requester's share set
    apart when someone else paid for the rest."""

    source = _usage({
        "company_news": _stage(2, 1000, 100),
        "tier2_analysis": _stage(12, 90000, 3000),
        "trade_plan": _stage(1, 500, 50),
    })
    own = {**_usage({"trade_plan": _stage(2, 1200, 300)}), "transcript_entries": 2}

    def test_shared_stages_leave_out_the_source_owners_plan(self):
        assert shared_llm_stages(self.source) == {
            "company_news": _stage(2, 1000, 100),
            "tier2_analysis": _stage(12, 90000, 3000),
        }
        assert shared_llm_stages(None) == {}
        assert shared_llm_stages({"total": _stage(1, 1, 1)}) == {}

    def test_totals_cover_the_whole_analysis_and_set_the_own_share_apart(self):
        merged = merged_llm_usage(self.source, self.own, shared_entries=14,
                                  other_owner=True)
        assert merged["total"] == _stage(16, 92200, 3400)
        assert merged["stages"]["trade_plan"] == _stage(2, 1200, 300)
        assert merged["paid_by_you"] == _stage(2, 1200, 300)
        assert merged["transcript_entries"] == 16
        assert merged["scope"] == "tiered"

    def test_reusing_ones_own_run_has_no_separate_share(self):
        merged = merged_llm_usage(self.source, self.own, shared_entries=14,
                                  other_owner=False)
        assert "paid_by_you" not in merged
        assert merged["total"]["calls"] == 16

    def test_a_run_without_own_calls_still_opens_the_transcript(self):
        merged = merged_llm_usage(self.source, _usage({}), shared_entries=14,
                                  other_owner=True)
        assert merged["paid_by_you"] == _stage(0, 0, 0)
        assert merged["transcript_entries"] == 14
        # a source stored before usage existed contributes nothing but
        # never breaks the run
        bare = merged_llm_usage(None, None, shared_entries=0, other_owner=True)
        assert bare["total"] == _stage(0, 0, 0)
        assert "transcript_entries" not in bare


def _record(task_id, stage, prompt_tokens=10):
    LlmTranscript.for_run(task_id).record(
        stage=stage, model="gemini/flash", temperature=0.0,
        prompt=f"{stage} prompt", reply="{}", prompt_tokens=prompt_tokens,
        completion_tokens=1,
    )


class TestTranscriptForRun:
    def test_own_run_shows_its_own_rows_paid_by_you(self, isolated_db):
        _create("s1")
        _record("s1", "company_news")
        _record("s1", "trade_plan")
        items = history.transcript_for_run("s1")
        assert [(i["seq"], i["stage"], i["paid_by"]) for i in items] == [
            (1, "company_news", "you"), (2, "trade_plan", "you")]
        assert history.transcript_for_run("nope") == []

    def test_reused_run_shows_the_shared_rows_then_its_own(self, isolated_db):
        _create("s1", owner_id=1)
        _create("copy", owner_id=2, source_task_id="s1")
        _record("s1", "company_news")
        _record("s1", "tier2_analysis")
        _record("s1", "trade_plan")   # the source owner's plan: not shown
        _record("copy", "trade_plan")
        items = history.transcript_for_run("copy")
        assert [(i["seq"], i["stage"], i["paid_by"]) for i in items] == [
            (1, "company_news", "another_user"),
            (2, "tier2_analysis", "another_user"),
            (3, "trade_plan", "you"),
        ]
        assert items[2]["prompt"] == "trade_plan prompt"
        assert history.count_transcript("s1") == 3
        assert history.count_transcript("s1", exclude_stages={"trade_plan"}) == 2
        # the source's own view is untouched
        assert [i["stage"] for i in history.transcript_for_run("s1")] == [
            "company_news", "tier2_analysis", "trade_plan"]

    def test_reusing_ones_own_run_is_all_paid_by_you(self, isolated_db):
        _create("s1", owner_id=1)
        _create("again", owner_id=1, source_task_id="s1")
        _record("s1", "company_news")
        _record("again", "trade_plan")
        assert [i["paid_by"] for i in history.transcript_for_run("again")] == ["you", "you"]
