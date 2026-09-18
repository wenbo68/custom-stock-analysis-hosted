# -*- coding: utf-8 -*-
"""US fundamentals provider — v2 envelope payload (regrouped 2026-07-31).

Groups and field names follow the TODO.md final-truth list: ``meta``
(company/sector/industry + data as-of dates), ``balance``,
``profitability`` (incl. free cash flow and its ratio to earnings),
``growth``, ``valuation`` and ``quarterly report`` (the earnings-event
block; the short-lived dividend group was dropped from the list on
2026-07-31). Every published metric ships as a
``{name, explanation, interpretation, value}`` envelope — the same
contract as technicals v2 — and computed metrics carry UI formula
receipts in ``DimensionResult.formulas``. Fields that cannot be
computed stay present with ``value: null`` (blank), never omitted.

Sources, split by what each can actually answer:

- **SEC EDGAR companyfacts (XBRL)** — audited statements: quarterly
  growth (10-Q), profitability / balance ratios (10-K), free cash
  flow (TTM from FY + YTD rows). Series math lives in
  ``edgar_series.py``.
- **Yahoo summary (yfinance)** — market-priced valuation ratios and
  the sector/industry profile.
- **Yahoo earnings data (yfinance)** — the earnings calendar (next
  date), the surprise history, the analyst EPS estimate trend and the
  30-day estimate revision counts.
- **Daily bars** (optional, injected) — the realized report-day moves.

EDGAR statements + Yahoo valuation are the core: either failing blanks
its fields explicitly (nulls with notes). The event and
history blocks are auxiliary — they warn, never degrade — matching the
long-standing rule that an event-calendar miss is not a statements
failure. An ok-but-empty response is treated as missing, never as a
silent blank.

SEC requires a descriptive User-Agent with contact info: set
``SEC_EDGAR_USER_AGENT`` in the environment (see .env.example).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
    note_fields,
)
from .edgar_series import (
    EPS_CONCEPTS,
    CAPEX_CONCEPTS,
    OPERATING_CASH_FLOW_CONCEPTS,
    REVENUE_CONCEPTS,
    best_series,
    extract_annual_series,
    extract_quarterly_series,
    prior_quarter_end,
    quarterly_yoy_pct,
    ttm_value,
)
from .technicals import make_metric, metric_value

EDGAR_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

#: The Yahoo Finance pages showing the cited figures: yfinance itself has
#: no per-request page, but the same numbers are published on the quote
#: subpages — cited so readers can verify at the source.
YAHOO_KEY_STATISTICS_URL = "https://finance.yahoo.com/quote/{symbol}/key-statistics"
YAHOO_ANALYSIS_URL = "https://finance.yahoo.com/quote/{symbol}/analysis"
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_EDGAR_TIMEOUT_SECONDS = 15

# Yahoo .info key -> normalized valuation field, in display order
# (TODO.md order 2026-07-31; P/B retired 2026-07-29: only informative
# for banks/asset-heavy names).
_VALUATION_KEYS = (
    ("marketCap", "market_cap"),
    ("priceToSalesTrailing12Months", "ps_ttm"),
    ("trailingPE", "pe_ttm"),
    ("forwardPE", "pe_forward"),
)

#: XBRL concept for reported earnings (net income) — the denominator of
#: the free-cash-flow-to-earnings ratio.
NET_INCOME_CONCEPTS = ("NetIncomeLoss",)

#: Growth-trend dead band, in percentage points of YoY change: a swing
#: smaller than this is "steady", not a real acceleration/deceleration.
GROWTH_TREND_BAND_PP = 2.0
#: Quarterly EPS YoY is meaningless off a near-zero base.
EPS_YOY_MIN_BASE = 0.05
#: The earnings history window: the last N reported quarters.
SURPRISE_REPORTS = 4
#: Earnings-day moves need at least this many reports to mean anything.
REACTION_MIN_REPORTS = 2


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number  # NaN guard
    return None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _to_count(value: Any) -> Optional[int]:
    """A published analyst count as an int; junk stays None (blank),
    never a fake zero. Yahoo's revisions table hands counts over as
    numpy integers — not Python ints, so ``_to_float``'s isinstance
    check drops them — hence the float() conversion here."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number < 0:  # NaN guard
        return None
    return int(number)


def _ratio_pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100.0


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _has_values(section: Optional[Mapping[str, Any]]) -> bool:
    return bool(section) and any(
        metric_value(node) is not None for node in section.values()
    )


# ---------------------------------------------------------------------------
# Pure metric computations (all offline-testable)
# ---------------------------------------------------------------------------


def growth_trend_label(
    yoy_now: Optional[float], yoy_prior: Optional[float]
) -> Optional[str]:
    """accelerating / slowing / steady with a ±2pp dead band."""
    if yoy_now is None or yoy_prior is None:
        return None
    # Round away float noise before the strict comparison (same edge as
    # macro_economy.trend_label): a delta sitting exactly ON the band must
    # read "steady", not tip over via 2.0000000000000018.
    delta = round(yoy_now - yoy_prior, 9)
    if delta > GROWTH_TREND_BAND_PP:
        return "accelerating"
    if delta < -GROWTH_TREND_BAND_PP:
        return "slowing"
    return "steady"


