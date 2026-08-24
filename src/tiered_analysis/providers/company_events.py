# -*- coding: utf-8 -*-
"""Company-news provider — the qualitative fifth report (2026-08-13).

The four existing dimensions are numbers; this one is words: recent
news coverage of the stock, last ``NEWS_WINDOW_BDAYS`` business days
(the calendar span varies with the weekday the run lands on; the
payload publishes the actual bounds). Each
bullet is a one-sentence LLM summary of the article (owner decision
2026-08-16: feed abstracts are often transcript dumps or boilerplate);
the feed's own abstract, then the headline, are the fail-soft
fallbacks when no summary could be written.

Two interchangeable feeds (2026-08-14, source-quality trial):
``FINNHUB_API_KEY`` set → Finnhub's company-news endpoint (per-symbol
with a real date range — Yahoo cannot do that); key absent → Yahoo
Finance via yfinance (works unconfigured, per the config house rule).
Both normalize to the same five-field entry shape, so everything
downstream is source-blind.

The card originally carried a second "company statements" group (SEC
filings); the owner deleted it 2026-08-13 — its only unique signal
(red-flag 8-K events) is moving into the fundamentals report as
explicit fields instead, where the deep debate can grade it.

Every bullet carries a 1-based ``citation`` index into the result's
citations list, and every citation URL is the product of a real fetch
(base.py contract) — an item whose source has no clickable URL is
dropped with a warning, never listed unverifiable.

Payload shape (consumed by the alt page's events renderer and dumped
verbatim into LLM evidence)::

    {
      "news_coverage": {
        "oldest": "2026-08-07", "newest": "2026-08-17",
        "filtered_out": 150, "mention_only": 18,
        "below_bar": 40, "score_bar": 4,
        "items": [
          {"text": "<one-sentence summary>", "date": "2026-08-12",
           "publisher": "SeekingAlpha", "citation": 1, "importance": 5,
           "articles_covering_event": 16},
        ]},
    }

``date``/``publisher`` are separate fields (owner format 2026-08-16)
so the card renders a "2026/08/12 | SeekingAlpha" header line above
each summary; items are ordered newest first. Runs stored before the
split carry the old single-line text and no date field — the frontend
renders those the old way (additive contract, old runs still display).

Selection ladder (2026-08-15): only articles that NAME the company
survive the keyword filter (``filtered_out`` counts the cut), then the
LLM screen (news_screen.py) cuts mention-only articles, groups
same-story rewrites into events, and every event whose importance
reaches ``score_bar`` gets ONE bullet — its most important article.
No fixed top-N; when more than 20 events pass the bar, a small LLM
ranking call keeps the top 20 (news_screen.MAX_EVENTS), loudly.

An empty items list means the feed was fetched and nothing fell inside
the window — checked-and-none, distinct from a failed fetch (an empty
timeline whose warning says the fetch failed).

TEXTUAL kind: never actionable, never feeds numeric consumers.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..news_screen import NewsJudgmentCache, screen_news
from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)

#: Lookback window in BUSINESS days (Mon-Fri); the payload publishes
#: the actual calendar bounds it resolves to, so the UI and the LLM
#: read the same horizon the data was cut to. Note: Yahoo's feed
#: returns only the newest articles (see NEWS_FETCH_COUNT), so for
#: heavily-covered stocks the window is an upper bound, not a
#: guarantee. Finnhub walks the window day-by-day and covers it fully.
#: History: 14 -> 7 calendar (2026-08-16) -> 10 calendar (2026-08-17,
#: to ride out the weekend cliff: weekend coverage is 5-15% of weekday
#: volume and almost never scores >= 4) -> 7 business days (owner
#: decision 2026-08-17): a weekday quota gives every run the same
#: news-producing depth — 10 calendar days gave Monday runs 6 weekdays
#: but Friday runs 8; 7 business days is 7 no matter the run day (9-11
#: calendar days, weekends ride along inside the span).
NEWS_WINDOW_BDAYS = 7

#: How many articles to request from Yahoo's feed (its default is 10).
#: 25 -> 150 (owner decision 2026-08-17): the keyless backup should
#: reach roughly as deep as the window; Yahoo honors counts up to ~200
#: (measured 2026-08-17: 300 requested -> 198 returned).
NEWS_FETCH_COUNT = 150


def business_days_back(today: date, count: int) -> date:
    """The start date whose inclusive range up to ``today`` contains
    ``count`` weekdays (Mon-Fri): walk backwards counting weekdays
    until the quota is met. No holiday calendar — a market holiday
    costs one quiet day, which the quota already tolerates."""
    day = today
    seen = 1 if day.weekday() < 5 else 0
    while seen < count:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            seen += 1
    return day

#: An event needs this materiality (the LLM screen's 0-5 importance
#: grade) to make the card. Measured 2026-08-15 on GOOGL/AAPL/NVDA:
#: >=3 admits 50-77 events a fortnight for a mega cap (unreadable),
#: >=4 admits 21-28 — news_screen's ranking call keeps the top 20
#: (MAX_EVENTS) when a mega cap's fortnight overflows the ceiling.
CARD_SCORE_BAR = 4


def _empty_news_coverage(since: date, today: date) -> Dict[str, Any]:
    """The card's payload shape with zero events — what a failed news
    fetch ships, so the card still renders (empty timeline + the
    warning) instead of vanishing."""
    return {
        "news_coverage": {
            "oldest": since.isoformat(),
            "newest": today.isoformat(),
            "filtered_out": 0,
            "mention_only": 0,
            "below_bar": 0,
            "score_bar": CARD_SCORE_BAR,
            "items": [],
        }
    }


def normalize_news_entry(entry: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """One yfinance news entry -> {title, publisher, url, date, summary}.

    yfinance changed its news shape (~0.2.5x): new entries nest under
    ``content`` with provider/canonicalUrl objects; old entries are flat
    with an epoch timestamp. Both normalize to the same five fields;
    anything missing stays None (the caller decides what is fatal).
    ``summary`` is Yahoo's own abstract of the article — the bullet text
    when present (the headline is only the fallback).
    """
    content = entry.get("content")
    if isinstance(content, Mapping):
        provider = content.get("provider")
        url_obj = content.get("canonicalUrl")
        pub_date = str(content.get("pubDate") or "")[:10]
        return {
            "title": content.get("title") or None,
            "publisher": (
                provider.get("displayName") if isinstance(provider, Mapping) else None
            ),
            "url": url_obj.get("url") if isinstance(url_obj, Mapping) else None,
            "date": pub_date or None,
            "summary": content.get("summary") or content.get("description") or None,
        }
    timestamp = entry.get("providerPublishTime")
    pub_date = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
        else None
    )
    return {
        "title": entry.get("title") or None,
        "publisher": entry.get("publisher") or None,
        "url": entry.get("link") or None,
        "date": pub_date,
        "summary": entry.get("summary") or None,
    }


def _yahoo_news_loader(symbol: str) -> List[Dict[str, Optional[str]]]:
    """Recent Yahoo Finance news, normalized to {title, publisher, url,
    date, summary}. Requests more than Yahoo's 10-article default so a
    heavily-covered stock still shows more than a day or two."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    try:
        raw = ticker.get_news(count=NEWS_FETCH_COUNT)
    except TypeError:  # older yfinance without the count parameter
        raw = ticker.news
    raw = raw or []
    return [normalize_news_entry(entry) for entry in raw if isinstance(entry, Mapping)]


FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
_FINNHUB_TIMEOUT_SECONDS = 15


def normalize_finnhub_entry(entry: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """One Finnhub company-news entry -> the same five-field shape.

    Finnhub fields: headline, source, url, datetime (epoch seconds),
    summary. Anything missing stays None (the caller decides what is
    fatal).
    """
    import html

    timestamp = entry.get("datetime")
    pub_date = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
        else None
    )

    def _text(key: str) -> Optional[str]:
        # Finnhub ships raw HTML entities ("hasn&#39;t") — unescape so
        # bullets read as prose.
        value = entry.get(key)
        return html.unescape(str(value)) if value else None

    return {
        "title": _text("headline"),
        "publisher": entry.get("source") or None,
        "url": entry.get("url") or None,
        "date": pub_date,
        "summary": _text("summary"),
    }


def _finnhub_news_loader(
    symbol: str, api_key: str, since: Optional[date] = None
) -> List[Dict[str, Optional[str]]]:
    """Company news from Finnhub, fetched one day per request.

    A single ranged request silently caps at ~250 articles — about 3 days
    of a hot ticker (measured 2026-08-15 on NVDA) — so the window is
    walked day-by-day from ``since`` (default: the business-day window's
    start): each day gets the full per-request budget, and the request
    count (~10-12) stays far under Finnhub's 60/min free-tier rate limit.
    """
    import requests

    today = date.today()
    if since is None:
        since = business_days_back(today, NEWS_WINDOW_BDAYS)
    entries: List[Dict[str, Optional[str]]] = []
    for offset in range((today - since).days, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        response = requests.get(
            FINNHUB_NEWS_URL,
            params={"symbol": symbol, "from": day, "to": day, "token": api_key},
            timeout=_FINNHUB_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, list):
            raise ValueError(f"unexpected Finnhub company-news response: {type(raw)}")
        entries.extend(
            normalize_finnhub_entry(entry)
            for entry in raw
            if isinstance(entry, Mapping)
        )
    return entries


def _default_news_loader(symbol: str) -> List[Dict[str, Optional[str]]]:
    """Finnhub when a key is configured (source-quality trial 2026-08-14),
    Yahoo otherwise — unconfigured keeps working, configured enhances."""
    api_key = os.getenv("FINNHUB_API_KEY") or None
    if api_key:
        return _finnhub_news_loader(symbol, api_key)
    return _yahoo_news_loader(symbol)


def _default_today() -> date:
    return date.today()


def _parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def flatten_summary(text: str) -> str:
    """The abstract with its whitespace flattened to single spaces —
    shown in FULL (owner decision 2026-08-13: no truncation)."""
    return " ".join(str(text).split())


# ---------------------------------------------------------------------------
# Relevance filter (2026-08-14). Measured on live feeds: ~50% (Yahoo) to
# ~61% (Finnhub) of a mega-cap's tagged articles never mention the company
# at all — other companies' stories, market wraps, fund letters. An article
# is kept only if the company is named (ticker, company name, or a known
# brand alias) in its headline or abstract, on word boundaries so "meta"
# never matches "metal". Audited 2026-08-13/14 on GOOGL+AAPL: cut every
# wrong-company article, lost no clearly material one.
# ---------------------------------------------------------------------------

#: Famous brands whose products/subsidiaries appear in headlines without
#: the registered company name ("Gemini hits 1B users" is an Alphabet
#: story). Symbols not listed fall back to ticker + company name, which
#: the name lookup provides.
BRAND_ALIASES: Dict[str, List[str]] = {
    "GOOGL": ["alphabet", "google", "gemini", "youtube", "deepmind", "waymo"],
    "GOOG": ["alphabet", "google", "gemini", "youtube", "deepmind", "waymo"],
    "AAPL": ["apple", "iphone", "ipad", "macbook", "app store", "siri"],
    "MSFT": ["microsoft", "azure", "windows", "copilot", "xbox"],
    "NVDA": ["nvidia", "geforce", "cuda"],
    "AMZN": ["amazon", "aws", "alexa", "prime video"],
    "META": ["meta", "meta platforms", "facebook", "instagram", "whatsapp"],
    "TSLA": ["tesla", "cybertruck", "robotaxi"],
}

#: Legal-suffix words dropped when turning a registered name ("Alphabet
#: Inc. Class A") into match terms.
_NAME_SUFFIX_WORDS = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "ltd",
    "limited", "plc", "holdings", "group", "class", "a", "b", "c", "the",
}


