# -*- coding: utf-8 -*-
"""Opinion provider — the analyst + crowd sentiment card (numeric,
2026-08-18).

The news cards carry facts (what happened); this card measures
OPINIONS about the stock, in two groups the owner named — and every
figure is a published number in the same ``{name, explanation,
interpretation, value}`` envelope the technicals/positioning reports
use. No LLM anywhere in this dimension (the first, textual cut of this
card screened Reddit posts through an LLM; it died the day it was
born — 2026-08-18 — when Reddit's API went approval-only and the owner
chose keyless numeric sources over prose):

- ``analyst`` — professional opinion as numbers, from Yahoo Finance
  via yfinance (keyless, works unconfigured): the buy/hold/sell
  consensus counts with the one-month drift of the buy share, the
  price-target average/range vs the current price, and counts of
  upgrades / downgrades / coverage initiations inside the
  ``ANALYST_WINDOW_BDAYS`` business-day window (the company-news
  card's weekday quota). If Yahoo fails entirely and
  ``FINNHUB_API_KEY`` is set, Finnhub's recommendation endpoint serves
  the consensus counts alone (no targets, no action counts), warned.

- ``crowd`` — retail chatter measured, not summarized, from two
  keyless public aggregators (both verified live 2026-08-18; the
  official Reddit API now needs Reddit's approval, Stocktwits sits
  behind a bot wall, Finnhub's social feed is paid-tier):
  ApeWisdom (apewisdom.io) counts Reddit mentions/upvotes per ticker
  over the last 24 hours and ranks tickers by that buzz;
  Tradestie (tradestie.com) scores the day's WallStreetBets comment
  tone per ticker (positive = bullish wording, negative = bearish).
  A stock the aggregators do not list simply is not being talked
  about — those fields stay null with a note saying exactly that.
  Both lists are symbol-independent, so the default loaders fetch each
  once per day and serve every ticker from an on-disk cache (the
  macro_econ per-day convention); failed fetches are never cached.

Both groups are always present in the payload; a field a source could
not deliver stays present with ``value: null`` plus a field note
(positioning's contract), never omitted — even when every source is
down, the card ships all-blank with each field's note saying why. (An
absent-from-the-ranking ticker is checked-and-none, not a failure.)

NUMERIC kind: the debate grades these fields under the standard
value-copy contract — but its rules text tells the graders these are
measures of sentiment, never facts about the business.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
    note_fields,
)
from .company_events import _parse_date, business_days_back
from ..cache_store import CacheStore, default_cache_store
from ..run_context import data_key
from .technicals import make_metric

#: Rating-action lookback in BUSINESS days — the same weekday quota the
#: company-news card uses, so both per-company timelines cover the same
#: depth. Outside earnings season the counts can be 0-2 (measured
#: 2026-08-18 on AAPL: one action in the trailing week, eight on
#: earnings day alone) — the card breathes with the calendar.
ANALYST_WINDOW_BDAYS = 7

#: ApeWisdom pages walked before concluding the ticker is not ranked.
#: The all-stocks filter held ~800 tickers over 8 pages of 100 when
#: measured live 2026-08-18; the ceiling only guards against the
#: listing growing without bound.
APEWISDOM_MAX_PAGES = 12

_APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
_APEWISDOM_PAGE_URL = "https://apewisdom.io/"
_TRADESTIE_URL = "https://tradestie.com/api/v1/apps/reddit"
_TRADESTIE_PAGE_URL = "https://tradestie.com/apps/reddit/wallstreetbets/"
_CROWD_TIMEOUT_SECONDS = 15

_FINNHUB_RECOMMENDATION_URL = "https://finnhub.io/api/v1/stock/recommendation"
_FINNHUB_TIMEOUT_SECONDS = 15

#: Payload paths ("group.key") each data source feeds — the fields a
#: source failure blanks, so its note can sit beside them (the
#: positioning pattern).
CONSENSUS_FIELDS = (
    "analyst.firms_total",
    "analyst.strong_buy_firms",
    "analyst.buy_firms",
    "analyst.hold_firms",
    "analyst.sell_firms",
    "analyst.strong_sell_firms",
    "analyst.buy_rating_pct",
    "analyst.buy_rating_change_1m_pp",
)
TARGET_FIELDS = (
    "analyst.price_target_mean",
    "analyst.price_target_high",
    "analyst.price_target_low",
    "analyst.target_vs_price_pct",
)
ACTION_FIELDS = (
    "analyst.upgrades_count",
    "analyst.downgrades_count",
    "analyst.initiations_count",
)
APEWISDOM_FIELDS = (
    "crowd.reddit_mentions",
    "crowd.reddit_mentions_24h_ago",
    "crowd.reddit_upvotes",
    "crowd.reddit_rank",
    "crowd.reddit_rank_24h_ago",
)
TRADESTIE_FIELDS = (
    "crowd.wsb_sentiment_score",
    "crowd.wsb_comments",
)


def _text(value: Any) -> Optional[str]:
    """A raw cell as clean text: NaN, empty and non-strings -> None."""
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _price(value: Any) -> Optional[float]:
    """A price-target cell as a float. Yahoo ships 0.00 for "no prior
    target" (verified live 2026-08-18), and NaN for missing — both
    normalize to None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or the 0.00 placeholder
        return None
    return number


