# -*- coding: utf-8 -*-
"""Run-gate tests (owner decisions 2026-08-08): the clock gate blocks
runs from market open until 30 minutes past the close in exchange time,
and the staleness rules define "the newest completed bar" relative to
the most recent completed trading session.

All tests run offline: exchange-calendars is absent in the test env, so
the gate exercises its weekday-arithmetic fallback (fixed session times,
no holidays) — which is also the production behavior whenever the
calendar library fails.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.tiered_analysis.run_gate import (
    RUN_BUFFER_MINUTES,
    bar_date_only,
    clock_gate,
    expected_bar_date,
    staleness_stop_reason,
    trim_incomplete_bars,
)

NY = ZoneInfo("America/New_York")
SH = ZoneInfo("Asia/Shanghai")


def ny(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


class Bar:
    def __init__(self, day):
        self.date = day


# ---------------------------------------------------------------------------
# clock gate
# ---------------------------------------------------------------------------

class TestClockGate:
    def test_blocked_during_us_trading_day(self):
        # Wednesday 2026-08-05, 14:00 New York — mid-session.
        result = clock_gate("AAPL", now=ny(2026, 8, 5, 14))
        assert result.blocked is True
        assert result.market == "us"

    def test_blocked_within_buffer_after_close(self):
        # 16:10 — closed, but inside the 30-minute vendor buffer.
        assert RUN_BUFFER_MINUTES == 30
        result = clock_gate("AAPL", now=ny(2026, 8, 5, 16, 10))
        assert result.blocked is True

    def test_allowed_after_buffer(self):
        result = clock_gate("AAPL", now=ny(2026, 8, 5, 16, 31))
        assert result.blocked is False

    def test_allowed_before_open(self):
        # 07:00 — yesterday's close is final; mornings are fine.
        result = clock_gate("AAPL", now=ny(2026, 8, 5, 7))
        assert result.blocked is False

    def test_allowed_on_weekend(self):
        # Saturday 2026-08-08 midday.
        result = clock_gate("AAPL", now=ny(2026, 8, 8, 12))
        assert result.blocked is False

    def test_override_always_passes(self):
        result = clock_gate("AAPL", now=ny(2026, 8, 5, 14), override=True)
        assert result.blocked is False

    def test_unknown_market_fails_open(self):
        result = clock_gate("???bogus", now=ny(2026, 8, 5, 14))
        assert result.blocked is False
        assert result.market is None

    def test_cn_market_uses_its_own_clock(self):
        # 10:00 Shanghai on a Wednesday — A-share session, blocked.
        now = datetime(2026, 8, 5, 10, 0, tzinfo=SH)
        result = clock_gate("600519", now=now)
        assert result.blocked is True
        assert result.market == "cn"

    def test_cn_after_close_plus_buffer_allowed(self):
        # 15:31 Shanghai — CN closes 15:00; buffer passed.
        now = datetime(2026, 8, 5, 15, 31, tzinfo=SH)
        result = clock_gate("600519", now=now)
        assert result.blocked is False

    def test_blocked_result_carries_session_bounds(self):
        # 2026-08-11 addition: the popup words today's hours from the
        # gate, so a blocked result must carry the session bounds in
        # market-local tz-aware datetimes.
        result = clock_gate("AAPL", now=ny(2026, 8, 5, 14))
        assert result.blocked is True
        assert result.session_open == ny(2026, 8, 5, 9, 30)
        assert result.session_close == ny(2026, 8, 5, 16, 0)

    def test_weekend_result_has_no_session_bounds(self):
        result = clock_gate("AAPL", now=ny(2026, 8, 8, 12))
        assert result.blocked is False
        assert result.session_open is None
        assert result.session_close is None


# ---------------------------------------------------------------------------
# expected completed session
# ---------------------------------------------------------------------------

class TestExpectedBarDate:
    def test_after_close_expects_today(self):
        assert expected_bar_date("us", now=ny(2026, 8, 5, 17)) == date(2026, 8, 5)

    def test_during_session_expects_previous_weekday(self):
        # Mid-session Wednesday: today's bar does not exist yet.
        assert expected_bar_date("us", now=ny(2026, 8, 5, 14)) == date(2026, 8, 4)

    def test_monday_morning_expects_friday(self):
        assert expected_bar_date("us", now=ny(2026, 8, 3, 8)) == date(2026, 7, 31)

    def test_saturday_expects_friday(self):
        assert expected_bar_date("us", now=ny(2026, 8, 8, 12)) == date(2026, 8, 7)

    def test_unknown_market_is_none(self):
        assert expected_bar_date(None) is None


# ---------------------------------------------------------------------------
# staleness + partial-bar trim
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_fresh_bars_pass(self):
        reason = staleness_stop_reason(
            "2026-08-05", "us", now=ny(2026, 8, 5, 17)
        )
        assert reason is None

    def test_stale_bars_stop(self):
        reason = staleness_stop_reason(
            "2026-08-04", "us", now=ny(2026, 8, 5, 17)
        )
        assert reason is not None and "stale" in reason

    def test_run_anyway_during_session_expects_yesterday(self):
        # The clock-gate override run at 14:00: yesterday's bar is the
        # newest completed one — NOT stale.
        reason = staleness_stop_reason(
            "2026-08-04", "us", now=ny(2026, 8, 5, 14)
        )
        assert reason is None

    def test_missing_bar_date_stops(self):
        reason = staleness_stop_reason(None, "us", now=ny(2026, 8, 5, 17))
        assert reason is not None and "no usable date" in reason

    def test_unknown_market_fails_open(self):
        assert staleness_stop_reason("2020-01-01", None) is None

    def test_datetime_suffix_tolerated(self):
        reason = staleness_stop_reason(
            "2026-08-05 00:00:00", "us", now=ny(2026, 8, 5, 17)
        )
        assert reason is None


class TestTrimIncompleteBars:
    def test_drops_bars_after_expected(self):
        bars = [Bar("2026-08-04"), Bar("2026-08-05")]
        kept = trim_incomplete_bars(bars, date(2026, 8, 4))
        assert [bar.date for bar in kept] == ["2026-08-04"]

    def test_keeps_everything_when_expected_unknown(self):
        bars = [Bar("2026-08-04"), Bar("2026-08-05")]
        assert len(trim_incomplete_bars(bars, None)) == 2

    def test_keeps_undated_bars(self):
        bars = [Bar(None), Bar("2026-08-04")]
        assert len(trim_incomplete_bars(bars, date(2026, 8, 4))) == 2


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-05", date(2026, 8, 5)),
        ("2026-08-05 00:00:00", date(2026, 8, 5)),
        (None, None),
        ("garbage", None),
    ],
)
def test_bar_date_only(raw, expected):
    assert bar_date_only(raw) == expected
