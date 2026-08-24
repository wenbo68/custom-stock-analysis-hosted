# -*- coding: utf-8 -*-
"""Forward-test metrics: noise-scaled outcome bands and plan simulation.

The shared outcome engine grades every decision signal with a fixed
±2% neutral band — one constant for every stock and every window. For
the tiered forward test that is statistically lopsided: 2% is about one
week of normal wobble for KO and far inside one day's wobble for TSLA.
This module supplies the experiment's own yardsticks, computed offline
from data the outcome job already stores (nothing here re-runs an LLM
or changes the shared grader):

- ``noise_band_pct``: a per-stock, per-window neutral band — the
  stock's typical daily move scaled by the square root of the window
  length (random drift accumulates with √time).
- ``classify_outcome``: the shared engine's hit/miss/neutral branches,
  verbatim, so the only difference from the stored grade is the band.
- ``directional_return_pct``: the sign-adjusted return of a call (buy
  wants up, sell wants down) for the mean-return scoreboard column.
- ``simulate_plan``: grades a saved trade plan against the daily bars —
  did the price reach the entry, and then the stop or the target first?

Daily bars cannot order moves within one day, so a bar that crosses
both stop and target is reported as ``ambiguous``, never guessed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple

#: Minimum daily returns required before volatility is trusted; below
#: this the caller should fall back to the shared engine's fixed band.
MIN_VOLATILITY_RETURNS = 20

#: Band width in units of accumulated typical wobble. k=1 means "the
#: move must beat one standard deviation of pure noise over the same
#: window". The shape (per-stock sigma x sqrt(time)) is the statistical
#: part; k itself is a judgment call, like the ~30-samples floor.
NOISE_BAND_K = 1.0


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def daily_volatility_pct(closes: Sequence[Any]) -> Optional[float]:
    """Sample standard deviation of day-over-day percent moves.

    Consecutive valid closes only; returns None below
    ``MIN_VOLATILITY_RETURNS`` usable returns (an unreliable sigma is
    worse than an honest fallback).
    """
    returns = []
    previous: Optional[float] = None
    for raw in closes:
        close = _finite(raw)
        if close is None or close <= 0:
            previous = None
            continue
        if previous is not None:
            returns.append((close - previous) / previous * 100.0)
        previous = close
    if len(returns) < MIN_VOLATILITY_RETURNS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def noise_band_pct(
    sigma_daily_pct: Optional[float],
    eval_days: int,
    k: float = NOISE_BAND_K,
) -> Optional[float]:
    """Neutral band for one window: k x sigma_daily x sqrt(days)."""
    sigma = _finite(sigma_daily_pct)
    if sigma is None or sigma <= 0 or eval_days <= 0:
        return None
    return k * sigma * math.sqrt(eval_days)


def classify_outcome(
    direction_expected: Optional[str],
    return_pct: Optional[float],
    band_pct: float,
) -> Tuple[Optional[str], Optional[bool]]:
    """Hit/miss/neutral under a caller-chosen band.

    Branch-for-branch the same rule as
    ``BacktestEngine._classify_signal_outcome`` — keep them aligned, the
    experiment's only intended difference is the band width.
    """
    r = _finite(return_pct)
    if r is None:
        return None, None
    band = abs(float(band_pct))
    if direction_expected == "up":
        if r >= band:
            return "hit", True
        if r <= -band:
            return "miss", False
        return "neutral", None
    if direction_expected == "not_down":
        if r >= 0:
            return "hit", True
        if r <= -band:
            return "miss", False
        return "neutral", None
    if direction_expected == "not_up":
        if r <= band:
            return "hit", True
        return "miss", False
    return None, None


def directional_return_pct(
    direction_expected: Optional[str], return_pct: Optional[float]
) -> Optional[float]:
    """Return earned by following the call: buy wants up, sell wants
    down; a hold predicts no direction so it contributes nothing."""
    r = _finite(return_pct)
    if r is None:
        return None
    if direction_expected == "up":
        return r
    if direction_expected == "not_up":
        return -r
    return None


@dataclass(frozen=True)
class PlanOutcome:
    """One plan graded against one window of daily bars.

    status: ``invalid`` (unusable levels), ``no_entry`` (price never
    reached the entry — no trade, not a miss), ``stop`` / ``target``
    (which line was struck first), ``ambiguous`` (daily data cannot
    order the moves — one bar crossed both lines, or the target was
    crossed on the entry's own fill bar), ``open`` (entered, window
    ended with neither line struck; graded at the final close).
    """

    status: str
    fill_index: Optional[int] = None
    exit_index: Optional[int] = None
    return_pct: Optional[float] = None


def simulate_plan(
    entry: Any,
    stop_loss: Any,
    take_profit: Any,
    bars: Sequence[Any],
) -> PlanOutcome:
    """Grade one long trade plan bar by bar.

    A limit entry: the trade fills the first bar whose low touches the
    entry price. From the fill bar on, a low at/under the stop exits at
    the stop and a high at/over the target exits at the target. Bars
    are anything with ``high`` / ``low`` / ``close`` attributes.
    """
    entry_price = _finite(entry)
    stop = _finite(stop_loss)
    target = _finite(take_profit)
    if (
        entry_price is None or stop is None or target is None
        or entry_price <= 0 or not stop < entry_price < target
    ):
        return PlanOutcome(status="invalid")

    fill_index: Optional[int] = None
    last_close: Optional[float] = None
    for index, bar in enumerate(bars):
        low = _finite(getattr(bar, "low", None))
        high = _finite(getattr(bar, "high", None))
        close = _finite(getattr(bar, "close", None))
        if close is not None:
            last_close = close
        if fill_index is None:
            if low is None or low > entry_price:
                continue
            fill_index = index
        stop_hit = low is not None and low <= stop
        target_hit = high is not None and high >= target
        # A stop on the fill bar is certain: the low reached the stop,
        # so the price crossed the entry (which sits above it) on the
        # way down. A target on the fill bar is not — the high may have
        # come before the dip that filled the entry.
        if target_hit and (stop_hit or index == fill_index):
            return PlanOutcome(
                status="ambiguous", fill_index=fill_index, exit_index=index
            )
        if stop_hit:
            return PlanOutcome(
                status="stop",
                fill_index=fill_index,
                exit_index=index,
                return_pct=(stop - entry_price) / entry_price * 100.0,
            )
        if target_hit:
            return PlanOutcome(
                status="target",
                fill_index=fill_index,
                exit_index=index,
                return_pct=(target - entry_price) / entry_price * 100.0,
            )
    if fill_index is None:
        return PlanOutcome(status="no_entry")
    return PlanOutcome(
        status="open",
        fill_index=fill_index,
        return_pct=(
            (last_close - entry_price) / entry_price * 100.0
            if last_close is not None else None
        ),
    )
