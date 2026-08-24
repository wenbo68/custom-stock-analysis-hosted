# -*- coding: utf-8 -*-
"""Offline tests for the US positioning provider (v2 envelopes).

Pure-function tests (short interest, ownership, insider window,
options board, implied report-day move) plus the provider's explicit
degradation contract: the payload always ships with all five groups —
a failed block publishes blank envelopes (value None) with warnings and
per-field notes, and even every block failing yields the all-blank
payload, never payload=None and never a raise.
"""
from __future__ import annotations

import unittest
from datetime import date

from src.tiered_analysis.providers.base import Market, SourceKind
from src.tiered_analysis.providers.positioning import (
    INSIDER_WINDOW_DAYS,
    PositioningUSProvider,
    implied_report_move,
    insider_metrics,
    options_metrics,
    ownership_metrics,
    short_interest_metrics,
)
from src.tiered_analysis.providers.technicals import metric_value

# 2026-07-01 as unix seconds (UTC midnight) for the as_of conversion.
_SHORT_INTEREST_EPOCH = 1782864000

_INFO = {
    "sharesShort": 50_000_000,
    "sharesShortPriorMonth": 40_000_000,
    "shortPercentOfFloat": 0.031,
    "shortRatio": 1.8,
    "floatShares": 1_600_000_000,
    "heldPercentInstitutions": 0.6155,
    "heldPercentInsiders": 0.021,
    "dateShortInterest": _SHORT_INTEREST_EPOCH,
}

_HOLDERS = [
    {"pctHeld": 0.05, "date_reported": "2026-03-31"},
    {"pctHeld": 0.04, "date_reported": "2026-03-31"},
    {"pctHeld": 0.03, "date_reported": "2025-12-31"},
]

_TODAY = date(2026, 7, 24)

_INSIDER_ROWS = [
    {"date": "2026-07-01", "text": "Purchase at price 100.00 per share.",
     "shares": 1000, "value": 100_000},
    {"date": "2026-06-15", "text": "Sale at price 110.00 per share.",
     "shares": 400, "value": 44_000},
    # Not an open-market trade: must be ignored.
    {"date": "2026-06-20", "text": "Stock Award (Grant)", "shares": 9999,
     "value": None},
    # Outside the six-month window: must be ignored.
    {"date": "2025-12-01", "text": "Sale at price 90.00 per share.",
     "shares": 5000, "value": 450_000},
    # Unparseable date: must be skipped, not crash.
    {"date": None, "text": "Purchase at price 95.00 per share.",
     "shares": 10, "value": 950},
]

_BOARD = {
    "current_price": 100.0,
    "iv30": 26.08,
    "chains": [
        {"expiration": "2026-08-21", "call_oi": 1000.0, "put_oi": 800.0,
         "call_volume": 200.0, "put_volume": 300.0,
         "atm_strike": 100.0, "atm_call_bid": 3.0, "atm_call_ask": 3.4,
         "atm_put_bid": 2.8, "atm_put_ask": 3.2},
        {"expiration": "2026-09-18", "call_oi": 500.0, "put_oi": 580.0,
         "call_volume": 100.0, "put_volume": 60.0,
         "atm_strike": 100.0, "atm_call_bid": 4.0, "atm_call_ask": 4.6,
         "atm_put_bid": 3.8, "atm_put_ask": 4.4},
    ],
}


class ShortInterestMetricsTest(unittest.TestCase):
    def test_fractions_become_percentages_and_epochs_become_dates(self):
        metrics = short_interest_metrics(_INFO)
        self.assertAlmostEqual(metrics["short_pct_of_float"], 3.1)
        self.assertFalse(metrics["short_pct_computed"])
        self.assertEqual(metrics["days_to_cover"], 1.8)
        self.assertAlmostEqual(metrics["change_vs_prior_month_pct"], 25.0)
        self.assertEqual(metrics["as_of"], "2026-07-01")

    def test_short_pct_falls_back_to_shares_over_float(self):
        info = dict(_INFO)
        del info["shortPercentOfFloat"]
        metrics = short_interest_metrics(info)
        self.assertAlmostEqual(metrics["short_pct_of_float"], 3.125)
        # The fallback is a computation and must carry receipt ingredients.
        self.assertTrue(metrics["short_pct_computed"])
        self.assertEqual(metrics["shares_short"], 50_000_000)
        self.assertEqual(metrics["float_shares"], 1_600_000_000)

    def test_missing_prior_month_yields_no_change(self):
        info = {k: v for k, v in _INFO.items() if k != "sharesShortPriorMonth"}
        self.assertIsNone(short_interest_metrics(info)["change_vs_prior_month_pct"])

    def test_nan_values_are_treated_as_missing(self):
        metrics = short_interest_metrics({"shortRatio": float("nan")})
        self.assertIsNone(metrics["days_to_cover"])


