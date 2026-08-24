# -*- coding: utf-8 -*-
"""Cross-provider enrichment: sector comparison fields + the implied vs
realized report-move ratio (TODO.md truth 2026-08-04)."""
from __future__ import annotations

import unittest
from typing import List, Optional

from src.tiered_analysis.cross_fields import RATIO_KEY, enrich_cross_fields
from src.tiered_analysis.providers.base import (
    DimensionResult,
    SourceKind,
)
from src.tiered_analysis.providers.technicals import Bar, make_metric, metric_value


def _technicals(with_benchmark: bool = True) -> DimensionResult:
    payload = {
        "market": {
            "regime": make_metric("market trend", "x", "bullish"),
            "rs_1m": make_metric("1m return diff (stock vs market)", "x", 3.0),
            "rs_3m": make_metric("3m return diff (stock vs market)", "x", 6.0),
            "rs_label": make_metric(
                "stock performance relative to market", "x", "leader"
            ),
        },
        "price": {"close": make_metric("closing price", "x", 100.0)},
    }
    formulas = {
        "market.rs_1m": {
            "formula": "stock_return_1m − index_return_1m",
            "inputs": {"stock_return_1m": 8.0, "index_return_1m": 5.0},
        },
        "market.rs_3m": {
            "formula": "stock_return_3m − index_return_3m",
            "inputs": {"stock_return_3m": 12.0, "index_return_3m": 6.0},
        },
    } if with_benchmark else {}
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        payload=payload,
        formulas=formulas or None,
    )


def _fundamentals(
    sector: Optional[str] = "Technology",
    reaction_avg: Optional[float] = 4.0,
) -> DimensionResult:
    return DimensionResult(
        dimension="fundamentals",
        kind=SourceKind.NUMERIC,
        payload={
            "meta": {"sector": make_metric("sector", "x", sector)},
            "quarterly_report": {
                "reaction_avg_abs_pct": make_metric(
                    "4q avg report day price change magnitude", "x",
                    reaction_avg,
                ),
            },
        },
    )


def _positioning(implied: Optional[float] = 6.2) -> DimensionResult:
    return DimensionResult(
        dimension="positioning",
        kind=SourceKind.NUMERIC,
        payload={
            "options": {
                "implied_report_move_pct": make_metric(
                    "implied quarterly report day price change magnitude",
                    "x", implied,
                ),
            },
        },
    )


def _etf_loader(calls: Optional[List[str]] = None):
    # 64 closes: 10% gain over both the 1m (21-bar) and 3m (63-bar)
    # windows -> sector return 10.0 in both.
    closes = [100.0] * 43 + [110.0] * 21

    def load(symbol: str):
        if calls is not None:
            calls.append(symbol)
        return [Bar(high=c, low=c, close=c) for c in closes]

    return load


class TestSectorEnrichment(unittest.TestCase):
    def _run(self, technicals=None, fundamentals=None, loader=None):
        dims = [technicals or _technicals(),
                fundamentals or _fundamentals(),
                _positioning()]
        return enrich_cross_fields(dims, loader or _etf_loader())

    def test_success_computes_all_six_fields(self):
        calls: List[str] = []
        enriched = self._run(loader=_etf_loader(calls))
        market = enriched[0].payload["market"]
        self.assertEqual(calls, ["XLK"])  # one fetch, the mapped ETF
        self.assertAlmostEqual(metric_value(market["rs_sector_1m"]), 5.0)
        self.assertAlmostEqual(metric_value(market["rs_sector_3m"]), 4.0)
        self.assertEqual(
            metric_value(market["sector_vs_market_label"]), "leader"
        )
        self.assertAlmostEqual(metric_value(market["rs_stock_sector_1m"]), -2.0)
        self.assertAlmostEqual(metric_value(market["rs_stock_sector_3m"]), 2.0)
        self.assertEqual(
            metric_value(market["stock_vs_sector_label"]), "neutral"
        )

    def test_market_group_follows_truth_order(self):
        enriched = self._run()
        self.assertEqual(list(enriched[0].payload["market"].keys()), [
            "regime",
            "rs_sector_1m", "rs_sector_3m", "sector_vs_market_label",
            "rs_1m", "rs_3m", "rs_label",
            "rs_stock_sector_1m", "rs_stock_sector_3m",
            "stock_vs_sector_label",
        ])

    def test_receipts_cover_diffs_and_labels(self):
        formulas = self._run()[0].formulas
        rs = formulas["market.rs_sector_1m"]
        self.assertEqual(rs["formula"], "sector_return_1m − index_return_1m")
        self.assertAlmostEqual(rs["inputs"]["sector_return_1m"], 10.0)
        self.assertAlmostEqual(rs["inputs"]["index_return_1m"], 5.0)
        stock_sector = formulas["market.rs_stock_sector_1m"]
        self.assertEqual(
            stock_sector["formula"], "stock_return_1m − sector_return_1m"
        )
        label = formulas["market.stock_vs_sector_label"]
        self.assertEqual(
            [branch["label"] for branch in label["branches"]],
            ["leader", "laggard", "neutral"],
        )

    def test_envelope_explanations_name_the_sector_and_etf(self):
        market = self._run()[0].payload["market"]
        explanation = market["rs_sector_1m"]["explanation"]
        self.assertIn("Technology", explanation)
        self.assertIn("XLK", explanation)

    def test_unknown_sector_degrades_with_warning(self):
        enriched = self._run(fundamentals=_fundamentals(sector=None))
        market = enriched[0].payload["market"]
        self.assertIsNone(metric_value(market["rs_sector_1m"]))
        self.assertIsNone(metric_value(market["stock_vs_sector_label"]))
        self.assertTrue(
            any("sector unknown" in w for w in enriched[0].warnings)
        )

    def test_unmapped_sector_degrades_with_warning(self):
        enriched = self._run(
            fundamentals=_fundamentals(sector="Conglomerates")
        )
        self.assertIsNone(
            metric_value(enriched[0].payload["market"]["rs_sector_1m"])
        )
        self.assertTrue(
            any("no sector-ETF mapping" in w for w in enriched[0].warnings)
        )

    def test_missing_benchmark_returns_degrade_with_warning(self):
        enriched = self._run(technicals=_technicals(with_benchmark=False))
        self.assertIsNone(
            metric_value(enriched[0].payload["market"]["rs_sector_1m"])
        )
        self.assertTrue(
            any("benchmark returns" in w for w in enriched[0].warnings)
        )

    def test_etf_fetch_failure_degrades_with_warning(self):
        def boom(symbol: str):
            raise RuntimeError("etf source down")

        enriched = self._run(loader=boom)
        self.assertIsNone(
            metric_value(enriched[0].payload["market"]["rs_sector_1m"])
        )
        self.assertTrue(
            any("etf source down" in w for w in enriched[0].warnings)
        )

    def test_none_loader_passes_results_through_untouched(self):
        dims = [_technicals(), _fundamentals(), _positioning()]
        enriched = enrich_cross_fields(dims, None)
        self.assertIs(enriched[0], dims[0])
        self.assertIs(enriched[2], dims[2])

    def test_original_results_are_not_mutated(self):
        technicals = _technicals()
        self._run(technicals=technicals)
        self.assertNotIn("rs_sector_1m", technicals.payload["market"])
        self.assertNotIn("market.rs_sector_1m", technicals.formulas or {})


