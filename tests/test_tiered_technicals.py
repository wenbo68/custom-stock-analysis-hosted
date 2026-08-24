# -*- coding: utf-8 -*-
"""Offline deterministic tests for the tiered-analysis technicals provider.

No numpy/pandas/network: indicators are pure Python and bars are injected
fixtures. v2 (2026-07-27): grouped envelope payload — every metric ships
as {name, explanation, value}; composites swallow their ingredients;
coordinates stay.
"""
from __future__ import annotations

import math
import unittest

from src.tiered_analysis.providers.base import SourceKind
from src.tiered_analysis.providers.technicals import (
    Bar,
    TechnicalsProvider,
    combined_trend,
    compute_atr,
    compute_avg_volume,
    compute_sma,
    compute_swing_high,
    compute_wilder_rsi,
    compute_worst_day_pct_1y,
    find_pivots,
    is_envelope,
    ma_stack,
    macd_histogram_series,
    metric_value,
    momentum_label,
    nearest_resistance,
    nearest_support,
    pct_change,
    pivot_structure,
    read_label,
    read_metric,
    regime_read,
    relative_strength_label,
    relative_strength_pct,
    resample_weekly,
    typical_pullback_atr,
    wilder_averages,
    worst_day_detail,
)

# Classic 14-period RSI walkthrough dataset (Wilder's method, as popularized
# by the StockCharts RSI example): first RSI value is 70.46.
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
]


def _flat_bars(count: int, close: float = 100.0, spread: float = 2.0) -> list:
    """Bars with constant close and constant high-low range."""
    return [
        Bar(high=close + spread / 2, low=close - spread / 2, close=close)
        for _ in range(count)
    ]


def _trend_bars(closes: list) -> list:
    """Bars derived from a close series with a fixed 1% intraday range."""
    return [
        Bar(high=c * 1.005, low=c * 0.995, close=c)
        for c in closes
    ]


def _wave_bars(count: int, drift: float = 0.0015, amp: float = 0.03,
               period: float = 9.0, volume: float = 1e6) -> list:
    """A drifting sine wave: produces real pivots, dips and rallies."""
    bars = []
    price = 100.0
    for i in range(count):
        price *= 1 + drift
        c = price * (1 + amp * math.sin(i / period))
        bars.append(Bar(
            high=c * 1.01, low=c * 0.99, close=c, open=c * 0.995,
            volume=volume, date=None,
        ))
    return bars


def _full_provider(bars, index_bars=None):
    return TechnicalsProvider(
        bars_loader=lambda s: bars,
        index_bars_loader=(lambda: index_bars) if index_bars else None,
        benchmark_name="S&P 500",
    )


class TestIndicatorMath(unittest.TestCase):
    def test_sma_simple_average(self):
        self.assertEqual(compute_sma([1.0, 2.0, 3.0, 4.0], period=4), 2.5)

    def test_sma_uses_most_recent_window(self):
        self.assertEqual(compute_sma([10.0, 1.0, 2.0, 3.0], period=3), 2.0)

    def test_sma_insufficient_data_returns_none(self):
        self.assertIsNone(compute_sma([1.0, 2.0], period=3))

    def test_rsi_matches_wilder_textbook_value(self):
        rsi = compute_wilder_rsi(WILDER_CLOSES, period=14)
        self.assertAlmostEqual(rsi, 70.46, places=2)

    def test_rsi_all_gains_is_100(self):
        closes = [float(i) for i in range(1, 20)]
        self.assertEqual(compute_wilder_rsi(closes, period=14), 100.0)

    def test_atr_constant_range_equals_range(self):
        bars = _flat_bars(30, close=100.0, spread=2.0)
        self.assertAlmostEqual(compute_atr(bars, period=14), 2.0)

    def test_atr_includes_gap_in_true_range(self):
        # A gap up: true range must use previous close, not just high-low.
        bars = _flat_bars(20, close=100.0, spread=2.0)
        bars.append(Bar(high=111.0, low=110.0, close=110.5))
        self.assertGreater(compute_atr(bars, period=14), 2.0)

    def test_pct_change_five_days(self):
        closes = [100.0] * 6 + [110.0]
        # The close 5 bars before the last one is 100 → +10%.
        self.assertAlmostEqual(pct_change(closes, 5), 10.0)

    def test_pct_change_needs_enough_history(self):
        self.assertIsNone(pct_change([100.0, 101.0], 5))

    def test_macd_histogram_series_positive_in_uptrend(self):
        closes = [100.0 * (1.01 ** i) for i in range(80)]
        line, hist = macd_histogram_series(closes)
        self.assertGreater(line, 0.0)
        self.assertTrue(hist)

    def test_macd_histogram_series_insufficient_data(self):
        line, hist = macd_histogram_series([1.0] * 10)
        self.assertIsNone(line)
        self.assertEqual(hist, [])


