# -*- coding: utf-8 -*-
"""Tier report envelope (docs/tiered-analysis-design.md §3.1, §4).

v1 outputs direction only. The sizing slots (capital / risk_fraction /
shares) are reserved in the schema from day one but stay empty until the
deterministic sizing engine lands in v2 — printing a share count creates an
obligation to justify it with a backtest, which v1 does not have.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .providers.base import DimensionResult, Market


#: Max hold time (owner decision 2026-08-08, supersedes the 2026-07-29
#: words-only rule): the user picks how long they plan to hold at most,
#: in weeks; the SAME number feeds the AI prompts, the report, the saved
#: signal and the forward-test grading window so they stay on one page.
HOLD_WEEKS_CHOICES = (1, 2, 3, 4)
DEFAULT_HOLD_WEEKS = 2
TRADING_DAYS_PER_WEEK = 5


def hold_weeks_text(hold_weeks: int) -> str:
    """Human wording for the max hold time ("1 week", "3 weeks")."""
    return f"{hold_weeks} week" + ("" if hold_weeks == 1 else "s")


class Direction(str, Enum):
    """Normalized trade direction, mapped from DSA's decision_type."""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    UNKNOWN = "unknown"

    @classmethod
    def from_decision_type(cls, value: Optional[str]) -> "Direction":
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.UNKNOWN


class Outlook(str, Enum):
    """The impersonal judgment about the stock (outlook redesign,
    2026-07-20): what the evidence says, with no knowledge of the user's
    position. Renamed from the old buy/hold/sell verdict — an assessment
    can't literally mean "you should sell" when it doesn't know whether
    you own anything."""

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    UNKNOWN = "unknown"
    #: Staleness gate (2026-08-08): the run stopped BEFORE any LLM stage
    #: because the newest daily bar predates the most recent completed
    #: trading session. No analysis or plan exists; the outlook itself is
    #: the whole user-facing story (the reason lives in logs only).
    STOPPED = "stopped"

    @classmethod
    def from_direction(cls, direction: Direction) -> "Outlook":
        return {
            Direction.BUY: cls.BULLISH,
            Direction.HOLD: cls.NEUTRAL,
            Direction.SELL: cls.BEARISH,
        }.get(direction, cls.UNKNOWN)


class Action(str, Enum):
    """The personal instruction, derived by code from the outlook plus,
    for entries, the plan's reward-to-risk vs the user's goal. The
    outlook decides WHETHER the stock deserves money; the action is what
    that means for a new position. (The held-shares column — keep
    holding / sell all — was removed with the ownership input,
    2026-09-16; a future portfolio feature would reintroduce it.)"""

    ENTER = "enter"  # buy now: the plan's reward-to-risk meets the goal
    ENTER_LATER = "enter_later"  # buy later: reward-to-risk below the goal
    NO_TRADE = "no_trade"  # nothing to do
    UNKNOWN = "unknown"


def derive_action(outlook: Outlook, plan_meets_goal: bool = True) -> Action:
    """The outlook → action table:

    | outlook  | action              |
    |----------|---------------------|
    | bullish  | enter / enter_later |
    | neutral  | no_trade            |
    | bearish  | no_trade            |

    ``plan_meets_goal`` splits the bullish cell (owner decision
    2026-08-23): ENTER ("buy now") when the trade plan's actual
    reward-to-risk ratio reaches the user's chosen goal, ENTER_LATER
    ("buy later") when it falls short — the same comparison as the plan
    card's reward-below-goal warning, so the two can never disagree. A
    ratio that cannot be computed counts as meeting the goal, mirroring
    that warning's silence.
    """
    if outlook is Outlook.BULLISH:
        return Action.ENTER if plan_meets_goal else Action.ENTER_LATER
    if outlook in (Outlook.NEUTRAL, Outlook.BEARISH):
        return Action.NO_TRADE
    return Action.UNKNOWN


def coerce_price(value: object) -> Optional[float]:
    """Best-effort float from DSA's str|int|float price fields.

    DSA sniper-point values may be numbers, numeric strings, or markers
    like "N/A". Anything non-numeric becomes None — callers must surface a
    warning rather than let a bad level pass silently.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


#: A price-like number in prose: digits (optionally decimal) not glued to a
#: letter/digit (rejects indicator names like MA20/RSI14) and not a percent.
_PRICE_IN_TEXT_RE = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?")


def extract_price(value: object) -> Optional[float]:
    """coerce_price plus a prose fallback (first price-like number).

    The live production run showed DSA sometimes returns sniper levels as
    full sentences ("理想买入点：303.80元（...）"). The number is still
    deterministic text — extract the first one that is not an indicator
    name (MA20) and not a percentage (7%).
    """
    strict = coerce_price(value)
    if strict is not None:
        return strict
    if not isinstance(value, str):
        return None
    for match in _PRICE_IN_TEXT_RE.finditer(value):
        end = match.end()
        if end < len(value) and value[end] == "%":
            continue
        return float(match.group())
    return None


@dataclass(frozen=True)
class SizingSlots:
    """Reserved position-sizing fields — intentionally always empty in v1."""

    capital: Optional[float] = None
    risk_fraction: Optional[float] = None
    shares: Optional[float] = None

    @property
    def is_empty(self) -> bool:
        return self.capital is None and self.risk_fraction is None and self.shares is None


@dataclass(frozen=True)
class SniperLevels:
    """The plan's price levels (formula-computed, see levels.py)."""

    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


#: Tolerance on the "did the plan reach the reward goal" comparison,
#: shared by the plan card's reward-below-goal warning and the buy-now /
#: buy-later action split so the two can never disagree.
REWARD_GOAL_EPS = 1e-3


def reward_ratio(levels: SniperLevels) -> Optional[float]:
    """The plan's actual reward-to-risk: (target − entry) / (entry − stop).

    None when any leg is missing or the risk side is not positive; the
    callers treat an unknowable ratio as "no complaint" (no warning, no
    buy-later downgrade)."""
    entry, stop, target = levels.entry, levels.stop_loss, levels.take_profit
    if entry is None or stop is None or target is None or entry <= stop:
        return None
    return (target - entry) / (entry - stop)


@dataclass(frozen=True)
class TierReport:
    """Output of one tier for one symbol: report + decision."""

    tier: int
    symbol: str
    market: Market
    direction: Direction
    confidence: Optional[str] = None
    score: Optional[int] = None
    levels: SniperLevels = field(default_factory=SniperLevels)
    narrative: Optional[str] = None
    dimensions: List[DimensionResult] = field(default_factory=list)
    sizing: SizingSlots = field(default_factory=SizingSlots)
    warnings: List[str] = field(default_factory=list)
    #: v2 slice 3 audit trail: per-level base/formula/inputs + AI adjustment
    #: (reason, evidence, rejection). JSON-ready dict; None on pre-v2 reports.
    levels_detail: Optional[Dict[str, Any]] = None
    #: v2 slice 4 audit trail (tier-2 reports only): debate turns + judge
    #: verdict with anchored reasons. JSON-ready dict; None elsewhere.
    debate_detail: Optional[Dict[str, Any]] = None
    #: Max hold time in weeks the run was judged against (2026-08-08);
    #: None on reports stored before the hold-time picker existed.
    hold_weeks: Optional[int] = None
