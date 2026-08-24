# -*- coding: utf-8 -*-
"""ATR volatility stops + stop precedence (v2 slice 2, design doc §8).

The Tier-1 stop level originates in LLM-written prose (DSA sniper points,
parsed by schema.extract_price), so it must pass sanity checks before the
sizing engine divides by (entry - stop). The deterministic fallback is
entry - k*ATR: ATR (average true range) is the stock's typical daily swing,
already computed by the technicals provider, and k=2 places the stop far
enough out that ordinary daily noise does not trigger it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

DEFAULT_ATR_MULTIPLIER = 2.0

#: A level-derived stop more than this fraction below the entry fails the
#: sanity check: risking >25% per share is almost certainly a parsing or
#: hallucination artifact, not a plan.
MAX_STOP_DISTANCE_FRACTION = 0.25


class StopSource(str, Enum):
    """Which stop the report/sizing actually used — always labeled."""

    LEVELS = "levels"  # Tier-1 sniper level (LLM prose -> extracted number)
    ATR = "atr"  # deterministic entry - k*ATR
    NONE = "none"


@dataclass(frozen=True)
class StopResolution:
    stop_loss: Optional[float]
    source: StopSource
    warnings: List[str] = field(default_factory=list)


def suggest_atr_stop(
    entry: Optional[float],
    atr: Optional[float],
    multiplier: float = DEFAULT_ATR_MULTIPLIER,
) -> Optional[float]:
    """entry - multiplier*ATR for a buy; None whenever the math is unsound."""
    if entry is None or atr is None:
        return None
    if entry <= 0 or atr <= 0 or multiplier <= 0:
        return None
    stop = entry - multiplier * atr
    return stop if stop > 0 else None


def _level_stop_problem(entry: float, level_stop: Optional[float]) -> Optional[str]:
    """Reason the level-derived stop is unusable, or None if it is sane."""
    if level_stop is None:
        return None  # merely missing — a fallback case, not a warning
    if level_stop <= 0:
        return f"level stop {level_stop} is not a positive price"
    if level_stop >= entry:
        return f"level stop {level_stop} is at or above the entry {entry}"
    if (entry - level_stop) / entry > MAX_STOP_DISTANCE_FRACTION:
        return (
            f"level stop {level_stop} sits too far below the entry {entry} "
            f"(>{MAX_STOP_DISTANCE_FRACTION:.0%} of entry)"
        )
    return None


def resolve_stop(
    entry: Optional[float],
    level_stop: Optional[float],
    atr: Optional[float],
    multiplier: float = DEFAULT_ATR_MULTIPLIER,
) -> StopResolution:
    """Pick the stop sizing should use: sane Tier-1 level first, else ATR.

    Never raises and never silently invents a stop: an unusable input becomes
    a warning, and when nothing sound remains the source is NONE (which makes
    the sizing engine refuse with NO_STOP downstream).
    """
    warnings: List[str] = []

    if entry is None or entry <= 0:
        return StopResolution(
            stop_loss=None,
            source=StopSource.NONE,
            warnings=["no usable entry price — cannot place a stop"],
        )

    problem = _level_stop_problem(entry, level_stop)
    if problem is None and level_stop is not None:
        return StopResolution(stop_loss=level_stop, source=StopSource.LEVELS)
    if problem is not None:
        warnings.append(problem + " — falling back to the ATR stop")

    atr_stop = suggest_atr_stop(entry, atr, multiplier)
    if atr_stop is not None:
        return StopResolution(stop_loss=atr_stop, source=StopSource.ATR, warnings=warnings)

    warnings.append("no ATR available to derive a volatility stop")
    return StopResolution(stop_loss=None, source=StopSource.NONE, warnings=warnings)