class TestWeeklyResample(unittest.TestCase):
    def test_resample_by_iso_week_groups_dates(self):
        bars = [
            Bar(high=11, low=9, close=10, open=10, volume=100, date="2026-07-20"),
            Bar(high=13, low=10, close=12, open=10, volume=100, date="2026-07-21"),
            Bar(high=12, low=8, close=9, open=12, volume=100, date="2026-07-24"),
            Bar(high=15, low=14, close=15, open=14, volume=200, date="2026-07-27"),
        ]
        weekly = resample_weekly(bars)
        self.assertEqual(len(weekly), 2)
        first = weekly[0]
        self.assertEqual(first.high, 13)      # max of the week
        self.assertEqual(first.low, 8)        # min of the week
        self.assertEqual(first.close, 9)      # last close of the week
        self.assertEqual(first.open, 10)      # first open of the week
        self.assertEqual(first.volume, 300)   # summed
        self.assertEqual(first.date, "2026-07-24")
        self.assertEqual(weekly[1].close, 15)

    def test_resample_without_dates_chunks_from_the_recent_end(self):
        # 12 dateless bars → chunks of 5 counted from the newest bar, so
        # the most recent weekly bar is always a full five sessions: 2+5+5.
        weekly = resample_weekly(_flat_bars(12))
        self.assertEqual(len(weekly), 3)

    def test_resample_empty(self):
        self.assertEqual(resample_weekly([]), [])


class TestPivots(unittest.TestCase):
    def test_finds_the_turning_bars(self):
        closes = [10, 11, 12, 15, 12, 11, 10, 9, 8, 11, 12, 13, 14]
        bars = [Bar(high=c + 0.5, low=c - 0.5, close=c) for c in closes]
        highs, lows = find_pivots(bars, fringe=2)
        self.assertEqual([price for _, price in highs], [15.5])
        self.assertEqual([price for _, price in lows], [7.5])

    def test_flat_shelf_produces_no_pivot(self):
        highs, lows = find_pivots(_flat_bars(20), fringe=2)
        self.assertEqual(highs, [])
        self.assertEqual(lows, [])

    def test_structure_higher_highs_and_lows(self):
        self.assertEqual(
            pivot_structure([(1, 10.0), (5, 12.0)], [(3, 8.0), (7, 9.0)]),
            "higher highs and lows",
        )

    def test_structure_lower_highs_and_lows(self):
        self.assertEqual(
            pivot_structure([(1, 12.0), (5, 10.0)], [(3, 9.0), (7, 8.0)]),
            "lower highs and lows",
        )

    def test_structure_disagreement_is_sideways(self):
        self.assertEqual(
            pivot_structure([(1, 10.0), (5, 12.0)], [(3, 9.0), (7, 8.0)]),
            "sideways",
        )

    def test_structure_needs_two_of_each(self):
        self.assertIsNone(pivot_structure([(1, 10.0)], [(3, 8.0), (7, 9.0)]))

    def test_nearest_support_and_resistance(self):
        lows = [(1, 90.0), (5, 95.0), (9, 80.0)]
        highs = [(3, 110.0), (7, 105.0), (11, 120.0)]
        self.assertEqual(nearest_support(lows, 100.0), 95.0)
        self.assertEqual(nearest_resistance(highs, 100.0), 105.0)

    def test_no_pivot_beyond_the_close_is_honest_none(self):
        # A close at its extreme has no pivot beyond it.
        self.assertIsNone(nearest_support([(1, 105.0)], 100.0))
        self.assertIsNone(nearest_resistance([(1, 95.0)], 100.0))


