# -*- coding: utf-8 -*-
"""SEC EDGAR companyfacts (XBRL) series extraction for fundamentals.

Pure functions over the companyfacts JSON — no network. Three reads:

- **Annual series** — 10-K fiscal-year values (the v1 read; margins,
  ROE and the balance-sheet ratios are computed strictly within one
  fiscal period).
- **Quarterly series** — rows whose start→end duration is one quarter
  (~90 days), from 10-Q filings (10-K rows are accepted too: a few
  filers tag Q4 frames there). Powers the quarterly growth fields —
  annual YoY was retired for swing use (TODO audit 2026-07-29).
- **TTM** — trailing-twelve-month value for year-to-date concepts
  (cash-flow statements in 10-Qs are cumulative): latest FY + latest
  YTD − the same YTD span one year earlier. Falls back to the plain FY
  value when the YTD pieces are missing, and says so in the basis.

Restatements: later rows for the same period end override earlier ones
(the row list is filing-ordered).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: One quarter / one fiscal year, with slack for 4-4-5 calendars and
#: 53-week fiscal years.
QUARTER_MIN_DAYS, QUARTER_MAX_DAYS = 75, 105
YEAR_MIN_DAYS, YEAR_MAX_DAYS = 350, 380
#: Matching windows: the same quarter one year earlier / the previous
#: quarter, as day distances between period ends.
YEAR_AGO_MIN_DAYS, YEAR_AGO_MAX_DAYS = 345, 385
PRIOR_QTR_MIN_DAYS, PRIOR_QTR_MAX_DAYS = 75, 106
#: Two YTD spans "match" across years when their durations differ less.
YTD_SPAN_SLACK_DAYS = 21

REVENUE_CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
)
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
OPERATING_CASH_FLOW_CONCEPTS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
CAPEX_CONCEPTS = ("PaymentsToAcquirePropertyPlantAndEquipment",)


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _pick_unit(units: Mapping[str, Any]) -> List[Any]:
    for preferred in ("USD", "USD/shares"):
        if preferred in units:
            return units[preferred]
    for rows in units.values():
        return rows
    return []


def _concept_rows(facts: Mapping[str, Any], concept: str) -> List[Mapping[str, Any]]:
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    entry = gaap.get(concept)
    if not isinstance(entry, Mapping):
        return []
    units = entry.get("units")
    if not isinstance(units, Mapping):
        return []
    return [row for row in _pick_unit(units) if isinstance(row, Mapping)]


def extract_annual_series(facts: Mapping[str, Any], concept: str) -> Dict[str, float]:
    """Fiscal-year values keyed by period-end date, 10-K/FY rows only.

    Later rows for the same period end (restatements in newer filings)
    override earlier ones.
    """
    series: Dict[str, float] = {}
    for row in _concept_rows(facts, concept):
        if str(row.get("fp", "")).upper() != "FY":
            continue
        if str(row.get("form", "")).upper() != "10-K":
            continue
        end = row.get("end")
        value = _to_float(row.get("val"))
        if end and value is not None:
            series[str(end)] = value
    return series


def _row_span_days(row: Mapping[str, Any]) -> Optional[int]:
    start = _to_date(row.get("start"))
    end = _to_date(row.get("end"))
    if start is None or end is None:
        return None
    return (end - start).days


def extract_quarterly_series(
    facts: Mapping[str, Any], concept: str
) -> Dict[str, float]:
    """Single-quarter values keyed by period-end date (~90-day spans)."""
    series: Dict[str, float] = {}
    for row in _concept_rows(facts, concept):
        if str(row.get("form", "")).upper() not in ("10-Q", "10-K"):
            continue
        span = _row_span_days(row)
        if span is None or not QUARTER_MIN_DAYS <= span <= QUARTER_MAX_DAYS:
            continue
        value = _to_float(row.get("val"))
        if value is not None:
            series[str(row.get("end"))] = value
    return series


def best_series(
    facts: Mapping[str, Any],
    concepts: Tuple[str, ...],
    extractor=extract_annual_series,
) -> Dict[str, float]:
    """The concept variant with the most recent data wins.

    Companies migrate between XBRL tags (e.g. Apple stopped filing plain
    ``Revenues`` after FY2018); taking the first non-empty concept would
    silently serve years-stale numbers.
    """
    best: Dict[str, float] = {}
    best_end = ""
    for concept in concepts:
        series = extractor(facts, concept)
        if series and max(series) > best_end:
            best, best_end = series, max(series)
    return best


def _find_end_near(
    series: Dict[str, float], anchor: date, min_days: int, max_days: int
) -> Optional[str]:
    """The series key whose end sits min..max days BEFORE the anchor."""
    for end in sorted(series, reverse=True):
        end_date = _to_date(end)
        if end_date is None:
            continue
        distance = (anchor - end_date).days
        if min_days <= distance <= max_days:
            return end
    return None


def quarterly_yoy_pct(
    series: Dict[str, float], end: str
) -> Optional[Tuple[float, float, float]]:
    """(yoy %, this quarter, same quarter last year) for a period end."""
    anchor = _to_date(end)
    current = series.get(end)
    if anchor is None or current is None:
        return None
    year_ago_end = _find_end_near(
        series, anchor, YEAR_AGO_MIN_DAYS, YEAR_AGO_MAX_DAYS
    )
    if year_ago_end is None:
        return None
    prior = series[year_ago_end]
    if prior == 0:
        return None
    return ((current - prior) / abs(prior) * 100.0, current, prior)


def prior_quarter_end(series: Dict[str, float], end: str) -> Optional[str]:
    anchor = _to_date(end)
    if anchor is None:
        return None
    return _find_end_near(series, anchor, PRIOR_QTR_MIN_DAYS, PRIOR_QTR_MAX_DAYS)


# ---------------------------------------------------------------------------
# TTM for year-to-date (cash-flow) concepts
# ---------------------------------------------------------------------------


def _ytd_rows(facts: Mapping[str, Any], concept: str) -> List[Tuple[date, date, float]]:
    """(start, end, value) rows from 10-Q filings — cumulative spans."""
    rows: List[Tuple[date, date, float]] = []
    seen: Dict[Tuple[date, date], int] = {}
    for row in _concept_rows(facts, concept):
        if str(row.get("form", "")).upper() != "10-Q":
            continue
        start, end = _to_date(row.get("start")), _to_date(row.get("end"))
        value = _to_float(row.get("val"))
        if start is None or end is None or value is None:
            continue
        key = (start, end)
        if key in seen:  # restatement: later filing overrides
            rows[seen[key]] = (start, end, value)
        else:
            seen[key] = len(rows)
            rows.append((start, end, value))
    return rows


def ttm_value(
    facts: Mapping[str, Any], concepts: Tuple[str, ...]
) -> Optional[Tuple[float, str, str]]:
    """(value, period end, basis) — basis is "ttm" or "annual".

    TTM = latest FY + latest YTD − the matching YTD one year earlier.
    When the YTD pieces are missing (or no 10-Q is newer than the 10-K),
    the plain fiscal-year value ships with basis "annual" — an honest
    downgrade, never a silently mixed period.
    """
    annual = best_series(facts, concepts, extract_annual_series)
    if not annual:
        return None
    fy_end = max(annual)
    fy_value = annual[fy_end]
    fy_end_date = _to_date(fy_end)

    ytd: List[Tuple[date, date, float]] = []
    for concept in concepts:
        rows = _ytd_rows(facts, concept)
        if rows and (not ytd or max(r[1] for r in rows) > max(r[1] for r in ytd)):
            ytd = rows
    if not ytd or fy_end_date is None:
        return fy_value, fy_end, "annual"

    latest_start, latest_end, latest_value = max(ytd, key=lambda r: r[1])
    if latest_end <= fy_end_date:
        return fy_value, fy_end, "annual"

    span = (latest_end - latest_start).days
    prior = [
        row for row in ytd
        if abs((row[1] - row[0]).days - span) <= YTD_SPAN_SLACK_DAYS
        and YEAR_AGO_MIN_DAYS <= (latest_end - row[1]).days <= YEAR_AGO_MAX_DAYS
    ]
    if not prior:
        return fy_value, fy_end, "annual"
    prior_value = max(prior, key=lambda r: r[1])[2]
    return (
        fy_value + latest_value - prior_value,
        latest_end.isoformat(),
        "ttm",
    )