def _count(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _int_or_none(value: Any) -> Optional[int]:
    """A published integer stat; junk stays None (never a fake zero)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN -> None


def _round1(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)


def _round2(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


# ---------------------------------------------------------------------------
# Analyst side — Yahoo Finance via yfinance (keyless), Finnhub
# consensus as the degraded backup.
# ---------------------------------------------------------------------------


def normalize_action_row(stamp: Any, row: Mapping[str, Any]) -> Dict[str, Any]:
    """One yfinance upgrades_downgrades row -> a plain dict. Columns
    (verified live 2026-08-18): Firm, ToGrade, FromGrade, Action
    (up/down/init/main/reit), priceTargetAction, currentPriceTarget,
    priorPriceTarget; the frame is indexed by the GradeDate stamp."""
    action_date = None
    if hasattr(stamp, "date"):
        try:
            action_date = stamp.date().isoformat()
        except Exception:
            action_date = None
    return {
        "date": action_date,
        "firm": _text(row.get("Firm")),
        "to_grade": _text(row.get("ToGrade")),
        "from_grade": _text(row.get("FromGrade")),
        "action": (_text(row.get("Action")) or "").lower() or None,
        "pt_current": _price(row.get("currentPriceTarget")),
        "pt_prior": _price(row.get("priorPriceTarget")),
    }


def _yahoo_analyst_loader(symbol: str) -> Tuple[Dict[str, Any], List[str]]:
    """Analyst data from Yahoo via yfinance: rating actions, monthly
    consensus counts, and the price-target summary. The three sub-feeds
    fail independently — a failed feed ships as None (its fields blank
    with a note), a fetched-but-empty feed as its empty shape (real
    zeros); all three down raises (the caller decides on the Finnhub
    backup)."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    failures: List[str] = []

    actions: Optional[List[Dict[str, Any]]] = None
    try:
        frame = ticker.upgrades_downgrades
        actions = (
            []
            if frame is None
            else [
                normalize_action_row(stamp, row)
                for stamp, row in frame.iterrows()
            ]
        )
    except Exception as exc:
        failures.append(f"rating actions ({exc})")

    consensus: Optional[List[Dict[str, Any]]] = None
    try:
        frame = ticker.recommendations
        consensus = []
        if frame is not None:
            for row in frame.to_dict("records"):
                consensus.append(
                    {
                        "period": _text(row.get("period")),
                        "strong_buy": _count(row.get("strongBuy")),
                        "buy": _count(row.get("buy")),
                        "hold": _count(row.get("hold")),
                        "sell": _count(row.get("sell")),
                        "strong_sell": _count(row.get("strongSell")),
                    }
                )
    except Exception as exc:
        failures.append(f"consensus counts ({exc})")

    targets: Optional[Dict[str, Any]] = None
    try:
        raw = ticker.analyst_price_targets
        targets = (
            {
                key: _price(raw.get(key))
                for key in ("current", "mean", "high", "low")
            }
            if isinstance(raw, Mapping)
            else {}
        )
    except Exception as exc:
        failures.append(f"price targets ({exc})")

    if len(failures) == 3:
        raise RuntimeError(
            "every Yahoo analyst feed failed: " + "; ".join(failures)
        )
    warnings = [
        f"analyst opinions: Yahoo {failure} unavailable" for failure in failures
    ]
    return (
        {
            "source": "yahoo",
            "actions": actions,
            "consensus": consensus,
            "targets": targets,
        },
        warnings,
    )


def _finnhub_consensus_loader(symbol: str, api_key: str) -> List[Dict[str, Any]]:
    """Consensus counts alone from Finnhub's free recommendation
    endpoint (rows newest month first, verified live 2026-08-18) — the
    backup when Yahoo is down entirely. No rating actions and no price
    targets on the free tier."""
    import requests

    response = requests.get(
        _FINNHUB_RECOMMENDATION_URL,
        params={"symbol": symbol, "token": api_key},
        timeout=_FINNHUB_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, list):
        raise ValueError(f"unexpected Finnhub recommendation response: {type(raw)}")
    consensus = []
    for offset, row in enumerate(raw[:2]):  # newest month + the prior one
        if not isinstance(row, Mapping):
            continue
        consensus.append(
            {
                "period": "0m" if offset == 0 else f"-{offset}m",
                "strong_buy": _count(row.get("strongBuy")),
                "buy": _count(row.get("buy")),
                "hold": _count(row.get("hold")),
                "sell": _count(row.get("sell")),
                "strong_sell": _count(row.get("strongSell")),
            }
        )
    return consensus


def _default_analyst_loader(symbol: str) -> Tuple[Dict[str, Any], List[str]]:
    """Yahoo first (keyless — works unconfigured); a total Yahoo
    failure falls back to Finnhub consensus counts when a key is set,
    loudly degraded."""
    try:
        return _yahoo_analyst_loader(symbol)
    except Exception as exc:
        api_key = data_key("finnhub")
        if not api_key:
            raise
        consensus = _finnhub_consensus_loader(symbol, api_key)
        return (
            {
                "source": "finnhub",
                "actions": None,
                "consensus": consensus,
                "targets": None,
            },
            [
                f"analyst opinions: Yahoo failed ({exc}); Finnhub consensus"
                " only — no price targets or rating-action counts"
            ],
        )


# ---------------------------------------------------------------------------
# Crowd side — keyless public aggregators.
# ---------------------------------------------------------------------------


def normalize_apewisdom_row(row: Mapping[str, Any]) -> Dict[str, Optional[int]]:
    """One ApeWisdom ranking row -> the five published stats (keys
    verified live 2026-08-18: rank, ticker, mentions, upvotes,
    rank_24h_ago, mentions_24h_ago)."""
    return {
        "mentions": _int_or_none(row.get("mentions")),
        "mentions_24h_ago": _int_or_none(row.get("mentions_24h_ago")),
        "upvotes": _int_or_none(row.get("upvotes")),
        "rank": _int_or_none(row.get("rank")),
        "rank_24h_ago": _int_or_none(row.get("rank_24h_ago")),
    }


def normalize_tradestie_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One Tradestie row -> the two published stats (keys verified live
    2026-08-18: ticker, sentiment, sentiment_score, no_of_comments)."""
    return {
        "sentiment_score": _float_or_none(row.get("sentiment_score")),
        "comments": _int_or_none(row.get("no_of_comments")),
    }


#: Cache format marker — bump when the cached list shape changes so a
#: same-day cache written by older code is refetched, not misread.
_CROWD_CACHE_VERSION = "v1"


def _fetch_apewisdom_list() -> List[Dict[str, Any]]:
    """ApeWisdom's complete all-stocks ranking (every page): the last
    24 hours of Reddit investing-sub chatter, all tickers."""
    import requests

    rows: List[Dict[str, Any]] = []
    page, total_pages = 1, 1
    while page <= min(total_pages, APEWISDOM_MAX_PAGES):
        response = requests.get(
            _APEWISDOM_URL.format(page=page), timeout=_CROWD_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        raw = response.json()
        results = raw.get("results") if isinstance(raw, Mapping) else None
        if not isinstance(results, list):
            raise ValueError("unexpected ApeWisdom response shape")
        rows.extend(row for row in results if isinstance(row, Mapping))
        total_pages = _int_or_none(raw.get("pages")) or 1
        page += 1
    return rows


def _fetch_tradestie_list() -> List[Dict[str, Any]]:
    """Tradestie's daily WallStreetBets comment scan (the ~50
    most-discussed tickers)."""
    import requests

    response = requests.get(_TRADESTIE_URL, timeout=_CROWD_TIMEOUT_SECONDS)
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, list):
        raise ValueError("unexpected Tradestie response shape")
    return [row for row in raw if isinstance(row, Mapping)]


def _cached_crowd_list(
    name: str,
    fetch: Callable[[], List[Dict[str, Any]]],
    cache: Optional[CacheStore] = None,
    today: Callable[[], date] = date.today,
) -> List[Dict[str, Any]]:
    """A crowd source's full ranking, fetched once per day and served
    from the cache after that (the macro_econ per-day convention): the
    lists are symbol-independent, so a multi-stock run must not refetch
    them per ticker. Only successful fetches are cached — a failed fetch
    raises and writes nothing, so the next ticker retries."""
    store = cache if cache is not None else default_cache_store()
    key = f"opinion_{name}_{_CROWD_CACHE_VERSION}_{today().isoformat()}"
    cached = store.read(key)  # None when missing or corrupt: refetch
    if isinstance(cached, list):
        return cached
    rows = fetch()
    store.write(key, rows)  # never raises; a cold cache beats a failed run
    return rows


def _find_ticker_row(
    rows: List[Dict[str, Any]], symbol: str
) -> Optional[Mapping[str, Any]]:
    wanted = symbol.upper()
    for row in rows:
        if str(row.get("ticker") or "").upper() == wanted:
            return row
    return None


def _default_apewisdom_loader(symbol: str) -> Optional[Dict[str, Any]]:
    """The ticker's row from ApeWisdom's all-stocks ranking (day-cached).
    None = fetched fine, ticker not ranked (no meaningful chatter)."""
    rows = _cached_crowd_list("apewisdom", _fetch_apewisdom_list)
    row = _find_ticker_row(rows, symbol)
    return None if row is None else normalize_apewisdom_row(row)


def _default_tradestie_loader(symbol: str) -> Optional[Dict[str, Any]]:
    """The ticker's row from Tradestie's daily WallStreetBets comment
    scan (day-cached). None = fetched fine, ticker not on today's
    list."""
    rows = _cached_crowd_list("tradestie", _fetch_tradestie_list)
    row = _find_ticker_row(rows, symbol)
    return None if row is None else normalize_tradestie_row(row)


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class OpinionProvider(DimensionProvider):
    """US analyst + crowd opinion measures: Yahoo analyst numbers and
    keyless Reddit-chatter aggregates, all in metric envelopes."""

    dimension = "opinion"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        analyst_loader: Callable[[str], Any] = _default_analyst_loader,
        apewisdom_loader: Callable[
            [str], Optional[Mapping[str, Any]]
        ] = _default_apewisdom_loader,
        tradestie_loader: Callable[
            [str], Optional[Mapping[str, Any]]
        ] = _default_tradestie_loader,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._load_analyst = analyst_loader
        self._load_apewisdom = apewisdom_loader
        self._load_tradestie = tradestie_loader
        self._today = today

    def supports(self, market: Market) -> bool:
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        today = self._today()
        warnings: List[str] = []
        field_notes: Dict[str, List[str]] = {}
        formulas: Dict[str, Any] = {}
        citations: List[Citation] = []

        analyst_data = self._fetch_analyst(symbol, warnings, field_notes)
        apewisdom = self._fetch_crowd_source(
            symbol, self._load_apewisdom, "ApeWisdom",
            APEWISDOM_FIELDS, warnings, field_notes,
        )
        tradestie = self._fetch_crowd_source(
            symbol, self._load_tradestie, "Tradestie",
            TRADESTIE_FIELDS, warnings, field_notes,
        )

        payload = {
            "analyst": self._analyst_group(analyst_data, today, formulas),
            "crowd": self._crowd_group(
                None if apewisdom == "failed" else apewisdom,
                None if tradestie == "failed" else tradestie,
            ),
        }

        if analyst_data is not None:
            # One source row serves every analyst field: the numbers
            # all come from the same fetched Yahoo analyst dataset (its
            # public page is the clickable form); the Finnhub backup
            # has no user-facing page, so its citation is a named
            # source without a link.
            if analyst_data.get("source") == "finnhub":
                citations.append(
                    Citation(source_name="Finnhub analyst consensus", url=None)
                )
            else:
                citations.append(
                    Citation(
                        source_name="Yahoo Finance analyst page",
                        url=f"https://finance.yahoo.com/quote/{symbol}/analysis",
                    )
                )
        if apewisdom != "failed":
            citations.append(
                Citation(
                    source_name="ApeWisdom Reddit mention ranking",
                    url=_APEWISDOM_PAGE_URL,
                )
            )
        if tradestie != "failed":
            citations.append(
                Citation(
                    source_name="Tradestie WallStreetBets comment sentiment",
                    url=_TRADESTIE_PAGE_URL,
                )
            )

        # Even with every source down the payload ships (all fields
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

    # ---- source fetches --------------------------------------------------

    def _fetch_analyst(
        self,
        symbol: str,
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Optional[Dict[str, Any]]:
        try:
            loaded = self._load_analyst(symbol)
        except Exception as exc:
            note_fields(
                warnings,
                field_notes,
                f"analyst opinions unavailable: {exc}",
                CONSENSUS_FIELDS + TARGET_FIELDS + ACTION_FIELDS,
            )
            return None
        if isinstance(loaded, tuple):
            data, loader_warnings = loaded[0], list(loaded[1])
        else:
            data, loader_warnings = loaded, []
        for message in loader_warnings:
            # A loader warning describes a failed sub-feed; pin it on
            # the fields that feed blanks.
            if "Finnhub consensus" in message:
                paths: Sequence[str] = TARGET_FIELDS + ACTION_FIELDS
            elif "rating actions" in message:
                paths = ACTION_FIELDS
            elif "consensus" in message:
                paths = CONSENSUS_FIELDS
            elif "price targets" in message:
                paths = TARGET_FIELDS
            else:
                paths = ()
            note_fields(warnings, field_notes, message, paths)
        return data

    def _fetch_crowd_source(
        self,
        symbol: str,
        loader: Callable[[str], Optional[Mapping[str, Any]]],
        source_name: str,
        fields: Sequence[str],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Any:
        """The source's row, None (fetched, not listed — noted quietly),
        or the string "failed" (fetch error — noted loudly)."""
        try:
            row = loader(symbol)
        except Exception as exc:
            note_fields(
                warnings,
                field_notes,
                f"crowd opinions: {source_name} unavailable ({exc})",
                fields,
            )
            return "failed"
        if row is None:
            note_fields(
                warnings,
                field_notes,
                f"crowd opinions: {symbol} is not on {source_name}'s ranking"
                " — too little Reddit chatter to register",
                fields,
            )
        return row

    # ---- payload groups --------------------------------------------------

    def _analyst_group(
        self,
        data: Optional[Mapping[str, Any]],
        today: date,
        formulas: Dict[str, Any],
    ) -> Dict[str, Any]:
        consensus = (data or {}).get("consensus")
        current = next(
            (
                row
                for row in (consensus or [])
                if row.get("period") == "0m"
            ),
            None,
        )
        prior = next(
            (
                row
                for row in (consensus or [])
                if row.get("period") == "-1m"
            ),
            None,
        )

        counts: Dict[str, Optional[int]] = {
            key: (current[key] if current else None)
            for key in ("strong_buy", "buy", "hold", "sell", "strong_sell")
        }
        firms_total = (
            sum(counts[key] for key in counts) if current else None
        )
        buy_pct = _buy_pct(current)
        prior_buy_pct = _buy_pct(prior)
        buy_drift = (
            _round1(buy_pct - prior_buy_pct)
            if buy_pct is not None and prior_buy_pct is not None
            else None
        )
        if firms_total:
            formulas["analyst.firms_total"] = {
                "formula": (
                    "strong_buy_firms + buy_firms + hold_firms + sell_firms"
                    " + strong_sell_firms"
                ),
                "inputs": {key: counts[key] for key in counts},
            }
        if buy_pct is not None:
            formulas["analyst.buy_rating_pct"] = {
                "formula": "(strong_buy_firms + buy_firms) / firms_total × 100",
                "inputs": {
                    "strong_buy_firms": counts["strong_buy"],
                    "buy_firms": counts["buy"],
                    "firms_total": firms_total,
                },
            }
        if buy_drift is not None:
            formulas["analyst.buy_rating_change_1m_pp"] = {
                "formula": "this month's buy share − last month's buy share",
                "inputs": {
                    "this_month_pct": buy_pct,
                    "last_month_pct": prior_buy_pct,
                },
            }

        targets = (data or {}).get("targets")
        # Yahoo ships means like 325.699 — targets are dollars, keep cents.
        mean = _round2((targets or {}).get("mean"))
        current_price = (targets or {}).get("current")
        vs_price = (
            _round1((mean / current_price - 1) * 100)
            if mean is not None and current_price
            else None
        )
        if vs_price is not None:
            formulas["analyst.target_vs_price_pct"] = {
                "formula": "(price_target_mean / current_price − 1) × 100",
                "inputs": {
                    "price_target_mean": mean,
                    "current_price": current_price,
                },
            }

        actions = (data or {}).get("actions")
        action_counts: Dict[str, Optional[int]] = {
            "up": None, "down": None, "init": None,
        }
        if actions is not None:
            since = business_days_back(today, ANALYST_WINDOW_BDAYS)
            windowed = [
                action
                for action in actions
                if action.get("date")
                and _parse_date(action["date"]) is not None
                and _parse_date(action["date"]) >= since
            ]
            for kind in action_counts:
                action_counts[kind] = sum(
                    1 for action in windowed if action.get("action") == kind
                )
            window_formula = {
                "formula": (
                    "count of rating actions of this kind published in the"
                    f" last {ANALYST_WINDOW_BDAYS} trading days"
                    f" (since {since.isoformat()})"
                ),
                "inputs": {},
            }
            formulas["analyst.upgrades_count"] = window_formula
            formulas["analyst.downgrades_count"] = window_formula
            formulas["analyst.initiations_count"] = window_formula

        window_phrase = f"the last {ANALYST_WINDOW_BDAYS} trading days"
        return {
            "firms_total": make_metric(
                "firms rating the stock",
                "How many Wall Street research firms currently publish a"
                " buy/hold/sell rating on this stock.",
                firms_total,
                interpretation=(
                    "More firms = a better-watched stock and a steadier"
                    " consensus; below ~5 the consensus fields are a few"
                    " voices, not a chorus."
                ),
            ),
            "strong_buy_firms": make_metric(
                "strong-buy ratings",
                "How many of those firms rate the stock strong buy this"
                " month.",
                counts["strong_buy"],
            ),
            "buy_firms": make_metric(
                "buy ratings",
                "How many firms rate the stock buy this month.",
                counts["buy"],
            ),
            "hold_firms": make_metric(
                "hold ratings",
                "How many firms rate the stock hold this month.",
                counts["hold"],
            ),
            "sell_firms": make_metric(
                "sell ratings",
                "How many firms rate the stock sell this month.",
                counts["sell"],
            ),
            "strong_sell_firms": make_metric(
                "strong-sell ratings",
                "How many firms rate the stock strong sell this month.",
                counts["strong_sell"],
            ),
            "buy_rating_pct": make_metric(
                "buy share of ratings",
                "The percent of rating firms on buy or strong buy this"
                " month.",
                buy_pct,
                interpretation=(
                    "Professional opinion, not a fact about the business —"
                    " analysts skew bullish as a group, so read the level"
                    " against the drift field below it."
                ),
            ),
            "buy_rating_change_1m_pp": make_metric(
                "buy share drift, 1 month",
                "How many percentage points the buy share moved versus a"
                " month ago (positive = analysts warming up).",
                buy_drift,
                interpretation=(
                    "The direction of drift often matters more than the"
                    " level — a falling buy share on a rising stock is a"
                    " quiet warning."
                ),
            ),
            "price_target_mean": make_metric(
                "average price target",
                "The average of the firms' 12-month price targets, in"
                " USD.",
                mean,
                interpretation=(
                    "A slow-moving opinion: targets chase the price as"
                    " often as they lead it."
                ),
            ),
            "price_target_high": make_metric(
                "highest price target",
                "The most bullish firm's 12-month price target, in USD.",
                _round2((targets or {}).get("high")),
            ),
            "price_target_low": make_metric(
                "lowest price target",
                "The most bearish firm's 12-month price target, in USD.",
                _round2((targets or {}).get("low")),
            ),
            "target_vs_price_pct": make_metric(
                "average target vs price",
                "How far the average price target sits from the current"
                " price (positive = target above the price).",
                vs_price,
                interpretation=(
                    "A big positive gap reads bullish only if the targets"
                    " are fresh — after a crash the gap is huge simply"
                    " because targets have not caught down yet."
                ),
            ),
            "upgrades_count": make_metric(
                "rating upgrades",
                f"How many firms raised their rating in {window_phrase}.",
                action_counts["up"],
                interpretation=(
                    "Fresh upgrades lean bullish; clusters usually follow"
                    " earnings."
                ),
            ),
            "downgrades_count": make_metric(
                "rating downgrades",
                f"How many firms cut their rating in {window_phrase}.",
                action_counts["down"],
                interpretation=(
                    "Fresh downgrades lean bearish — and often land with"
                    " a price-target cut attached."
                ),
            ),
            "initiations_count": make_metric(
                "new coverage started",
                "How many firms started covering the stock in"
                f" {window_phrase} (first-time ratings).",
                action_counts["init"],
                interpretation=(
                    "New coverage means new professional attention —"
                    " mildly bullish regardless of the opening grade."
                ),
            ),
        }

    @staticmethod
    def _crowd_group(
        apewisdom: Optional[Mapping[str, Any]],
        tradestie: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        ape = apewisdom or {}
        wsb = tradestie or {}
        return {
            "reddit_mentions": make_metric(
                "Reddit mentions, 24h",
                "How many times the last 24 hours of posts and comments"
                " on Reddit's big investing boards named this stock"
                " (ApeWisdom's count).",
                ape.get("mentions"),
                interpretation=(
                    "Attention, not direction: a spike means retail"
                    " traders are suddenly watching — crowded in both"
                    " directions, expect noisier moves."
                ),
            ),
            "reddit_mentions_24h_ago": make_metric(
                "Reddit mentions, prior 24h",
                "The same mention count for the 24 hours before that —"
                " the baseline the current count is judged against.",
                ape.get("mentions_24h_ago"),
            ),
            "reddit_upvotes": make_metric(
                "Reddit upvotes, 24h",
                "Total upvotes on the posts behind those mentions —"
                " how much the chatter resonated.",
                ape.get("upvotes"),
            ),
            "reddit_rank": make_metric(
                "Reddit buzz rank",
                "This stock's place on ApeWisdom's most-mentioned list"
                " right now (1 = the most talked-about ticker).",
                ape.get("rank"),
                interpretation=(
                    "Single digits = a main-character stock today; a fast"
                    " rank climb is the clearest crowd-attention signal"
                    " in this group."
                ),
            ),
            "reddit_rank_24h_ago": make_metric(
                "Reddit buzz rank, prior 24h",
                "The same rank a day earlier — compare to see the climb"
                " or fade.",
                ape.get("rank_24h_ago"),
            ),
            "wsb_sentiment_score": make_metric(
                "WallStreetBets comment tone",
                "Tradestie's word-scoring of today's WallStreetBets"
                " comments about this stock: above 0 = bullish wording"
                " dominates, below 0 = bearish (roughly −1 to +1).",
                wsb.get("sentiment_score"),
                interpretation=(
                    "The least reliable number in this report — one"
                    " forum's mood, scored by word choice. Direction"
                    " color at most; never a reason on its own."
                ),
            ),
            "wsb_comments": make_metric(
                "WallStreetBets comments",
                "How many WallStreetBets comments mentioned the stock in"
                " today's scan (only the ~50 most-discussed tickers make"
                " the list).",
                wsb.get("comments"),
            ),
        }


def _buy_pct(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    """The buy + strong-buy share of one consensus month, in percent."""
    if not row:
        return None
    total = sum(
        row[key]
        for key in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    )
    if total <= 0:
        return None
    return _round1((row["strong_buy"] + row["buy"]) / total * 100)