class TestTypicalPullback(unittest.TestCase):
    def test_median_depth_of_completed_dips(self):
        # Two completed pullbacks: 110→104 (6) and 112→108 (4); ATR 2
        # → depths 3.0 and 2.0 ATR, median 2.5.
        highs = [(10, 110.0), (30, 112.0)]
        lows = [(20, 104.0), (40, 108.0)]
        self.assertAlmostEqual(
            typical_pullback_atr(highs, lows, atr=2.0), 2.5
        )

    def test_one_dip_is_not_a_norm(self):
        self.assertIsNone(
            typical_pullback_atr([(10, 110.0)], [(20, 104.0)], atr=2.0)
        )

    def test_no_atr_means_no_units(self):
        self.assertIsNone(
            typical_pullback_atr([(10, 110.0)], [(20, 104.0)], atr=None)
        )


class TestTrendComposites(unittest.TestCase):
    def test_ma_stack(self):
        self.assertEqual(ma_stack(100.0, 95.0, 90.0), "up")
        self.assertEqual(ma_stack(80.0, 85.0, 90.0), "down")
        self.assertEqual(ma_stack(100.0, 105.0, 90.0), "mixed")
        self.assertIsNone(ma_stack(100.0, None, 90.0))

    def test_combined_trend_requires_agreement(self):
        self.assertEqual(
            combined_trend("up", "higher highs and lows"), "bullish"
        )
        self.assertEqual(
            combined_trend("down", "lower highs and lows"), "bearish"
        )
        self.assertEqual(
            combined_trend("up", "lower highs and lows"), "neutral"
        )
        self.assertIsNone(combined_trend(None, "sideways"))

    def test_momentum_label_states(self):
        rising = [0.1, 0.2, 0.3, 0.4, 0.5]
        falling = list(reversed(rising))
        self.assertEqual(momentum_label(60.0, rising, 1.0), "strong")
        self.assertEqual(momentum_label(40.0, falling, -1.0), "weak")
        self.assertEqual(momentum_label(60.0, falling, 1.0), "fading")
        self.assertEqual(momentum_label(40.0, rising, -1.0), "basing")
        self.assertEqual(momentum_label(50.0, rising, 1.0), "neutral")
        self.assertIsNone(momentum_label(None, rising, 1.0))
        self.assertIsNone(momentum_label(60.0, [0.1], 1.0))


class TestBenchmarkFields(unittest.TestCase):
    def test_relative_strength_leader_and_laggard(self):
        stock = [100.0 * (1.002 ** i) for i in range(80)]
        index = [100.0] * 80
        rs = relative_strength_pct(stock, index, 63)
        self.assertGreater(rs, 0.0)
        self.assertEqual(relative_strength_label(1.0, 5.0), "leader")
        self.assertEqual(relative_strength_label(-1.0, -5.0), "laggard")
        self.assertEqual(relative_strength_label(1.0, -5.0), "neutral")
        self.assertIsNone(relative_strength_label(None, 5.0))

    def test_regime_bullish_above_200d_and_high_in_range(self):
        closes = [1000.0 * (1.001 ** i) for i in range(300)]
        regime = regime_read(closes)
        self.assertEqual(regime["label"], "bullish")
        self.assertTrue(regime["above_200d"])

    def test_regime_bearish_below_200d_and_low_in_range(self):
        closes = [1000.0 * (0.999 ** i) for i in range(300)]
        self.assertEqual(regime_read(closes)["label"], "bearish")

    def test_regime_short_history_is_none(self):
        self.assertIsNone(regime_read([1000.0] * 50))


