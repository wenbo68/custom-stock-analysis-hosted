# -*- coding: utf-8 -*-
"""Run gating for tiered analysis (owner decisions 2026-08-08).

Two gates keep every tiered run anchored on completed daily bars:

- The CLOCK gate (interactive runs): a run is rejected from market open
  until ``RUN_BUFFER_MINUTES`` past the close, in the exchange's own
  timezone. Weekends and pre-open mornings are allowed; holidays are only
  known when exchange-calendars is installed (without it a holiday
  daytime is a false block — accepted for now). The web popup offers a
  "run anyway" override, which the API honors.
- The STALENESS gate (all runs, enforced inside the pipeline): after the
  bars are fetched and BEFORE any LLM call, the run stops when the
  newest completed bar is older than the most recent completed trading
  session. A stopped run FAILS (``StaleDataError``, owner decision
  2026-09-17 — it used to finish with a "stopped" outlook) with a plain
  message naming the two dates; the detailed reason also goes to the
  log. There is deliberately NO override here — a clock-gate "run
  anyway" during the trading day expects YESTERDAY's bar and passes;
  only a genuinely lagging vendor stops a run.

Calendar duty is delegated to ``src.core.trading_calendar``
(exchange-calendars under the hood). Without that library the clock gate
fails OPEN (a run is never blocked on a guess) and the expected-session
calculation falls back to weekday arithmetic over fixed session times —
the constants below are that fallback only, never the primary source.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Minutes after the regular-session close during which runs stay blocked
#: — free data vendors usually publish the finished daily bar within this
#: window, so waiting cuts most staleness stops.
RUN_BUFFER_MINUTES = 30

#: Fallback regular-session times (market-local), used ONLY when
#: exchange-calendars is unavailable. Ordinary weekdays only — holidays
#: and half-days need the real calendar.
_FALLBACK_OPEN = {
    "cn": time(9, 30),
    "hk": time(9, 30),
    "us": time(9, 30),
    "jp": time(9, 0),
    "kr": time(9, 0),
    "tw": time(9, 0),
}
_FALLBACK_CLOSE = {
    "cn": time(15, 0),
    "hk": time(16, 0),
    "us": time(16, 0),
    "jp": time(15, 30),
    "kr": time(15, 30),
    "tw": time(13, 30),
}

_SATURDAY = 5  # date.weekday() >= 5 → weekend


@dataclass(frozen=True)
class ClockGateResult:
    """Outcome of the clock gate for one symbol."""

    blocked: bool
    market: Optional[str]
    #: Log/debug wording — never shown in the UI verbatim.
    detail: str
    #: Today's regular session bounds, market-local and tz-aware — always
    #: set when blocked (the popup words the hours from them), None when
    #: the gate never got as far as a session (unknown market, override,
    #: weekend/no-session days).
    session_open: Optional[datetime] = None
    session_close: Optional[datetime] = None


def market_for_symbol(symbol: str) -> Optional[str]:
    """Market key ('cn'/'hk'/'us'/...) for a symbol, None when unknown."""
    from src.core.trading_calendar import get_market_for_stock

    return get_market_for_stock(symbol)


def clock_gate(
    symbol: str, now: Optional[datetime] = None, override: bool = False
) -> ClockGateResult:
    """Decide whether an interactive tiered run may start right now.

    Blocked window: [session open, session close + RUN_BUFFER_MINUTES) in
    the exchange's local time. Unknown markets, non-session days and
    calendar failures fail OPEN — the staleness gate still protects the
    run's correctness.
    """
    from src.core.trading_calendar import (
        calendar_available,
        get_market_now,
        get_session_window,
    )

    market = market_for_symbol(symbol)
    if override:
        return ClockGateResult(False, market, "override accepted")
    if market is None:
        return ClockGateResult(False, None, f"unknown market for {symbol!r}")

    market_now = get_market_now(market, current_time=now)
    buffer = timedelta(minutes=RUN_BUFFER_MINUTES)

    if calendar_available():
        session_open, session_close = get_session_window(market, current_time=now)
        if session_open is None or session_close is None:
            return ClockGateResult(False, market, "no session today")
        blocked = session_open <= market_now < session_close + buffer
        return ClockGateResult(
            blocked,
            market,
            f"session {session_open:%H:%M}-{session_close:%H:%M} "
            f"+{RUN_BUFFER_MINUTES}min, local now {market_now:%H:%M}",
            session_open=session_open,
            session_close=session_close,
        )

    # Fallback: fixed weekday sessions, no holiday knowledge.
    open_t, close_t = _FALLBACK_OPEN.get(market), _FALLBACK_CLOSE.get(market)
    if open_t is None or close_t is None or market_now.weekday() >= _SATURDAY:
        return ClockGateResult(False, market, "fallback: weekend/unknown session")
    day = market_now.date()
    start = datetime.combine(day, open_t, tzinfo=market_now.tzinfo)
    close = datetime.combine(day, close_t, tzinfo=market_now.tzinfo)
    blocked = start <= market_now < close + buffer
    return ClockGateResult(
        blocked,
        market,
        f"fallback session {open_t:%H:%M}-{close_t:%H:%M}"
        f"+{RUN_BUFFER_MINUTES}min, local now {market_now:%H:%M}",
        session_open=start,
        session_close=close,
    )


def expected_bar_date(
    market: Optional[str], now: Optional[datetime] = None
) -> Optional[date]:
    """The most recent COMPLETED trading session's date for a market.

    This is the date the newest daily bar must carry for a run to be
    fresh. A run during the trading day (clock-gate override) expects
    yesterday's session — today's bar does not exist yet. None when the
    market is unknown.
    """
    if market is None:
        return None
    from src.core.trading_calendar import (
        calendar_available,
        get_effective_trading_date,
        get_market_now,
    )

    if calendar_available():
        return get_effective_trading_date(market, current_time=now)

    market_now = get_market_now(market, current_time=now)
    day = market_now.date()
    close_t = _FALLBACK_CLOSE.get(market)
    if (
        close_t is not None
        and day.weekday() < _SATURDAY
        and market_now.time() >= close_t
    ):
        return day
    day -= timedelta(days=1)
    while day.weekday() >= _SATURDAY:
        day -= timedelta(days=1)
    return day


def bar_date_only(raw: Optional[str]) -> Optional[date]:
    """Date part of a bar date string ("YYYY-MM-DD[ 00:00:00]")."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def trim_incomplete_bars(bars: Sequence, expected: Optional[date]) -> List:
    """Drop bars dated after the most recent completed session.

    Some vendors include today's half-finished bar during the trading
    day; the analysis must only ever see completed days. Bars without a
    parseable date are kept (fail-open — the providers already warn on
    missing dates).
    """
    if expected is None:
        return list(bars)
    kept = []
    for bar in bars:
        bar_day = bar_date_only(getattr(bar, "date", None))
        if bar_day is not None and bar_day > expected:
            continue
        kept.append(bar)
    return kept