class OwnershipMetricsTest(unittest.TestCase):
    def test_percentages_top10_and_latest_report_date(self):
        metrics = ownership_metrics(_INFO, _HOLDERS)
        self.assertAlmostEqual(metrics["institutional_pct"], 61.55)
        self.assertAlmostEqual(metrics["insider_pct"], 2.1)
        self.assertAlmostEqual(metrics["top10_institutions_pct"], 12.0)
        self.assertEqual(metrics["float_shares"], 1_600_000_000)
        self.assertEqual(metrics["as_of"], "2026-03-31")

    def test_only_the_ten_largest_holders_count(self):
        holders = [{"pctHeld": 0.01}] * 15
        metrics = ownership_metrics({}, holders)
        self.assertAlmostEqual(metrics["top10_institutions_pct"], 10.0)

    def test_older_yfinance_percent_out_key_is_accepted(self):
        metrics = ownership_metrics({}, [{"% Out": 0.07}])
        self.assertAlmostEqual(metrics["top10_institutions_pct"], 7.0)

    def test_no_holders_leaves_concentration_and_date_none(self):
        for holders in (None, []):
            metrics = ownership_metrics(_INFO, holders)
            self.assertIsNone(metrics["top10_institutions_pct"])
            self.assertIsNone(metrics["as_of"])


class InsiderMetricsTest(unittest.TestCase):
    def test_open_market_trades_inside_the_window_are_netted(self):
        metrics = insider_metrics(_INSIDER_ROWS, _TODAY)
        self.assertEqual(metrics["buy_count"], 1)
        self.assertEqual(metrics["sell_count"], 1)
        self.assertEqual(metrics["buy_value_usd"], 100_000.0)
        self.assertEqual(metrics["sell_value_usd"], 44_000.0)
        self.assertEqual(metrics["net_value_usd"], 56_000.0)

    def test_the_window_edge_is_inclusive(self):
        edge = (_TODAY - date.resolution * INSIDER_WINDOW_DAYS).isoformat()
        rows = [{"date": edge, "text": "Purchase at price 1.00 per share.",
                 "shares": 5, "value": 5}]
        self.assertEqual(insider_metrics(rows, _TODAY)["buy_count"], 1)

    def test_no_trades_is_zeros_not_blanks(self):
        metrics = insider_metrics([], _TODAY)
        self.assertEqual(metrics["buy_count"], 0)
        self.assertEqual(metrics["sell_count"], 0)
        self.assertEqual(metrics["net_value_usd"], 0.0)


class OptionsMetricsTest(unittest.TestCase):
    def test_ratios_are_summed_over_the_nearest_expirations(self):
        metrics, notes = options_metrics(_BOARD)
        self.assertAlmostEqual(metrics["put_call_oi_ratio"], 1380.0 / 1500.0)
        self.assertAlmostEqual(metrics["put_call_volume_ratio"], 1.2)
        self.assertEqual(metrics["total_open_interest"], 2880.0)
        self.assertEqual(metrics["implied_vol_pct"], 26.08)
        self.assertEqual(metrics["bets_through"], "2026-09-18")
        self.assertEqual(notes, [])

    def test_only_the_nearest_expirations_feed_the_sums(self):
        chains = [
            {"expiration": f"2026-0{n}-15", "call_oi": 10.0, "put_oi": 10.0}
            for n in range(1, 7)  # six expirations; only the first 4 count
        ]
        metrics, _warnings = options_metrics({"chains": chains, "iv30": 20.0})
        self.assertEqual(metrics["total_open_interest"], 80.0)
        self.assertEqual(metrics["bets_through"], "2026-04-15")

    def test_zero_call_side_yields_none_with_warnings_not_a_crash(self):
        board = {"chains": [
            {"expiration": "2026-08-21", "call_oi": 0, "put_oi": 10,
             "call_volume": 0, "put_volume": 5},
        ]}
        metrics, notes = options_metrics(board)
        self.assertIsNone(metrics["put_call_oi_ratio"])
        self.assertIsNone(metrics["put_call_volume_ratio"])
        self.assertIsNone(metrics["total_open_interest"])
        self.assertEqual(len(notes), 3)  # OI + volume + missing iv30

    def test_zero_put_side_is_blank_not_a_misleading_zero(self):
        # Yahoo intraday chains often carry no open interest; a zero put
        # side must never surface as "puts to calls (held) 0" (owner
        # report 2026-07-24 — a real NVDA run showed exactly that).
        board = {"iv30": 20.0, "chains": [
            {"expiration": "2026-08-21", "call_oi": 25, "put_oi": 0,
             "call_volume": 1000, "put_volume": 550},
        ]}
        metrics, notes = options_metrics(board)
        self.assertIsNone(metrics["put_call_oi_ratio"])
        self.assertIsNone(metrics["total_open_interest"])
        self.assertAlmostEqual(metrics["put_call_volume_ratio"], 0.55)
        self.assertTrue(any("open interest" in message for message, _ in notes))
        self.assertFalse(any("volume missing" in message for message, _ in notes))
        # Each note names the payload fields it blanks.
        oi_note = next(paths for message, paths in notes
                       if "open interest" in message)
        self.assertIn("options.put_call_oi_ratio", oi_note)
        self.assertIn("options.total_open_interest", oi_note)

    def test_missing_or_zero_iv30_is_blank_with_a_warning(self):
        for iv30 in (None, 0.0):
            board = {"iv30": iv30, "chains": _BOARD["chains"]}
            metrics, notes = options_metrics(board)
            self.assertIsNone(metrics["implied_vol_pct"])
            self.assertTrue(
                any("implied volatility" in message for message, _ in notes)
            )