class TestWorstDay(unittest.TestCase):
    def test_worst_day_picks_the_single_worst_return_as_a_percent(self):
        closes = [100.0]
        for _ in range(20):
            closes.append(closes[-1] * 1.01)
        closes.append(closes[-1] * 0.90)
        for _ in range(20):
            closes.append(closes[-1] * 1.01)
        self.assertAlmostEqual(compute_worst_day_pct_1y(closes), -10.0)

    def test_worst_day_needs_enough_history(self):
        self.assertIsNone(compute_worst_day_pct_1y([100.0] * 10))

    def test_worst_day_honours_its_window_instead_of_all_history(self):
        crash_then_calm = [100.0, 60.0]  # a -40% day, 400 bars back
        crash_then_calm += [60.0 * (1.001 ** i) for i in range(400)]
        self.assertAlmostEqual(
            compute_worst_day_pct_1y(crash_then_calm, lookback=300), 0.1,
            places=1,
        )
        self.assertAlmostEqual(
            compute_worst_day_pct_1y(crash_then_calm, lookback=500), -40.0
        )


class TestEnvelopeHelpers(unittest.TestCase):
    def test_envelope_detection_and_unwrap(self):
        env = {"name": "n", "explanation": "e", "value": 42.0}
        self.assertTrue(is_envelope(env))
        self.assertFalse(is_envelope({"value": 1}))
        self.assertFalse(is_envelope(42.0))
        self.assertEqual(metric_value(env), 42.0)
        self.assertEqual(metric_value(7), 7)

    def test_read_metric_and_label(self):
        payload = {
            "volatility": {
                "atr_14": {"name": "n", "explanation": "e", "value": 3.2},
                "atr_trend": {
                    "name": "n", "explanation": "e", "value": "stable",
                },
            },
        }
        self.assertEqual(read_metric(payload, "volatility", "atr_14"), 3.2)
        self.assertEqual(
            read_label(payload, "volatility", "atr_trend"), "stable"
        )
        self.assertIsNone(read_metric(payload, "volatility", "atr_trend"))
        self.assertIsNone(read_metric(payload, "missing", "atr_14"))
        self.assertIsNone(read_metric(None, "volatility", "atr_14"))