class TestReportMoveRatio(unittest.TestCase):
    def _run(self, positioning=None, fundamentals=None):
        dims = [_technicals(), fundamentals or _fundamentals(),
                positioning or _positioning()]
        return enrich_cross_fields(dims, _etf_loader())

    def test_ratio_divides_implied_by_realized(self):
        enriched = self._run()
        options = enriched[2].payload["options"]
        self.assertAlmostEqual(metric_value(options[RATIO_KEY]), 1.55)
        receipt = enriched[2].formulas[f"options.{RATIO_KEY}"]
        self.assertEqual(
            receipt["formula"],
            "implied_report_move_pct / reaction_avg_abs_pct",
        )
        self.assertAlmostEqual(
            receipt["inputs"]["implied_report_move_pct"], 6.2
        )
        self.assertAlmostEqual(receipt["inputs"]["reaction_avg_abs_pct"], 4.0)

    def test_ratio_is_last_in_the_options_group(self):
        enriched = self._run()
        self.assertEqual(
            list(enriched[2].payload["options"].keys())[-1], RATIO_KEY
        )

    def test_missing_implied_blanks_the_ratio_without_receipt(self):
        enriched = self._run(positioning=_positioning(implied=None))
        options = enriched[2].payload["options"]
        self.assertIsNone(metric_value(options[RATIO_KEY]))
        self.assertNotIn(f"options.{RATIO_KEY}", enriched[2].formulas or {})
        # The blank names its missing ingredient (2026-08-23) so the
        # report page can link straight to the blank ingredient row.
        notes = enriched[2].field_notes[f"options.{RATIO_KEY}"]
        self.assertTrue(
            any(note.startswith("implied report-day move missing")
                for note in notes)
        )
        self.assertFalse(
            any("realized 4q average" in note for note in notes)
        )

    def test_missing_realized_blanks_the_ratio(self):
        enriched = self._run(fundamentals=_fundamentals(reaction_avg=None))
        self.assertIsNone(
            metric_value(enriched[2].payload["options"][RATIO_KEY])
        )
        notes = enriched[2].field_notes[f"options.{RATIO_KEY}"]
        self.assertTrue(
            any(note.startswith("realized 4q average report-day move")
                for note in notes)
        )
        self.assertFalse(
            any(note.startswith("implied report-day move missing")
                for note in notes)
        )

    def test_both_ingredients_missing_notes_both(self):
        enriched = self._run(
            positioning=_positioning(implied=None),
            fundamentals=_fundamentals(reaction_avg=None),
        )
        notes = enriched[2].field_notes[f"options.{RATIO_KEY}"]
        self.assertEqual(len(notes), 2)

    def test_published_ratio_adds_no_ingredient_notes(self):
        enriched = self._run()
        notes = (enriched[2].field_notes or {}).get(
            f"options.{RATIO_KEY}", []
        )
        self.assertEqual(notes, [])

    def test_original_positioning_not_mutated(self):
        positioning = _positioning()
        self._run(positioning=positioning)
        self.assertNotIn(RATIO_KEY, positioning.payload["options"])


if __name__ == "__main__":
    unittest.main()