def name_to_terms(raw_name: str) -> List[str]:
    """Match terms from a registered company name: the cleaned full name,
    plus its first word when the name has several ("berkshire hathaway"
    and "berkshire")."""
    words = [
        word for word in re.sub(r"[^\w\s]", " ", str(raw_name)).lower().split()
        if word not in _NAME_SUFFIX_WORDS
    ]
    if not words:
        return []
    terms = [" ".join(words)]
    if len(words) > 1 and len(words[0]) >= 3:
        terms.append(words[0])
    return terms


def _default_name_terms(symbol: str) -> List[str]:
    """Company-name terms via the same yfinance info the fundamentals
    provider already fetches per run. Failure returns [] — the filter
    then runs on ticker + aliases alone (fail-soft, never fail-closed)."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).get_info() or {}
        raw = info.get("shortName") or info.get("longName") or ""
        return name_to_terms(raw)
    except Exception:
        return []


def relevance_terms(symbol: str, name_terms: Sequence[str]) -> List[str]:
    """The full term set: ticker, registered-name terms, brand aliases."""
    terms = [symbol.lower()]
    terms += [term.lower() for term in name_terms]
    terms += BRAND_ALIASES.get(symbol.upper(), [])
    seen = set()
    unique = []
    for term in terms:
        if term and term not in seen:
            seen.add(term)
            unique.append(term)
    return unique


def mentions_company(entry: Mapping[str, Any], terms: Sequence[str]) -> bool:
    """Whether the headline or abstract names the company: any term on a
    word boundary (so "meta" matches "Meta beats" but never "metal")."""
    text = f"{entry.get('title') or ''} {entry.get('summary') or ''}".lower()
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in terms
    )


class CompanyEventsProvider(DimensionProvider):
    """US company news: recent Yahoo Finance coverage, cited."""

    dimension = "company_events"
    kind = SourceKind.TEXTUAL

    def __init__(
        self,
        news_loader: Callable[
            [str], Sequence[Mapping[str, Any]]
        ] = _default_news_loader,
        today: Callable[[], date] = _default_today,
        name_terms_loader: Callable[[str], Sequence[str]] = _default_name_terms,
        screener: Optional[
            Callable[[str, Sequence[Mapping[str, Any]], Optional[str]], Dict[str, Any]]
        ] = None,
    ) -> None:
        self._load_news = news_loader
        self._today = today
        self._load_name_terms = name_terms_loader
        self._screen = screener or self._default_screener

    @staticmethod
    def _default_screener(
        symbol: str,
        entries: Sequence[Mapping[str, Any]],
        company: Optional[str],
    ) -> Dict[str, Any]:
        """The production screen: judge (URL-cached on disk) -> group ->
        select at the card's score bar. LLM failures inside degrade to
        keep-with-warning (news_screen contract), never to a crash."""
        return screen_news(
            symbol,
            entries,
            company=company,
            threshold=CARD_SCORE_BAR,
            cache=NewsJudgmentCache(symbol),
        )

    def supports(self, market: Market) -> bool:
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        today = self._today()
        warnings: List[str] = []
        try:
            entries = list(self._load_news(symbol))
        except Exception as exc:
            # A failed fetch still ships the card's shape — an empty
            # timeline with the warning saying why (degradation lives on
            # the card notes, never on a card-level grade, 2026-08-19).
            since = business_days_back(today, NEWS_WINDOW_BDAYS)
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                payload=_empty_news_coverage(since, today),
                warnings=[f"news headlines unavailable: {exc}"],
            )

        since = business_days_back(today, NEWS_WINDOW_BDAYS)
        dropped = 0
        seen_urls = set()
        dated: List[Dict[str, Optional[str]]] = []
        for entry in entries:
            title, url = entry.get("title"), entry.get("url")
            published = _parse_date(entry.get("date")) if entry.get("date") else None
            if not title or not url or published is None:
                # An unverifiable bullet (no link) or an undatable one (no
                # window position) must not masquerade as evidence.
                dropped += 1
                continue
            if published < since or url in seen_urls:
                # Same URL = same story syndicated twice; one bullet is
                # enough — and unique URLs keep the frontend's
                # dedupe-then-number source list aligned with the
                # bullets' citation indices.
                continue
            seen_urls.add(url)
            dated.append({**entry, "date": published.isoformat()})
        if dropped:
            warnings.append(
                f"{dropped} news item(s) skipped (missing headline, link, or date)"
            )

        # Relevance filter: keep only articles that name the company.
        # A failed name lookup degrades to ticker+aliases (fail-soft) —
        # it must never turn into an empty term set that cuts everything.
        name_terms = list(self._load_name_terms(symbol))
        terms = relevance_terms(symbol, name_terms)
        relevant = [entry for entry in dated if mentions_company(entry, terms)]
        filtered_out = len(dated) - len(relevant)
        if dated and not relevant:
            warnings.append(
                f"{len(dated)} news item(s) fetched but none mention the company"
                " — check the relevance terms"
            )

        # Identical body text = the same syndicated story under another
        # URL (fund-letter boilerplate ships this way); one bullet is
        # enough.
        seen_text = set()
        unique: List[Dict[str, Optional[str]]] = []
        for entry in relevant:
            body = flatten_summary(entry.get("summary") or entry["title"]).lower()
            if body in seen_text:
                continue
            seen_text.add(body)
            unique.append(entry)

        # Newest first: deterministic screen prompts, and the fail-soft
        # degradation (LLM down -> everything kept, materiality unknown)
        # then shows the newest events, loudly warned.
        unique.sort(key=lambda entry: entry["date"] or "", reverse=True)

        # LLM screen (news_screen.py): judge each article (about the
        # company? importance 0-5; cached by URL so daily runs re-judge
        # only unseen articles), group same-story rewrites into events,
        # keep every event at or above the card's score bar — no fixed
        # top-N; the card's length reflects the week.
        company = name_terms[0] if name_terms else None
        screen = self._screen(symbol, unique, company)
        warnings.extend(screen["warnings"])

        # Display order is chronological, newest first (owner format
        # 2026-08-16) — the ranking already did its job picking WHICH
        # events survive; the card reads as a timeline.
        shown = sorted(
            screen["selected"],
            key=lambda event: event["entry"].get("date") or "",
            reverse=True,
        )
        citations: List[Citation] = []
        items: List[Dict[str, Any]] = []
        for event in shown:
            entry = event["entry"]
            # The bullet is the screen's one-sentence summary of the
            # source; the feed's own abstract (headline as last resort)
            # only when no summary could be written (fail-soft). One
            # bullet per EVENT: its most important article represents
            # the whole group of rewrites.
            body = event.get("card_text") or flatten_summary(
                entry.get("summary") or entry["title"]
            )
            citations.append(
                Citation(
                    source_name=entry.get("publisher") or "news feed",
                    url=entry["url"],
                    title=entry["title"],
                )
            )
            item: Dict[str, Any] = {
                "text": body,
                "date": entry["date"],
                "publisher": entry.get("publisher"),
                "citation": len(citations),
            }
            # Data-side extras (the LLM evidence reads them; the card
            # renders only text + citation).
            if event.get("materiality") is not None:
                item["importance"] = event["materiality"]
            if event.get("group_size", 1) > 1:
                item["articles_covering_event"] = event["group_size"]
            items.append(item)

        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            payload={
                "news_coverage": {
                    # The fetch window's actual bounds — the card title
                    # shows this span (owner format 2026-08-17, matching
                    # the world card) instead of a "last N days" phrase;
                    # the business-day quota makes the calendar length
                    # vary by run day, so no window_days promise (the
                    # frontend keeps its window_days fallback for old
                    # stored runs only).
                    "oldest": since.isoformat(),
                    "newest": today.isoformat(),
                    # Screen transparency (frontend ignores unknown keys;
                    # the LLM evidence sees them): keyword-filter cut,
                    # LLM cuts, and the importance bar applied.
                    "filtered_out": filtered_out,
                    "mention_only": screen["mention_only"],
                    "below_bar": screen["below_threshold"],
                    "score_bar": CARD_SCORE_BAR,
                    "items": items,
                }
            },
            citations=citations,
            warnings=warnings,
        )
