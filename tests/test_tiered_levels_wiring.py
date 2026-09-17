# -*- coding: utf-8 -*-
"""Offline tests: formula-only levels wired into the tiered run.

Outlook redesign (2026-07-20): the AI level adjuster is retired — levels
are formula bases everywhere. run_tiered_analysis must set the
deterministic bases as the plan levels (the judge never proposes
prices), attach the levels_detail audit trail (adjusted always None),
and surface level warnings on the report. v2 (2026-07-27): the anchors
come from the envelope payload (daily.sma_50 / daily.sma_200 /
levels.support_1).
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.earnings import EarningsInfo
from src.tiered_analysis.integration import run_tiered_analysis
from src.tiered_analysis.providers.base import (
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.providers.technicals import (
    Bar,
    TechnicalsProvider,
    read_metric,
)


class _StubProvider(DimensionProvider):
    kind = SourceKind.NUMERIC

    def __init__(self, result):
        self.dimension = result.dimension
        self._result = result

    def supports(self, market):
        return True

    def collect(self, symbol):
        return self._result


def _env(value):
    return {"name": "n", "explanation": "e", "value": value}


def _payload(close=100.0, sma_50=96.0, sma_200=90.0, support_1=94.0,
             atr_14=3.0):
    return {
        "price": {"close": _env(close), "high_1y": _env(None)},
        "daily": {"sma_50": _env(sma_50), "sma_200": _env(sma_200)},
        "volatility": {"atr_14": _env(atr_14)},
        "levels": {"support_1": _env(support_1),
                   "resistance_1": _env(None)},
    }


def _technicals_dim():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        payload=_payload(),
    )


class _FakeQuickJudge:
    """Canned BUY verdict — levels wiring is what's under test here."""

    def run(self, symbol, dimensions, hold_weeks):
        from src.tiered_analysis.quick_judge import QuickResult, QuickVerdict
        from src.tiered_analysis.schema import Direction

        return QuickResult(
            verdict=QuickVerdict(
                direction=Direction.BUY,
                final_score=7.5,
                summary="buy the pullback",
            )
        )


def _run(providers=None):
    return run_tiered_analysis(
        "AAPL",
        market=Market.US,
        providers=providers or [_StubProvider(_technicals_dim())],
        quick_judge=_FakeQuickJudge(),
        earnings_lookup=lambda symbol, market: EarningsInfo(),
        # BUY verdicts whose plan trips a check (the downtrend test)
        # consult the plan-review AI; without this canned "no change
        # helps" reply the test made a REAL network LLM call whenever an
        # earlier test had already loaded .env (found via the run
        # transcript, 2026-08-25).
        plan_summarizer=lambda prompt: '{"adjustments": []}',
    )


class TestLevelsWiring(unittest.TestCase):
    def test_deterministic_bases_replace_dsa_sniper_levels(self):
        outcome = _run()
        levels = outcome.report.levels
        self.assertAlmostEqual(levels.entry, 96.0)  # not 210.0
        self.assertAlmostEqual(levels.stop_loss, 90.0)
        self.assertAlmostEqual(levels.take_profit, 108.0)

    def test_detail_present_with_no_adjustments_ever(self):
        outcome = _run()
        detail = outcome.report.levels_detail["levels"]["entry"]
        self.assertAlmostEqual(detail["base"], 96.0)
        self.assertIsNone(detail["adjusted"])
        self.assertIn("support candidates", detail["formula"])

    def test_missing_technicals_leaves_levels_empty_with_warning(self):
        other = DimensionResult(
            dimension="macro_econ", kind=SourceKind.NUMERIC,
            payload={"x": 1},
        )
        outcome = _run(providers=[_StubProvider(other)])
        self.assertIsNone(outcome.report.levels.entry)
        self.assertTrue(
            any("technicals unavailable" in w for w in outcome.report.warnings)
        )

    def test_downtrend_plan_still_issues_and_warns_in_the_report(self):
        downtrend = DimensionResult(
            dimension="technicals", kind=SourceKind.NUMERIC,
            payload=_payload(close=89.0),
        )
        outcome = _run(providers=[_StubProvider(downtrend)])
        self.assertIsNotNone(outcome.report.levels.entry)
        self.assertTrue(
            any("trend warning" in w for w in outcome.report.warnings)
        )


class TestLevelAnchorsPayload(unittest.TestCase):
    """The provider payload carries the anchors the level formulas read."""

    def _bars(self, count=70):
        bars = []
        for i in range(count):
            close = 100.0 + i * 0.1
            bars.append(Bar(high=close + 1, low=close - 1, close=close,
                            open=close, volume=1000, date=None))
        return bars

    def test_provider_payload_carries_the_level_anchors(self):
        provider = TechnicalsProvider(bars_loader=lambda symbol: self._bars(70))
        payload = provider.collect("AAPL").payload
        self.assertAlmostEqual(read_metric(payload, "price", "close"), 106.9)
        self.assertAlmostEqual(
            read_metric(payload, "daily", "sma_50"),
            round(sum(100.0 + i * 0.1 for i in range(20, 70)) / 50, 2),
        )
        self.assertIsNotNone(read_metric(payload, "volatility", "atr_14"))


if __name__ == "__main__":
    unittest.main()
