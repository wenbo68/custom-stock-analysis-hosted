# -*- coding: utf-8 -*-
"""Offline tests for the production wiring of tiered analysis (integration).

The real connections are faked here (data manager, quick judge, debate
engine, signal logger); what's under test is the glue:

- dsa_bars_loader: DataFetcherManager daily DataFrame -> chronological Bars
- run_tiered_analysis: collect dimensions + judge + merge + signal log
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import pandas as pd

from src.tiered_analysis.debate import direction_from_final
from src.tiered_analysis.earnings import EarningsInfo
from src.tiered_analysis.integration import (
    dsa_bars_loader,
    run_tiered_analysis,
)
from src.tiered_analysis.providers.technicals import technicals_as_of
from src.tiered_analysis.quick_judge import QuickResult, QuickOutlook
from src.tiered_analysis.run_gate import expected_bar_date
from src.tiered_analysis.schema import Action, Outlook, derive_action
from src.tiered_analysis.providers.base import (
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels


def _daily_df(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


class FakeManager:
    def __init__(self, df):
        self._df = df
        self.calls = []

    def get_daily_data(self, stock_code, days=30):
        self.calls.append((stock_code, days))
        return self._df, "fake-source"


class TestDsaBarsLoader(unittest.TestCase):
    def test_maps_dataframe_to_chronological_bars(self):
        df = _daily_df([
            ("2026-07-03", 11.0, 12.0, 10.5, 11.5, 1000),
            ("2026-07-01", 10.0, 11.0, 9.5, 10.5, 900),  # out of order
            ("2026-07-02", 10.5, 11.5, 10.0, 11.0, 950),
        ])
        manager = FakeManager(df)
        bars = dsa_bars_loader("AAPL", manager=manager)
        self.assertEqual([b.date for b in bars],
                         ["2026-07-01", "2026-07-02", "2026-07-03"])
        self.assertEqual(bars[-1].close, 11.5)
        self.assertEqual(bars[0].high, 11.0)
        # enough calendar days requested to cover 60 trading bars
        self.assertGreaterEqual(manager.calls[0][1], 90)

    def test_rows_with_missing_prices_are_dropped(self):
        df = _daily_df([
            ("2026-07-01", 10.0, 11.0, 9.5, 10.5, 900),
            ("2026-07-02", None, None, None, None, None),
        ])
        bars = dsa_bars_loader("AAPL", manager=FakeManager(df))
        self.assertEqual(len(bars), 1)

    def test_empty_dataframe_returns_empty_list(self):
        bars = dsa_bars_loader("AAPL", manager=FakeManager(_daily_df([])))
        self.assertEqual(bars, [])


class _StubProvider(DimensionProvider):
    kind = SourceKind.NUMERIC

    def __init__(self, name, result=None, crash=False):
        self.dimension = name
        self._result = result
        self._crash = crash

    def supports(self, market):
        return True

    def collect(self, symbol):
        if self._crash:
            raise RuntimeError("provider blew up")
        return self._result


def _dim(name):
    return DimensionResult(
        dimension=name,
        kind=SourceKind.NUMERIC,
        payload={"x": 1},
    )


class _FakeQuickJudge:
    """Canned tier-1 outlook; records (symbol, hold_weeks) calls."""

    def __init__(self, score=7.5, summary="buy the pullback",
                 outlook=True, warnings=()):
        self.calls = []
        if outlook:
            self._result = QuickResult(
                outlook=QuickOutlook(
                    direction=direction_from_final(score),
                    final_score=score,
                    summary=summary,
                ),
                warnings=list(warnings),
            )
        else:
            self._result = QuickResult(warnings=list(warnings))

    def run(self, symbol, dimensions, hold_weeks):
        self.calls.append((symbol, hold_weeks))
        return self._result


def _no_earnings(symbol, market):
    """Offline stand-in for the yfinance earnings lookup."""
    return EarningsInfo()


class TestRunTieredAnalysis(unittest.TestCase):
    def _run(self, providers=None, judge=None):
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=providers if providers is not None
            else [_StubProvider("technicals", _dim("technicals"))],
            quick_judge=judge or _FakeQuickJudge(),
            earnings_lookup=_no_earnings,
        )
        return outcome, []

    def test_dimensions_attached(self):
        outcome, _ = self._run()
        report = outcome.report
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual([d.dimension for d in report.dimensions], ["technicals"])

    def test_crashing_provider_becomes_warned_empty_dimension(self):
        providers = [_StubProvider("fundamentals", crash=True)]
        outcome, _ = self._run(providers=providers)
        dim = outcome.report.dimensions[0]
        self.assertEqual(dim.dimension, "fundamentals")
        self.assertIsNone(dim.payload)
        self.assertTrue(any("provider blew up" in w for w in dim.warnings))

    def test_injected_providers_with_explicit_cross_loader_enrich(self):
        """The cross_bars_loader seam: a harness that injects providers
        (which normally skips cross-provider enrichment) can opt in by
        passing its own loader — the demo seeder relies on this."""
        tech = DimensionResult(
            dimension="technicals",
            kind=SourceKind.NUMERIC,
            payload={"market": {"regime": {"value": "bullish"}}},
        )
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals", tech)],
            quick_judge=_FakeQuickJudge(),
            earnings_lookup=_no_earnings,
            cross_bars_loader=lambda ticker: [],
        )
        enriched = outcome.report.dimensions[0]
        self.assertIn("rs_sector_1m", enriched.payload["market"])
        self.assertTrue(
            any("sector unknown" in w for w in enriched.warnings)
        )

    def test_failed_tier1_still_returns_report_with_dimensions(self):
        judge = _FakeQuickJudge(
            outlook=False,
            warnings=["quick judge LLM call failed: LLM down"],
        )
        outcome, _ = self._run(judge=judge)
        self.assertEqual(outcome.report.direction, Direction.UNKNOWN)
        self.assertTrue(outcome.report.dimensions)
        self.assertTrue(any("LLM down" in w for w in outcome.report.warnings))


class _FakeDebateEngine:
    def __init__(self, outlook=None, warnings=()):
        self._outlook = outlook
        self._warnings = list(warnings)
        self.calls = []

    def run(self, symbol, tier1, dimensions, hold_weeks=2):
        from src.tiered_analysis.debate import DebateResult

        self.calls.append(symbol)
        return DebateResult(outlook=self._outlook, warnings=self._warnings)


def _env(value):
    return {"name": "n", "explanation": "e", "value": value}


def _tech_payload(close=100.0, sma_50=96.0, sma_200=90.0, support_1=94.0,
                  atr_14=3.0, avg_vol_60d=None, resistance_1=None):
    """A minimal v2 envelope payload with the plan-pipeline anchors."""
    return {
        "price": {"close": _env(close), "high_1y": _env(None)},
        "daily": {"sma_50": _env(sma_50), "sma_200": _env(sma_200)},
        "volatility": {"atr_14": _env(atr_14)},
        "volume": {"avg_vol_60d": _env(avg_vol_60d)},
        "levels": {"support_1": _env(support_1),
                   "resistance_1": _env(resistance_1)},
    }


def _technicals_dim_with_levels():
    """Payload the base-level formulas can compute from.

    Bases: entry=96 (nearest support capped at close), stop=90
    (entry − 2×ATR), target=108 (entry + 2×(entry−stop); no overhead
    resistance to cap it). Trend check passes: close 100 > sma_50 96.
    """
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        payload=_tech_payload(),
    )


def _debate_outlook(direction=Direction.BUY, score=7.4):
    from src.tiered_analysis.debate import DebateOutlook

    return DebateOutlook(direction=direction, final_score=score,
                         summary="the vote settled it", initial_score=score,
                         pools={})


class TestDepthRoutingAndSizing(unittest.TestCase):
    """Outlook redesign: depth 1|2 routing, outlook/action, sizing."""

    def _run(self, depth=1, sizing_settings=None, sizing_overrides=None,
             debate_outlook=None, quick_score=7.5, tech_payload=None):
        from src.tiered_analysis.settings import SizingSettings
        from src.tiered_analysis.tiers import Tier2Stage

        technicals = (
            DimensionResult(dimension="technicals", kind=SourceKind.NUMERIC,
                            payload=tech_payload)
            if tech_payload is not None else _technicals_dim_with_levels()
        )
        judge = _FakeQuickJudge(score=quick_score)
        debate_engine = _FakeDebateEngine(outlook=debate_outlook)
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals", technicals)],
            quick_judge=judge,
            depth=depth,
            sizing_settings=sizing_settings or SizingSettings(),
            sizing_overrides=sizing_overrides,
            tier2_stage=Tier2Stage(engine=debate_engine),
            earnings_lookup=_no_earnings,
        )
        # ``logged`` mirrors the deepest report (the parent project's
        # signal ledger is gone; the report itself is what matters).
        logged = [outcome.final_report]
        return outcome, logged, debate_engine, judge.calls

    def test_default_depth_is_tier1_only(self):
        outcome, logged, debate_engine, judge_calls = self._run()
        self.assertEqual(outcome.depth, 1)
        self.assertEqual(sorted(outcome.state.reports), [1])
        self.assertIs(outcome.final_report, outcome.report)
        # The quick judge IS the depth-1 judge, and it sees the hold time.
        self.assertEqual(judge_calls, [("AAPL", 2)])
        self.assertEqual(debate_engine.calls, [])
        self.assertEqual(logged[0].tier, 1)
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(outcome.action, Action.ENTER)

    def test_depth_2_skips_the_quick_judge_and_runs_the_vote(self):
        outcome, logged, debate_engine, judge_calls = self._run(
            depth=2, debate_outlook=_debate_outlook())
        # The quick-judge call must NOT run at depth 2.
        self.assertEqual(judge_calls, [])
        self.assertEqual(sorted(outcome.state.reports), [1, 2])
        self.assertEqual(outcome.final_report.tier, 2)
        self.assertEqual(outcome.final_report.direction, Direction.BUY)
        self.assertEqual(debate_engine.calls, ["AAPL"])
        # Skipping the blob is the documented depth-2 contract, not a data
        # problem — the foundation report must NOT warn about it.
        self.assertFalse(any("skipped" in w for w in outcome.report.warnings))
        # the ledger gets the deepest tier, with the evidence attached
        self.assertEqual(logged[0].tier, 2)
        self.assertTrue(logged[0].dimensions)

    def test_depth_2_failure_has_no_tier1_fallback(self):
        outcome, _, _, _ = self._run(depth=2, debate_outlook=None)
        self.assertEqual(outcome.final_report.direction, Direction.UNKNOWN)
        self.assertEqual(outcome.outlook, Outlook.UNKNOWN)
        self.assertEqual(outcome.action, Action.UNKNOWN)
        self.assertTrue(any("re-run" in w
                            for w in outcome.final_report.warnings))

    def test_invalid_depth_rejected(self):
        for depth in (0, 3, 4):
            with self.assertRaises(ValueError):
                self._run(depth=depth)

    def test_missing_sizing_falls_back_to_the_form_defaults(self):
        # Owner decision 2026-07-24: every run sizes. With no settings and
        # no overrides, the web form's defaults fill in (100k capital, 1%
        # risk) — entry 96, stop 90 → loss/share 6 → floor(1000/6) = 166.
        outcome, _, _, _ = self._run()
        self.assertTrue(outcome.sizing["enabled"])
        self.assertEqual(outcome.sizing["inputs"]["capital"], 100000.0)
        self.assertEqual(outcome.sizing["inputs"]["risk_fraction"], 0.01)
        self.assertEqual(outcome.sizing["shares"], 166)

    def test_enabled_sizing_computes_shares_from_final_levels(self):
        from src.tiered_analysis.settings import SizingSettings

        outcome, logged, _, _ = self._run(
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01))
        # entry 96, stop 90 → loss/share 6 → floor(1000/6) = 166 shares
        self.assertEqual(outcome.sizing["shares"], 166)
        self.assertTrue(outcome.sizing["enabled"])
        self.assertEqual(outcome.final_report.sizing.shares, 166.0)
        self.assertEqual(logged[0].sizing.shares, 166.0)

    def test_hold_direction_refuses_sizing_and_maps_to_no_trade(self):
        outcome, _, _, _ = self._run(quick_score=5.0)
        self.assertEqual(outcome.sizing["reason_code"], "not_a_buy")
        self.assertEqual(outcome.outlook, Outlook.NEUTRAL)
        self.assertEqual(outcome.action, Action.NO_TRADE)

    def test_per_run_overrides_enable_sizing(self):
        outcome, _, _, _ = self._run(
            sizing_overrides={"capital": 100000.0, "risk_fraction": 0.01})
        self.assertEqual(outcome.sizing["shares"], 166)

    def test_reward_capped_plan_maps_bullish_to_buy_later(self):
        # Resistance at 104 caps the target (geometric would be 108):
        # ratio (104−96)/(96−90) ≈ 1.33 < the 2× goal → "buy later",
        # the same condition that raises the reward-below-goal warning.
        outcome, _, _, _ = self._run(
            tech_payload=_tech_payload(resistance_1=104.0))
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(outcome.action, Action.ENTER_LATER)

    def test_bearish_is_no_trade_and_sizes_nothing(self):
        outcome, _, _, _ = self._run(
            depth=2, debate_outlook=_debate_outlook(Direction.SELL, 2.5))
        self.assertEqual(outcome.outlook, Outlook.BEARISH)
        self.assertEqual(outcome.action, Action.NO_TRADE)
        # The ownership input is gone (2026-09-16): no held-shares block.
        self.assertNotIn("ownership", outcome.sizing)
        self.assertNotIn("sell_shares", outcome.sizing)
        self.assertIn(outcome.sizing["reason_code"], ("not_a_buy", "sizing_off"))

    def test_plan_review_emits_structured_warnings_and_shares_detail(self):
        outcome, _, _, _ = self._run(
            sizing_overrides={"capital": 100000.0, "risk_fraction": 0.01})
        pw = outcome.plan_warnings
        self.assertEqual(sorted(pw), ["entry", "shares", "stop_loss", "take_profit"])
        gap = pw["stop_loss"][0]
        self.assertEqual(gap["id"], "gap_atr")
        # open = stop 90 − 1×ATR 3 = 87; loss = 166 × (96 − 87) = 1494
        self.assertAlmostEqual(gap["values"]["atr_open"], 87.0)
        self.assertAlmostEqual(gap["values"]["atr_loss"], 1494.0)
        self.assertEqual(pw["take_profit"], [])  # R:R exactly the 2× goal
        shares_detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertEqual(shares_detail["base"], 166)
        self.assertEqual(shares_detail["final"], 166)
        self.assertIsNone(shares_detail["adjusted"])

    def test_plan_review_absent_on_non_buy(self):
        outcome, _, _, _ = self._run(quick_score=5.0)
        self.assertIsNone(outcome.plan_warnings)
        self.assertNotIn("shares",
                         (outcome.report.levels_detail or {}).get("levels", {}))

    def test_earnings_detail_rides_along(self):
        outcome, _, _, _ = self._run()
        self.assertIsNotNone(outcome.earnings)
        self.assertIsNone(outcome.earnings.next_date)

    def test_llm_usage_always_present_with_scope_note(self):
        outcome, _, _, _ = self._run(depth=2, debate_outlook=None)
        self.assertEqual(outcome.llm_usage["total"]["calls"], 0)  # all fakes
        self.assertIn("tier-1", outcome.llm_usage["scope"])


class TestDeriveAction(unittest.TestCase):
    """The pure action table, including the buy-now/buy-later split."""

    def test_bullish_splits_on_the_reward_goal(self):
        self.assertEqual(
            derive_action(Outlook.BULLISH, plan_meets_goal=True),
            Action.ENTER)
        self.assertEqual(
            derive_action(Outlook.BULLISH, plan_meets_goal=False),
            Action.ENTER_LATER)

    def test_a_goal_miss_never_changes_the_other_cells(self):
        for outlook, expected in [
            (Outlook.NEUTRAL, Action.NO_TRADE),
            (Outlook.BEARISH, Action.NO_TRADE),
            (Outlook.UNKNOWN, Action.UNKNOWN),
        ]:
            self.assertEqual(
                derive_action(outlook, plan_meets_goal=False), expected)


class TestPlanReviewAdjustments(unittest.TestCase):
    """The AI plan review through the full orchestrator, LLM faked."""

    def _run_with_reply(self, reply: str):
        return self._run_with_reply_sequence([reply])

    def _run_with_reply_sequence(self, replies):
        """Fake LLM replies, one per call; the last one repeats."""
        from src.tiered_analysis.settings import SizingSettings

        payload = _tech_payload(avg_vol_60d=1000.0)
        dim = DimensionResult(
            dimension="technicals", kind=SourceKind.NUMERIC,
            payload=payload,
        )
        prompts = []

        def summarizer(prompt):
            prompts.append(prompt)
            return replies[min(len(prompts), len(replies)) - 1]

        outcome = run_tiered_analysis(
            "AAPL", market=Market.US,
            providers=[_StubProvider("technicals", dim)],
            quick_judge=_FakeQuickJudge(),
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01),
            earnings_lookup=_no_earnings,
            plan_summarizer=summarizer,
        )
        return outcome, prompts

    def test_ai_share_trim_with_cited_reason(self):
        # 166 shares are 16.6% of the 1000-share ADV → liquidity flags →
        # the fake AI trims to 50 with a verified link.
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 50,
            "reasons": [{
                "check": "liquidity",
                "text": ("The planned order is far above the 5% liquidity "
                         "limit against an average daily volume of 1000."),
                "links": [{"ref": "technicals.volume.avg_vol_60d", "value": "1000"}],
            }],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 1)
        self.assertIn("liquidity", prompts[0])
        self.assertEqual(outcome.sizing["shares"], 50)
        detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertEqual(detail["base"], 166)
        self.assertEqual(detail["adjusted"], 50)
        self.assertEqual(detail["reasons"][0]["check"], "liquidity")
        self.assertIn("liquidity limit", detail["reasons"][0]["text"])
        self.assertEqual(detail["reasons"][0]["links"][0]["ref"],
                         "technicals.volume.avg_vol_60d")
        # Receipt data always rides with an adjusted count (2026-07-22):
        # the mechanical recompute and the inputs it used.
        self.assertEqual(detail["mechanical"], 166)
        self.assertEqual(detail["adjusted_inputs"]["entry"], 96.0)
        # gap warning recomputes off the trimmed count: 50 × (96−87) = 450
        gap = outcome.plan_warnings["stop_loss"][0]
        self.assertAlmostEqual(gap["values"]["atr_loss"], 450.0)
        self.assertEqual(outcome.llm_usage["stages"].get("plan_adjust", {})
                         .get("calls", 0), 0)  # fake summarizer records none

    def test_uncited_number_in_reason_drops_adjustment(self):
        # "12.34%" is stated but cited by nothing and matches no report
        # value → both rounds fail → the computed plan stands.
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 50,
            "reasons": [{
                "check": "liquidity",
                "text": ("Order flow above 12.34% of daily volume is "
                         "hard to exit, so the count comes down."),
                "links": [{"ref": "technicals.volume.avg_vol_60d",
                           "value": "1000"}],
            }],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 2)  # one call + one fix round
        self.assertEqual(outcome.sizing["shares"], 166)
        self.assertTrue(any("has no citation" in w
                            for w in outcome.report.warnings))

    def test_threshold_and_own_numbers_need_no_citation(self):
        # "5%" restates the liquidity threshold and "50" is the proposed
        # value itself — neither needs a link; "1000" is cited.
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 50,
            "reasons": [{
                "check": "liquidity",
                "text": ("Cutting to 50 keeps the order under the 5% "
                         "limit against the average daily volume of "
                         "1000."),
                "links": [{"ref": "technicals.volume.avg_vol_60d",
                           "value": "1000"}],
            }],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(outcome.sizing["shares"], 50)

    def test_share_increase_never_converges_so_plan_reverts(self):
        # The AI "fixes" liquidity by INCREASING shares every round; the
        # trim guardrail voids it, liquidity keeps firing, and after the
        # last round every adjustment is discarded (cycle, 2026-07-22).
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 500,
            "reasons": [{"check": "liquidity", "text": "More is better.",
                         "links": []}],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 3)  # one call per round, no fix rounds
        self.assertEqual(outcome.sizing["shares"], 166)
        detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertIsNone(detail["adjusted"])
        failures = outcome.report.levels_detail["review_failures"]
        self.assertEqual([f["round"] for f in failures], [1, 2, 3])
        self.assertTrue(all(f["checks"] == ["liquidity"] for f in failures))
        self.assertTrue(any("did not converge" in w
                            for w in outcome.report.warnings))

    def test_second_round_fixes_what_the_first_missed(self):
        # Round 1 trims to 100 — still 10% of the 1000-share ADV, so the
        # re-run liquidity check flags again; round 2 trims to 50 → 5%,
        # not above the limit → converged with round 2's value/reason.
        def trim_reply(value):
            return json.dumps({"adjustments": [{
                "target": "shares", "value": value,
                "reasons": [{
                    "check": "liquidity",
                    "text": (f"Cutting to {value} moves the order toward "
                             "the 5% limit against the average daily "
                             "volume of 1000."),
                    "links": [{"ref": "technicals.volume.avg_vol_60d",
                               "value": "1000"}],
                }],
            }]})

        replies = [trim_reply(100), trim_reply(50)]
        outcome, prompts = self._run_with_reply_sequence(replies)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(outcome.sizing["shares"], 50)
        detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertEqual(detail["adjusted"], 50)
        # Same check re-explained → round 2's reason replaces round 1's.
        self.assertEqual(len(detail["reasons"]), 1)
        self.assertIn("Cutting to 50", detail["reasons"][0]["text"])
        self.assertNotIn("review_failures", outcome.report.levels_detail)

    def test_unparseable_reply_keeps_computed_plan(self):
        outcome, prompts = self._run_with_reply("not json at all")
        self.assertEqual(len(prompts), 2)  # one call + one fix round
        self.assertEqual(outcome.sizing["shares"], 166)
        self.assertTrue(any("plan-review reply problem" in w
                            for w in outcome.report.warnings))
        # An empty answer while liquidity fires is a round-1 failure: the
        # computed plan stands and the failure list says why.
        failures = outcome.report.levels_detail["review_failures"]
        self.assertEqual(failures, [{"round": 1, "checks": ["liquidity"]}])


class TestRegistryBarsLoaderWiring(unittest.TestCase):
    def test_get_providers_accepts_bars_loader(self):
        from src.tiered_analysis.providers.registry import get_providers
        from src.tiered_analysis.providers.technicals import Bar

        closes = [100.0 + i * 0.5 for i in range(70)]
        bars = [
            Bar(high=c + 1.0, low=c - 1.0, close=c, date=f"d{i}")
            for i, c in enumerate(closes)
        ]
        providers = get_providers(Market.US, bars_loader=lambda symbol: bars)
        technicals = next(p for p in providers if p.dimension == "technicals")
        result = technicals.collect("AAPL")
        # 70 bars: the thin-history fields blank with notes (no 200-day
        # average, thin weekly read) — but the payload exists and the
        # close is served.
        self.assertTrue(result.field_notes)
        self.assertIsNotNone(result.payload["price"]["close"]["value"])


class TestDowntrendCheckAndWarning(unittest.TestCase):
    """A close at or below the 50-day average no longer voids the plan
    (owner decision 2026-07-24) — it flags the adjust cycle and lands a
    structured warning on the entry column instead."""

    DOWNTREND_TECH = _tech_payload(close=89.0, sma_50=90.0, support_1=None)
    LEVELS = SniperLevels(entry=89.0, stop_loss=83.0, take_profit=101.0)

    def test_downtrend_is_flagged_for_the_adjust_cycle(self):
        from src.tiered_analysis.plan_review import _flagged_checks

        names = [c.name for c in
                 _flagged_checks(self.DOWNTREND_TECH, self.LEVELS, shares=None)]
        self.assertIn("downtrend", names)

    def test_uptrend_is_not_flagged(self):
        from src.tiered_analysis.plan_review import _flagged_checks

        uptrend = _tech_payload(close=91.0, sma_50=90.0, support_1=None)
        names = [c.name for c in
                 _flagged_checks(uptrend, self.LEVELS, shares=None)]
        self.assertNotIn("downtrend", names)

    def test_entry_column_carries_the_downtrend_warning(self):
        from src.tiered_analysis.plan_review import build_plan_warnings

        warnings = build_plan_warnings(
            self.DOWNTREND_TECH, self.LEVELS,
            shares=None, risk_amount=None, reward_goal=2.0,
        )
        self.assertEqual(
            warnings["entry"],
            [{"id": "downtrend", "values": {"close": 89.0, "sma_50": 90.0}}],
        )

    def test_no_entry_warning_without_an_entry(self):
        from src.tiered_analysis.plan_review import build_plan_warnings

        warnings = build_plan_warnings(
            self.DOWNTREND_TECH, SniperLevels(),
            shares=None, risk_amount=None, reward_goal=2.0,
        )
        self.assertEqual(warnings["entry"], [])


class TestEarningsGateWarning(unittest.TestCase):
    """The earnings gate (2026-07-27): a plan whose hold window straddles
    the next report gets a code-computed warning — previously the date
    was display + a debate-prompt nudge only, with nothing in the plan
    pipeline reading it."""

    TECH = _tech_payload()
    LEVELS = SniperLevels(entry=96.0, stop_loss=90.0, take_profit=108.0)

    def _warnings(self, earnings):
        from src.tiered_analysis.plan_review import build_plan_warnings

        return build_plan_warnings(
            self.TECH, self.LEVELS,
            shares=None, risk_amount=None, reward_goal=2.0,
            earnings=earnings,
        )

    def test_near_earnings_lands_a_structured_entry_warning(self):
        from src.tiered_analysis.earnings import EarningsInfo

        warnings = self._warnings(
            EarningsInfo(next_date="2026-07-30", days_until=3)
        )
        self.assertEqual(warnings["entry"], [{
            "id": "earnings_soon",
            "values": {
                "days_until": 3, "next_date": "2026-07-30",
                "warning_days": 7,
            },
        }])

    def test_distant_earnings_stays_quiet(self):
        from src.tiered_analysis.earnings import EarningsInfo

        warnings = self._warnings(
            EarningsInfo(next_date="2026-09-30", days_until=64)
        )
        self.assertEqual(warnings["entry"], [])

    def test_no_earnings_info_stays_quiet(self):
        self.assertEqual(self._warnings(None)["entry"], [])

    def test_full_run_reads_earnings_from_the_fundamentals_payload(self):
        # End to end: the fundamentals dimension carries the date; the
        # plan review must find it there without a second fetch.
        from src.tiered_analysis.settings import SizingSettings

        fundamentals = DimensionResult(
            dimension="fundamentals", kind=SourceKind.NUMERIC,
            payload={"next_earnings_date": "2026-07-30",
                     "days_until_earnings": 3},
        )
        outcome = run_tiered_analysis(
            "AAPL", market=Market.US,
            providers=[
                _StubProvider("technicals", _technicals_dim_with_levels()),
                _StubProvider("fundamentals", fundamentals),
            ],
            quick_judge=_FakeQuickJudge(),
            sizing_settings=SizingSettings(),
        )
        entry_warnings = outcome.plan_warnings["entry"]
        self.assertTrue(
            any(w["id"] == "earnings_soon" for w in entry_warnings)
        )


class TestMacroEventGateWarning(unittest.TestCase):
    """The macro-event gate (2026-08-04): a rate decision / CPI print /
    jobs report inside the hold window is market-wide gap risk — the
    macro mirror of the earnings gate, reusing the same warning window."""

    TECH = _tech_payload()
    LEVELS = SniperLevels(entry=96.0, stop_loss=90.0, take_profit=108.0)

    @staticmethod
    def _macro_dim(events):
        from src.tiered_analysis.providers.technicals import make_metric

        return DimensionResult(
            dimension="macro_econ", kind=SourceKind.NUMERIC,
            payload={"events": {
                key: make_metric(key, "x", value)
                for key, value in events.items()
            }},
        )

    def test_soonest_event_in_window_is_picked(self):
        from datetime import date

        from src.tiered_analysis.plan_review import macro_event_from_dimensions

        event = macro_event_from_dimensions(
            [self._macro_dim({
                "next_rate_decision_date": "2026-07-29",
                "next_cpi_release_date": "2026-07-10",
                "next_jobs_release_date": "2026-08-07",
            })],
            today=date(2026, 7, 7),
        )
        self.assertEqual(event, {
            "event": "inflation_data",
            "next_date": "2026-07-10",
            "days_until": 3,
        })

    def test_all_events_outside_window_stay_quiet(self):
        from datetime import date

        from src.tiered_analysis.plan_review import macro_event_from_dimensions

        event = macro_event_from_dimensions(
            [self._macro_dim({
                "next_rate_decision_date": "2026-07-29",
                "next_cpi_release_date": "2026-08-12",
            })],
            today=date(2026, 7, 7),
        )
        self.assertIsNone(event)

    def test_no_macro_dimension_stays_quiet(self):
        from src.tiered_analysis.plan_review import macro_event_from_dimensions

        self.assertIsNone(macro_event_from_dimensions([]))

    def test_macro_event_lands_a_structured_entry_warning(self):
        from src.tiered_analysis.plan_review import build_plan_warnings

        warnings = build_plan_warnings(
            self.TECH, self.LEVELS,
            shares=None, risk_amount=None, reward_goal=2.0,
            macro_event={
                "event": "rate_decision",
                "next_date": "2026-07-29",
                "days_until": 2,
            },
        )
        self.assertEqual(warnings["entry"], [{
            "id": "macro_event_soon",
            "values": {
                "event": "rate_decision",
                "next_date": "2026-07-29",
                "days_until": 2,
                "warning_days": 7,
            },
        }])


if __name__ == "__main__":
    unittest.main()


class TestStalenessGate(unittest.TestCase):
    """The staleness gate (owner decisions 2026-08-08): stop before any
    LLM stage when the bars predate the newest completed session."""

    def _run(self, stop_reason, staleness_gate=True, depth=1):
        calls = {"judge": 0}
        judge = _FakeQuickJudge()

        with patch(
            "src.tiered_analysis.integration.staleness_stop_reason",
            lambda bars_up_to, market, now=None: stop_reason,
        ):
            outcome = run_tiered_analysis(
                "AAPL",
                market=Market.US,
                providers=[_StubProvider("technicals", _dim("technicals"))],
                quick_judge=judge,
                earnings_lookup=_no_earnings,
                staleness_gate=staleness_gate,
                depth=depth,
            )
        calls["judge"] = len(judge.calls)
        return outcome, calls

    def test_stale_bars_stop_before_any_llm(self):
        outcome, calls = self._run("stale bars: 2026-08-04 < 2026-08-05")
        self.assertEqual(outcome.outlook, Outlook.STOPPED)
        self.assertEqual(outcome.action, Action.UNKNOWN)
        self.assertEqual(calls, {"judge": 0})
        # The data cards survive; no outlook, no tier-2 section.
        self.assertTrue(outcome.report.dimensions)
        self.assertEqual(outcome.report.direction, Direction.UNKNOWN)
        self.assertNotIn(2, outcome.state.reports)

    def test_stopped_run_reports_no_stop_text_in_warnings(self):
        # The outlook says everything (owner decision): the reason lives
        # in logs only, never in the user-facing report warnings.
        outcome, _ = self._run("stale bars: vendor lagging")
        self.assertEqual(outcome.report.warnings, [])

    def test_fresh_bars_run_normally(self):
        outcome, calls = self._run(None)
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(calls["judge"], 1)

    def test_gate_defaults_off_for_injected_providers(self):
        # Same convention as cross-field enrichment: canned payloads mean
        # a test harness — the gate must not judge their as-of dates.
        outcome, calls = self._run("stale", staleness_gate=None)
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(calls["judge"], 1)


class TestStalenessGateReadsTheBarDate(unittest.TestCase):
    """The payload -> gate handoff, with NOTHING mocked out.

    The tests above patch ``staleness_stop_reason``, so they never
    exercise the step that pulls the bar date out of the technicals
    payload. That gap hid a real bug (2026-08-08): ``technicals_as_of``
    read the date STRING with the numeric reader, always got None, and
    the gate stopped every run for "bars carry no usable date" — with
    perfectly fresh data. These tests run the real gate.
    """

    def _dim_dated(self, as_of):
        payload = _tech_payload()
        payload["meta"] = {"as_of": _env(as_of)}
        return DimensionResult(
            dimension="technicals",
            kind=SourceKind.NUMERIC,
            payload=payload,
        )

    def _run(self, as_of):
        judge = _FakeQuickJudge()
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals", self._dim_dated(as_of))],
            quick_judge=judge,
            earnings_lookup=_no_earnings,
            staleness_gate=True,
        )
        return outcome, {"judge": len(judge.calls)}

    def test_reads_the_date_string_out_of_the_payload(self):
        self.assertEqual(
            technicals_as_of([self._dim_dated("2026-08-07")]), "2026-08-07"
        )

    def test_fresh_bars_reach_the_llm_stages(self):
        # The date the gate itself considers current, so this stays true
        # on any day the suite runs.
        fresh = expected_bar_date("us")
        outcome, calls = self._run(fresh.isoformat())
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(calls["judge"], 1)

    def test_genuinely_stale_bars_still_stop(self):
        stale = expected_bar_date("us") - timedelta(days=30)
        outcome, calls = self._run(stale.isoformat())
        self.assertEqual(outcome.outlook, Outlook.STOPPED)
        self.assertEqual(calls["judge"], 0)

    def test_missing_date_stops(self):
        outcome, calls = self._run(None)
        self.assertEqual(outcome.outlook, Outlook.STOPPED)
        self.assertEqual(calls["judge"], 0)


class TestHoldWeeks(unittest.TestCase):
    """The max hold time (owner decisions 2026-08-08) threads through."""

    def _run(self, **kwargs):
        return run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals", _dim("technicals"))],
            quick_judge=_FakeQuickJudge(),
            earnings_lookup=_no_earnings,
            **kwargs,
        )

    def test_default_is_two_weeks(self):
        outcome = self._run()
        self.assertEqual(outcome.hold_weeks, 2)
        self.assertEqual(outcome.final_report.hold_weeks, 2)

    def test_chosen_hold_weeks_lands_on_outcome_and_report(self):
        outcome = self._run(hold_weeks=4)
        self.assertEqual(outcome.hold_weeks, 4)
        self.assertEqual(outcome.final_report.hold_weeks, 4)

    def test_invalid_hold_weeks_rejected(self):
        with self.assertRaises(ValueError):
            self._run(hold_weeks=5)