def quarterly_growth_metrics(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Quarterly YoY + trend for revenue and EPS, with receipt inputs.

    Returns per series: ``yoy`` (%), ``now``/``year_ago`` (the receipt
    ingredients), ``yoy_prior`` (the previous quarter's YoY, feeding the
    trend), ``trend`` and ``end`` (the quarter end used).
    """
    out: Dict[str, Any] = {}
    for series_key, concepts, min_base in (
        ("revenue", REVENUE_CONCEPTS, None),
        ("eps", EPS_CONCEPTS, EPS_YOY_MIN_BASE),
    ):
        series = best_series(facts, concepts, extract_quarterly_series)
        entry: Dict[str, Any] = {
            "yoy": None, "now": None, "year_ago": None,
            "yoy_prior": None, "trend": None, "end": None,
        }
        if series:
            latest = max(series)
            entry["end"] = latest
            current = quarterly_yoy_pct(series, latest)
            if current is not None and (
                min_base is None or abs(current[2]) >= min_base
            ):
                entry["yoy"], entry["now"], entry["year_ago"] = current
            prior_end = prior_quarter_end(series, latest)
            if prior_end is not None:
                prior = quarterly_yoy_pct(series, prior_end)
                if prior is not None and (
                    min_base is None or abs(prior[2]) >= min_base
                ):
                    entry["yoy_prior"] = prior[0]
            entry["trend"] = growth_trend_label(
                entry["yoy"], entry["yoy_prior"]
            )
        out[series_key] = entry
    return out


def annual_statement_metrics(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Margins / ROE / balance-sheet ratios, strictly within one fiscal
    period (the latest revenue period end): mixing numerator and
    denominator from different fiscal years fabricates numbers, so a
    missing same-period counterpart yields None instead. Receipt
    ingredients ride along with each value.
    """
    revenue = best_series(facts, REVENUE_CONCEPTS)
    net_income = extract_annual_series(facts, "NetIncomeLoss")
    gross_profit = extract_annual_series(facts, "GrossProfit")
    operating_income = extract_annual_series(facts, "OperatingIncomeLoss")
    equity = extract_annual_series(facts, "StockholdersEquity")
    liabilities = extract_annual_series(facts, "Liabilities")
    assets_current = extract_annual_series(facts, "AssetsCurrent")
    liabilities_current = extract_annual_series(facts, "LiabilitiesCurrent")

    period_end = max(revenue) if revenue else (max(net_income) if net_income else None)

    def at_period(series: Dict[str, float]) -> Optional[float]:
        return series.get(period_end) if period_end else None

    revenue_now = at_period(revenue)
    net_income_now = at_period(net_income)
    equity_now = at_period(equity)

    return {
        "period_end": period_end,
        "entity_name": facts.get("entityName"),
        "gross_margin_pct": _ratio_pct(at_period(gross_profit), revenue_now),
        "gross_profit": at_period(gross_profit),
        "operating_margin_pct": _ratio_pct(at_period(operating_income), revenue_now),
        "operating_income": at_period(operating_income),
        "revenue": revenue_now,
        "roe_pct": _ratio_pct(net_income_now, equity_now),
        "net_income": net_income_now,
        "equity": equity_now,
        "current_ratio": _ratio(at_period(assets_current), at_period(liabilities_current)),
        "assets_current": at_period(assets_current),
        "liabilities_current": at_period(liabilities_current),
        "debt_to_equity": _ratio(at_period(liabilities), equity_now),
        "liabilities": at_period(liabilities),
    }


def fcf_metrics(facts: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Free cash flow = operating cash flow − capital spending, both on
    the same basis (TTM when the YTD rows allow it, else the latest
    fiscal year). Mismatched bases would fabricate a number, so they
    downgrade together."""
    ocf = ttm_value(facts, OPERATING_CASH_FLOW_CONCEPTS)
    capex = ttm_value(facts, CAPEX_CONCEPTS)
    if ocf is None or capex is None:
        return None
    if ocf[2] != capex[2] or ocf[1] != capex[1]:
        # Recompute both on the annual basis: ttm_value falls back to
        # annual only when TTM pieces are missing, so a mismatch means
        # exactly one side had them.
        ocf_annual = best_series(facts, OPERATING_CASH_FLOW_CONCEPTS)
        capex_annual = best_series(facts, CAPEX_CONCEPTS)
        shared = set(ocf_annual) & set(capex_annual)
        if not shared:
            return None
        end = max(shared)
        return {
            "fcf": ocf_annual[end] - capex_annual[end],
            "operating_cash_flow": ocf_annual[end],
            "capital_spending": capex_annual[end],
            "end": end,
            "basis": "annual",
        }
    return {
        "fcf": ocf[0] - capex[0],
        "operating_cash_flow": ocf[0],
        "capital_spending": capex[0],
        "end": ocf[1],
        "basis": ocf[2],
    }


def fcf_to_earnings_metrics(
    facts: Optional[Mapping[str, Any]], fcf: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Free cash flow as a percent of the SAME period's earnings.

    The earnings figure must match the FCF's basis AND period end (a TTM
    FCF needs a TTM net income ending the same quarter; an annual FCF
    needs the same fiscal year) — mixing periods fabricates numbers, so
    a missing same-period figure returns None (the whole field blank).
    ``pct`` is None when earnings are zero or negative: dividing by a
    loss flips the sign and reads backwards, so the ratio is blank while
    the receipt ingredients stay absent (owner decision 2026-07-30).
    """
    if facts is None or fcf is None:
        return None
    earnings: Optional[float] = None
    if fcf["basis"] == "ttm":
        net_income = ttm_value(facts, NET_INCOME_CONCEPTS)
        if (
            net_income is not None
            and net_income[2] == "ttm"
            and net_income[1] == fcf["end"]
        ):
            earnings = net_income[0]
    else:
        series = best_series(facts, NET_INCOME_CONCEPTS)
        earnings = series.get(fcf["end"]) if series else None
    if earnings is None:
        return None
    return {
        "pct": fcf["fcf"] / earnings * 100.0 if earnings > 0 else None,
        "fcf": fcf["fcf"],
        "earnings": earnings,
    }


def surprise_metrics(
    rows: Sequence[Mapping[str, Any]], today: date
) -> Dict[str, Any]:
    """Beat count + average surprise over the last reported quarters.

    Rows carry ``date`` (ISO), ``eps_estimate``, ``eps_actual``,
    ``surprise_pct``. Only rows with a reported actual on/before today
    count; rows without an estimate are excluded from the beat count
    (you cannot beat a bar that was never set).
    """
    past: List[Tuple[date, Mapping[str, Any]]] = []
    for row in rows:
        try:
            when = date.fromisoformat(str(row.get("date") or "")[:10])
        except ValueError:
            continue
        if when > today or _to_float(row.get("eps_actual")) is None:
            continue
        past.append((when, row))
    past.sort(key=lambda item: item[0], reverse=True)
    recent = past[:SURPRISE_REPORTS]

    beats = total = 0
    surprises: List[float] = []
    for _when, row in recent:
        actual = _to_float(row.get("eps_actual"))
        estimate = _to_float(row.get("eps_estimate"))
        if estimate is not None and actual is not None:
            total += 1
            if actual >= estimate:
                beats += 1
        surprise = _to_float(row.get("surprise_pct"))
        if surprise is None and estimate not in (None, 0) and actual is not None:
            surprise = (actual - estimate) / abs(estimate) * 100.0
        if surprise is not None:
            surprises.append(surprise)

    return {
        "beats": f"{beats}/{total}" if total else None,
        "avg_surprise_pct": _round(mean(surprises)) if surprises else None,
        "report_dates": [when for when, _row in recent],
    }


def reaction_metrics(
    bars: Sequence[Any], report_dates: Sequence[date]
) -> Dict[str, Any]:
    """Realized close-to-close moves around past report dates, from the
    daily bars: last close on/before the report date → first close
    after it (BMO/AMC timing is not distinguishable from date-only
    data, so the bracketing pair is the honest read)."""
    dated: List[Tuple[date, float]] = []
    for bar in bars:
        raw = getattr(bar, "date", None)
        close = getattr(bar, "close", None)
        if raw is None or close is None:
            continue
        try:
            dated.append((date.fromisoformat(str(raw)[:10]), float(close)))
        except ValueError:
            continue
    dated.sort(key=lambda item: item[0])

    moves: List[float] = []
    for report in report_dates:
        before = [close for when, close in dated if when <= report]
        after = [close for when, close in dated if when > report]
        if before and after and before[-1] != 0:
            moves.append((after[0] - before[-1]) / before[-1] * 100.0)

    if len(moves) < REACTION_MIN_REPORTS:
        return {"avg_abs_pct": None, "worst_pct": None, "count": len(moves)}
    return {
        "avg_abs_pct": _round(mean(abs(move) for move in moves)),
        "worst_pct": _round(min(moves)),
        "count": len(moves),
    }


def revision_pct(trend: Mapping[str, Any]) -> Optional[float]:
    """Percent change of the current-quarter consensus EPS estimate vs
    30 days ago (owner swap 2026-08-23: 90d was too slow for a 1-4 week
    hold); a near-zero base makes the percentage meaningless."""
    now = _to_float(trend.get("current"))
    then = _to_float(trend.get("days_ago_30"))
    if now is None or then is None or abs(then) < EPS_YOY_MIN_BASE:
        return None
    return (now - then) / abs(then) * 100.0


# ---------------------------------------------------------------------------
# Default loaders (thin network shims; everything above stays pure)
# ---------------------------------------------------------------------------


def _edgar_user_agent() -> str:
    return os.getenv(
        "SEC_EDGAR_USER_AGENT",
        "daily_stock_analysis tiered-analysis (SEC_EDGAR_USER_AGENT not set)",
    )


_cik_cache: Dict[str, int] = {}


def _resolve_cik(symbol: str) -> int:
    """Ticker -> CIK via SEC's public mapping file (cached in-process)."""
    global _cik_cache
    if not _cik_cache:
        import requests

        response = requests.get(
            EDGAR_TICKERS_URL,
            headers={"User-Agent": _edgar_user_agent()},
            timeout=_EDGAR_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        _cik_cache = {
            str(row.get("ticker", "")).upper(): int(row["cik_str"])
            for row in response.json().values()
            if isinstance(row, Mapping) and row.get("cik_str") is not None
        }
    cik = _cik_cache.get(symbol.upper())
    if cik is None:
        raise LookupError(f"no SEC CIK found for ticker {symbol!r}")
    return cik


def _default_facts_loader(symbol: str) -> Mapping[str, Any]:
    import requests

    cik = _resolve_cik(symbol)
    response = requests.get(
        EDGAR_COMPANYFACTS_URL.format(cik=cik),
        headers={"User-Agent": _edgar_user_agent()},
        timeout=_EDGAR_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _default_info_loader(symbol: str) -> Mapping[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.get_info() if hasattr(ticker, "get_info") else (ticker.info or {})
    return info if isinstance(info, Mapping) else {}


def _default_earnings_lookup(symbol: str) -> Mapping[str, Any]:
    """Next earnings date as payload-ready fields (empty dict = unknown)."""
    from ..earnings import next_earnings_info

    info = next_earnings_info(symbol, Market.US)
    if info.next_date is None:
        return {}
    return {
        "next_earnings_date": info.next_date,
        "days_until_earnings": info.days_until,
    }


def _default_earnings_history_loader(symbol: str) -> List[Dict[str, Any]]:
    """Past + upcoming earnings rows from yfinance's earnings-dates table."""
    import yfinance as yf

    frame = yf.Ticker(symbol).get_earnings_dates(limit=12)
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: List[Dict[str, Any]] = []
    for stamp, record in frame.iterrows():
        when = stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10]
        rows.append(
            {
                "date": when,
                "eps_estimate": record.get("EPS Estimate"),
                "eps_actual": record.get("Reported EPS"),
                "surprise_pct": record.get("Surprise(%)"),
            }
        )
    return rows


def _default_eps_trend_loader(symbol: str) -> Mapping[str, Any]:
    """Current-quarter consensus EPS estimate now vs 30 days ago."""
    import yfinance as yf

    frame = yf.Ticker(symbol).eps_trend
    if frame is None or getattr(frame, "empty", True):
        return {}
    if "0q" not in frame.index:
        return {}
    row = frame.loc["0q"]
    return {"current": row.get("current"), "days_ago_30": row.get("30daysAgo")}


def _default_eps_revisions_loader(symbol: str) -> Mapping[str, Any]:
    """How many analysts raised / cut their current-quarter EPS estimate
    in the last 30 days (Yahoo's revisions table; columns verified live
    2026-08-23: upLast7days, upLast30days, downLast30days,
    downLast7Days)."""
    import yfinance as yf

    frame = yf.Ticker(symbol).eps_revisions
    if frame is None or getattr(frame, "empty", True):
        return {}
    if "0q" not in frame.index:
        return {}
    row = frame.loc["0q"]
    return {"up": row.get("upLast30days"), "down": row.get("downLast30days")}


def _default_today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------

#: Payload paths ("group.key") each data source feeds — the fields a
#: source failure blanks, so its note can sit beside them on the report
#: page.
VALUATION_FIELDS = (
    "valuation.market_cap", "valuation.ps_ttm",
    "valuation.pe_ttm", "valuation.pe_forward",
)
PROFILE_FIELDS = ("meta.sector", "meta.industry")
EDGAR_FIELDS = (
    "balance.current_ratio", "balance.debt_to_equity",
    "profitability.gross_margin_pct", "profitability.operating_margin_pct",
    "profitability.roe_pct", "profitability.fcf",
    "profitability.fcf_to_earnings_pct",
    "growth.revenue_yoy_q", "growth.revenue_growth_trend",
    "growth.eps_yoy_q", "growth.eps_growth_trend",
    "meta.entity_name", "meta.period_end", "meta.period_end_q",
)
SURPRISE_FIELDS = (
    "quarterly_report.beats_4q", "quarterly_report.avg_surprise_pct_4q",
)
REACTION_FIELDS = (
    "quarterly_report.reaction_avg_abs_pct",
    "quarterly_report.reaction_worst_pct",
)


class FundamentalsUSProvider(DimensionProvider):
    """NUMERIC US fundamentals: EDGAR statements + Yahoo market data."""

    dimension = "fundamentals"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        facts_loader: Callable[[str], Mapping[str, Any]] = _default_facts_loader,
        info_loader: Callable[[str], Mapping[str, Any]] = _default_info_loader,
        earnings_lookup: Callable[[str], Mapping[str, Any]] = _default_earnings_lookup,
        earnings_history_loader: Callable[
            [str], Sequence[Mapping[str, Any]]
        ] = _default_earnings_history_loader,
        eps_trend_loader: Callable[[str], Mapping[str, Any]] = _default_eps_trend_loader,
        eps_revisions_loader: Callable[
            [str], Mapping[str, Any]
        ] = _default_eps_revisions_loader,
        bars_loader: Optional[Callable[[str], Sequence[Any]]] = None,
        today: Callable[[], date] = _default_today,
    ) -> None:
        self._facts_loader = facts_loader
        self._info_loader = info_loader
        self._earnings_lookup = earnings_lookup
        self._earnings_history_loader = earnings_history_loader
        self._eps_trend_loader = eps_trend_loader
        self._eps_revisions_loader = eps_revisions_loader
        self._bars_loader = bars_loader
        self._today = today

    def supports(self, market: Market) -> bool:
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        citations: List[Citation] = []
        warnings: List[str] = []
        field_notes: Dict[str, List[str]] = {}
        formulas: Dict[str, Any] = {}

        info = self._load_info(symbol, warnings, field_notes)
        facts = self._load_facts(symbol, warnings, field_notes)

        # Group order = display order (TODO.md final-truth list).
        payload: Dict[str, Any] = {
            "meta": self._meta_group(info, facts),
            "balance": self._balance_group(facts, formulas),
            "profitability": self._profitability_group(facts, formulas),
            "growth": self._growth_group(facts, formulas),
            "valuation": self._valuation_group(
                symbol, info, citations, warnings, field_notes
            ),
            "quarterly_report": self._quarterly_report_group(
                symbol, citations, warnings, field_notes, formulas
            ),
        }

        edgar_ok = facts is not None and any(
            _has_values(payload[group])
            for group in ("growth", "profitability", "balance")
        )
        if facts is not None and not edgar_ok:
            note_fields(
                warnings, field_notes,
                f"EDGAR returned no usable statement facts for {symbol}",
                EDGAR_FIELDS,
            )
        if edgar_ok:
            cik = facts.get("cik")
            citations.append(
                Citation(
                    source_name="SEC EDGAR companyfacts (XBRL)",
                    url=(
                        EDGAR_COMPANYFACTS_URL.format(cik=int(cik))
                        if isinstance(cik, (int, float, str)) and str(cik).isdigit()
                        else None
                    ),
                )
            )
        # Even with both sources down the payload ships (every field
        # blank, each with its note) — degradation lives on the fields,
        # never on a card-level grade (2026-08-19).
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            payload=payload,
            citations=citations,
            warnings=warnings,
            formulas=formulas or None,
            field_notes=field_notes or None,
        )

    # ---- source fetches -------------------------------------------------

    def _load_info(
        self,
        symbol: str,
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Optional[Mapping[str, Any]]:
        try:
            return self._info_loader(symbol) or {}
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"Yahoo summary failed for {symbol}: {exc}",
                VALUATION_FIELDS + PROFILE_FIELDS,
            )
            return None

    def _load_facts(
        self,
        symbol: str,
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Optional[Mapping[str, Any]]:
        try:
            return self._facts_loader(symbol)
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"EDGAR fundamentals failed for {symbol}: {exc}",
                EDGAR_FIELDS,
            )
            return None

    # ---- payload groups --------------------------------------------------

    def _quarterly_report_group(
        self,
        symbol: str,
        citations: List[Citation],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
        formulas: Dict[str, Any],
    ) -> Dict[str, Any]:
        today = self._today()

        next_date: Optional[str] = None
        try:
            fields = self._earnings_lookup(symbol) or {}
            raw_date = fields.get("next_earnings_date")
            next_date = raw_date if isinstance(raw_date, str) else None
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"earnings date lookup failed for {symbol}: {exc}",
                ("quarterly_report.next_earnings_date",),
            )

        surprises: Dict[str, Any] = {
            "beats": None, "avg_surprise_pct": None, "report_dates": []
        }
        try:
            rows = self._earnings_history_loader(symbol)
        except Exception as exc:
            rows = []
            note_fields(
                warnings, field_notes,
                f"earnings history failed for {symbol}: {exc}",
                SURPRISE_FIELDS + REACTION_FIELDS,
            )
        if rows:
            surprises = surprise_metrics(rows, today)
            citations.append(
                Citation(
                    source_name="Earnings history via Yahoo Finance (yfinance)",
                    url=YAHOO_ANALYSIS_URL.format(symbol=symbol),
                )
            )
        else:
            note_fields(
                warnings, field_notes,
                f"no earnings history rows for {symbol} — the beat and "
                "report-day-move fields are blank",
                SURPRISE_FIELDS + REACTION_FIELDS,
            )

        reaction: Dict[str, Any] = {"avg_abs_pct": None, "worst_pct": None, "count": 0}
        if surprises["report_dates"] and self._bars_loader is not None:
            try:
                bars = self._bars_loader(symbol)
            except Exception as exc:
                bars = []
                note_fields(
                    warnings, field_notes,
                    f"bars for earnings reaction failed: {exc}",
                    REACTION_FIELDS,
                )
            if bars:
                reaction = reaction_metrics(bars, surprises["report_dates"])
                if reaction["avg_abs_pct"] is None and reaction["count"]:
                    note_fields(
                        warnings, field_notes,
                        "too few earnings reports inside the bar history "
                        f"({reaction['count']}) for the earnings-day move",
                        REACTION_FIELDS,
                    )

        revision: Optional[float] = None
        try:
            trend = self._eps_trend_loader(symbol) or {}
        except Exception as exc:
            trend = {}
            note_fields(
                warnings, field_notes,
                f"EPS estimate trend failed for {symbol}: {exc}",
                ("quarterly_report.eps_rev_30d_pct",),
            )
        if trend:
            revision = revision_pct(trend)

        revisions: Mapping[str, Any] = {}
        try:
            revisions = self._eps_revisions_loader(symbol) or {}
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"EPS revision counts failed for {symbol}: {exc}",
                (
                    "quarterly_report.eps_up_revisions_30d",
                    "quarterly_report.eps_down_revisions_30d",
                ),
            )

        if surprises["beats"] is not None:
            formulas["quarterly_report.beats_4q"] = {
                "formula": (
                    "reports with actual EPS ≥ the analyst estimate, out "
                    f"of the last {SURPRISE_REPORTS} reported quarters"
                ),
                "inputs": {},
            }
        if surprises["avg_surprise_pct"] is not None:
            formulas["quarterly_report.avg_surprise_pct_4q"] = {
                "formula": (
                    "mean of (actual EPS − estimate) / |estimate| × 100 "
                    f"over the last {SURPRISE_REPORTS} reported quarters"
                ),
                "inputs": {},
            }
        if reaction["avg_abs_pct"] is not None:
            formulas["quarterly_report.reaction_avg_abs_pct"] = {
                "formula": (
                    "mean absolute close-to-close % move across each of "
                    "the last report dates (last close before the report "
                    "→ first close after it)"
                ),
                "inputs": {},
            }
        if reaction["worst_pct"] is not None:
            formulas["quarterly_report.reaction_worst_pct"] = {
                "formula": (
                    "most negative close-to-close % move across those "
                    "same report dates"
                ),
                "inputs": {},
            }
        if revision is not None:
            formulas["quarterly_report.eps_rev_30d_pct"] = {
                "formula": "(estimate_now − estimate_30d_ago) / |estimate_30d_ago| × 100",
                "inputs": {
                    "estimate_now": _to_float(trend.get("current")),
                    "estimate_30d_ago": _to_float(trend.get("days_ago_30")),
                },
            }

        return {
            "next_earnings_date": make_metric(
                "next quarterly report date",
                "The date the company next reports quarterly results. "
                "Blank when no report is scheduled yet or the calendar "
                "lookup failed.",
                next_date,
                interpretation=(
                    "A report inside the hold window means the stock can "
                    "gap straight past a stop overnight — exit before it "
                    "or size for it. The plan's report warning fires "
                    "when this date is inside a week."
                ),
            ),
            "eps_rev_30d_pct": make_metric(
                "30d EPS estimate change",
                "Change in the analyst consensus EPS estimate for the "
                "current quarter versus 30 days ago, in %.",
                _round(revision),
                interpretation=(
                    "The direction analysts are moving next quarter's "
                    "earnings bar. Rising estimates tend to precede "
                    "price drift over the following weeks; cuts are the "
                    "more reliable side — analysts cut slowly and "
                    "reluctantly. Around ±1% is noise."
                ),
            ),
            "eps_up_revisions_30d": make_metric(
                "30d analysts that increased EPS estimates",
                "How many analysts raised their EPS estimate for the "
                "current quarter in the last 30 days.",
                _to_count(revisions.get("up")),
                interpretation=(
                    "How many analysts moved, not how far — an estimate "
                    "change backed by one analyst is a single view; "
                    "backed by five or six, a consensus is shifting."
                ),
            ),
            "eps_down_revisions_30d": make_metric(
                "30d analysts that decreased EPS estimates",
                "How many analysts cut their EPS estimate for the "
                "current quarter in the last 30 days.",
                _to_count(revisions.get("down")),
                interpretation=(
                    "Read beside the up count: high in both directions "
                    "= genuine disagreement the estimate-change percent "
                    "alone hides; 0 and 0 = no analyst touched the "
                    "estimate in a month, so treat the estimate-based "
                    "fields with extra caution."
                ),
            ),
            "beats_4q": make_metric(
                "4q EPS beat estimate history",
                "How many of the last 4 reported quarters came in at or "
                "above the analyst EPS estimate.",
                surprises["beats"],
                interpretation=(
                    "Consistent beaters get the benefit of the doubt "
                    "into a report; habitual missers lose it."
                ),
            ),
            "avg_surprise_pct_4q": make_metric(
                "4q avg diff (EPS vs estimate)",
                "Average gap between reported EPS and the analyst "
                "estimate over the last 4 reports, in %.",
                surprises["avg_surprise_pct"],
                interpretation=(
                    "Says whether the company tends to clear the bar "
                    "analysts set — not how the stock reacts; read it "
                    "with the report-day move below."
                ),
            ),
            "reaction_avg_abs_pct": make_metric(
                "4q avg report day price change magnitude",
                "Average size of the close-to-close price move around "
                "the last 4 reports, ignoring direction, in %.",
                reaction["avg_abs_pct"],
                interpretation=(
                    "The realized event risk: a stock that moves ±10% on "
                    "report day needs a different plan than one that "
                    "moves ±2%."
                ),
            ),
            "reaction_worst_pct": make_metric(
                "4q worst report day price drop",
                "The most negative close-to-close price move around "
                "those same reports, in %.",
                reaction["worst_pct"],
                interpretation=(
                    "How badly holding through a report has actually "
                    "gone recently."
                ),
            ),
        }

    @staticmethod
    def _growth_group(
        facts: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        growth = (
            quarterly_growth_metrics(facts)
            if facts is not None
            else {"revenue": {}, "eps": {}}
        )
        revenue = growth.get("revenue") or {}
        eps = growth.get("eps") or {}

        for series_key, entry in (("revenue", revenue), ("eps", eps)):
            # Receipt variable names follow the user-facing word canon:
            # "sales", never "revenue" (payload keys stay stable).
            shown = "sales" if series_key == "revenue" else series_key
            if entry.get("yoy") is not None:
                formulas[f"growth.{series_key}_yoy_q"] = {
                    "formula": (
                        f"({shown}_q − {shown}_q_year_ago) / "
                        f"|{shown}_q_year_ago| × 100"
                    ),
                    "inputs": {
                        f"{shown}_q": entry["now"],
                        f"{shown}_q_year_ago": entry["year_ago"],
                    },
                }
            if entry.get("trend") is not None:
                # The current-quarter ingredient IS the published YoY
                # row, so the receipt names it by its payload key — the
                # UI then labels it with the field's display name and
                # links the plugged number back to that row.
                yoy_key = f"{series_key}_yoy_q"
                formulas[f"growth.{series_key}_growth_trend"] = {
                    "branches": [
                        {"label": "accelerating",
                         "condition": f"{yoy_key} − prior_quarter_yoy > 2"},
                        {"label": "slowing",
                         "condition": f"{yoy_key} − prior_quarter_yoy < -2"},
                        {"label": "steady", "condition": None},
                    ],
                    "inputs": {
                        yoy_key: round(entry["yoy"], 2),
                        "prior_quarter_yoy": round(entry["yoy_prior"], 2),
                    },
                }

        return {
            "revenue_yoy_q": make_metric(
                "quarterly sales (YoY)",
                "Latest reported quarter's sales versus the same "
                "quarter last year, in %.",
                _round(revenue.get("yoy")),
                interpretation=(
                    "Positive and rising = an expanding business; the "
                    "direction of change matters more than the level."
                ),
            ),
            "revenue_growth_trend": make_metric(
                "growth trend (sales)",
                "Whether that sales growth rate sped up or slowed "
                "versus the previous quarter (±2 percentage-point dead "
                "band).",
                revenue.get("trend"),
                interpretation=(
                    "Acceleration is the classic fuel for multi-week "
                    "runs; deceleration often ends them while growth is "
                    "still positive."
                ),
            ),
            "eps_yoy_q": make_metric(
                "quarterly EPS (YoY)",
                "Latest reported quarter's earnings per share (EPS) "
                "versus the same quarter last year, in %.",
                _round(eps.get("yoy")),
                interpretation=(
                    "Diverges from sales growth when margins or the "
                    "share count move; buybacks boost it, dilution "
                    "drags it."
                ),
            ),
            "eps_growth_trend": make_metric(
                "growth trend (EPS)",
                "Whether EPS growth sped up or slowed versus the "
                "previous quarter (±2 percentage-point dead band).",
                eps.get("trend"),
                interpretation=(
                    "The market pays for the change in trajectory, not "
                    "the level."
                ),
            ),
        }

    @staticmethod
    def _profitability_group(
        facts: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        annual = annual_statement_metrics(facts) if facts is not None else {}
        fcf = fcf_metrics(facts) if facts is not None else None
        fcf_ratio = fcf_to_earnings_metrics(facts, fcf)

        # Receipt variable names follow the user-facing word canon:
        # "sales" and "earnings", never "revenue"/"profit"/"income".
        if annual.get("gross_margin_pct") is not None:
            formulas["profitability.gross_margin_pct"] = {
                "formula": "gross_earnings / sales × 100",
                "inputs": {
                    "gross_earnings": annual["gross_profit"],
                    "sales": annual["revenue"],
                },
            }
        if annual.get("operating_margin_pct") is not None:
            formulas["profitability.operating_margin_pct"] = {
                "formula": "operating_earnings / sales × 100",
                "inputs": {
                    "operating_earnings": annual["operating_income"],
                    "sales": annual["revenue"],
                },
            }
        if annual.get("roe_pct") is not None:
            formulas["profitability.roe_pct"] = {
                "formula": "earnings / equity × 100",
                "inputs": {
                    "earnings": annual["net_income"],
                    "equity": annual["equity"],
                },
            }
        if fcf is not None:
            formulas["profitability.fcf"] = {
                "formula": "operating_cash_flow − capital_spending",
                "inputs": {
                    "operating_cash_flow": fcf["operating_cash_flow"],
                    "capital_spending": fcf["capital_spending"],
                },
            }
        if fcf_ratio is not None and fcf_ratio["pct"] is not None:
            formulas["profitability.fcf_to_earnings_pct"] = {
                "formula": "fcf / earnings × 100",
                "inputs": {
                    "fcf": fcf_ratio["fcf"],
                    "earnings": fcf_ratio["earnings"],
                },
            }

        fcf_basis = (
            f"trailing twelve months to {fcf['end']}"
            if fcf and fcf["basis"] == "ttm"
            else (f"fiscal year ended {fcf['end']}" if fcf else "period unavailable")
        )
        return {
            "gross_margin_pct": make_metric(
                "gross earnings to sales",
                "Percent of each sales dollar left after the direct "
                "cost of making the product (latest fiscal year).",
                _round(annual.get("gross_margin_pct")),
                interpretation=(
                    "High or rising = pricing power; falling = "
                    "competition or cost pressure biting."
                ),
            ),
            "operating_margin_pct": make_metric(
                "operating earnings to sales",
                "Percent of sales left after all operating costs, "
                "before interest and taxes (latest fiscal year).",
                _round(annual.get("operating_margin_pct")),
                interpretation=(
                    "The efficiency number the market judges at each "
                    "report; a trend break here moves the stock."
                ),
            ),
            "roe_pct": make_metric(
                "earnings to equity",
                "Yearly earnings as a percent of the shareholders' "
                "capital tied up in the business.",
                _round(annual.get("roe_pct")),
                interpretation=(
                    "Sustained ~15%+ marks a quality business; very low "
                    "or negative means the business burns capital."
                ),
            ),
            "fcf": make_metric(
                "free cash flow",
                "Cash generated after operating costs and capital "
                f"spending ({fcf_basis}).",
                _round(fcf["fcf"], 0) if fcf else None,
                interpretation=(
                    "Positive and close to reported earnings = the "
                    "earnings are real; reported earnings with negative "
                    "cash flow is a red flag."
                ),
            ),
            "fcf_to_earnings_pct": make_metric(
                "free cash flow to earnings",
                "Free cash flow as a percent of the same period's "
                "earnings. Blank when earnings are zero or negative "
                "(the ratio would read backwards) or when no "
                "same-period earnings figure exists.",
                _round(fcf_ratio["pct"]) if fcf_ratio else None,
                interpretation=(
                    "Near or above 100% = the reported earnings arrive "
                    "as real cash; far below 100% for years = the "
                    "earnings may be accounting, not cash."
                ),
            ),
        }

    @staticmethod
    def _balance_group(
        facts: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        annual = annual_statement_metrics(facts) if facts is not None else {}

        if annual.get("current_ratio") is not None:
            formulas["balance.current_ratio"] = {
                "formula": "current_assets / current_liabilities",
                "inputs": {
                    "current_assets": annual["assets_current"],
                    "current_liabilities": annual["liabilities_current"],
                },
            }
        if annual.get("debt_to_equity") is not None:
            formulas["balance.debt_to_equity"] = {
                "formula": "total_liabilities / equity",
                "inputs": {
                    "total_liabilities": annual["liabilities"],
                    "equity": annual["equity"],
                },
            }

        return {
            "current_ratio": make_metric(
                "assets to liabilities (short term)",
                "Short-term assets divided by short-term liabilities — "
                "can it pay what's due within a year (latest fiscal "
                "year).",
                _round(annual.get("current_ratio")),
                interpretation=(
                    "Above about 1.5 is comfortable; below 1 hints at a "
                    "cash crunch, where bad news hits twice as hard."
                ),
            ),
            "debt_to_equity": make_metric(
                "liabilities to equity (total)",
                "Total liabilities compared to shareholders' capital "
                "(equity) — how much the company runs on borrowed "
                "money.",
                _round(annual.get("debt_to_equity")),
                interpretation=(
                    "Heavy borrowing amplifies moves both ways and "
                    "hurts most when rates are high; compare within the "
                    "same industry."
                ),
            ),
        }

    @staticmethod
    def _valuation_group(
        symbol: str,
        info: Optional[Mapping[str, Any]],
        citations: List[Citation],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        values = {
            target: _to_float(info.get(source)) if info else None
            for source, target in _VALUATION_KEYS
        }
        if info is not None and not any(v is not None for v in values.values()):
            # ok-but-empty is the silent-blank trap: surface it explicitly.
            note_fields(
                warnings, field_notes,
                f"Yahoo returned no valuation ratios for {symbol}",
                VALUATION_FIELDS,
            )
        elif any(v is not None for v in values.values()):
            citations.append(
                Citation(
                    source_name="Yahoo Finance summary (yfinance)",
                    url=YAHOO_KEY_STATISTICS_URL.format(symbol=symbol),
                )
            )

        return {
            "market_cap": make_metric(
                "market cap",
                "Total value of all the company's shares, in dollars.",
                values["market_cap"],
                interpretation=(
                    "Mega caps grind, small caps gap and squeeze; also "
                    "sets what liquidity to expect."
                ),
            ),
            "ps_ttm": make_metric(
                "price to sales",
                "Price divided by the last 12 months of sales.",
                _round(values["ps_ttm"]),
                interpretation=(
                    "The valuation gauge for money-losing names where "
                    "price to earnings is meaningless."
                ),
            ),
            "pe_ttm": make_metric(
                "trailing price to earnings",
                "Price divided by the last 12 months of earnings — how "
                "many years of current earnings you pay for the stock. "
                "Blank when the company lost money over that period.",
                _round(values["pe_ttm"]),
                interpretation=(
                    "High = big expectations already priced in, good "
                    "news is needed just to hold the level; low = cheap, "
                    "or the market expects decline."
                ),
            ),
            "pe_forward": make_metric(
                "forward price to earnings",
                "Price divided by the earnings analysts expect over "
                "the next 12 months. Blank when analysts forecast a "
                "loss or do not cover the stock.",
                _round(values["pe_forward"]),
                interpretation=(
                    "Well below the trailing number = analysts expect "
                    "growth; above it = expected shrinkage."
                ),
            ),
        }

    @staticmethod
    def _meta_group(
        info: Optional[Mapping[str, Any]], facts: Optional[Mapping[str, Any]]
    ) -> Dict[str, Any]:
        annual = annual_statement_metrics(facts) if facts is not None else {}
        growth = (
            quarterly_growth_metrics(facts)
            if facts is not None
            else {"revenue": {}, "eps": {}}
        )
        period_end_q = (growth.get("revenue") or {}).get("end") or (
            (growth.get("eps") or {}).get("end")
        )
        entity = annual.get("entity_name")
        sector = info.get("sector") if info else None
        industry = info.get("industry") if info else None
        return {
            "entity_name": make_metric(
                "company",
                "The registrant name on the SEC filings.",
                entity if isinstance(entity, str) else None,
                interpretation=(
                    "Confirms the filings belong to the ticker being "
                    "analyzed."
                ),
            ),
            "sector": make_metric(
                "sector",
                "The company's sector classification.",
                sector if isinstance(sector, str) else None,
                interpretation=(
                    "The ratios below only mean anything against "
                    "industry peers; the sector also says which macro "
                    "series matter most (oil for energy, the 10y yield "
                    "for long-duration tech)."
                ),
            ),
            "industry": make_metric(
                "industry",
                "The finer industry classification within the sector.",
                industry if isinstance(industry, str) else None,
                interpretation=(
                    "The peer group this company's ratios should be "
                    "compared against."
                ),
            ),
            "period_end": make_metric(
                "annual data up to",
                "The fiscal year end the yearly figures (the balance "
                "and profitability ratios) come from.",
                annual.get("period_end"),
                interpretation=(
                    "Nearly a year old = treat those numbers as stale "
                    "background."
                ),
            ),
            "period_end_q": make_metric(
                "quarterly data up to",
                "The quarter end the quarterly growth fields come from.",
                period_end_q,
                interpretation=(
                    "Right after an annual report the latest quarterly "
                    "filing can lag a full quarter — check this date "
                    "before treating growth as fresh."
                ),
            ),
        }