class ImpliedReportMoveTest(unittest.TestCase):
    def test_straddle_on_the_first_post_report_expiration(self):
        move, warning = implied_report_move(_BOARD, "2026-08-10", _TODAY)
        self.assertIsNone(warning)
        # 2026-08-21 chain: call mid 3.2 + put mid 3.0 = 6.2 on price 100.
        self.assertAlmostEqual(move["move_pct"], 6.2)
        self.assertEqual(move["expiration"], "2026-08-21")
        self.assertAlmostEqual(move["atm_call_price"], 3.2)
        self.assertAlmostEqual(move["atm_put_price"], 3.0)

    def test_report_date_on_the_expiration_day_uses_that_expiration(self):
        move, warning = implied_report_move(_BOARD, "2026-08-21", date(2026, 8, 10))
        self.assertIsNone(warning)
        self.assertEqual(move["expiration"], "2026-08-21")

    def test_unknown_report_date_is_a_reasoned_blank(self):
        move, warning = implied_report_move(_BOARD, None, _TODAY)
        self.assertIsNone(move)
        self.assertIn("report date unknown", warning)

    def test_a_far_away_report_is_a_reasoned_blank_not_a_drift_number(self):
        # A straddle months out prices ordinary drift, not the report
        # jump (a live AAPL run read ±12.4% that way) — never publish it.
        move, warning = implied_report_move(_BOARD, "2026-09-01", _TODAY)
        self.assertIsNone(move)
        self.assertIn("more than", warning)
        # The note carries the real countdown and both dates (2026-08-23)
        # so the report page can show the number with its receipt.
        self.assertIn("39 days away", warning)
        self.assertIn("report 2026-09-01, today 2026-07-24", warning)

    def test_no_expiration_after_the_report_is_a_reasoned_blank(self):
        board = {
            "current_price": 100.0,
            "chains": [{"expiration": "2026-07-31", "call_oi": 1.0}],
        }
        move, warning = implied_report_move(board, "2026-08-05", _TODAY)
        self.assertIsNone(move)
        self.assertIn("no fetched option expiration", warning)

    def test_missing_price_or_quotes_is_a_reasoned_blank(self):
        no_price = {**_BOARD, "current_price": None}
        move, warning = implied_report_move(no_price, "2026-08-10", _TODAY)
        self.assertIsNone(move)
        self.assertIn("no stock price", warning)

        no_quotes = {
            "current_price": 100.0,
            "chains": [{"expiration": "2026-08-14", "call_oi": 1.0}],
        }
        move, warning = implied_report_move(no_quotes, "2026-08-10", _TODAY)
        self.assertIsNone(move)
        self.assertIn("at-the-money", warning)