class TestTechnicalsProvider(unittest.TestCase):
    def test_provider_is_numeric(self):
        provider = TechnicalsProvider(bars_loader=lambda symbol: [])
        self.assertEqual(provider.kind, SourceKind.NUMERIC)
        self.assertEqual(provider.dimension, "technicals")

    def test_collect_with_a_year_of_bars_leaves_no_field_blank(self):
        bars = _wave_bars(320)
        index = [Bar(high=1, low=1, close=1000 * (1.0007 ** i))
                 for i in range(320)]
        result = _full_provider(bars, index).collect("AAPL")
        self.assertTrue(result.is_actionable)
        # Enough history + a wired benchmark: no field is missing data.
        self.assertFalse(
            any("indicators lacking history" in w for w in result.warnings)
        )
        self.assertEqual(len(result.citations), 1)

    def test_payload_has_exactly_the_v2_metrics(self):
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        leaves = {
            f"{group}.{key}"
            for group, metrics in payload.items()
            for key in metrics
        }
        self.assertEqual(leaves, {
            "meta.as_of", "meta.bars_daily", "meta.bars_weekly",
            "market.regime", "market.rs_1m", "market.rs_3m",
            "market.rs_label",
            "price.close", "price.chg_5d_pct", "price.high_1y",
            "price.low_1y", "price.range_pct_1y",
            "volume.avg_vol_60d", "volume.avg_vol_5d",
            "volume.vol_ratio_5_60",
            "volatility.atr_14", "volatility.atr_pct",
            "volatility.atr_trend", "volatility.typical_pullback_atr",
            "volatility.worst_day_pct_1y",
            "weekly.sma_10w", "weekly.stretch_10w_atr", "weekly.trend",
            "daily.sma_50", "daily.sma_200", "daily.stretch_50d_atr",
            "daily.stretch_200d_atr",
            "daily.trend", "daily.rsi_14", "daily.momentum",
            "levels.support_1", "levels.support_dist_atr",
            "levels.resistance_1", "levels.resistance_dist_atr",
        })

    def test_stretch_200d_and_level_distances_do_the_arithmetic(self):
        # The published values are computed from unrounded ingredients,
        # so recomputing from the rounded payload numbers can differ by
        # one rounding step — hence the small delta.
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        close = payload["price"]["close"]["value"]
        atr = payload["volatility"]["atr_14"]["value"]
        sma_200 = payload["daily"]["sma_200"]["value"]
        self.assertAlmostEqual(
            payload["daily"]["stretch_200d_atr"]["value"],
            (close - sma_200) / atr,
            delta=0.02,
        )
        support = payload["levels"]["support_1"]["value"]
        if support is not None:
            self.assertAlmostEqual(
                payload["levels"]["support_dist_atr"]["value"],
                (close - support) / atr,
                delta=0.02,
            )
        resistance = payload["levels"]["resistance_1"]["value"]
        if resistance is not None:
            self.assertAlmostEqual(
                payload["levels"]["resistance_dist_atr"]["value"],
                (resistance - close) / atr,
                delta=0.02,
            )

    def test_market_group_names_follow_the_truth_spec(self):
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        self.assertEqual(payload["market"]["regime"]["name"], "market trend")
        self.assertEqual(
            payload["market"]["rs_label"]["name"],
            "stock performance relative to market",
        )
        self.assertEqual(payload["meta"]["as_of"]["name"], "bars up to")

    def test_every_metric_is_an_envelope(self):
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        for group, metrics in payload.items():
            for key, node in metrics.items():
                self.assertTrue(is_envelope(node), f"{group}.{key}")
                self.assertTrue(node["name"], f"{group}.{key} has no name")
                self.assertTrue(
                    node["explanation"], f"{group}.{key} has no explanation"
                )

    def test_retired_fields_stay_retired(self):
        # The v2 payload publishes composites, not their ingredients, and
        # no code-computed verdict: no score, no EMA pair, no raw MACD
        # lines, no bias, no flat swing keys.
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        flat = set(payload.keys())
        for group in payload.values():
            flat.update(group.keys())
        for retired in ("score", "ema_12", "ema_26", "macd", "bias_20",
                        "sma_20", "sma_60", "swing_low_20", "swing_high_20",
                        "volatility_pct", "avg_volume_20", "high_52w"):
            self.assertNotIn(retired, flat)

    def test_neutral_trend_explains_its_disagreement(self):
        # Explanation style rule: an agreeing label gets method text only;
        # a neutral label must say which ingredient said what.
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        for scope in ("weekly", "daily"):
            trend = payload[scope]["trend"]
            if trend["value"] == "neutral":
                self.assertIn("disagree", trend["explanation"])
            elif trend["value"] in ("bullish", "bearish"):
                self.assertNotIn("disagree", trend["explanation"])

    def test_benchmark_unwired_degrades_to_none_with_warning(self):
        result = _full_provider(_wave_bars(320)).collect("AAPL")
        # Benchmark fields are optional: their absence never joins the
        # missing-history sweep.
        self.assertFalse(
            any("indicators lacking history" in w for w in result.warnings)
        )
        self.assertIsNone(result.payload["market"]["regime"]["value"])
        self.assertIsNone(
            result.payload["market"]["rs_3m"]["value"]
        )
        self.assertTrue(
            any("benchmark index not configured" in w for w in result.warnings)
        )

    def test_benchmark_failure_degrades_to_none_with_warning(self):
        def _boom():
            raise RuntimeError("index source down")

        provider = TechnicalsProvider(
            bars_loader=lambda s: _wave_bars(320), index_bars_loader=_boom,
        )
        result = provider.collect("AAPL")
        self.assertIsNone(result.payload["market"]["regime"]["value"])
        # The stock's own fields are untouched by a benchmark outage.
        self.assertIsNotNone(result.payload["volatility"]["atr_14"]["value"])
        self.assertTrue(
            any("index source down" in w for w in result.warnings)
        )

    def test_benchmark_wired_produces_regime_and_rs(self):
        bars = _wave_bars(320)
        index = [Bar(high=1, low=1, close=1000 * (1.0007 ** i))
                 for i in range(320)]
        payload = _full_provider(bars, index).collect("AAPL").payload
        self.assertIn(
            payload["market"]["regime"]["value"],
            ("bullish", "bearish", "mixed"),
        )
        self.assertIsInstance(
            payload["market"]["rs_3m"]["value"], float
        )
        # The regime explanation embeds the benchmark's name and its
        # ingredients (the label is the only citable field).
        self.assertIn("S&P 500", payload["market"]["regime"]["explanation"])
        self.assertIn("200-day", payload["market"]["regime"]["explanation"])

    def test_collect_insufficient_bars_still_ships_payload_from_real_bars(self):
        provider = TechnicalsProvider(bars_loader=lambda symbol: _flat_bars(3))
        result = provider.collect("AAPL")
        self.assertTrue(
            any("insufficient history" in w for w in result.warnings)
        )
        # The payload still ships, built from the bars that do exist.
        self.assertEqual(
            metric_value(result.payload["meta"]["bars_daily"]), 3
        )
        self.assertAlmostEqual(
            metric_value(result.payload["price"]["close"]), 100.0
        )
        # Indicators needing more history are blank, with the sweep note.
        self.assertIsNone(metric_value(result.payload["daily"]["rsi_14"]))
        self.assertTrue(
            any("indicators lacking history" in w for w in result.warnings)
        )
        # A NUMERIC card with a payload is actionable; consumers gate on
        # each field's value, which is where the blanks live.
        self.assertTrue(result.is_actionable)

    def test_collect_loader_failure_ships_all_blank_payload_with_warning(self):
        def _boom(symbol):
            raise RuntimeError("source down")

        provider = TechnicalsProvider(bars_loader=_boom)
        result = provider.collect("AAPL")
        self.assertTrue(any("source down" in w for w in result.warnings))
        # The card keeps its shape: bar counts are real zeros, every
        # indicator blank, and the sweep note names the blanks.
        self.assertIsNotNone(result.payload)
        self.assertEqual(
            metric_value(result.payload["meta"]["bars_daily"]), 0
        )
        self.assertEqual(
            metric_value(result.payload["meta"]["bars_weekly"]), 0
        )
        self.assertIsNone(metric_value(result.payload["price"]["close"]))
        self.assertTrue(
            any("indicators lacking history" in w for w in result.warnings)
        )
        self.assertTrue(result.is_actionable)  # payload present; fields gate

    def test_collect_short_history_blanks_missing_fields_with_named_gaps(self):
        # 80 bars: RSI/ATR fine, but no 200-day average and no honest
        # weekly read — those fields are blank and the warning names them.
        closes = [100.0 * (1.005 ** i) for i in range(80)]
        provider = TechnicalsProvider(
            bars_loader=lambda s: _trend_bars(closes),
        )
        result = provider.collect("AAPL")
        self.assertTrue(result.is_actionable)
        self.assertIsNone(result.payload["daily"]["sma_200"]["value"])
        # Fields the 80 bars do support still carry values.
        self.assertIsNotNone(result.payload["daily"]["rsi_14"]["value"])
        self.assertTrue(
            any("daily.sma_200" in w for w in result.warnings)
        )
        self.assertTrue(
            any("weekly bars" in w for w in result.warnings)
        )

    def test_short_history_warns_about_the_one_year_window(self):
        closes = [100.0 * (1.002 ** i) for i in range(60)]
        result = TechnicalsProvider(
            bars_loader=lambda s: _trend_bars(closes)
        ).collect("AAPL")
        self.assertTrue(any("one-year fields" in w for w in result.warnings))

    def test_missing_volume_blanks_only_the_volume_fields(self):
        bars = [
            Bar(high=b.high, low=b.low, close=b.close, open=b.open,
                volume=None, date=b.date)
            for b in _wave_bars(320)
        ]
        result = TechnicalsProvider(bars_loader=lambda s: bars).collect("AAPL")
        self.assertIsNone(result.payload["volume"]["avg_vol_60d"]["value"])
        # Volume fields are optional: no missing-history sweep note, and
        # the price-based indicators still carry values.
        self.assertFalse(
            any("indicators lacking history" in w for w in result.warnings)
        )
        self.assertIsNotNone(result.payload["volatility"]["atr_14"]["value"])

    def test_avg_volume_ignores_missing_volumes(self):
        bars = [
            Bar(high=101, low=99, close=100, volume=1000.0),
            Bar(high=101, low=99, close=100, volume=None),
            Bar(high=101, low=99, close=100, volume=3000.0),
        ]
        self.assertAlmostEqual(compute_avg_volume(bars, lookback=3), 2000.0)

    def test_worst_day_shares_the_percent_convention_of_its_neighbours(self):
        closes = [100.0]
        for _ in range(60):
            closes.append(closes[-1] * 1.01)
        closes.append(closes[-1] * 0.85)  # a -15% day
        payload = TechnicalsProvider(
            bars_loader=lambda s: _trend_bars(closes)
        ).collect("AAPL").payload
        worst = payload["volatility"]["worst_day_pct_1y"]["value"]
        self.assertAlmostEqual(worst, -15.0)
        self.assertLess(worst, -1.0)  # percent, not a fraction

    def test_no_composite_score_is_handed_to_the_judgment_stages(self):
        # The payload is dumped verbatim into the LLM prompt, so a
        # code-computed 0-100 verdict in it would pre-answer the question
        # those stages exist to answer and invite anchoring.
        payload = _full_provider(_wave_bars(320)).collect("AAPL").payload
        self.assertNotIn("score", payload)
        self.assertNotIn("score", payload.get("meta", {}))

    def test_high_1y_is_the_highest_traded_high(self):
        bars = _wave_bars(320)
        payload = _full_provider(bars).collect("AAPL").payload
        expected = compute_swing_high(bars, 253)
        self.assertAlmostEqual(
            payload["price"]["high_1y"]["value"], round(expected, 2)
        )


