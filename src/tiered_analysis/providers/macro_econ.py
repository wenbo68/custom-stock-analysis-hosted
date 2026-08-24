# -*- coding: utf-8 -*-
"""Macro-economic provider — reformed payload (TODO.md truth 2026-08-04).

A US-centric shared background set from FRED, published in the same
envelope format as technicals so the LLM stages and the UI read one
source of truth per field. Groups follow the truth spec:

- meta: region + staleness dates for the two monthly (lagged) series
- inflation / employment: level + 3-month trend
- interest rates: the one rate the central bank *sets* (daily effective
  fed funds), plus the market's priced-in policy path (2y yield minus
  the official rate)
- bonds: the market-priced yields — 10y level + trend, the 10y-vs-2y
  recession dial + trend, the high-yield credit spread + trend
- markets: VIX, oil (level + trend), dollar (trend only — the broad
  index level is an arbitrary-basket number nobody can read)
- events: the three scheduled market-wide gap risks (CPI print, jobs
  report, rate decision) — the macro mirror of the earnings date

Valid context for every market, so the provider supports all markets
and its result is cached **once per region per day and never fetched
per ticker** (economic data is low-frequency and shared by every
symbol; the payload is deliberately stock-independent).

Requires a free FRED API key: set ``FRED_API_KEY`` (see .env.example).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
    note_fields,
)
from .technicals import make_metric, metric_value

Observation = Tuple[str, float]  # (YYYY-MM-DD, value)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
FRED_SERIES_PAGE = "https://fred.stlouisfed.org/series/"
_FRED_TIMEOUT_SECONDS = 15
_LOOKBACK_DAYS = 550  # 12-month YoY on monthly series + a 3-month trend base

DEFAULT_CACHE_DIR = Path("data") / "tiered_analysis_cache"

#: Trend fields compare the latest value against the last observation at
#: least this many calendar days back (~3 months).
TREND_LOOKBACK_DAYS = 91

#: Dead bands: a 3-month change inside the band reads "flat". Yield-type
#: series band in percentage points; oil and the dollar (whose levels are
#: prices/index units) band on percent change. Set from how far each
#: series drifts in a quiet quarter — moves beyond the band are the ones
#: a trader would call a trend.
CPI_TREND_BAND_PP = 0.2
UNEMPLOYMENT_TREND_BAND_PP = 0.2
GOV10Y_TREND_BAND_PP = 0.25
CURVE_TREND_BAND_PP = 0.15
HY_SPREAD_TREND_BAND_PP = 0.25
OIL_TREND_BAND_PCT = 5.0
DOLLAR_TREND_BAND_PCT = 2.0

#: FRED release ids for the two scheduled data prints (fred/releases):
#: 10 = Consumer Price Index, 50 = Employment Situation (jobs report).
CPI_RELEASE_ID = 10
JOBS_RELEASE_ID = 50

#: Scheduled FOMC rate-decision dates (the statement lands on the second
#: meeting day, 2 p.m. ET) — published years ahead at
#: federalreserve.gov/monetarypolicy/fomccalendars.htm; FRED carries no
#: forward calendar for it. Extend this table when the Fed publishes the
#: next year; past the table's end the field goes None with a warning
#: instead of guessing.
FOMC_DECISION_DATES: Tuple[str, ...] = (
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
)

#: FRED series per ingredient. DFF (daily effective fed funds) rather
#: than the monthly-average FEDFUNDS: after a decision the monthly
#: average keeps showing the old rate for weeks, and the priced-in-path
#: diff needs a same-day official rate next to the daily 2y yield.
SERIES_IDS: Dict[str, str] = {
    "official": "DFF",
    "gov10y": "DGS10",
    "gov2y": "DGS2",
    "curve_10y_2y": "T10Y2Y",
    "hy_oas": "BAMLH0A0HYM2",
    "cpi_index": "CPIAUCSL",
    "unemployment": "UNRATE",
    "vix": "VIXCLS",
    "oil_wti": "DCOILWTICO",
    "dollar_broad": "DTWEXBGS",
}

#: Payload paths ("group.key") each FRED series feeds — the fields a
#: series outage blanks, so its note can sit beside them on the report
#: page.
SERIES_FIELDS: Dict[str, Tuple[str, ...]] = {
    "official": (
        "interest_rates.official_rate_pct",
        "interest_rates.diff_2y_vs_official_pp",
    ),
    "gov10y": ("bonds.gov10y_yield_pct", "bonds.gov10y_trend"),
    "gov2y": ("interest_rates.diff_2y_vs_official_pp",),
    "curve_10y_2y": (
        "bonds.yield_diff_10y_2y_pp", "bonds.yield_diff_10y_2y_trend",
    ),
    "hy_oas": (
        "bonds.yield_diff_hy_gov_pp", "bonds.yield_diff_hy_gov_trend",
    ),
    "cpi_index": (
        "inflation.cpi_yoy_pct", "inflation.cpi_yoy_trend",
        "meta.inflation_data_up_to",
    ),
    "unemployment": (
        "employment.unemployment_rate_pct", "employment.unemployment_trend",
        "meta.employment_data_up_to",
    ),
    "vix": ("markets.vix",),
    "oil_wti": ("markets.wti_oil_usd", "markets.oil_trend"),
    "dollar_broad": ("markets.dollar_trend",),
}

#: Ingredients whose latest value must exist for the card to count as
#: complete (each missing one gets a field note). Trends and events
#: degrade to None + warning quietly (short history / calendar outage
#: must not sink the shared report).
_REQUIRED_FIELDS = (
    ("inflation", "cpi_yoy_pct"),
    ("employment", "unemployment_rate_pct"),
    ("interest_rates", "official_rate_pct"),
    ("interest_rates", "diff_2y_vs_official_pp"),
    ("bonds", "gov10y_yield_pct"),
    ("bonds", "yield_diff_10y_2y_pp"),
    ("bonds", "yield_diff_hy_gov_pp"),
    ("markets", "vix"),
    ("markets", "wti_oil_usd"),
)


class MacroConfigError(RuntimeError):
    """Raised when FRED is not configured (missing API key)."""


# ---------------------------------------------------------------------------
# Pure computation helpers (offline-testable)
# ---------------------------------------------------------------------------


def cpi_yoy_pct(observations: List[Observation]) -> Optional[float]:
    """YoY percent change of a monthly index vs the same month last year."""
    if not observations:
        return None
    latest_date_str, latest_value = observations[-1]
    year, month = int(latest_date_str[:4]), int(latest_date_str[5:7])
    target = (year - 1, month)
    for date_str, value in observations:
        if (int(date_str[:4]), int(date_str[5:7])) == target:
            if value == 0:
                return None
            return (latest_value / value - 1.0) * 100.0
    return None


def observations_as_of(
    observations: List[Observation], lookback_days: int = TREND_LOOKBACK_DAYS
) -> List[Observation]:
    """The series truncated to ~``lookback_days`` before its latest point —
    the baseline snapshot every 3-month trend compares against."""
    if not observations:
        return []
    latest = date.fromisoformat(observations[-1][0][:10])
    cutoff = (latest - timedelta(days=lookback_days)).isoformat()
    return [obs for obs in observations if obs[0][:10] <= cutoff]


def latest_value(observations: List[Observation]) -> Optional[float]:
    return observations[-1][1] if observations else None


def trend_label(
    now: Optional[float], then: Optional[float], band: float
) -> Optional[str]:
    """up / down / flat comparing now vs ~3 months ago with a dead band."""
    if now is None or then is None:
        return None
    # Round away float noise before the strict comparison: 4.1 − 4.3
    # computes as −0.20000000000000018, which would flip a change sitting
    # exactly ON the band ("flat" by the published rule) to "down".
    change = round(now - then, 9)
    if change > band:
        return "up"
    if change < -band:
        return "down"
    return "flat"


def pct_trend_label(
    now: Optional[float], then: Optional[float], band_pct: float
) -> Optional[str]:
    """Trend on percent change — for series whose level unit is a price."""
    if now is None or then is None or then == 0:
        return None
    return trend_label((now / then - 1.0) * 100.0, 0.0, band_pct)


def next_date_after(
    dates: List[str], today: date
) -> Optional[str]:
    """First YYYY-MM-DD strictly after ``today`` in an unsorted list."""
    future = sorted(d for d in dates if d > today.isoformat())
    return future[0] if future else None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


# ---------------------------------------------------------------------------
# Default network fetchers (injected for tests)
# ---------------------------------------------------------------------------


def _fred_api_key() -> str:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise MacroConfigError(
            "FRED_API_KEY is not set; get a free key at fred.stlouisfed.org"
        )
    return api_key


def _default_series_fetcher(series_id: str) -> List[Observation]:
    import requests

    start = (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    response = requests.get(
        FRED_OBSERVATIONS_URL,
        params={
            "series_id": series_id,
            "api_key": _fred_api_key(),
            "file_type": "json",
            "observation_start": start,
        },
        timeout=_FRED_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    observations: List[Observation] = []
    for row in response.json().get("observations", []):
        raw = row.get("value")
        if raw in (None, "", "."):  # FRED marks missing datapoints with "."
            continue
        try:
            observations.append((str(row.get("date")), float(raw)))
        except ValueError:
            continue
    return observations


def _default_release_dates_fetcher(release_id: int) -> List[str]:
    """Scheduled dates for a FRED release, including future ones (the
    ``include_release_dates_with_no_data`` flag is what exposes the
    forward calendar)."""
    import requests

    response = requests.get(
        FRED_RELEASE_DATES_URL,
        params={
            "release_id": release_id,
            "api_key": _fred_api_key(),
            "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "sort_order": "desc",
            "limit": 60,
        },
        timeout=_FRED_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [
        str(row.get("date"))
        for row in response.json().get("release_dates", [])
        if row.get("date")
    ]


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class MacroEconProvider(DimensionProvider):
    """NUMERIC shared macro background, cached once per region per day."""

    dimension = "macro_econ"
    kind = SourceKind.NUMERIC
    region = "us"
    #: Cache format marker — bump when the payload shape changes so a
    #: same-day cache written by older code is refetched, not misread.
    cache_version = "v2"

    def __init__(
        self,
        series_fetcher: Callable[[str], List[Observation]] = _default_series_fetcher,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        today: Callable[[], date] = date.today,
        release_dates_fetcher: Callable[[int], List[str]] = _default_release_dates_fetcher,
    ) -> None:
        self._series_fetcher = series_fetcher
        self._cache_dir = Path(cache_dir)
        self._today = today
        self._release_dates_fetcher = release_dates_fetcher

    def supports(self, market: Market) -> bool:
        return True

    # The symbol is intentionally ignored: macro data is per-region.
    def collect(self, symbol: str) -> DimensionResult:
        cached = self._read_cache()
        if cached is not None:
            return cached

        series, warnings, field_notes = self._fetch_series()
        # A total fetch failure still ships the full payload shape (all
        # fields blank; the missing-fields sweep below pins a note on
        # every one) — degradation lives on the fields, never on a
        # card-level grade (2026-08-19).
        payload, formulas = self._build_payload(series or {}, warnings, field_notes)
        missing = [
            f"{group}.{key}"
            for group, key in _REQUIRED_FIELDS
            if metric_value(payload.get(group, {}).get(key)) is None
        ]
        if missing:
            message = (
                f"macro fields lacking data: {', '.join(sorted(missing))}"
            )
            warnings.append(message)
            for path in sorted(missing):
                # A missing field whose series note already explains it
                # keeps that specific note; the aggregate covers the rest
                # (e.g. a YoY needing more history than the series has).
                if path not in field_notes:
                    field_notes[path] = [message]
        result = DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            payload=payload,
            citations=[self._citation()],
            warnings=warnings,
            formulas=formulas or None,
            field_notes=field_notes or None,
        )
        # A total failure is never day-cached — the next run must retry
        # the fetch, not reread an all-blank card.
        if series is not None:
            self._write_cache(result)
        return result

    def _citation(self) -> Citation:
        return Citation(
            source_name="FRED (Federal Reserve Economic Data)",
            url=FRED_SERIES_PAGE.rstrip("/"),
        )

    # -- fetching -----------------------------------------------------------

    def _fetch_series(
        self,
    ) -> Tuple[
        Optional[Dict[str, List[Observation]]], List[str],
        Dict[str, List[str]],
    ]:
        series: Dict[str, List[Observation]] = {}
        warnings: List[str] = []
        field_notes: Dict[str, List[str]] = {}
        got_any = False
        for name, series_id in SERIES_IDS.items():
            try:
                observations = self._series_fetcher(series_id)
            except MacroConfigError as exc:
                # Not configured at all: one clear warning, no partial noise.
                return None, [str(exc)], {}
            except Exception as exc:
                note_fields(
                    warnings, field_notes,
                    f"FRED series {series_id} failed: {exc}",
                    SERIES_FIELDS.get(name, ()),
                )
                observations = []
            if not observations:
                if not any(series_id in w for w in warnings):
                    note_fields(
                        warnings, field_notes,
                        f"FRED series {series_id} returned no data",
                        SERIES_FIELDS.get(name, ()),
                    )
            series[name] = observations
            got_any = got_any or bool(observations)
        if not got_any:
            return None, warnings, {}
        return series, warnings, field_notes

    def _next_release_date(
        self,
        release_id: int,
        label: str,
        warnings: List[str],
        field_notes: Dict[str, List[str]],
        field_path: str,
    ) -> Optional[str]:
        try:
            dates = self._release_dates_fetcher(release_id)
        except MacroConfigError:
            return None
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"FRED release calendar for {label} failed: {exc}",
                (field_path,),
            )
            return None
        upcoming = next_date_after(dates, self._today())
        if upcoming is None:
            note_fields(
                warnings, field_notes,
                f"no upcoming {label} release date found",
                (field_path,),
            )
        return upcoming

    # -- payload assembly ---------------------------------------------------

    def _build_payload(
        self,
        series: Dict[str, List[Observation]],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        def obs(name: str) -> List[Observation]:
            return series.get(name, [])

        def obs_date(name: str) -> Optional[str]:
            data = obs(name)
            return data[-1][0][:10] if data else None

        # Levels.
        official = latest_value(obs("official"))
        gov10y = latest_value(obs("gov10y"))
        gov2y = latest_value(obs("gov2y"))
        curve = latest_value(obs("curve_10y_2y"))
        hy_oas = latest_value(obs("hy_oas"))
        unemployment = latest_value(obs("unemployment"))
        vix = latest_value(obs("vix"))
        oil = latest_value(obs("oil_wti"))
        dollar = latest_value(obs("dollar_broad"))
        cpi_yoy = cpi_yoy_pct(obs("cpi_index"))

        # 3-month baselines for the trend fields.
        gov10y_then = latest_value(observations_as_of(obs("gov10y")))
        curve_then = latest_value(observations_as_of(obs("curve_10y_2y")))
        hy_then = latest_value(observations_as_of(obs("hy_oas")))
        unemployment_then = latest_value(observations_as_of(obs("unemployment")))
        oil_then = latest_value(observations_as_of(obs("oil_wti")))
        dollar_then = latest_value(observations_as_of(obs("dollar_broad")))
        cpi_yoy_then = cpi_yoy_pct(observations_as_of(obs("cpi_index")))

        # Computed comparisons and trends.
        diff_2y_official = (
            round(gov2y - official, 2)
            if gov2y is not None and official is not None
            else None
        )
        cpi_trend = trend_label(cpi_yoy, cpi_yoy_then, CPI_TREND_BAND_PP)
        unemployment_trend = trend_label(
            unemployment, unemployment_then, UNEMPLOYMENT_TREND_BAND_PP
        )
        gov10y_trend = trend_label(gov10y, gov10y_then, GOV10Y_TREND_BAND_PP)
        curve_trend = trend_label(curve, curve_then, CURVE_TREND_BAND_PP)
        hy_trend = trend_label(hy_oas, hy_then, HY_SPREAD_TREND_BAND_PP)
        oil_trend = pct_trend_label(oil, oil_then, OIL_TREND_BAND_PCT)
        dollar_trend = pct_trend_label(dollar, dollar_then, DOLLAR_TREND_BAND_PCT)

        # Events.
        next_cpi = self._next_release_date(
            CPI_RELEASE_ID, "inflation data (CPI)", warnings, field_notes,
            "events.next_cpi_release_date",
        )
        next_jobs = self._next_release_date(
            JOBS_RELEASE_ID, "employment data (jobs report)", warnings,
            field_notes, "events.next_jobs_release_date",
        )
        next_decision = next_date_after(
            list(FOMC_DECISION_DATES), self._today()
        )
        if next_decision is None:
            note_fields(
                warnings, field_notes,
                "FOMC decision-date table exhausted; extend "
                "FOMC_DECISION_DATES from the Fed's published calendar",
                ("events.next_rate_decision_date",),
            )

        payload: Dict[str, Any] = {
            "meta": {
                "region": make_metric(
                    "region",
                    "The economy this report describes; every stock "
                    "analyzed in this region shares the same macro data.",
                    self.region,
                ),
                "inflation_data_up_to": make_metric(
                    "inflation data up to",
                    "Month the latest consumer-price reading describes. "
                    "Inflation data is published monthly with a delay.",
                    obs_date("cpi_index"),
                    interpretation=(
                        "Can be four to six weeks old — it describes that "
                        "month, not today."
                    ),
                ),
                "employment_data_up_to": make_metric(
                    "employment data up to",
                    "Month the latest unemployment reading describes. "
                    "Jobs data is published monthly with a delay.",
                    obs_date("unemployment"),
                    interpretation=(
                        "Can be four to six weeks old — it describes that "
                        "month, not today."
                    ),
                ),
            },
            "inflation": {
                "cpi_yoy_pct": make_metric(
                    "consumer price index (YoY)",
                    "Consumer prices versus the same month last year — "
                    "the inflation rate, in %.",
                    _round(cpi_yoy),
                    interpretation=(
                        "Central banks aim for about 2%. Hot readings "
                        "push rates up (bad for stocks); cooling readings "
                        "make rate cuts possible."
                    ),
                ),
                "cpi_yoy_trend": make_metric(
                    "consumer price index (YoY) trend",
                    "Inflation rate now vs about 3 months ago "
                    f"(±{CPI_TREND_BAND_PP} point dead band): up, down or "
                    "flat.",
                    cpi_trend,
                    interpretation=(
                        "Down = pressure easing, rate cuts closer; up = "
                        "pressure building, rates stay high or rise."
                    ),
                ),
            },
            "employment": {
                "unemployment_rate_pct": make_metric(
                    "unemployment rate",
                    "Percent of the workforce without a job.",
                    _round(unemployment),
                    interpretation=(
                        "Low = strong economy but keeps rates high; a "
                        "fast rise is the classic recession signal."
                    ),
                ),
                "unemployment_trend": make_metric(
                    "unemployment rate trend",
                    "Unemployment now vs about 3 months ago "
                    f"(±{UNEMPLOYMENT_TREND_BAND_PP} point dead band): up, "
                    "down or flat.",
                    unemployment_trend,
                    interpretation=(
                        "Up is the hard recession gauge moving the wrong "
                        "way — the direction matters more than the level."
                    ),
                ),
            },
            "interest_rates": {
                "official_rate_pct": make_metric(
                    "official interest rate",
                    "The one rate the central bank sets directly (US: "
                    "the effective federal funds rate) — the base price "
                    "of money. Everything else in this report is priced "
                    "by markets.",
                    _round(official),
                    interpretation=(
                        "Changes only at scheduled decisions (~8 a year). "
                        "High or rising = pressure on stock valuations; "
                        "cuts = fuel for stocks."
                    ),
                ),
                "diff_2y_vs_official_pp": make_metric(
                    "diff (2y gov bond yield vs official interest rate)",
                    "The 2-year government bond yield minus the official "
                    "rate, in percentage points. The 2y is roughly the "
                    "market's expected average official rate over the "
                    "next two years, so the gap is the change the market "
                    "has priced in.",
                    diff_2y_official,
                    interpretation=(
                        "Negative = rate cuts priced in (the more "
                        "negative, the bigger the expected easing); "
                        "positive = hikes priced in; near zero = the "
                        "central bank is expected to sit still."
                    ),
                ),
            },
            "bonds": {
                "gov10y_yield_pct": make_metric(
                    "10y gov bond yield",
                    "The yield locked in by lending to the government "
                    "for 10 years at today's traded bond price — the "
                    "market's long-term interest rate. Moves every "
                    "trading day; payments on bonds already owned never "
                    "change.",
                    _round(gov10y),
                    interpretation=(
                        "The guaranteed alternative competing with "
                        "stocks: the higher it sits, the less future "
                        "profits are worth today — far-future (growth) "
                        "profits get hit hardest."
                    ),
                ),
                "gov10y_trend": make_metric(
                    "10y gov bond yield trend",
                    "10y yield now vs about 3 months ago "
                    f"(±{GOV10Y_TREND_BAND_PP} point dead band): up, down "
                    "or flat.",
                    gov10y_trend,
                    interpretation=(
                        "Up = valuation pressure actively building while "
                        "a swing trade is held — a headwind for growth "
                        "stock longs; down = support."
                    ),
                ),
                "yield_diff_10y_2y_pp": make_metric(
                    "yield diff (10y gov bond vs 2y gov bond)",
                    "10-year yield minus 2-year yield, in percentage "
                    "points.",
                    _round(curve),
                    interpretation=(
                        "Negative (short rates above long) is the "
                        "classic recession warning: the market expects "
                        "cuts because trouble is coming."
                    ),
                ),
                "yield_diff_10y_2y_trend": make_metric(
                    "yield diff (10y gov bond vs 2y gov bond) trend",
                    "The 10y-vs-2y gap now vs about 3 months ago "
                    f"(±{CURVE_TREND_BAND_PP} point dead band): up, down "
                    "or flat.",
                    curve_trend,
                    interpretation=(
                        "The recession dial's direction: down = sliding "
                        "toward/deeper into warning; up = climbing back "
                        "out, often a regime change."
                    ),
                ),
                "yield_diff_hy_gov_pp": make_metric(
                    "yield diff (high-yield company bond vs gov bond)",
                    "Extra yield investors demand for risky ('junk') "
                    "company bonds over government bonds of matching "
                    "maturity, in percentage points — matching cancels "
                    "the maturity effect, leaving pure default fear. "
                    "Traders call this the high-yield credit spread.",
                    _round(hy_oas),
                    interpretation=(
                        "Tight and stable = lenders relaxed, risk-on "
                        "backdrop; widening = credit stress building, "
                        "often before stocks react."
                    ),
                ),
                "yield_diff_hy_gov_trend": make_metric(
                    "yield diff (high-yield company bond vs gov bond) trend",
                    "The credit spread now vs about 3 months ago "
                    f"(±{HY_SPREAD_TREND_BAND_PP} point dead band): up, "
                    "down or flat.",
                    hy_trend,
                    interpretation=(
                        "Up (widening) is the early credit-stress "
                        "warning light; down = fear draining out."
                    ),
                ),
            },
            "markets": {
                "vix": make_metric(
                    "implied market volatility",
                    "Expected size of overall market (S&P 500) swings "
                    "over the next month, priced from index options — "
                    "the 'fear index'. The market-wide sibling of the "
                    "per-stock implied volatility in positioning.",
                    _round(vix),
                    interpretation=(
                        "Under ~15 = calm; 20+ = nervous; 30+ = stress. "
                        "In high-VIX regimes use smaller size and wider "
                        "stops."
                    ),
                ),
                "wti_oil_usd": make_metric(
                    "crude oil price",
                    "US crude oil (WTI), dollars per barrel.",
                    _round(oil),
                    interpretation=(
                        "Direct driver for energy and transport names; "
                        "the level sets their world regardless of trend."
                    ),
                ),
                "oil_trend": make_metric(
                    "crude oil price trend",
                    "Oil price now vs about 3 months ago "
                    f"(±{OIL_TREND_BAND_PCT:.0f}% dead band): up, down or "
                    "flat.",
                    oil_trend,
                    interpretation=(
                        "Sustained rises feed future inflation readings "
                        "(oil moves daily, CPI reports monthly) and weigh "
                        "on the whole market."
                    ),
                ),
                "dollar_trend": make_metric(
                    "dollar strength trend",
                    "The dollar's value against a basket of "
                    "trading-partner currencies, now vs about 3 months "
                    f"ago (±{DOLLAR_TREND_BAND_PCT:.0f}% dead band): up, "
                    "down or flat. Only the direction is published — the "
                    "index level is an arbitrary-basket number.",
                    dollar_trend,
                    interpretation=(
                        "A fast-rising dollar shrinks US multinationals' "
                        "foreign earnings and often accompanies risk-off; "
                        "a falling dollar supports risk appetite."
                    ),
                ),
            },
            "events": {
                "next_cpi_release_date": make_metric(
                    "next inflation data date",
                    "Scheduled date of the next consumer-price (CPI) "
                    "release.",
                    next_cpi,
                    interpretation=(
                        "A market-wide gap risk, the way earnings is a "
                        "single-stock gap risk."
                    ),
                ),
                "next_jobs_release_date": make_metric(
                    "next employment data date",
                    "Scheduled date of the next jobs report "
                    "(unemployment release).",
                    next_jobs,
                    interpretation=(
                        "A market-wide gap risk, the way earnings is a "
                        "single-stock gap risk."
                    ),
                ),
                "next_rate_decision_date": make_metric(
                    "next official interest rate date",
                    "Scheduled date of the next central-bank rate "
                    "decision (US: FOMC statement day).",
                    next_decision,
                    interpretation=(
                        "The biggest scheduled market-wide event; inside "
                        "a holding window it is gap risk for every "
                        "stock."
                    ),
                ),
            },
        }

        formulas = self._build_formulas(
            payload,
            official=official,
            gov2y=gov2y,
            gov10y=gov10y,
            gov10y_then=gov10y_then,
            curve=curve,
            curve_then=curve_then,
            hy_oas=hy_oas,
            hy_then=hy_then,
            cpi_yoy=cpi_yoy,
            cpi_yoy_then=cpi_yoy_then,
            unemployment=unemployment,
            unemployment_then=unemployment_then,
            oil=oil,
            oil_then=oil_then,
            dollar=dollar,
            dollar_then=dollar_then,
        )
        return payload, formulas

    @staticmethod
    def _build_formulas(
        payload: Dict[str, Any],
        *,
        official: Optional[float],
        gov2y: Optional[float],
        gov10y: Optional[float],
        gov10y_then: Optional[float],
        curve: Optional[float],
        curve_then: Optional[float],
        hy_oas: Optional[float],
        hy_then: Optional[float],
        cpi_yoy: Optional[float],
        cpi_yoy_then: Optional[float],
        unemployment: Optional[float],
        unemployment_then: Optional[float],
        oil: Optional[float],
        oil_then: Optional[float],
        dollar: Optional[float],
        dollar_then: Optional[float],
    ) -> Dict[str, Any]:
        """UI receipts, keyed "group.key" — the technicals pattern: a
        one-outcome comparison ships "formula" + inputs; a trend ships
        "branches" (one {label, condition} per outcome, catch-all None)
        so the UI renders one line per outcome. Published only when the
        metric has a value and every input is present."""
        formulas: Dict[str, Any] = {}

        def add(
            path: str,
            formula: Optional[str] = None,
            inputs: Optional[Dict[str, Any]] = None,
            branches: Optional[List[Dict[str, Optional[str]]]] = None,
        ) -> None:
            group, key = path.split(".")
            if metric_value(payload.get(group, {}).get(key)) is None:
                return
            plugged: Dict[str, Any] = {}
            for var, value in (inputs or {}).items():
                if value is None:
                    return
                plugged[var] = (
                    round(value, 2) if isinstance(value, (int, float)) else value
                )
            entry: Dict[str, Any] = {"inputs": plugged}
            if formula is not None:
                entry["formula"] = formula
            if branches is not None:
                entry["branches"] = branches
            formulas[path] = entry

        def trend_branches(band: float, unit: str = "") -> List[Dict[str, Optional[str]]]:
            return [
                {"label": "up",
                 "condition": f"value_now > value_3m_ago + {band}{unit}"},
                {"label": "down",
                 "condition": f"value_now < value_3m_ago − {band}{unit}"},
                {"label": "flat", "condition": None},
            ]

        def pct_trend_branches(band_pct: float) -> List[Dict[str, Optional[str]]]:
            return [
                {"label": "up",
                 "condition": "change_3m_pct > " f"{band_pct:.0f}"},
                {"label": "down",
                 "condition": "change_3m_pct < −" f"{band_pct:.0f}"},
                {"label": "flat", "condition": None},
            ]

        add(
            "interest_rates.diff_2y_vs_official_pp",
            "gov_bond_yield_2y − official_interest_rate",
            {"gov_bond_yield_2y": gov2y, "official_interest_rate": official},
        )
        add(
            "bonds.yield_diff_10y_2y_pp",
            "gov_bond_yield_10y − gov_bond_yield_2y",
            {"gov_bond_yield_10y": gov10y, "gov_bond_yield_2y": gov2y},
        )
        add(
            "inflation.cpi_yoy_trend",
            inputs={"value_now": cpi_yoy, "value_3m_ago": cpi_yoy_then},
            branches=trend_branches(CPI_TREND_BAND_PP),
        )
        add(
            "employment.unemployment_trend",
            inputs={"value_now": unemployment,
                    "value_3m_ago": unemployment_then},
            branches=trend_branches(UNEMPLOYMENT_TREND_BAND_PP),
        )
        add(
            "bonds.gov10y_trend",
            inputs={"value_now": gov10y, "value_3m_ago": gov10y_then},
            branches=trend_branches(GOV10Y_TREND_BAND_PP),
        )
        add(
            "bonds.yield_diff_10y_2y_trend",
            inputs={"value_now": curve, "value_3m_ago": curve_then},
            branches=trend_branches(CURVE_TREND_BAND_PP),
        )
        add(
            "bonds.yield_diff_hy_gov_trend",
            inputs={"value_now": hy_oas, "value_3m_ago": hy_then},
            branches=trend_branches(HY_SPREAD_TREND_BAND_PP),
        )
        if oil is not None and oil_then not in (None, 0):
            add(
                "markets.oil_trend",
                inputs={
                    "price_now": oil,
                    "price_3m_ago": oil_then,
                    "change_3m_pct": (oil / oil_then - 1.0) * 100.0,
                },
                branches=pct_trend_branches(OIL_TREND_BAND_PCT),
            )
        if dollar is not None and dollar_then not in (None, 0):
            add(
                "markets.dollar_trend",
                inputs={
                    "index_now": dollar,
                    "index_3m_ago": dollar_then,
                    "change_3m_pct": (dollar / dollar_then - 1.0) * 100.0,
                },
                branches=pct_trend_branches(DOLLAR_TREND_BAND_PCT),
            )
        return formulas

    # ---- per-day cache ----

    def _cache_path(self) -> Path:
        return self._cache_dir / (
            f"macro_econ_{self.region}_{self.cache_version}_"
            f"{self._today().isoformat()}.json"
        )

    def _read_cache(self) -> Optional[DimensionResult]:
        path = self._cache_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                payload=raw["payload"],
                citations=[self._citation()],
                warnings=list(raw.get("warnings", [])),
                formulas=raw.get("formulas"),
                field_notes=raw.get("field_notes"),
            )
        except FileNotFoundError:
            return None
        except Exception:
            return None  # corrupt cache: refetch, never fail on cache

    def _write_cache(self, result: DimensionResult) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path().write_text(
                json.dumps(
                    {
                        "payload": result.payload,
                        "warnings": result.warnings,
                        "formulas": result.formulas,
                        "field_notes": result.field_notes,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass  # a cold cache tomorrow is acceptable; failing the run is not