def _provider(**overrides):
    loaders = {
        "info_loader": lambda symbol: _INFO,
        "holders_loader": lambda symbol: _HOLDERS,
        "insider_loader": lambda symbol: _INSIDER_ROWS,
        "options_loader": lambda symbol: _BOARD,
        "earnings_lookup": lambda symbol: "2026-08-10",
        "today": lambda: _TODAY,
    }
    loaders.update(overrides)
    return PositioningUSProvider(**loaders)


def _boom(symbol):
    raise RuntimeError("boom")


_GROUPS = ["insider_activity_6m", "meta", "options", "ownership", "short_interest"]


class ProviderTest(unittest.TestCase):
    def test_supports_us_only(self):
        provider = _provider()
        self.assertTrue(provider.supports(Market.US))
        for market in (Market.CN, Market.HK, Market.JP, Market.UNKNOWN):
            self.assertFalse(provider.supports(market))

    def test_all_blocks_up_carries_all_groups_envelopes_and_citations(self):
        result = _provider().collect("AAPL")
        self.assertEqual(result.dimension, "positioning")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        self.assertTrue(result.is_actionable)
        self.assertEqual(sorted(result.payload), _GROUPS)
        self.assertEqual(len(result.citations), 3)
        self.assertEqual(result.warnings, [])
        # Envelope contract: {name, explanation, interpretation, value}.
        node = result.payload["short_interest"]["short_pct_of_float"]
        self.assertEqual(node["name"], "shorted shares to float")
        self.assertAlmostEqual(node["value"], 3.1)
        self.assertIn("interpretation", node)
        # Meta dates from all three blocks. Every one is a date its own
        # SOURCE publishes — the retired options_fetched_at recorded the
        # run's own clock instead, which the run gate made redundant
        # (owner decision 2026-08-08). Exact set, so it cannot creep back.
        meta = result.payload["meta"]
        self.assertEqual(metric_value(meta["ownership_as_of"]), "2026-03-31")
        self.assertEqual(metric_value(meta["short_interest_as_of"]), "2026-07-01")
        self.assertEqual(metric_value(meta["options_bets_through"]), "2026-09-18")
        self.assertEqual(
            sorted(meta),
            ["options_bets_through", "ownership_as_of", "short_interest_as_of"],
        )
        # The implied report-day move landed with its receipt.
        options = result.payload["options"]
        self.assertAlmostEqual(metric_value(options["implied_report_move_pct"]), 6.2)
        self.assertIn("options.implied_report_move_pct", result.formulas)
        self.assertIn("insider_activity_6m.net_value_usd", result.formulas)
        self.assertIn("options.put_call_oi_ratio", result.formulas)

    def test_unsourced_truth_fields_are_dropped(self):
        # Dropped entirely (owner decision 2026-08-05): permanently blank
        # rows carry no information. Old stored runs still render theirs
        # from their saved payloads.
        payload = _provider().collect("AAPL").payload
        self.assertNotIn("institutional_diff_q_pp", payload["ownership"])
        self.assertNotIn("implied_vol_rank_1y", payload["options"])

    def test_one_failing_block_blanks_its_envelopes_with_notes(self):
        result = _provider(options_loader=_boom).collect("AAPL")
        self.assertTrue(result.is_actionable)  # payload still ships
        # The group stays present; every field is a blank envelope.
        options = result.payload["options"]
        self.assertTrue(all(metric_value(node) is None for node in options.values()))
        self.assertIsNone(metric_value(result.payload["meta"]["options_bets_through"]))
        self.assertTrue(any("options chain failed" in w for w in result.warnings))
        # The healthy blocks still carry their values.
        self.assertAlmostEqual(
            metric_value(result.payload["short_interest"]["short_pct_of_float"]),
            3.1,
        )

    def test_no_listed_options_is_an_explicit_warning(self):
        result = _provider(
            options_loader=lambda symbol: {"chains": []}
        ).collect("AAPL")
        options = result.payload["options"]
        self.assertTrue(all(metric_value(node) is None for node in options.values()))
        self.assertTrue(any("no listed options" in w for w in result.warnings))

    def test_info_failure_takes_out_both_summary_blocks(self):
        result = _provider(info_loader=_boom).collect("AAPL")
        short = result.payload["short_interest"]
        self.assertTrue(all(metric_value(node) is None for node in short.values()))
        ownership = result.payload["ownership"]
        self.assertTrue(
            all(metric_value(node) is None for node in ownership.values())
        )
        # One warning for the shared fetch, not one per block.
        self.assertEqual(
            sum("Yahoo summary failed" in w for w in result.warnings), 1
        )

    def test_empty_info_is_surfaced_never_a_silent_blank(self):
        result = _provider(
            info_loader=lambda symbol: {},
            holders_loader=lambda symbol: [],
        ).collect("AAPL")
        self.assertTrue(
            any("no short-interest fields" in w for w in result.warnings)
        )
        self.assertTrue(any("no ownership fields" in w for w in result.warnings))

    def test_empty_insider_table_is_blank_with_a_warning_not_zeros(self):
        # An empty table could be a Yahoo outage — never claim "0 buys,
        # 0 sells" from it (owner rule 2026-07-24). Zeros stay real only
        # when computed from actual rows.
        result = _provider(insider_loader=lambda symbol: []).collect("AAPL")
        self.assertTrue(result.is_actionable)  # payload still ships
        insiders = result.payload["insider_activity_6m"]
        self.assertTrue(all(metric_value(node) is None for node in insiders.values()))
        self.assertTrue(
            any("no insider transaction rows" in w for w in result.warnings)
        )

    def test_holders_failure_only_blanks_concentration_and_date(self):
        result = _provider(holders_loader=_boom).collect("AAPL")
        ownership = result.payload["ownership"]
        self.assertIsNone(metric_value(ownership["top10_institutions_pct"]))
        # The summary-fed ownership fields are untouched.
        self.assertAlmostEqual(metric_value(ownership["institutional_pct"]), 61.55)
        self.assertIsNone(metric_value(result.payload["meta"]["ownership_as_of"]))
        self.assertTrue(
            any("institutional holders failed" in w for w in result.warnings)
        )

    def test_earnings_lookup_failure_only_blanks_the_report_move(self):
        result = _provider(earnings_lookup=_boom).collect("AAPL")
        self.assertIsNone(
            metric_value(result.payload["options"]["implied_report_move_pct"])
        )
        # The rest of the options block is untouched.
        self.assertIsNotNone(
            metric_value(result.payload["options"]["put_call_oi_ratio"])
        )
        self.assertTrue(
            any("earnings date lookup failed" in w for w in result.warnings)
        )

    def test_every_warning_lands_on_the_fields_it_blanks(self):
        # The report page shows each note beside its own field — a note
        # the map misses falls back to the card-level list.
        result = _provider(
            info_loader=_boom,
            insider_loader=lambda symbol: [],
            earnings_lookup=lambda symbol: "2026-12-01",  # >21 days out
        ).collect("AAPL")
        notes = result.field_notes
        self.assertIsNotNone(notes)
        # The far-away report note sits on the implied-move field only.
        self.assertTrue(
            any("more than" in note
                for note in notes["options.implied_report_move_pct"])
        )
        # The shared Yahoo fetch failure sits on both summary blocks.
        for path in ("short_interest.short_pct_of_float",
                     "ownership.institutional_pct",
                     "meta.short_interest_as_of"):
            self.assertTrue(
                any("Yahoo summary failed" in note for note in notes[path])
            )
        # The empty insider table note sits on all three insider fields.
        for key in ("buy_count", "sell_count", "net_value_usd"):
            self.assertTrue(
                any("no insider transaction rows" in note
                    for note in notes[f"insider_activity_6m.{key}"])
            )
        # Every card warning is covered by at least one field note — the
        # card-level fallback list should be empty on this run.
        covered = {note for field in notes.values() for note in field}
        self.assertEqual([w for w in result.warnings if w not in covered], [])

    def test_everything_failing_ships_all_blank_payload_not_a_raise(self):
        result = _provider(
            info_loader=_boom, insider_loader=_boom, options_loader=_boom
        ).collect("AAPL")
        # The payload still ships: all five groups, every field a blank
        # envelope — degradation lives on the fields, never card-level.
        self.assertEqual(sorted(result.payload), _GROUPS)
        for group_name, group in result.payload.items():
            for key, node in group.items():
                self.assertIsNone(
                    metric_value(node), f"{group_name}.{key} not blank"
                )
        # An all-blank NUMERIC payload is still present, so downstream
        # numeric consumers gate per-field, not on the card.
        self.assertTrue(result.is_actionable)
        # Every block's failure lands as a warning with per-field notes.
        for message in (
            "Yahoo summary failed",
            "insider transactions failed",
            "options chain failed",
        ):
            self.assertTrue(any(message in w for w in result.warnings), message)
        self.assertTrue(
            any("options chain failed" in note
                for note in result.field_notes["options.put_call_oi_ratio"])
        )


if __name__ == "__main__":
    unittest.main()
