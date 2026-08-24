# -*- coding: utf-8 -*-
"""US positioning provider — v2 envelope payload (TODO.md truth, 2026-08-01).

Who holds the stock and who can be forced to transact — the questions a
trade thesis always has to answer: who is on the other side, how crowded
the trade is, who can be squeezed, and what the informed parties are
doing. Every number is a published figure (yfinance for the disclosure
blocks, CBOE for options); no LLM anywhere in this dimension.

Groups and field names follow the TODO.md final-truth list: ``meta``
(the three dates that scope the lagged/forward blocks), ``ownership``
(structure), ``short_interest``, ``insider_activity_6m`` and
``options``. Every published metric ships as a
``{name, explanation, interpretation, value}`` envelope — the same
contract as technicals/fundamentals v2 — and computed metrics carry UI
formula receipts in ``DimensionResult.formulas``. Fields that cannot be
computed stay present with ``value: null`` (blank), never omitted.

Sources:

- **Short interest** — FINRA/exchange settlement data via the Yahoo
  summary (published twice a month, ~2 weeks late; the meta group's
  "short interest up to" carries the report date).
- **Ownership structure** — quarterly 13F institutional filings (up to
  45 days after quarter end) plus the float/insider split from the
  Yahoo summary. "ownership structure up to" carries the 13F quarter
  end read from the holders table.
- **Insider activity** — SEC Form 4 open-market buys and sells over the
  trailing six months. Awards, option exercises and gifts are excluded:
  only open-market trades carry conviction.
- **Options** — put/call held contracts (open interest) and today's
  volume summed over the nearest expirations, the exchange's own 30-day
  at-the-money implied volatility (``iv30``), and the implied
  report-day move (ATM straddle on the expiration just after the next
  earnings date), all from CBOE's delayed-quotes feed (Yahoo's intraday
  chains proved to carry no OI).

Two truth fields were DROPPED entirely (owner decision 2026-08-05 —
permanently blank rows carry no information; old stored runs still
render theirs from their saved payloads):

- ``institutional_diff_q_pp`` — Yahoo's per-holder ``pctChange`` proved
  unreliable (placeholder values like exactly +100% for top holders),
  and no free source publishes the prior-quarter aggregate.
- ``implied_vol_rank_1y`` — needs a year of implied-volatility history;
  no free source publishes it and the system stores none.

``options_fetched_at`` was dropped the same way (owner decision
2026-08-08). It recorded the clock moment the board was pulled, on the
theory that options are the one near-live block while everything else
is dated by its own source. The run gate landed that day and blocks
every run until 30 minutes past the close, so the board is now always
the frozen close — the same session ``meta.as_of`` already names on the
technicals report. The field could only ever repeat the run's own date
or, worse, contradict it (a Saturday 04:31 ET stamp on Friday's close).

Each block failing blanks its fields explicitly (nulls with notes) —
an ok-but-empty response is treated as missing, never
as a silent blank. Zero counts are real only when computed from actual
rows (owner rule 2026-07-24).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
    note_fields,
)
from .technicals import make_metric, metric_value

#: The Yahoo Finance page showing each block's numbers: yfinance itself
#: has no per-request page, but every block's figures are published on a
#: quote subpage — cited so readers can verify the data at the source.
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"

#: Near-dated expirations are where positioning information concentrates;
#: the puts-to-calls sums cover the nearest ones only (the implied
#: report-day move scans the whole fetched board for the post-earnings
#: expiration).
MAX_OPTION_EXPIRATIONS = 4

#: The Form 4 lookback: trailing six months.
INSIDER_WINDOW_DAYS = 183

#: The implied report-day move is published only when the next report is
#: this close: further out, the post-report straddle mostly prices weeks
#: of ordinary drift (verified on a live AAPL run: a report ~3 months
#: out read ±12.4% — the 3-month total move, not the report jump).
REPORT_MOVE_MAX_DAYS = 21

_TOP_HOLDERS_COUNT = 10

#: Payload paths ("group.key") each data source feeds — the fields a
#: source failure blanks, so its note can sit beside them on the report
#: page.
SHORT_INTEREST_FIELDS = (
    "short_interest.short_pct_of_float",
    "short_interest.days_to_cover",
    "short_interest.change_vs_prior_month_pct",
    "meta.short_interest_as_of",
)
OWNERSHIP_FIELDS = (
    "ownership.institutional_pct",
    "ownership.top10_institutions_pct",
    "ownership.insider_pct",
    "ownership.float_shares",
    "meta.ownership_as_of",
)
INSIDER_FIELDS = (
    "insider_activity_6m.buy_count",
    "insider_activity_6m.sell_count",
    "insider_activity_6m.net_value_usd",
)
OPTIONS_FIELDS = (
    "options.put_call_oi_ratio",
    "options.put_call_volume_ratio",
    "options.total_open_interest",
    "options.implied_vol_pct",
    "options.implied_report_move_pct",
    "meta.options_bets_through",
)
REPORT_MOVE_FIELD = "options.implied_report_move_pct"


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number  # NaN guard
    return None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _epoch_to_date(value: Any) -> Optional[str]:
    """Yahoo's ``dateShortInterest`` is unix seconds; show it as a date."""
    number = _to_float(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _fraction_pct(value: Any) -> Optional[float]:
    """Yahoo serves ownership/short ratios as fractions (0.0234 = 2.34%)."""
    number = _to_float(value)
    return number * 100.0 if number is not None else None


def _has_values(section: Optional[Mapping[str, Any]]) -> bool:
    return bool(section) and any(
        metric_value(node) is not None for node in section.values()
    )


# ---------------------------------------------------------------------------
# Pure metric computations (all offline-testable)
# ---------------------------------------------------------------------------


def short_interest_metrics(info: Mapping[str, Any]) -> Dict[str, Any]:
    """The crowdedness-and-squeeze block from the Yahoo summary fields.

    Alongside each value ride the receipt ingredients: ``short_pct_
    computed`` marks the shares÷float fallback (a fetched percentage
    needs no receipt), and the prior-report share count feeds the diff
    receipt.
    """
    shares_short = _to_float(info.get("sharesShort"))
    prior = _to_float(info.get("sharesShortPriorMonth"))
    float_shares = _to_float(info.get("floatShares"))

    short_pct = _fraction_pct(info.get("shortPercentOfFloat"))
    short_pct_computed = False
    if short_pct is None and shares_short is not None and float_shares:
        short_pct = shares_short / float_shares * 100.0
        short_pct_computed = True

    change_pct: Optional[float] = None
    if shares_short is not None and prior:
        change_pct = (shares_short - prior) / prior * 100.0

    return {
        "short_pct_of_float": short_pct,
        "short_pct_computed": short_pct_computed,
        "days_to_cover": _to_float(info.get("shortRatio")),
        "shares_short": shares_short,
        "prior_report_shares": prior,
        "float_shares": float_shares,
        "change_vs_prior_month_pct": change_pct,
        "as_of": _epoch_to_date(info.get("dateShortInterest")),
    }


def ownership_metrics(
    info: Mapping[str, Any],
    holders: Optional[Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Who holds it: 13F institutional %, insider %, top-10 concentration,
    plus the 13F quarter end the holders table describes.

    ``holders`` rows come from the institutional-holders table; ``pctHeld``
    (older yfinance: ``% Out``) is each holder's fraction of shares
    outstanding, ``date_reported`` (loader-normalized) the filing's
    quarter end.
    """
    top10: Optional[float] = None
    as_of: Optional[str] = None
    if holders:
        rows = list(holders)
        fractions = [
            _to_float(row.get("pctHeld", row.get("% Out")))
            for row in rows[:_TOP_HOLDERS_COUNT]
        ]
        present = [fraction for fraction in fractions if fraction is not None]
        if present:
            top10 = sum(present) * 100.0
        dates = [
            str(row.get("date_reported"))[:10]
            for row in rows
            if row.get("date_reported")
        ]
        if dates:
            as_of = max(dates)

    return {
        "institutional_pct": _fraction_pct(info.get("heldPercentInstitutions")),
        "insider_pct": _fraction_pct(info.get("heldPercentInsiders")),
        "top10_institutions_pct": top10,
        "float_shares": _to_float(info.get("floatShares")),
        "as_of": as_of,
    }


def _trade_kind(text: str) -> Optional[str]:
    """Open-market buy/sell from the Form 4 row text; anything else
    (awards, exercises, gifts, conversions) is not a conviction trade."""
    lowered = text.lower()
    if "purchase" in lowered:
        return "buy"
    if "sale" in lowered:
        return "sell"
    return None


def insider_metrics(
    rows: Sequence[Mapping[str, Any]], today: date
) -> Dict[str, Any]:
    """Net open-market insider activity over the trailing window.

    Rows carry ``date`` (ISO string), ``text``, ``shares``, ``value``.
    Rows with unparseable dates or non-open-market text are skipped.
    Zero counts are real information — no insider traded — not a blank.
    ``buy_value_usd``/``sell_value_usd`` are the money-diff receipt's
    ingredients.
    """
    cutoff = today - timedelta(days=INSIDER_WINDOW_DAYS)
    buys = sells = 0
    buy_value = 0.0
    sell_value = 0.0
    for row in rows:
        raw_date = str(row.get("date") or "")
        try:
            when = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        if when < cutoff or when > today:
            continue
        kind = _trade_kind(str(row.get("text") or ""))
        if kind is None:
            continue
        value = _to_float(row.get("value")) or 0.0
        if kind == "buy":
            buys += 1
            buy_value += value
        else:
            sells += 1
            sell_value += value
    return {
        "buy_count": buys,
        "sell_count": sells,
        "buy_value_usd": buy_value,
        "sell_value_usd": sell_value,
        "net_value_usd": buy_value - sell_value,
    }


def _sum_side(chains: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    """Sum one side's per-expiration totals; None when no chain carried
    the field at all (missing data must never masquerade as 0)."""
    values = [_to_float(chain.get(key)) for chain in chains]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def options_metrics(
    board: Mapping[str, Any],
) -> Tuple[Dict[str, Any], List[Tuple[str, Tuple[str, ...]]]]:
    """(metrics, notes) from the CBOE board: put/call ratios summed
    over the nearest ``MAX_OPTION_EXPIRATIONS`` expirations, the last
    expiration those sums cover, and the exchange's 30-day at-the-money
    implied volatility. Each note is (message, affected payload paths).

    A zero side is indistinguishable from a source that failed to
    publish the field, so a ratio is computed only when BOTH sides are
    positive; otherwise the fields stay blank (None) and a warning says
    why. No default values on bad data (owner decision 2026-07-24).
    """
    chains = sorted(
        board.get("chains") or [], key=lambda chain: str(chain.get("expiration"))
    )[:MAX_OPTION_EXPIRATIONS]
    call_oi = _sum_side(chains, "call_oi")
    put_oi = _sum_side(chains, "put_oi")
    call_volume = _sum_side(chains, "call_volume")
    put_volume = _sum_side(chains, "put_volume")

    notes: List[Tuple[str, Tuple[str, ...]]] = []
    oi_usable = bool(call_oi and put_oi and call_oi > 0 and put_oi > 0)
    if not oi_usable:
        notes.append((
            "options open interest missing or zero at the source — "
            "puts-to-calls (held) and the held total omitted",
            ("options.put_call_oi_ratio", "options.total_open_interest"),
        ))
    volume_usable = bool(
        call_volume and put_volume and call_volume > 0 and put_volume > 0
    )
    if not volume_usable:
        notes.append((
            "options volume missing or zero at the source — "
            "puts-to-calls (traded today) omitted",
            ("options.put_call_volume_ratio",),
        ))

    iv30 = _to_float(board.get("iv30"))
    if iv30 is not None and iv30 <= 0:
        iv30 = None
    if iv30 is None:
        notes.append((
            "CBOE published no 30-day implied volatility — "
            "implied stock volatility omitted",
            ("options.implied_vol_pct",),
        ))

    expirations = [
        str(chain.get("expiration")) for chain in chains if chain.get("expiration")
    ]
    metrics = {
        "put_call_oi_ratio": put_oi / call_oi if oi_usable else None,
        "put_call_volume_ratio": (
            put_volume / call_volume if volume_usable else None
        ),
        "total_open_interest": call_oi + put_oi if oi_usable else None,
        "implied_vol_pct": iv30,
        "bets_through": max(expirations) if expirations else None,
        # Receipt ingredients.
        "call_oi": call_oi,
        "put_oi": put_oi,
        "call_volume": call_volume,
        "put_volume": put_volume,
    }
    return metrics, notes


def implied_report_move(
    board: Mapping[str, Any], earnings_date: Optional[str], today: date
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(ingredients, warning): the % move the options market prices in
    for the next quarterly report — the at-the-money straddle (call mid
    + put mid) on the first expiration on/after the report date, as a
    percent of the stock price. Unsigned by nature: option prices say
    how BIG the jump should be, not which way.

    Published only when the report is within ``REPORT_MOVE_MAX_DAYS``:
    the straddle prices ALL movement until its expiration, so the
    number reads as the report jump only when the report dominates it.

    Returns (None, reason) when the report date is unknown or too far,
    no fetched expiration falls after it, or the ATM quotes are
    unusable.
    """
    if not earnings_date:
        return None, (
            "next report date unknown — implied report-day move omitted"
        )
    try:
        report_day = date.fromisoformat(earnings_date[:10])
    except ValueError:
        return None, (
            "next report date unparseable — implied report-day move omitted"
        )
    days_away = (report_day - today).days
    if days_away > REPORT_MOVE_MAX_DAYS:
        # The note carries the actual countdown and both dates so the
        # report page can show the real number of days (with its
        # date-minus-date receipt), not just the threshold.
        return None, (
            f"next quarterly report is {days_away} days away (report "
            f"{report_day.isoformat()}, today {today.isoformat()}) — "
            f"more than {REPORT_MOVE_MAX_DAYS} days out, option prices "
            "mostly reflect ordinary drift, not the report jump; "
            "implied report-day move omitted"
        )
    price = _to_float(board.get("current_price"))
    if price is None or price <= 0:
        return None, (
            "CBOE published no stock price — implied report-day move omitted"
        )
    chains = sorted(
        board.get("chains") or [], key=lambda chain: str(chain.get("expiration"))
    )
    for chain in chains:
        expiration = str(chain.get("expiration") or "")
        if not expiration or expiration < earnings_date:
            continue
        call_mid = _quote_mid(chain, "atm_call_bid", "atm_call_ask")
        put_mid = _quote_mid(chain, "atm_put_bid", "atm_put_ask")
        if call_mid is None or put_mid is None:
            return None, (
                "no usable at-the-money quotes on the post-report "
                "expiration — implied report-day move omitted"
            )
        return {
            "move_pct": (call_mid + put_mid) / price * 100.0,
            "atm_call_price": call_mid,
            "atm_put_price": put_mid,
            "stock_price": price,
            "expiration": expiration,
        }, None
    return None, (
        "no fetched option expiration falls after the next report date — "
        "implied report-day move omitted"
    )


def _quote_mid(
    chain: Mapping[str, Any], bid_key: str, ask_key: str
) -> Optional[float]:
    bid = _to_float(chain.get(bid_key))
    ask = _to_float(chain.get(ask_key))
    if bid is None or ask is None or ask <= 0 or bid < 0 or ask < bid:
        return None
    return (bid + ask) / 2.0


# ---------------------------------------------------------------------------
# Default loaders (thin network shims; everything above stays pure)
# ---------------------------------------------------------------------------


def _default_info_loader(symbol: str) -> Mapping[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.get_info() if hasattr(ticker, "get_info") else (ticker.info or {})
    return info if isinstance(info, Mapping) else {}


def _default_holders_loader(symbol: str) -> List[Dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(symbol).institutional_holders
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: List[Dict[str, Any]] = []
    for record in frame.to_dict("records"):
        reported = record.get("Date Reported")
        if hasattr(reported, "date"):
            date_text: Optional[str] = reported.date().isoformat()
        else:
            date_text = str(reported)[:10] if reported is not None else None
        rows.append({**record, "date_reported": date_text})
    return rows


def _default_insider_loader(symbol: str) -> List[Dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(symbol).insider_transactions
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: List[Dict[str, Any]] = []
    for record in frame.to_dict("records"):
        start = record.get("Start Date")
        if hasattr(start, "date"):
            date_text: Optional[str] = start.date().isoformat()
        else:
            date_text = str(start)[:10] if start is not None else None
        text = next(
            (record[key] for key in ("Text", "Transaction")
             if isinstance(record.get(key), str)),
            "",
        )
        rows.append(
            {
                "date": date_text,
                "text": text,
                "shares": record.get("Shares"),
                "value": record.get("Value"),
            }
        )
    return rows


#: CBOE's free delayed-quotes feed: every listed contract with its
#: exchange-published open interest, per-contract quotes, and the
#: underlying's price and 30-day ATM implied volatility — replacing
#: Yahoo for the options block (owner decision 2026-07-24: Yahoo's
#: intraday chains carry zero/absent OI until their overnight update,
#: which a real NVDA run surfaced as a bogus "put/call OI ratio 0").
CBOE_OPTIONS_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
CBOE_QUOTE_PAGE = "https://www.cboe.com/delayed_quotes/{symbol}/quote_table"
_CBOE_TIMEOUT_SECONDS = 20

#: OCC option symbol: root + YYMMDD expiration + C/P + strike×1000.
_OPTION_SYMBOL_RE = re.compile(r"^[A-Z.]+(\d{6})([CP])(\d{8})$")

_CBOE_SIDE_KEYS = {"C": ("call_oi", "call_volume"), "P": ("put_oi", "put_volume")}


def _expiration_iso(yymmdd: str) -> str:
    return f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"


def _default_options_loader(symbol: str) -> Dict[str, Any]:
    """The CBOE board: underlying price + 30-day ATM implied volatility
    + per-expiration OI/volume totals and at-the-money quotes for ALL
    listed expirations (one request carries the whole board). A side's
    sum key is present only when at least one contract carried the
    field — absent data stays absent, never 0."""
    import requests

    response = requests.get(
        CBOE_OPTIONS_URL.format(symbol=symbol.upper()),
        timeout=_CBOE_TIMEOUT_SECONDS,
        headers={"User-Agent": "daily-stock-analysis"},
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    contracts = data.get("options") or []
    price = _to_float(data.get("current_price")) or _to_float(data.get("close"))

    sums: Dict[str, Dict[str, float]] = {}
    quotes: Dict[str, Dict[float, Dict[str, Optional[float]]]] = {}
    for contract in contracts:
        match = _OPTION_SYMBOL_RE.match(str(contract.get("option") or ""))
        if not match:
            continue
        expiration, side, raw_strike = match.groups()
        oi_key, volume_key = _CBOE_SIDE_KEYS[side]
        expiration_sums = sums.setdefault(expiration, {})
        for key, value in (
            (oi_key, _to_float(contract.get("open_interest"))),
            (volume_key, _to_float(contract.get("volume"))),
        ):
            if value is None:
                continue
            expiration_sums[key] = expiration_sums.get(key, 0.0) + value
        strike = int(raw_strike) / 1000.0
        entry = quotes.setdefault(expiration, {}).setdefault(strike, {})
        prefix = "call" if side == "C" else "put"
        entry[f"{prefix}_bid"] = _to_float(contract.get("bid"))
        entry[f"{prefix}_ask"] = _to_float(contract.get("ask"))

    chains: List[Dict[str, Any]] = []
    for expiration in sorted(sums):
        entry: Dict[str, Any] = {"expiration": _expiration_iso(expiration)}
        entry.update(sums[expiration])
        entry.update(_atm_quote(quotes.get(expiration) or {}, price))
        chains.append(entry)
    return {"current_price": price, "iv30": _to_float(data.get("iv30")), "chains": chains}


def _atm_quote(
    strikes: Mapping[float, Mapping[str, Optional[float]]],
    price: Optional[float],
) -> Dict[str, Optional[float]]:
    """The both-sides quote at the strike nearest the stock price."""
    if price is None:
        return {}
    two_sided = {
        strike: quote
        for strike, quote in strikes.items()
        if quote.get("call_ask") is not None and quote.get("put_ask") is not None
    }
    if not two_sided:
        return {}
    strike = min(two_sided, key=lambda value: abs(value - price))
    quote = two_sided[strike]
    return {
        "atm_strike": strike,
        "atm_call_bid": quote.get("call_bid"),
        "atm_call_ask": quote.get("call_ask"),
        "atm_put_bid": quote.get("put_bid"),
        "atm_put_ask": quote.get("put_ask"),
    }


def _default_earnings_lookup(symbol: str) -> Optional[str]:
    """Next report date (ISO) for the implied report-day move; None when
    no report is scheduled or the calendar lookup failed."""
    from ..earnings import next_earnings_info

    return next_earnings_info(symbol, Market.US).next_date


def _default_today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class PositioningUSProvider(DimensionProvider):
    """NUMERIC US positioning: short interest, ownership, insiders, options."""

    dimension = "positioning"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        info_loader: Callable[[str], Mapping[str, Any]] = _default_info_loader,
        holders_loader: Callable[[str], Sequence[Mapping[str, Any]]] = _default_holders_loader,
        insider_loader: Callable[[str], Sequence[Mapping[str, Any]]] = _default_insider_loader,
        options_loader: Callable[[str], Mapping[str, Any]] = _default_options_loader,
        earnings_lookup: Callable[[str], Optional[str]] = _default_earnings_lookup,
        today: Callable[[], date] = _default_today,
    ) -> None:
        self._info_loader = info_loader
        self._holders_loader = holders_loader
        self._insider_loader = insider_loader
        self._options_loader = options_loader
        self._earnings_lookup = earnings_lookup
        self._today = today

    def supports(self, market: Market) -> bool:
        # US disclosure only for now: FINRA short interest, 13F, Form 4.
        # A-share margin balances / HK short positions are separate designs.
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        citations: List[Citation] = []
        warnings: List[str] = []
        field_notes: Dict[str, List[str]] = {}
        formulas: Dict[str, Any] = {}

        info = self._load_info(symbol, warnings, field_notes)
        short = short_interest_metrics(info or {})
        ownership = ownership_metrics(
            info or {}, self._load_holders(symbol, info, warnings, field_notes)
        )
        insiders = self._load_insiders(symbol, warnings, field_notes)
        board = self._load_board(symbol, warnings, field_notes)
        options, report_move = self._options_blocks(
            symbol, board, warnings, field_notes
        )
        # Group order = display order (TODO.md final-truth list).
        payload: Dict[str, Any] = {
            "meta": self._meta_group(ownership, short, options, formulas),
            "ownership": self._ownership_group(ownership, formulas),
            "short_interest": self._short_interest_group(short, formulas),
            "insider_activity_6m": self._insider_group(insiders, formulas),
            "options": self._options_group(options, report_move, formulas),
        }

        # These checks attach the sources' citations and blank-field
        # notes as side effects.
        self._short_ok(symbol, info, short, citations, warnings, field_notes)
        self._ownership_ok(
            symbol, info, ownership, citations, warnings, field_notes
        )
        options_ok = bool(board and board.get("chains"))
        if options_ok:
            citations.append(
                Citation(
                    source_name="CBOE delayed quotes (options chain)",
                    url=CBOE_QUOTE_PAGE.format(symbol=symbol.lower()),
                )
            )

        # Even with every block down the payload ships (all fields
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
                SHORT_INTEREST_FIELDS + OWNERSHIP_FIELDS,
            )
            return None

    def _load_holders(
        self,
        symbol: str,
        info: Optional[Mapping[str, Any]],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Optional[Sequence[Mapping[str, Any]]]:
        if info is None:
            return None  # the shared fetch failure is already on the warnings
        try:
            return self._holders_loader(symbol)
        except Exception as exc:
            # Concentration + as-of alone degrade; the summary fields count.
            note_fields(
                warnings, field_notes,
                f"institutional holders failed for {symbol}: {exc}",
                ("ownership.top10_institutions_pct", "meta.ownership_as_of"),
            )
            return None

    def _load_insiders(
        self,
        symbol: str,
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Optional[Dict[str, Any]]:
        try:
            rows = self._insider_loader(symbol)
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"insider transactions failed for {symbol}: {exc}",
                INSIDER_FIELDS,
            )
            return None
        if not rows:
            # An empty table is indistinguishable from a source outage —
            # zero counts are only real when computed from actual rows
            # (no defaults on missing data, owner rule 2026-07-24).
            note_fields(
                warnings, field_notes,
                f"Yahoo returned no insider transaction rows for {symbol} — "
                "insider trades omitted",
                INSIDER_FIELDS,
            )
            return None
        return insider_metrics(rows, self._today())

    def _load_board(
        self,
        symbol: str,
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Optional[Mapping[str, Any]]:
        try:
            board = self._options_loader(symbol)
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"options chain failed for {symbol}: {exc}",
                OPTIONS_FIELDS,
            )
            return None
        if not board or not board.get("chains"):
            note_fields(
                warnings, field_notes,
                f"no listed options found for {symbol}",
                OPTIONS_FIELDS,
            )
            return None
        return board

    def _options_blocks(
        self,
        symbol: str,
        board: Optional[Mapping[str, Any]],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        if board is None:
            return {}, None
        metrics, option_notes = options_metrics(board)
        for message, paths in option_notes:
            note_fields(warnings, field_notes, message, paths)

        earnings_date: Optional[str] = None
        try:
            earnings_date = self._earnings_lookup(symbol)
        except Exception as exc:
            note_fields(
                warnings, field_notes,
                f"earnings date lookup failed for {symbol}: {exc}",
                (REPORT_MOVE_FIELD,),
            )
        move, move_warning = implied_report_move(board, earnings_date, self._today())
        if move_warning:
            note_fields(
                warnings, field_notes, move_warning, (REPORT_MOVE_FIELD,)
            )
        return metrics, move

    def _short_ok(
        self,
        symbol: str,
        info: Optional[Mapping[str, Any]],
        short: Mapping[str, Any],
        citations: List[Citation],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> bool:
        if info is None:
            return False  # the fetch failure is already on the warnings
        published = {
            key: short[key]
            for key in ("short_pct_of_float", "days_to_cover",
                        "change_vs_prior_month_pct", "as_of")
        }
        if not any(value is not None for value in published.values()):
            # ok-but-empty is the silent-blank trap: surface it explicitly.
            note_fields(
                warnings, field_notes,
                f"Yahoo returned no short-interest fields for {symbol}",
                SHORT_INTEREST_FIELDS,
            )
            return False
        citations.append(
            Citation(
                source_name="FINRA short interest via Yahoo Finance (yfinance)",
                url=f"{YAHOO_QUOTE_URL.format(symbol=symbol)}/key-statistics",
            )
        )
        return True

    def _ownership_ok(
        self,
        symbol: str,
        info: Optional[Mapping[str, Any]],
        ownership: Mapping[str, Any],
        citations: List[Citation],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> bool:
        if info is None:
            return False
        if not any(value is not None for value in ownership.values()):
            note_fields(
                warnings, field_notes,
                f"Yahoo returned no ownership fields for {symbol}",
                OWNERSHIP_FIELDS,
            )
            return False
        citations.append(
            Citation(
                source_name="13F institutional holdings via Yahoo Finance (yfinance)",
                url=f"{YAHOO_QUOTE_URL.format(symbol=symbol)}/holders",
            )
        )
        return True

    # ---- payload groups --------------------------------------------------

    @staticmethod
    def _meta_group(
        ownership: Mapping[str, Any],
        short: Mapping[str, Any],
        options: Mapping[str, Any],
        formulas: Dict[str, Any],
    ) -> Dict[str, Any]:
        bets_through = options.get("bets_through")
        if bets_through is not None:
            formulas["meta.options_bets_through"] = {
                "formula": (
                    "the furthest expiration date included in the "
                    f"puts-to-calls sums (the nearest {MAX_OPTION_EXPIRATIONS} "
                    "expiration dates)"
                ),
                "inputs": {},
            }
        return {
            "ownership_as_of": make_metric(
                "ownership structure up to",
                "The quarter end the fund-ownership figures describe — "
                "big funds report their holdings once a quarter, up to "
                "45 days after the quarter closes.",
                ownership.get("as_of"),
                interpretation=(
                    "The ownership block can describe positioning from "
                    "3–4.5 months ago: read it as background, never as "
                    "current buying or selling."
                ),
            ),
            "short_interest_as_of": make_metric(
                "short interest up to",
                "The date the short-interest figures were measured — "
                "they publish twice a month, about two weeks late.",
                short.get("as_of"),
                interpretation=(
                    "If the price has moved sharply since this date, "
                    "the shorts it describes may already have bought "
                    "back and left — discount the block."
                ),
            ),
            "options_bets_through": make_metric(
                "options betting up to",
                "The furthest option expiration date included in the "
                "puts-to-calls sums. Unlike the two dates above, this "
                "one points forward: the options data itself is fresh "
                "as of this report.",
                bets_through,
                interpretation=(
                    "How far into the future the summed bets run — a "
                    "near date means the ratios read only the next few "
                    "weeks of positioning, not the whole board."
                ),
            ),
        }

    @staticmethod
    def _ownership_group(
        ownership: Mapping[str, Any], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        if ownership.get("top10_institutions_pct") is not None:
            formulas["ownership.top10_institutions_pct"] = {
                "formula": (
                    "sum of the ten largest fund holders' stakes, from "
                    "the institutional-holders table"
                ),
                "inputs": {},
            }
        return {
            "institutional_pct": make_metric(
                "institutional ownership",
                "Percent of the company held by professional funds "
                "(mutual funds, pensions, ETFs), from their quarterly "
                "13F filings.",
                _round(ownership.get("institutional_pct")),
                interpretation=(
                    "Roughly 30–90% is healthy sponsorship. Very low = "
                    "funds can't or won't own it — a quality/liquidity "
                    "red flag; very high = fully discovered, who's left "
                    "to buy?"
                ),
            ),
            "top10_institutions_pct": make_metric(
                "top-10 institutional ownership",
                "The combined stake of the ten largest fund holders "
                "(insiders are not part of this table).",
                _round(ownership.get("top10_institutions_pct")),
                interpretation=(
                    "Concentration risk: if a third of the company sits "
                    "with ten funds, one fund's exit is a surprise down "
                    "day — argues for smaller size or a wider stop."
                ),
            ),
            "insider_pct": make_metric(
                "insider ownership",
                "Percent held by the company's insiders — its "
                "executives, board directors, and anyone owning more "
                "than 10% — the people required by law to report their "
                "trades.",
                _round(ownership.get("insider_pct")),
                interpretation=(
                    "High = management's own wealth rides on the stock, "
                    "and those locked-up shares shrink the float below "
                    "what it looks like — bigger swings both ways."
                ),
            ),
            "float_shares": make_metric(
                "float",
                "The number of shares actually available to trade — "
                "total shares minus locked-up insider and strategic "
                "stakes.",
                ownership.get("float_shares"),
                interpretation=(
                    "A small float moves and squeezes harder in both "
                    "directions: size smaller, expect gaps. It is also "
                    "the denominator behind the short-interest block."
                ),
            ),
        }

    @staticmethod
    def _short_interest_group(
        short: Mapping[str, Any], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        if short.get("short_pct_computed"):
            formulas["short_interest.short_pct_of_float"] = {
                "formula": "shorted_shares / float_shares × 100",
                "inputs": {
                    "shorted_shares": short["shares_short"],
                    "float_shares": short["float_shares"],
                },
            }
        if short.get("change_vs_prior_month_pct") is not None:
            formulas["short_interest.change_vs_prior_month_pct"] = {
                "formula": (
                    "(shorted_shares − prior_report_shares) / "
                    "prior_report_shares × 100"
                ),
                "inputs": {
                    "shorted_shares": short["shares_short"],
                    "prior_report_shares": short["prior_report_shares"],
                },
            }
        return {
            "short_pct_of_float": make_metric(
                "shorted shares to float",
                "Of the shares actually available to trade (the "
                "float), the percent that has been borrowed and sold "
                "by investors betting the price will fall (shorts).",
                _round(short.get("short_pct_of_float")),
                interpretation=(
                    "Under ~3% is normal; ~10%+ is a crowded bear "
                    "trade; 20%+ is squeeze territory — good news can "
                    "force shorts to buy back at once and spike the "
                    "price. Expect violent moves both ways."
                ),
            ),
            "days_to_cover": make_metric(
                "shorted shares to avg daily volume",
                "Shorted shares divided by average daily trading "
                "volume — how many full days of normal trading the "
                "shorts would need to buy everything back. Unit: days. "
                "The average volume is the data vendor's own figure, "
                "so it can differ a little from the 60d average in "
                "the technicals report.",
                _round(short.get("days_to_cover")),
                interpretation=(
                    "1–2 days = shorts can exit quietly; 5+ = their own "
                    "buying pushes the price while they exit, so "
                    "squeezes run further."
                ),
            ),
            "change_vs_prior_month_pct": make_metric(
                "shorted shares diff (current vs prev report)",
                "Percent change in shorted shares versus the previous "
                "twice-monthly report.",
                _round(short.get("change_vs_prior_month_pct")),
                interpretation=(
                    "Direction beats level: rising = bears pressing "
                    "the bet; falling = shorts already giving up and "
                    "buying back, which itself supports the price."
                ),
            ),
        }

    @staticmethod
    def _insider_group(
        insiders: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        counts_note = (
            "Counts only open-market trades from SEC Form 4 filings "
            "over the last six months — stock awards, option exercises "
            "and gifts are excluded, because only trades made with "
            "insiders' own money reveal conviction."
        )
        if insiders is not None:
            words = {
                "buy_count": "open-market insider purchases",
                "sell_count": "open-market insider sales",
            }
            for key, what in words.items():
                formulas[f"insider_activity_6m.{key}"] = {
                    "formula": (
                        f"count of {what} (SEC Form 4) in the last 6 "
                        "months; awards, option exercises and gifts "
                        "excluded"
                    ),
                    "inputs": {},
                }
            formulas["insider_activity_6m.net_value_usd"] = {
                "formula": "insider_buy_money − insider_sell_money",
                "inputs": {
                    "insider_buy_money": insiders["buy_value_usd"],
                    "insider_sell_money": insiders["sell_value_usd"],
                },
            }
        value = (lambda key: insiders.get(key)) if insiders else (lambda key: None)
        return {
            "buy_count": make_metric(
                "6m total insider buys",
                f"How many times insiders bought on the open market. {counts_note}",
                value("buy_count"),
                interpretation=(
                    "The strongest signal in this report: insiders sell "
                    "for many reasons but buy for exactly one. Even one "
                    "or two real buys tilt bullish."
                ),
            ),
            "sell_count": make_metric(
                "6m total insider sells",
                f"How many times insiders sold on the open market. {counts_note}",
                value("sell_count"),
                interpretation=(
                    "Scattered selling is routine (taxes, "
                    "diversification); many different insiders selling "
                    "in a tight cluster is the warning shape."
                ),
            ),
            "net_value_usd": make_metric(
                "6m money diff (insider buys vs sells)",
                "Dollars insiders spent buying minus dollars they took "
                "out selling, over those same open-market trades. "
                "Positive = net buying.",
                _round(value("net_value_usd"), 0),
                interpretation=(
                    "The bottom line of insider conviction, comparable "
                    "across stocks: clearly positive = bullish tell; a "
                    "large negative during a rally = management cashing "
                    "out into strength."
                ),
            ),
        }

    @staticmethod
    def _options_group(
        options: Mapping[str, Any],
        report_move: Optional[Mapping[str, Any]],
        formulas: Dict[str, Any],
    ) -> Dict[str, Any]:
        if options.get("put_call_oi_ratio") is not None:
            formulas["options.put_call_oi_ratio"] = {
                "formula": "held_puts / held_calls",
                "inputs": {
                    "held_puts": options["put_oi"],
                    "held_calls": options["call_oi"],
                },
            }
        if options.get("put_call_volume_ratio") is not None:
            formulas["options.put_call_volume_ratio"] = {
                "formula": "puts_traded_today / calls_traded_today",
                "inputs": {
                    "puts_traded_today": options["put_volume"],
                    "calls_traded_today": options["call_volume"],
                },
            }
        if options.get("total_open_interest") is not None:
            formulas["options.total_open_interest"] = {
                "formula": "held_puts + held_calls",
                "inputs": {
                    "held_puts": options["put_oi"],
                    "held_calls": options["call_oi"],
                },
            }
        if report_move is not None:
            formulas["options.implied_report_move_pct"] = {
                "formula": "(atm_call_price + atm_put_price) / stock_price × 100",
                "inputs": {
                    "atm_call_price": round(report_move["atm_call_price"], 2),
                    "atm_put_price": round(report_move["atm_put_price"], 2),
                    "stock_price": round(report_move["stock_price"], 2),
                },
            }
        return {
            # Field order = TODO.md truth-spec order: the trust meter
            # leads, then the two ratios it qualifies.
            "total_open_interest": make_metric(
                "total held options",
                "Total option contracts currently held open (puts plus "
                "calls) over the covered expirations — not the number "
                "of listed option products, and not trading volume.",
                options.get("total_open_interest"),
                interpretation=(
                    "A trust meter for the two ratios below: big = a "
                    "liquid, well-watched options market whose ratios "
                    "mean something; tiny = the ratios are noise — "
                    "ignore the group."
                ),
            ),
            "put_call_oi_ratio": make_metric(
                "puts to calls (held)",
                "All outstanding put contracts (bets on a fall / "
                "insurance) divided by all outstanding call contracts "
                "(bets on a rise) — the positions people currently "
                "hold, accumulated over past weeks, not just today's "
                "trades. Summed over the nearest expirations.",
                _round(options.get("put_call_oi_ratio")),
                interpretation=(
                    "~0.7–1.0 is typical. Well above 1 = heavy downside "
                    "bets or hedging; very low = one-sided bullishness "
                    "— complacency, bad news hits hardest then."
                ),
            ),
            "put_call_volume_ratio": make_metric(
                "puts to calls (traded today)",
                "The same ratio using only contracts traded today — "
                "today's fresh flow, not the standing positions.",
                _round(options.get("put_call_volume_ratio")),
                interpretation=(
                    "When today's flow diverges from the held ratio "
                    "above, sentiment is turning right now — the held "
                    "ratio is the climate, this is the weather."
                ),
            ),
            "implied_vol_pct": make_metric(
                "implied stock volatility",
                "The size of yearly move the options market is pricing "
                "in, in %, read from option prices near the current "
                "stock price (at-the-money) — CBOE's 30-day figure. "
                "Options far from the current price are not counted: "
                "their prices carry distortions.",
                _round(options.get("implied_vol_pct")),
                interpretation=(
                    "The market's fear gauge for this one stock: high = "
                    "insurance is expensive, turbulence expected — "
                    "wider stops, smaller size. The raw level means "
                    "little alone; every stock has its own normal."
                ),
            ),
            "implied_report_move_pct": make_metric(
                "implied quarterly report day price change magnitude",
                "The size of price jump the options market prices in "
                "for the next quarterly report, in % — from the "
                "at-the-money call + put prices on the first expiration "
                "after the report date. Unsigned: option prices say how "
                "BIG the jump should be, not which way (read it as ±). "
                "Published only when the report is within ~3 weeks — "
                "further out, option prices mostly reflect ordinary "
                "drift, not the report jump.",
                _round(report_move["move_pct"]) if report_move else None,
                interpretation=(
                    "Compare it to the stop distance: an implied ±9% "
                    "move against a 5% stop means the gap jumps the "
                    "stop — exit before the report or size so the full "
                    "move is survivable."
                ),
            ),
        }