class TestFormulaReceipts(unittest.TestCase):
    """UI receipts (DimensionResult.formulas): formula words + this run's
    plugged-in inputs, living OUTSIDE the payload so the LLM prompt and
    the envelope contract stay untouched."""

    def _result(self):
        bars = _wave_bars(320)
        index = [Bar(high=1, low=1, close=1000 * (1.0007 ** i))
                 for i in range(320)]
        return _full_provider(bars, index).collect("AAPL")

    def test_payload_stays_free_of_formula_keys(self):
        result = self._result()
        for group, metrics in result.payload.items():
            for key, node in metrics.items():
                self.assertTrue(is_envelope(node), f"{group}.{key}")

    def test_receipt_arithmetic_reproduces_the_published_value(self):
        result = self._result()
        cases = {
            "daily.stretch_50d_atr": lambda i: (
                (i["close"] - i["sma_50"]) / i["atr_14"]
            ),
            "volatility.atr_pct": lambda i: i["atr_14"] / i["close"] * 100,
            "price.range_pct_1y": lambda i: (
                (i["close"] - i["low_1y"])
                / (i["high_1y"] - i["low_1y"]) * 100
            ),
            "daily.rsi_14": lambda i: (
                100 - 100 / (1 + i["avg_gain_14"] / i["avg_loss_14"])
            ),
            "volatility.worst_day_pct_1y": lambda i: (
                (i["worst_close"] - i["prev_close"]) / i["prev_close"] * 100
            ),
            "market.rs_3m": lambda i: (
                i["stock_return_3m"] - i["index_return_3m"]
            ),
        }
        for path, compute in cases.items():
            receipt = result.formulas[path]
            group, key = path.split(".")
            published = metric_value(result.payload[group][key])
            self.assertAlmostEqual(
                compute(receipt["inputs"]), published, places=1,
                msg=path,
            )

    def test_every_receipt_targets_a_published_metric(self):
        result = self._result()
        for path, receipt in result.formulas.items():
            group, key = path.split(".")
            self.assertIsNotNone(
                metric_value(result.payload[group][key]), path
            )
            self.assertTrue(
                receipt.get("formula") or receipt.get("branches"), path
            )
            for var, value in receipt["inputs"].items():
                self.assertIsInstance(value, (float, str), f"{path}:{var}")

    def test_multi_outcome_rules_ship_branches(self):
        # Owner format 2026-07-28: rules with several possible outcomes
        # render one line per outcome — the receipt ships them as
        # {label, condition} branches, catch-all (condition None) last,
        # and the published label is always one of the branch labels.
        result = self._result()
        for path in ("market.regime", "market.rs_label",
                     "weekly.trend", "daily.trend", "daily.momentum",
                     "volatility.atr_trend"):
            receipt = result.formulas[path]
            branches = receipt["branches"]
            self.assertNotIn("formula", receipt, path)
            self.assertGreaterEqual(len(branches), 3, path)
            self.assertIsNone(branches[-1]["condition"], path)
            for branch in branches[:-1]:
                self.assertTrue(branch["condition"], path)
            group, key = path.split(".")
            self.assertIn(
                metric_value(result.payload[group][key]),
                [branch["label"] for branch in branches],
                path,
            )

    def test_raw_facts_and_meta_get_no_receipt(self):
        result = self._result()
        for path in ("meta.as_of", "meta.bars_daily", "meta.bars_weekly",
                     "price.close"):
            self.assertNotIn(path, result.formulas)

    def test_label_receipts_carry_their_rule_ingredients(self):
        # Rule fields (2026-07-28): the receipt is the rule in words plus
        # this run's ingredient values — word ingredients ship as strings.
        result = self._result()
        for path in ("weekly.trend", "daily.trend"):
            receipt = result.formulas[path]
            self.assertIn(
                receipt["inputs"]["ma_stack"], ("up", "down", "mixed")
            )
            self.assertIn(
                receipt["inputs"]["pivot_structure"],
                ("higher highs and lows", "lower highs and lows",
                 "sideways"),
            )
        momentum = result.formulas["daily.momentum"]
        self.assertIn(momentum["inputs"]["macd_hist"],
                      ("rising", "falling"))
        self.assertIsInstance(momentum["inputs"]["rsi_14"], float)
        self.assertIsInstance(momentum["inputs"]["macd_line"], float)
        atr_trend_receipt = result.formulas["volatility.atr_trend"]
        self.assertIsInstance(
            atr_trend_receipt["inputs"]["atr_20_bars_ago"], float
        )

    def test_regime_receipt_reproduces_the_label(self):
        result = self._result()
        receipt = result.formulas["market.regime"]
        i = receipt["inputs"]
        above = i["index_close"] > i["index_sma_200"]
        if above and i["index_range_pct"] > 50:
            expected = "bullish"
        elif not above and i["index_range_pct"] < 50:
            expected = "bearish"
        else:
            expected = "mixed"
        self.assertEqual(
            metric_value(result.payload["market"]["regime"]), expected
        )

    def test_rs_label_receipt_reproduces_the_label(self):
        result = self._result()
        i = result.formulas["market.rs_label"]["inputs"]
        expected = (
            "leader" if i["rs_1m"] > 0 and i["rs_3m"] > 0
            else "laggard" if i["rs_1m"] < 0 and i["rs_3m"] < 0
            else "neutral"
        )
        self.assertEqual(
            metric_value(
                result.payload["market"]["rs_label"]
            ),
            expected,
        )

    def test_no_benchmark_means_no_rs_receipt_not_a_crash(self):
        result = _full_provider(_wave_bars(320)).collect("AAPL")
        self.assertNotIn("market.rs_3m", result.formulas)
        self.assertIn("daily.stretch_50d_atr", result.formulas)

    def test_wilder_averages_match_the_rsi(self):
        avg_gain, avg_loss = wilder_averages(WILDER_CLOSES)
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)
        self.assertAlmostEqual(rsi, compute_wilder_rsi(WILDER_CLOSES))

    def test_worst_day_detail_names_the_two_closes(self):
        closes = [100.0]
        for _ in range(30):
            closes.append(closes[-1] * 1.01)
        closes.append(closes[-1] * 0.90)
        pct, prev_close, worst_close = worst_day_detail(closes)
        self.assertAlmostEqual(pct, -10.0)
        self.assertAlmostEqual(worst_close / prev_close - 1.0, -0.10)


if __name__ == "__main__":
    unittest.main()
