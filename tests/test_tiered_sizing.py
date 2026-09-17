# -*- coding: utf-8 -*-
"""Offline tests for the deterministic position-sizing engine (v2 slice 1).

Fixed-fractional sizing: shares = (capital * risk_fraction) / loss_per_share,
where loss_per_share = entry - stop. Every refusal path must carry an
explicit reason code — never a silent zero. (Fee rate and the position
cap were removed 2026-07-22; they return as user inputs later.)

Fractional shares (2026-09-17): markets without a board lot keep the
fraction, floored to a thousandth of a share; CN still rounds down to
whole lots of 100.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.providers.base import Market
from src.tiered_analysis.schema import Direction
from src.tiered_analysis.sizing import (
    FRACTIONAL_SHARE_STEP,
    RefusalReason,
    SizingInputs,
    floor_to_tradeable,
    size_position,
    to_sizing_slots,
)


def _inputs(**overrides) -> SizingInputs:
    """A valid US buy that sizes cleanly; tests override one field at a time."""
    base = dict(
        capital=100_000.0,
        risk_fraction=0.005,
        entry=210.0,
        stop_loss=202.0,
        direction=Direction.BUY,
        market=Market.US,
    )
    base.update(overrides)
    return SizingInputs(**base)


class TestFormula(unittest.TestCase):
    def test_fixed_fractional_happy_path(self):
        # risk budget 500; loss/share 8 -> 62.5 shares (fractional shares
        # are kept where no board lot applies).
        result = size_position(_inputs())
        self.assertIsNone(result.refusal_reason)
        self.assertEqual(result.shares, 62.5)
        self.assertAlmostEqual(result.position_value, 62.5 * 210.0)
        self.assertAlmostEqual(result.risk_amount, 62.5 * 8.0)

    def test_less_than_one_share_is_a_size_not_a_refusal(self):
        # Budget 2; loss/share 8 -> 0.25 shares: a small account still
        # gets a count instead of an empty cell.
        result = size_position(_inputs(capital=400.0))
        self.assertIsNone(result.refusal_reason)
        self.assertEqual(result.shares, 0.25)
        self.assertAlmostEqual(result.risk_amount, 2.0)

    def test_fraction_floors_to_a_thousandth_of_a_share(self):
        # Budget 1; loss/share 3 -> 0.3333… -> 0.333.
        result = size_position(
            _inputs(capital=100.0, risk_fraction=0.01, entry=10.0, stop_loss=7.0)
        )
        self.assertEqual(result.shares, 0.333)

    def test_floor_to_tradeable_survives_float_noise(self):
        # 0.57 * 100 is 56.999… in floating point; the count must not
        # drop a step because of that.
        self.assertEqual(floor_to_tradeable(0.57, 1), 0.57)
        self.assertEqual(floor_to_tradeable(1818.18, 100), 1800.0)
        self.assertEqual(FRACTIONAL_SHARE_STEP, 0.001)

    def test_wider_stop_means_fewer_shares(self):
        tight = size_position(_inputs(stop_loss=206.0))  # loss/share 4
        wide = size_position(_inputs(stop_loss=190.0))  # loss/share 20
        self.assertGreater(tight.shares, wide.shares)

    def test_loss_per_share_is_the_entry_stop_distance(self):
        # Budget 300, loss/share 2 -> exactly 150 shares (no fee term).
        result = size_position(
            _inputs(capital=120_000.0, risk_fraction=0.0025, entry=100.0, stop_loss=98.0)
        )
        self.assertEqual(result.shares, 150)
        self.assertAlmostEqual(result.loss_per_share, 2.0)
        self.assertAlmostEqual(result.risk_amount, 150 * 2.0)


class TestGuardrails(unittest.TestCase):
    def test_no_position_cap_anymore(self):
        # loss/share 1 -> 500 shares = a 50k position on 50k capital; the
        # old 25% cap would have cut this to 125 — removed 2026-07-22.
        result = size_position(
            _inputs(capital=50_000.0, risk_fraction=0.01, entry=100.0, stop_loss=99.0)
        )
        self.assertEqual(result.shares, 500)

    def test_cn_lot_rounding(self):
        # 1000 budget / 0.55 = 1818.18 -> floor to lot 100 -> 1800.
        result = size_position(
            _inputs(
                capital=100_000.0,
                risk_fraction=0.01,
                entry=10.0,
                stop_loss=9.45,
                market=Market.CN,
            )
        )
        self.assertEqual(result.lot_size, 100)
        self.assertEqual(result.shares, 1800)

    def test_us_lot_is_single_share(self):
        self.assertEqual(size_position(_inputs()).lot_size, 1)

    def test_hk_board_lot_unknown_gets_a_note(self):
        result = size_position(_inputs(market=Market.HK))
        self.assertTrue(any("board lot" in note.lower() for note in result.notes))

    def test_rounds_down_to_zero_is_a_refusal_not_a_zero(self):
        # Budget 5 / loss 0.1 = 50 raw shares -> CN lot 100 floor -> 0 -> refuse.
        result = size_position(
            _inputs(
                capital=500.0,
                risk_fraction=0.01,
                entry=10.0,
                stop_loss=9.9,
                market=Market.CN,
            )
        )
        self.assertIsNone(result.shares)
        self.assertEqual(result.reason_code, RefusalReason.TOO_SMALL)

    def test_below_a_thousandth_of_a_share_is_still_too_small(self):
        # Budget 0.01 / loss 20 = 0.0005 shares -> below the fractional
        # step -> refuse, and the message names the step.
        result = size_position(
            _inputs(capital=1.0, risk_fraction=0.01, entry=100.0, stop_loss=80.0)
        )
        self.assertIsNone(result.shares)
        self.assertEqual(result.reason_code, RefusalReason.TOO_SMALL)
        self.assertIn("0.001 of a share", result.refusal_reason)

    def test_high_risk_fraction_gets_a_note(self):
        result = size_position(_inputs(risk_fraction=0.08))
        self.assertTrue(any("risk" in note.lower() for note in result.notes))


class TestRefusals(unittest.TestCase):
    def _assert_refused(self, result, code: RefusalReason):
        self.assertIsNone(result.shares)
        self.assertIsNone(result.position_value)
        self.assertEqual(result.reason_code, code)
        self.assertTrue(result.refusal_reason)

    def test_hold_and_sell_and_unknown_are_not_sized(self):
        for direction in (Direction.HOLD, Direction.SELL, Direction.UNKNOWN):
            self._assert_refused(
                size_position(_inputs(direction=direction)), RefusalReason.NOT_A_BUY
            )

    def test_missing_capital_or_risk_means_sizing_off(self):
        self._assert_refused(size_position(_inputs(capital=None)), RefusalReason.SIZING_OFF)
        self._assert_refused(
            size_position(_inputs(risk_fraction=None)), RefusalReason.SIZING_OFF
        )

    def test_sizing_off_message_names_only_the_missing_input(self):
        only_risk_missing = size_position(_inputs(risk_fraction=None))
        self.assertEqual(
            only_risk_missing.refusal_reason,
            "Sizing is off: risk per trade was not provided.",
        )
        only_capital_missing = size_position(_inputs(capital=None))
        self.assertEqual(
            only_capital_missing.refusal_reason,
            "Sizing is off: capital was not provided.",
        )
        both_missing = size_position(_inputs(capital=None, risk_fraction=None))
        self.assertEqual(
            both_missing.refusal_reason,
            "Sizing is off: capital and risk per trade were not provided.",
        )

    def test_missing_stop_is_refused(self):
        self._assert_refused(size_position(_inputs(stop_loss=None)), RefusalReason.NO_STOP)

    def test_missing_entry_is_refused(self):
        self._assert_refused(size_position(_inputs(entry=None)), RefusalReason.NO_ENTRY)

    def test_stop_at_or_above_entry_is_refused(self):
        for stop in (210.0, 215.0):
            self._assert_refused(
                size_position(_inputs(stop_loss=stop)), RefusalReason.STOP_NOT_BELOW_ENTRY
            )

    def test_non_positive_inputs_are_invalid(self):
        for overrides in (
            {"capital": 0.0},
            {"capital": -1.0},
            {"risk_fraction": 0.0},
            {"risk_fraction": 1.0},
            {"entry": 0.0},
        ):
            self._assert_refused(
                size_position(_inputs(**overrides)), RefusalReason.INVALID_INPUT
            )


class TestSizingSlots(unittest.TestCase):
    def test_sized_result_fills_the_reserved_slots(self):
        inputs = _inputs()
        slots = to_sizing_slots(inputs, size_position(inputs))
        self.assertFalse(slots.is_empty)
        self.assertEqual(slots.capital, inputs.capital)
        self.assertEqual(slots.risk_fraction, inputs.risk_fraction)
        self.assertEqual(slots.shares, 62.5)

    def test_refused_result_keeps_slots_empty(self):
        inputs = _inputs(stop_loss=None)
        slots = to_sizing_slots(inputs, size_position(inputs))
        self.assertTrue(slots.is_empty)


if __name__ == "__main__":
    unittest.main()
