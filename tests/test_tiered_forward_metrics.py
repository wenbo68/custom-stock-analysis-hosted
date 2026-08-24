# -*- coding: utf-8 -*-
"""Offline tests for the forward-test metrics: noise-scaled bands,
direction-adjusted returns, and daily-bar plan simulation."""
from __future__ import annotations

import math
from types import SimpleNamespace

from src.tiered_analysis.forward_metrics import (
    MIN_VOLATILITY_RETURNS,
    classify_outcome,
    daily_volatility_pct,
    directional_return_pct,
    noise_band_pct,
    simulate_plan,
)


def _bar(low, high, close=None):
    return SimpleNamespace(
        low=low, high=high, close=close if close is not None else high
    )


class TestVolatility:
    def test_too_little_history_returns_none(self):
        closes = [100 + i for i in range(MIN_VOLATILITY_RETURNS)]  # N-1 returns
        assert daily_volatility_pct(closes) is None

    def test_alternating_moves_have_known_sigma(self):
        # +1% then ~-0.99% forever: returns alternate around zero.
        closes = [100.0]
        for _ in range(30):
            closes.append(closes[-1] * (1.01 if len(closes) % 2 else 0.99))
        sigma = daily_volatility_pct(closes)
        assert sigma is not None
        assert 0.9 < sigma < 1.1  # ~1% daily wobble

    def test_bad_closes_break_the_return_chain_not_the_math(self):
        closes = [100.0, None, *[100.0 + i * 0.5 for i in range(40)]]
        assert daily_volatility_pct(closes) is not None


class TestNoiseBand:
    def test_scales_with_sqrt_of_time(self):
        one_day = noise_band_pct(2.0, 1)
        four_days = noise_band_pct(2.0, 4)
        assert one_day == 2.0
        assert math.isclose(four_days, 4.0)

    def test_unusable_sigma_returns_none(self):
        assert noise_band_pct(None, 5) is None
        assert noise_band_pct(0.0, 5) is None
        assert noise_band_pct(2.0, 0) is None


class TestClassifyOutcome:
    """Branch-parity with BacktestEngine._classify_signal_outcome."""

    def test_up_semantics(self):
        assert classify_outcome("up", 5.0, 3.0) == ("hit", True)
        assert classify_outcome("up", -5.0, 3.0) == ("miss", False)
        assert classify_outcome("up", 1.0, 3.0) == ("neutral", None)
        assert classify_outcome("up", 3.0, 3.0) == ("hit", True)  # >= band

    def test_hold_semantics_any_gain_is_a_hit(self):
        assert classify_outcome("not_down", 0.0, 3.0) == ("hit", True)
        assert classify_outcome("not_down", -5.0, 3.0) == ("miss", False)
        assert classify_outcome("not_down", -1.0, 3.0) == ("neutral", None)

    def test_sell_semantics_has_no_neutral(self):
        assert classify_outcome("not_up", 2.9, 3.0) == ("hit", True)
        assert classify_outcome("not_up", 3.1, 3.0) == ("miss", False)

    def test_missing_inputs(self):
        assert classify_outcome("up", None, 3.0) == (None, None)
        assert classify_outcome("sideways", 1.0, 3.0) == (None, None)


class TestDirectionalReturn:
    def test_buy_keeps_sign_sell_flips_hold_excluded(self):
        assert directional_return_pct("up", 4.0) == 4.0
        assert directional_return_pct("not_up", 4.0) == -4.0
        assert directional_return_pct("not_up", -4.0) == 4.0
        assert directional_return_pct("not_down", 4.0) is None
        assert directional_return_pct("up", None) is None


class TestSimulatePlan:
    def test_unusable_levels_are_invalid(self):
        bars = [_bar(99, 101)]
        assert simulate_plan(None, 95, 110, bars).status == "invalid"
        assert simulate_plan(100, 105, 110, bars).status == "invalid"  # stop>entry
        assert simulate_plan(100, 95, 90, bars).status == "invalid"  # target<entry

    def test_price_never_reaches_entry(self):
        bars = [_bar(101, 105), _bar(102, 108)]
        assert simulate_plan(100, 95, 110, bars).status == "no_entry"

    def test_fill_then_target(self):
        bars = [_bar(100, 102), _bar(101, 111)]
        result = simulate_plan(100, 95, 110, bars)
        assert result.status == "target"
        assert result.fill_index == 0
        assert result.exit_index == 1
        assert math.isclose(result.return_pct, 10.0)

    def test_fill_then_stop(self):
        bars = [_bar(100, 102), _bar(94, 101)]
        result = simulate_plan(100, 95, 110, bars)
        assert result.status == "stop"
        assert math.isclose(result.return_pct, -5.0)

    def test_stop_on_the_fill_bar_is_certain(self):
        # The low reached the stop, so the price crossed the entry on
        # the way down — ordering is knowable from one bar.
        bars = [_bar(94, 101)]
        result = simulate_plan(100, 95, 110, bars)
        assert result.status == "stop"
        assert result.fill_index == 0

    def test_target_on_the_fill_bar_is_ambiguous(self):
        # The high may have come before the dip that filled the entry.
        bars = [_bar(99, 111)]
        assert simulate_plan(100, 95, 110, bars).status == "ambiguous"

    def test_both_lines_in_one_bar_is_ambiguous(self):
        bars = [_bar(100, 102), _bar(94, 111)]
        assert simulate_plan(100, 95, 110, bars).status == "ambiguous"

    def test_entered_but_neither_line_struck_grades_at_last_close(self):
        bars = [_bar(100, 102, close=101), _bar(101, 104, close=103)]
        result = simulate_plan(100, 95, 110, bars)
        assert result.status == "open"
        assert math.isclose(result.return_pct, 3.0)

    def test_pre_fill_target_moves_are_ignored(self):
        # A rally to the target BEFORE the entry ever filled is not a win.
        bars = [_bar(101, 112), _bar(100, 103), _bar(94, 102)]
        result = simulate_plan(100, 95, 110, bars)
        assert result.status == "stop"
        assert result.fill_index == 1
        assert result.exit_index == 2
