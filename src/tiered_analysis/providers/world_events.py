# -*- coding: utf-8 -*-
"""World-news provider — the macro/world backdrop card (2026-08-16).

The macro_econ card is numbers (rates, CPI, yields); this card is the
words the numbers can't carry yet: what just changed in the backdrop —
central-bank language, policy moves, geopolitics, data surprises —
before it is fully reflected in the series. It complements, never
replaces, the numeric macro report.

Sources (owner decision 2026-08-17): AlphaVantage's NEWS_SENTIMENT
endpoint when ``ALPHAVANTAGE_API_KEY`` is configured — it takes a real
time range, so one run fetches the full ``WORLD_WINDOW_DAYS``
calendar-day window directly, one request per macro topic in
``WORLD_TOPICS`` (the API ANDs a multi-topic list, so a union needs
separate calls; four calls/day fits the free tier's 25/day because the
screened result is day-cached). Key absent, or AlphaVantage down: the
keyless backup is Yahoo's ^GSPC (S&P 500) news tab via yfinance — no
date control, but its newest ``NEWS_FETCH_COUNT`` articles reach ~3-4
days back, comfortably covering the short window. Every fetch merges
into the rolling on-disk article pool (``world_articles_*.json``,
merge-by-URL, pruned past ``ARTICLE_RETENTION_DAYS``) whose depth
serves the fetch-failure fallback. The screen judges EVERYTHING in the
window — no sampling; ``MAX_SCREEN_ARTICLES`` is a pure fuse that,
when tripped, spreads across the window's days so no single flood-day
swallows the budget (warned). The payload publishes the ACTUAL date
span screened
(``oldest``/``newest``); ``window_days`` stays absent on purpose. A
failed fetch falls back to the pool (warned, never day-cached) — only
an empty pool reads UNAVAILABLE. History: the first build (2026-08-16)
used Finnhub's general feed, dropped because it has no date range at
all (newest ~100 only, verified live 2026-08-17 — ``minId`` merely
filters that same set).

The screen is the company-news pipeline with the world lens
(``news_screen.WORLD_PROMPTS``): judge each article (about the macro
backdrop? importance 0-5 for the OVERALL market; URL-cached), group
same-story rewrites, keep events at or above the card bar, rank-trim
past the ceiling, summarize winners. The company card's keyword
WHITELIST ("names the company") has no world equivalent — but the
feed's junk is concentrated enough for a deterministic BLACKLIST:
``is_world_spam`` drops the auto-generated fund-holdings genre
(publisher + title templates) before any tokens are spent, and a
blacklist can only ever drop recognizable spam, never a real macro
story with unusual wording. ``filtered_out`` counts that free cut;
``off_topic`` counts what the LLM judge then dropped.

The backdrop is the same for every ticker, so the screened result is
cached ONCE PER DAY (macro_econ convention) and every symbol in a run
reuses it — the symbol argument is intentionally ignored, and cost
stays flat no matter how many stocks a run covers. Citations ride in
the day cache so a cache hit rebuilds them verbatim.

Payload shape — same ``news_coverage`` contract as company news (the
debate's news-row enumeration and the alt page's events renderer are
keyed on kind/payload, not the dimension name)::

    {
      "news_coverage": {
        "oldest": "2026-08-14", "newest": "2026-08-16",
        "filtered_out": 640, "off_topic": 61, "below_bar": 20,
        "score_bar": 4,
        "items": [
          {"text": "<one-sentence summary>", "date": "2026-08-16",
           "publisher": "Reuters", "citation": 1, "importance": 5,
           "articles_covering_event": 7},
        ]},
    }

TEXTUAL kind: never actionable, never feeds numeric consumers.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..news_screen import WORLD_PROMPTS, NewsJudgmentCache, screen_news
from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)
from .company_events import (
    CARD_SCORE_BAR,
    NEWS_FETCH_COUNT,
    _parse_date,
    flatten_summary,
    normalize_news_entry,
)
from .macro_econ import DEFAULT_CACHE_DIR

ALPHAVANTAGE_NEWS_URL = "https://www.alphavantage.co/query"
_ALPHAVANTAGE_TIMEOUT_SECONDS = 30

#: The macro lenses fetched from AlphaVantage, one request each — the
#: API ANDs a comma-joined topics list ("simultaneously cover", per
#: the docs), so a union of topics means separate calls.
WORLD_TOPICS = (
    "economy_macro",
    "economy_monetary",
    "economy_fiscal",
    "financial_markets",
)

#: Lookback in CALENDAR days, today inclusive (owner decision
#: 2026-08-17: "2 days, business or weekend"). World news prices in
#: within hours-to-days, and unlike company news the world's weekend
#: volume is healthy (measured 2026-08-17: Sat ~half a weekday, Sun
#: near-full), so plain calendar days carry no Monday cliff. History:
#: launched at 7 business days; cut after the volume tests showed the
#: extra days' events mostly die at the top-20 rank anyway.
WORLD_WINDOW_DAYS = 2

#: The index whose Yahoo news tab serves as the keyless backup feed —
#: S&P 500 coverage is the closest thing Yahoo has to a general
#: market-news stream.
YAHOO_WORLD_SYMBOL = "^GSPC"

#: PURE safety fuse: judging everything in the window is the design —
#: no sampling (measured 2026-08-17: the 2-day window runs ~1.3-1.9k
#: articles, ~340k tokens ≈ 10 cents cold on the screening model, ~3
#: cents/day warm via the URL cache). Set well above the observed
#: ceiling so it only trips if a feed goes haywire; when it does, the
#: cap spreads across the window's days (newest first within each day,
#: trims warned) so no single flood-day swallows the budget.
MAX_SCREEN_ARTICLES = 3000

#: Pooled articles older than this are pruned on load — far past the
#: 2-day window; the extra depth exists only so a failed fetch can
#: still fill the window from disk, whatever day it happens on.
ARTICLE_RETENTION_DAYS = 14

#: The judgment cache's file key — one shared world file, not
#: per-symbol (the feed is symbol-independent).
WORLD_CACHE_KEY = "WORLD"

#: The label the screen prompts use where company news uses the ticker.
_SCREEN_LABEL = "the overall market"

#: Deterministic spam blacklist (owner request 2026-08-19, token cost).
#: The world feed's junk is dominated by one auto-generated genre:
#: "Fund X bought N shares of Company Y" holdings notices. Measured
#: over every article the judge had verdicted to date (3,828):
#: MarketBeat alone accounted for 1,856 of the 3,442 off-topic
#: verdicts against 3 on-topic ever — and all 3 were themselves
#: single-fund holdings pieces, i.e. judge slips, not macro stories.
SPAM_PUBLISHERS = frozenset({"marketbeat"})

#: Title templates of the same holdings-notice genre from other
#: outlets (measured 2026-08-19 on the judgment cache: 838 off-topic
#: matches vs 1 on-topic — itself a MarketBeat holdings piece).
#: Together with the publisher list this cut 54% of all off-topic
#: articles. Deliberately narrow: each phrase is the fixed wording of
#: an auto-generated headline, not a topic keyword.
SPAM_TITLE_RE = re.compile(
    r"(?i)\b("
    r"shares? (?:sold|purchased|bought|acquired) by"
    r"|(?:boosts?|raises?|lowers?|trims?|cuts?|increases?|decreases?"
    r"|reduces?) (?:its )?(?:stock )?(?:position|holdings|stake) in"
    r"|(?:takes?|has|buys?) (?:a )?(?:new )?"
    r"(?:\$[\d.,]+ (?:million|billion) )?"
    r"(?:stock )?(?:position|stake|holdings) in"
    r"|invests? \$[\d.,]+ (?:million|billion) in"
    r"|(?:sells?|acquires?|purchases?|buys?) [\d,]+ shares"
    r"|short interest (?:update|down|up)"
    r"|stock (?:position|holdings) (?:raised|lowered|boosted|trimmed"
    r"|increased|decreased)"
    r")\b"
)


def is_world_spam(entry: Mapping[str, Any]) -> bool:
    """True when the article is recognizable auto-generated single-stock
    spam that should never reach (or pay for) the LLM judge."""
    publisher = str(entry.get("publisher") or "").strip().lower()
    if publisher in SPAM_PUBLISHERS:
        return True
    return bool(SPAM_TITLE_RE.search(str(entry.get("title") or "")))


def normalize_alphavantage_entry(
    entry: Mapping[str, Any]
) -> Dict[str, Optional[str]]:
    """One AlphaVantage NEWS_SENTIMENT feed item -> the shared
    five-field entry shape. Fields (verified live 2026-08-17): title,
    url, source, summary, and ``time_published`` as "20260817T085901" —
    only its date part matters here. Anything missing stays None (the
    caller decides what is fatal)."""
    stamp = str(entry.get("time_published") or "")
    pub_date = (
        f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
        if len(stamp) >= 8 and stamp[:8].isdigit()
        else None
    )
    return {
        "title": entry.get("title") or None,
        "publisher": entry.get("source") or None,
        "url": entry.get("url") or None,
        "date": pub_date,
        "summary": entry.get("summary") or None,
    }


def _alphavantage_world_news_loader() -> List[Dict[str, Optional[str]]]:
    """Macro/market news from AlphaVantage's NEWS_SENTIMENT endpoint —
    the primary feed. It takes a real time range (``time_from``,
    YYYYMMDDTHHMM), so one run covers the full window directly: one
    request per WORLD_TOPICS lens, merged and deduped by URL. The
    2-day window sits well inside the endpoint's complete zone (its
    per-topic newest-1000 cap only truncates ~4+ days back)."""
    import requests

    api_key = os.getenv("ALPHAVANTAGE_API_KEY") or None
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not set")
    since = date.today() - timedelta(days=WORLD_WINDOW_DAYS - 1)
    merged: Dict[str, Dict[str, Optional[str]]] = {}
    for index, topic in enumerate(WORLD_TOPICS):
        if index:
            # The free tier throttles at 1 request/second (observed
            # live 2026-08-17: back-to-back topic requests tripped it);
            # pace the walk so the primary feed never trips itself.
            time.sleep(1.2)
        response = requests.get(
            ALPHAVANTAGE_NEWS_URL,
            params={
                "function": "NEWS_SENTIMENT",
                "topics": topic,
                "time_from": f"{since.strftime('%Y%m%d')}T0000",
                "sort": "LATEST",
                "limit": "1000",
                "apikey": api_key,
            },
            timeout=_ALPHAVANTAGE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw = response.json()
        feed = raw.get("feed") if isinstance(raw, Mapping) else None
        if not isinstance(feed, list):
            # Rate-limit and error responses come back HTTP 200 with an
            # explanatory note instead of a feed — a failure (the backup
            # feed takes over), never an empty news day.
            note = ""
            if isinstance(raw, Mapping):
                note = str(
                    raw.get("Information")
                    or raw.get("Note")
                    or raw.get("Error Message")
                    or ""
                )[:200]
            raise ValueError(
                f"AlphaVantage returned no feed for topic {topic}:"
                f" {note or 'unexpected response shape'}"
            )
        for item in feed:
            if not isinstance(item, Mapping):
                continue
            entry = normalize_alphavantage_entry(item)
            if entry["url"]:
                merged.setdefault(entry["url"], entry)
    return list(merged.values())


def _yahoo_world_news_loader() -> List[Dict[str, Optional[str]]]:
    """Market news from Yahoo's ^GSPC news tab via yfinance — the
    keyless backup. No date control: just the newest NEWS_FETCH_COUNT
    articles, which reach ~3-4 days back — enough for the 2-day
    window; the rolling pool adds failure-fallback depth."""
    import yfinance as yf

    ticker = yf.Ticker(YAHOO_WORLD_SYMBOL)
    try:
        raw = ticker.get_news(count=NEWS_FETCH_COUNT)
    except TypeError:  # older yfinance without the count parameter
        raw = ticker.news
    raw = raw or []
    return [
        normalize_news_entry(entry) for entry in raw if isinstance(entry, Mapping)
    ]


def _default_world_news_loader() -> Tuple[
    List[Dict[str, Optional[str]]], List[str]
]:
    """AlphaVantage when a key is configured, Yahoo otherwise —
    unconfigured keeps working, configured enhances (config house
    rule). Returns (entries, warnings): an AlphaVantage failure falls
    back to Yahoo WITH a warning, which also keeps the degraded result
    out of the day cache so the next run retries the primary feed."""
    if os.getenv("ALPHAVANTAGE_API_KEY"):
        try:
            return _alphavantage_world_news_loader(), []
        except Exception as exc:
            try:
                return (
                    _yahoo_world_news_loader(),
                    [
                        "world news: AlphaVantage failed"
                        f" ({exc}); used the Yahoo backup feed"
                    ],
                )
            except Exception as backup_exc:
                raise RuntimeError(
                    f"AlphaVantage failed ({exc}) and the Yahoo backup"
                    f" failed ({backup_exc})"
                ) from backup_exc
    return _yahoo_world_news_loader(), []


class WorldEventsProvider(DimensionProvider):
    """World/macro news: AlphaVantage (Yahoo backup), screened, cited."""

    dimension = "world_events"
    kind = SourceKind.TEXTUAL
    #: Day-cache format marker — bump when the payload shape or the
    #: collection behavior changes so a same-day cache written by older
    #: code is refetched, not misread (v2: the rolling article pool;
    #: v3: AlphaVantage/Yahoo sources + the business-day window;
    #: v4: the 2-calendar-day window, sampling off; v5: the
    #: deterministic spam prefilter + its filtered_out counter).
    cache_version = "v5"

    def __init__(
        self,
        news_loader: Callable[
            [], Any
        ] = _default_world_news_loader,
        today: Callable[[], date] = date.today,
        screener: Optional[
            Callable[[Sequence[Mapping[str, Any]]], Dict[str, Any]]
        ] = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ) -> None:
        self._load_news = news_loader
        self._today = today
        self._screen = screener or self._default_screener
        self._cache_dir = Path(cache_dir)

    @staticmethod
    def _default_screener(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        """The production screen with the world prompt set. Judgments and
        summaries cache by URL in one shared world file."""
        return screen_news(
            _SCREEN_LABEL,
            entries,
            threshold=CARD_SCORE_BAR,
            cache=NewsJudgmentCache(WORLD_CACHE_KEY),
            prompts=WORLD_PROMPTS,
        )

    # The backdrop is global context: every market gets the same card
    # (macro_econ convention — the judge scores world relevance, and a
    # US-centric feed is still the backdrop that moves global risk).
    def supports(self, market: Market) -> bool:
        return True

    # The symbol is intentionally ignored: world news is per-day, not
    # per-stock — the day cache makes a multi-ticker run screen once.
    def collect(self, symbol: str) -> DimensionResult:
        cached = self._read_cache()
        if cached is not None:
            return cached

        warnings: List[str] = []
        fetched: List[Dict[str, Optional[str]]] = []
        fetch_ok = True
        degraded_fetch = False
        try:
            loaded = self._load_news()
        except Exception as exc:
            # The rolling pool is the fallback: a transient feed failure
            # degrades to yesterday's articles (warned), never to a
            # blank card while news exists on disk.
            fetch_ok = False
            entries: List[Any] = []
            warnings.append(f"world news fetch failed: {exc}")
        else:
            # The default loader reports source degradation (primary
            # feed down, backup used) as (entries, warnings); injected
            # plain-sequence loaders keep working unchanged.
            if isinstance(loaded, tuple):
                entries = list(loaded[0])
                loader_warnings = list(loaded[1])
            else:
                entries, loader_warnings = list(loaded), []
            if loader_warnings:
                degraded_fetch = True
                warnings.extend(loader_warnings)

        # Same evidence hygiene as company news: an unverifiable item
        # (no link) or an undatable one must not masquerade as evidence;
        # one URL = one story.
        dropped = 0
        seen_urls = set()
        for entry in entries:
            title, url = entry.get("title"), entry.get("url")
            published = _parse_date(entry.get("date")) if entry.get("date") else None
            if not title or not url or published is None:
                dropped += 1
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            fetched.append({**entry, "date": published.isoformat()})
        if dropped:
            warnings.append(
                f"{dropped} world news item(s) skipped (missing headline, link,"
                " or date)"
            )

        # The rolling pool: the Yahoo backup only ever serves its
        # newest articles, so successive fetches accumulate on disk
        # until the pool covers the window; the AlphaVantage primary
        # covers the window in one fetch and the pool then just adds
        # resilience. Merge by URL (a refetch refreshes its entry),
        # prune past retention, persist.
        pool = self._load_pool()
        for entry in fetched:
            pool[entry["url"]] = entry
        oldest_kept = self._today() - timedelta(days=ARTICLE_RETENTION_DAYS)
        pool = {
            url: entry
            for url, entry in pool.items()
            if str(entry.get("date") or "") >= oldest_kept.isoformat()
        }
        if fetch_ok:
            self._save_pool(pool)
        elif not pool:
            # A failed fetch with an empty pool still ships the card's
            # shape — an empty timeline with the warning saying why
            # (degradation lives on the card notes, never on a
            # card-level grade, 2026-08-19).
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                payload={
                    "news_coverage": {
                        "oldest": None,
                        "newest": None,
                        "filtered_out": 0,
                        "off_topic": 0,
                        "below_bar": 0,
                        "score_bar": CARD_SCORE_BAR,
                        "items": [],
                    }
                },
                warnings=warnings + ["world news unavailable: no pooled articles"],
            )
        else:
            warnings.append(
                f"showing {len(pool)} previously fetched article(s) instead"
            )

        # The calendar-day window is the cut the card promises; the
        # pool's extra retention days exist only so a failed fetch can
        # still fill the whole window from disk.
        since = self._today() - timedelta(days=WORLD_WINDOW_DAYS - 1)
        in_window = [
            entry
            for entry in sorted(
                pool.values(), key=lambda entry: entry["date"] or "", reverse=True
            )
            if str(entry.get("date") or "") >= since.isoformat()
        ]

        # Identical body text = the same syndicated story under another
        # URL; one bullet is enough.
        seen_text = set()
        deduped: List[Dict[str, Optional[str]]] = []
        for entry in in_window:
            body = flatten_summary(entry.get("summary") or entry["title"]).lower()
            if body in seen_text:
                continue
            seen_text.add(body)
            deduped.append(entry)

        # The free deterministic cut, before any tokens are spent:
        # recognizable holdings-notice spam never reaches the judge.
        # Counted in the payload (filtered_out), never silent.
        kept = [entry for entry in deduped if not is_world_spam(entry)]
        spam_cut = len(deduped) - len(kept)

        # The screen cap, spread across the window's days: round-robin
        # one article per day (newest first within each day) until the
        # cap fills, so every day stays represented — a plain
        # newest-first cut hands the whole budget to today and
        # collapses the card's span to one day (observed live
        # 2026-08-17 on the first AlphaVantage run). Trims are warned —
        # a silent cap would read as "covered the window" when it
        # didn't.
        if len(kept) <= MAX_SCREEN_ARTICLES:
            unique = kept
        else:
            by_day: Dict[str, List[Dict[str, Optional[str]]]] = {}
            for entry in kept:  # already newest-first within a day
                by_day.setdefault(str(entry["date"]), []).append(entry)
            days = sorted(by_day, reverse=True)
            unique = []
            while len(unique) < MAX_SCREEN_ARTICLES:
                took_any = False
                for day in days:
                    if not by_day[day]:
                        continue
                    unique.append(by_day[day].pop(0))
                    took_any = True
                    if len(unique) >= MAX_SCREEN_ARTICLES:
                        break
                if not took_any:
                    break
            unique.sort(key=lambda entry: entry["date"] or "", reverse=True)
            warnings.append(
                f"busy world window: screening {len(unique)} of"
                f" {len(kept)} article(s), spread evenly across the"
                " window's days"
            )

        # The actual horizon screened — published instead of a window
        # promise (the Yahoo backup cannot guarantee the full window).
        newest = unique[0]["date"] if unique else None
        oldest = unique[-1]["date"] if unique else None

        screen = self._screen(unique)
        warnings.extend(screen["warnings"])

        shown = sorted(
            screen["selected"],
            key=lambda event: event["entry"].get("date") or "",
            reverse=True,
        )
        citations: List[Citation] = []
        items: List[Dict[str, Any]] = []
        for event in shown:
            entry = event["entry"]
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
            if event.get("materiality") is not None:
                item["importance"] = event["materiality"]
            if event.get("group_size", 1) > 1:
                item["articles_covering_event"] = event["group_size"]
            items.append(item)

        result = DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            payload={
                "news_coverage": {
                    "oldest": oldest,
                    "newest": newest,
                    # Screen transparency: the deterministic spam cut
                    # (free, pre-judge), the judge's off-topic cut
                    # (select_events' mention_only under the world lens)
                    # and the importance bar applied.
                    "filtered_out": spam_cut,
                    "off_topic": screen["mention_only"],
                    "below_bar": screen["below_threshold"],
                    "score_bar": CARD_SCORE_BAR,
                    "items": items,
                }
            },
            citations=citations,
            warnings=warnings,
        )
        # A degraded result (pool fallback, or the backup feed standing
        # in for a failed primary) is never day-cached: the next run the
        # same day should retry the real feed, not inherit the
        # degradation.
        if fetch_ok and not degraded_fetch:
            self._write_cache(result)
        return result

    # ---- rolling article pool (the feed has no lookback) ----

    #: Pool format marker — bump when the entry shape changes.
    pool_version = "v1"

    def _pool_path(self) -> Path:
        return self._cache_dir / f"world_articles_{self.pool_version}.json"

    def _load_pool(self) -> Dict[str, Dict[str, Optional[str]]]:
        try:
            raw = json.loads(self._pool_path().read_text(encoding="utf-8"))
            articles = raw.get("articles") if isinstance(raw, Mapping) else None
            if not isinstance(articles, Mapping):
                return {}
            return {
                str(url): dict(entry)
                for url, entry in articles.items()
                if isinstance(entry, Mapping) and entry.get("title")
            }
        except FileNotFoundError:
            return {}
        except Exception:
            return {}  # corrupt pool: rebuild from fetches, never fail

    def _save_pool(self, pool: Dict[str, Dict[str, Optional[str]]]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._pool_path().write_text(
                json.dumps({"articles": pool}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # a thinner pool tomorrow is acceptable; failing the run is not

    # ---- per-day cache (macro_econ convention) ----

    def _cache_path(self) -> Path:
        return self._cache_dir / (
            f"world_events_{self.cache_version}_{self._today().isoformat()}.json"
        )

    def _read_cache(self) -> Optional[DimensionResult]:
        try:
            raw = json.loads(self._cache_path().read_text(encoding="utf-8"))
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                payload=raw["payload"],
                citations=[
                    Citation(
                        source_name=entry.get("source_name") or "news feed",
                        url=entry.get("url"),
                        title=entry.get("title"),
                    )
                    for entry in raw.get("citations", [])
                    if isinstance(entry, Mapping)
                ],
                warnings=list(raw.get("warnings", [])),
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
                        "citations": [
                            {
                                "source_name": citation.source_name,
                                "url": citation.url,
                                "title": citation.title,
                            }
                            for citation in result.citations
                        ],
                        "warnings": result.warnings,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass  # a cold cache tomorrow is acceptable; failing the run is not
