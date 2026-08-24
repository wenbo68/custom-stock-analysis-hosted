# -*- coding: utf-8 -*-
"""Next-earnings-date lookup (outlook redesign, 2026-07-20).

Warning-only by design: the date never gates a plan and never touches a
number. Within EARNINGS_WARNING_DAYS of the next report the run shows
"N days until next earnings — expect turbulence"; otherwise the date (or
its absence) sits quietly in the run detail.

US symbols use yfinance's earnings calendar. CN/HK calendars need
market-specific sources and are a future slice — those markets return an
empty result with an explanatory note, never a fake date. The fetcher is
injectable so tests stay offline.
"""
from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .providers.base import Market

logger = logging.getLogger(__name__)

#: Show the turbulence warning when the next report is this close.
EARNINGS_WARNING_DAYS = 7


@dataclass(frozen=True)
class EarningsInfo:
    """Next earnings date for one symbol; empty fields are honest gaps."""

    next_date: Optional[str] = None  # ISO date, e.g. "2026-07-29"
    days_until: Optional[int] = None
    note: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def is_near(self) -> bool:
        return self.days_until is not None and 0 <= self.days_until <= EARNINGS_WARNING_DAYS

    def to_detail(self) -> Dict[str, Any]:
        return {
            "next_date": self.next_date,
            "days_until": self.days_until,
            "warning_days": EARNINGS_WARNING_DAYS,
            "is_near": self.is_near,
            "note": self.note,
        }


def _as_date(value: Any) -> Optional[_dt.date]:
    """Best-effort date from yfinance's mixed types (date/datetime/Timestamp/str)."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        try:
            return to_pydatetime().date()
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _yfinance_earnings_dates(symbol: str) -> List[_dt.date]:
    """All earnings dates yfinance knows for a US symbol (may be empty)."""
    import yfinance as yf

    calendar = yf.Ticker(symbol).calendar
    raw: List[Any] = []
    if isinstance(calendar, dict):
        value = calendar.get("Earnings Date")
        if isinstance(value, (list, tuple)):
            raw = list(value)
        elif value is not None:
            raw = [value]
    else:  # older yfinance returns a DataFrame indexed by row name
        try:
            raw = list(calendar.loc["Earnings Date"])
        except Exception:
            raw = []
    return [d for d in (_as_date(v) for v in raw) if d is not None]


def next_earnings_info(
    symbol: str,
    market: Market,
    today: Optional[_dt.date] = None,
    fetcher: Optional[Callable[[str], List[_dt.date]]] = None,
) -> EarningsInfo:
    """Next earnings date on/after ``today``; failures become notes, never
    raises — this is a warning layer, not a data dependency."""
    if market is not Market.US:
        return EarningsInfo(
            note=f"earnings calendar not yet available for market {market.value}"
        )
    if today is None:
        today = _dt.date.today()
    if fetcher is None:
        fetcher = _yfinance_earnings_dates

    try:
        dates = fetcher(symbol)
    except Exception as exc:
        logger.warning("earnings date fetch failed for %s: %s", symbol, exc)
        return EarningsInfo(note=f"earnings date fetch failed: {exc}")

    future = sorted(d for d in dates if d >= today)
    if not future:
        return EarningsInfo(note="no upcoming earnings date found")
    next_date = future[0]
    return EarningsInfo(
        next_date=next_date.isoformat(),
        days_until=(next_date - today).days,
    )


def earnings_warning(info: EarningsInfo) -> Optional[str]:
    """The user-facing turbulence warning, or None outside the window."""
    if not info.is_near:
        return None
    return (
        f"{info.days_until} day(s) until next earnings ({info.next_date}) — "
        "expect turbulence around the report; a single announcement can gap "
        "the price far past any stop"
    )


def earnings_from_dimensions(
    dimensions: Any, today: Optional[_dt.date] = None
) -> EarningsInfo:
    """The next earnings date the fundamentals provider already fetched
    (no second network call). Shared by the run-detail block and the
    plan review's earnings gate (2026-07-27) so both read one source.

    Reads all three payload generations: v3 (2026-07-31) nests the date
    under ``quarterly_report`` with no days field — days are computed
    here from the date; v2 (2026-07-29) nests both fields as envelopes
    under ``earnings``; v1 stored runs carry them flat."""
    from .providers.technicals import metric_value

    if today is None:
        today = _dt.date.today()
    for dim in dimensions:
        if getattr(dim, "dimension", None) != "fundamentals" or not dim.payload:
            continue
        group = dim.payload.get("quarterly_report") or dim.payload.get("earnings")
        source = group if isinstance(group, dict) else dim.payload
        date = metric_value(source.get("next_earnings_date"))
        days = metric_value(source.get("days_until_earnings"))
        if isinstance(date, str) and date:
            if not isinstance(days, int):
                parsed = _as_date(date)
                days = (parsed - today).days if parsed is not None else None
            return EarningsInfo(next_date=date, days_until=days)
    return EarningsInfo(note="no upcoming earnings date found")
