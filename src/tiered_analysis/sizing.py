# -*- coding: utf-8 -*-
"""Deterministic position sizing (docs/tiered-analysis-design.md §3.2; v2 slice 1).

Fixed-fractional risk sizing: the user picks the loss they can accept
(capital * risk_fraction); the entry-to-stop distance gives the loss per
share; division gives the share count. Pure functions, no I/O, no LLM —
every refusal carries an explicit reason instead of a silent zero,
mirroring the provider layer's no-silent-blanks rule.

Fee rate and the 25% single-name position cap were removed 2026-07-22
(owner decision): they return later as a per-run fee input and a
whole-portfolio cap once those features exist.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from .providers.base import Market
from .schema import Direction, SizingSlots

#: Above this per-trade risk fraction we still size, but flag it as unusual.
HIGH_RISK_FRACTION_NOTE_THRESHOLD = 0.05

#: Minimum tradeable increment per market family. CN cash equities trade in
#: board lots of 100; HK board lots vary per stock (we size in single shares
#: and attach a note); everywhere else single shares are assumed.
_LOT_SIZES = {Market.CN: 100}
_DEFAULT_LOT_SIZE = 1


def lot_size_for(market: Market) -> int:
    """The market's minimum tradeable increment (CN board lots of 100)."""
    return _LOT_SIZES.get(market, _DEFAULT_LOT_SIZE)


class RefusalReason(str, Enum):
    """Stable machine-readable codes so the UI can localize the message."""

    NOT_A_BUY = "not_a_buy"
    SIZING_OFF = "sizing_off"
    NO_ENTRY = "no_entry"
    NO_STOP = "no_stop"
    STOP_NOT_BELOW_ENTRY = "stop_not_below_entry"
    INVALID_INPUT = "invalid_input"
    TOO_SMALL = "too_small"


@dataclass(frozen=True)
class SizingInputs:
    """Everything the engine needs; capital/risk_fraction come from the user."""

    capital: Optional[float]
    risk_fraction: Optional[float]
    entry: Optional[float]
    stop_loss: Optional[float]
    direction: Direction
    market: Market = Market.UNKNOWN


@dataclass(frozen=True)
class SizingResult:
    shares: Optional[int] = None
    position_value: Optional[float] = None
    #: Planned maximum loss if the stop is hit.
    risk_amount: Optional[float] = None
    loss_per_share: Optional[float] = None
    lot_size: int = _DEFAULT_LOT_SIZE
    reason_code: Optional[RefusalReason] = None
    refusal_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def is_sized(self) -> bool:
        return self.shares is not None and self.shares > 0


def _refuse(code: RefusalReason, message: str, *, lot_size: int = _DEFAULT_LOT_SIZE,
            notes: Optional[List[str]] = None) -> SizingResult:
    return SizingResult(
        lot_size=lot_size,
        reason_code=code,
        refusal_reason=message,
        notes=notes or [],
    )


def _validate(inputs: SizingInputs) -> Tuple[Optional[SizingResult], List[str]]:
    """Refusal-or-notes gate, run before any arithmetic."""
    notes: List[str] = []

    if inputs.direction is not Direction.BUY:
        return _refuse(
            RefusalReason.NOT_A_BUY,
            "Sizing only applies when opening a position (direction is "
            f"'{inputs.direction.value}', not 'buy').",
        ), notes
    if inputs.capital is None or inputs.risk_fraction is None:
        # Name exactly what is missing — "capital not provided" when the
        # user did provide capital reads as a bug, not a refusal.
        missing = [
            label
            for label, value in (
                ("capital", inputs.capital),
                ("risk per trade", inputs.risk_fraction),
            )
            if value is None
        ]
        verb = "were" if len(missing) > 1 else "was"
        return _refuse(
            RefusalReason.SIZING_OFF,
            f"Sizing is off: {' and '.join(missing)} {verb} not provided.",
        ), notes
    if inputs.capital <= 0 or not 0 < inputs.risk_fraction < 1:
        return _refuse(
            RefusalReason.INVALID_INPUT,
            "capital must be positive and risk per trade strictly between 0 and 1.",
        ), notes
    if inputs.entry is None:
        return _refuse(
            RefusalReason.NO_ENTRY, "No usable entry price — cannot size a position."
        ), notes
    if inputs.stop_loss is None:
        return _refuse(
            RefusalReason.NO_STOP,
            "No stop-loss price — without it the risk per share is unmeasurable, "
            "so no share count is printed.",
        ), notes
    # None means "level missing"; a zero/negative price means garbage input.
    if inputs.entry <= 0 or inputs.stop_loss <= 0:
        return _refuse(
            RefusalReason.INVALID_INPUT, "entry and stop-loss prices must be positive."
        ), notes
    if inputs.stop_loss >= inputs.entry:
        return _refuse(
            RefusalReason.STOP_NOT_BELOW_ENTRY,
            "Stop-loss is at or above the entry price for a buy — levels are "
            "inconsistent, refusing to size.",
        ), notes

    if inputs.risk_fraction > HIGH_RISK_FRACTION_NOTE_THRESHOLD:
        notes.append(
            f"Risk per trade of {inputs.risk_fraction:.1%} is unusually high; "
            "1-2% is the common range."
        )
    if inputs.market is Market.HK:
        notes.append(
            "HK board lot sizes vary per stock; the count below is in single "
            "shares — round to the stock's board lot before ordering."
        )
    return None, notes


def size_position(inputs: SizingInputs) -> SizingResult:
    """Compute a share count, or refuse with an explicit reason."""
    refusal, notes = _validate(inputs)
    lot_size = _LOT_SIZES.get(inputs.market, _DEFAULT_LOT_SIZE)
    if refusal is not None:
        return SizingResult(
            lot_size=lot_size,
            reason_code=refusal.reason_code,
            refusal_reason=refusal.refusal_reason,
            notes=notes,
        )

    loss_per_share = inputs.entry - inputs.stop_loss
    risk_budget = inputs.capital * inputs.risk_fraction
    raw_shares = risk_budget / loss_per_share

    shares = int(math.floor(raw_shares / lot_size)) * lot_size
    if shares <= 0:
        return _refuse(
            RefusalReason.TOO_SMALL,
            "The computed size rounds down to zero — the risk budget is too "
            "small for even one "
            + ("board lot" if lot_size > 1 else "share")
            + " at this price.",
            lot_size=lot_size,
            notes=notes,
        )

    return SizingResult(
        shares=shares,
        position_value=shares * inputs.entry,
        risk_amount=shares * loss_per_share,
        loss_per_share=loss_per_share,
        lot_size=lot_size,
        notes=notes,
    )


def to_sizing_slots(inputs: SizingInputs, result: SizingResult) -> SizingSlots:
    """Fill the TierReport slots reserved since v1; refusals keep them empty."""
    if not result.is_sized:
        return SizingSlots()
    return SizingSlots(
        capital=inputs.capital,
        risk_fraction=inputs.risk_fraction,
        shares=float(result.shares),
    )
