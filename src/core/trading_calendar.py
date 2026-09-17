# -*- coding: utf-8 -*-
"""Exchange calendars for the clock gate (src/tiered_analysis/run_gate.py).

What the tiered app needs from a market's calendar: which market a
symbol trades on, the current time in that market's zone, today's
regular-session open/close, and the latest completed session's date.
exchange-calendars is optional — without it every lookup fails open.
"""

import logging
from datetime import date, datetime
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from src.services.market_symbol_utils import get_suffix_market

logger = logging.getLogger(__name__)

# Exchange-calendars availability
_XCALS_AVAILABLE = False
try:
    import exchange_calendars as xcals
    _XCALS_AVAILABLE = True
except ImportError:
    logger.warning(
        "exchange-calendars not installed; trading day check disabled. "
        "Run: pip install exchange-calendars"
    )

# Market -> exchange code (exchange-calendars)
MARKET_EXCHANGE = {"cn": "XSHG", "hk": "XHKG", "us": "XNYS", "jp": "XTKS", "kr": "XKRX", "tw": "XTAI"}

# Market -> IANA timezone for "today"
MARKET_TIMEZONE = {
    "cn": "Asia/Shanghai",
    "hk": "Asia/Hong_Kong",
    "us": "America/New_York",
    "jp": "Asia/Tokyo",
    "kr": "Asia/Seoul",
    "tw": "Asia/Taipei",
}


def calendar_available() -> bool:
    """Public probe: is the exchange-calendars library importable?"""
    return _XCALS_AVAILABLE


def get_market_for_stock(code: str) -> Optional[str]:
    """
    Infer market region for a stock code.

    Returns:
        'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw' | None (None = unrecognized, fail-open: treat as open)
    """
    if not code or not isinstance(code, str):
        return None
    code = (code or "").strip().upper()

    from data_provider import is_us_stock_code, is_us_index_code, is_hk_stock_code

    if is_us_stock_code(code) or is_us_index_code(code):
        return "us"
    if is_hk_stock_code(code):
        return "hk"
    suffix_market = get_suffix_market(code)
    if suffix_market:
        return suffix_market
    # A-share: 6-digit numeric
    if code.isdigit() and len(code) == 6:
        return "cn"
    return None


def get_market_now(
    market: Optional[str], current_time: Optional[datetime] = None
) -> datetime:
    """
    Return current time in the market's local timezone.

    If current_time is naive, treat it as already expressed in the market timezone.
    Unknown markets fall back to the given datetime (or local system time).
    """
    tz_name = MARKET_TIMEZONE.get(market or "")

    if current_time is None:
        if tz_name:
            return datetime.now(ZoneInfo(tz_name))
        return datetime.now()

    if not tz_name:
        return current_time

    tz = ZoneInfo(tz_name)
    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=tz)
    return current_time.astimezone(tz)


def get_effective_trading_date(
    market: Optional[str], current_time: Optional[datetime] = None
) -> date:
    """
    Resolve the latest reusable daily-bar date for checkpoint/resume logic.

    Rules:
    - Non-trading day / holiday: previous trading session
    - Trading day before market close: previous completed trading session
    - Trading day after market close: current trading session
    - Calendar lookup failure: fail-open to market-local natural date
    """
    market_now = get_market_now(market, current_time=current_time)
    fallback_date = market_now.date()

    if not _XCALS_AVAILABLE:
        return fallback_date

    ex = MARKET_EXCHANGE.get(market or "")
    tz_name = MARKET_TIMEZONE.get(market or "")
    if not ex or not tz_name:
        return fallback_date

    try:
        cal = xcals.get_calendar(ex)
        local_date = market_now.date()

        if not cal.is_session(local_date):
            return cal.date_to_session(local_date, direction="previous").date()

        session = cal.date_to_session(local_date, direction="previous")
        session_close = cal.session_close(session)
        if hasattr(session_close, "tz_convert"):
            close_local = session_close.tz_convert(tz_name).to_pydatetime()
        elif session_close.tzinfo is not None:
            close_local = session_close.astimezone(ZoneInfo(tz_name))
        else:
            close_local = session_close.replace(tzinfo=ZoneInfo(tz_name))

        if market_now >= close_local:
            return session.date()

        return cal.previous_session(session).date()
    except Exception as e:
        logger.warning("trading_calendar.get_effective_trading_date fail-open: %s", e)
        return fallback_date


def _as_market_datetime(value: Any, tz_name: str) -> Optional[datetime]:
    """
    Convert exchange-calendar timestamps into market-local datetimes.

    Returns None for missing or pandas NaT-like values. Naive datetimes are
    interpreted as already expressed in the target market timezone, matching
    get_market_now()'s current_time contract.
    """
    if value is None:
        return None
    if pd.isna(value):
        return None

    try:
        if isinstance(value, pd.Timestamp):
            if value.tzinfo is None:
                dt = value.to_pydatetime()
            else:
                dt = value.tz_convert(tz_name).to_pydatetime()
        elif isinstance(value, datetime):
            dt = value
        elif hasattr(value, "to_pydatetime"):
            dt = value.to_pydatetime()
        else:
            return None
    except (AttributeError, TypeError, ValueError):
        return None

    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _session_open_close_for_today(
    market: str,
    market_now: datetime,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    ex = MARKET_EXCHANGE.get(market)
    tz_name = MARKET_TIMEZONE.get(market)
    if not ex or not tz_name or not _XCALS_AVAILABLE:
        return None, None

    cal = xcals.get_calendar(ex)
    local_date = market_now.date()
    if not cal.is_session(local_date):
        return None, None

    session = cal.date_to_session(local_date, direction="previous")
    return (
        _as_market_datetime(cal.session_open(session), tz_name),
        _as_market_datetime(cal.session_close(session), tz_name),
    )


def get_session_window(
    market: Optional[str], current_time: Optional[datetime] = None
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Public wrapper: today's regular-session open/close in market-local time.

    Returns (None, None) when today is not a trading session, the market is
    unknown, or exchange-calendars is unavailable/errors (fail-open, logged).
    """
    if market not in MARKET_EXCHANGE:
        return None, None
    market_now = get_market_now(market, current_time=current_time)
    try:
        return _session_open_close_for_today(market, market_now)
    except Exception as e:
        logger.warning("trading_calendar.get_session_window fail-open: %s", e)
        return None, None