class StaleDataError(RuntimeError):
    """The run refused to analyze bars older than the newest completed
    session. ``str(exc)`` is the message the user sees on the failed
    run; ``reason`` is the log-only detail."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def stale_data_message(
    bars_up_to: Optional[str],
    market: Optional[str],
    now: Optional[datetime] = None,
) -> str:
    """What the user reads when the staleness gate stops a run."""
    expected = expected_bar_date(market, now=now)
    newest = bar_date_only(bars_up_to)
    newest_text = newest.isoformat() if newest else "missing"
    expected_text = expected.isoformat() if expected else "unknown"
    return (
        "The price data is not up to date yet: the newest daily bar is "
        f"{newest_text} but the last completed trading day is "
        f"{expected_text}. Data vendors can take a while after the close; "
        "try again later."
    )


def staleness_stop_reason(
    bars_up_to: Optional[str],
    market: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Log-only stop reason when the bars are stale, else None.

    Stale = the newest completed bar is OLDER than the most recent
    completed trading session. A missing/unparseable bar date is treated
    as stale — an analysis that cannot say which day it describes must
    not run. Unknown markets fail open (no expected date to compare).
    """
    expected = expected_bar_date(market, now=now)
    if expected is None:
        return None
    newest = bar_date_only(bars_up_to)
    if newest is None:
        return (
            f"bars carry no usable date (bars_up_to={bars_up_to!r}); "
            f"expected session {expected.isoformat()}"
        )
    if newest < expected:
        return (
            f"stale bars: newest completed bar {newest.isoformat()} < "
            f"expected session {expected.isoformat()}"
        )
    return None
