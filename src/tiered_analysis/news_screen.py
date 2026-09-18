# -*- coding: utf-8 -*-
"""LLM news screen — the judgment stage of the company-news pipeline.

The deterministic relevance filter (company_news.py) answers "does the
article NAME the company?" — cheap, no AI, cuts the bulk junk. This
stage answers what a keyword cannot, split into two LLM steps with
opposite caching behavior:

1. JUDGE (expensive, cacheable): per article — about_company (actually
   ABOUT the company, or only a name-drop?) and materiality 0-5 (how
   much it could move the stock over weeks). These judgments are
   article-INTRINSIC — they never change once made — so they cache on
   disk by URL: a daily run re-judges only articles it has never seen
   (~20-40/day even for a mega cap), not the whole window. Cache
   entries are pruned once the article's publish date ages out of any
   possible card window (``CACHE_MAX_AGE_DAYS``); until then they never
   go stale. Uncached articles are judged in size-bounded batches that
   run in PARALLEL threads, and judgments are compact arrays
   (``[n, about, materiality]``) because judgment-TYPING time dominates
   latency (measured 2026-08-15; ``include_reasons=True`` restores the
   audit phrase for trials).

2. GROUP (cheap, always fresh): one small headline-only call over just
   the important survivors, marking which cover the same underlying
   event — so eight rewrites of one financing deal collapse to one
   card bullet. Grouping is batch-RELATIVE (it links articles to each
   other), which is why it is never cached; being small it re-runs in
   seconds, and because it sees the WHOLE window at once, a story
   spanning two weeks groups correctly instead of appearing once per
   chunk.

``select_events`` then does the plain-code selection: collapse each
event group to its most important article (highest score; an abstract,
then recency, break ties), keep every event at or above
``INCLUDE_THRESHOLD`` — no fixed top-N, the card's length reflects the
week. When more than ``MAX_EVENTS`` events pass the bar, a third small
LLM call (RANK, batch-relative like grouping, never cached) orders the
finalists most-to-least important and only the top ``MAX_EVENTS``
survive — a comparative ranking over ~25 headlines is a task the model
does reliably, unlike a global ordering of hundreds. A quiet week still
shows only what passed the bar: the ceiling never pads.

4. SUMMARIZE (small, cacheable): one call turns each surviving event's
   representative headline+abstract into a single plain-English card
   sentence — feed abstracts are often video-transcript dumps,
   press-release boilerplate, or bare URLs (measured 2026-08-16 on
   GOOGL run #8). A summary is article-intrinsic, so it caches by URL
   next to the judgment; warm runs only summarize newly-won articles.
   This is the one stage where the model writes card text — constrained
   to facts present in the given text, with the feed's own words as the
   fail-soft fallback.

Fail-soft contract: an LLM failure (config missing, bad JSON, missing
judgments) must never HIDE news. An article without a usable judgment is
kept with materiality None — which passes selection — with a warning,
and such fallbacks are NEVER written to the cache (a failure must not
persist as fact). A failed grouping call degrades to no grouping
(possible duplicate bullets), a failed ranking to importance-score
order, a failed summary to the feed's verbatim abstract — all warned,
never dropped news.

``screen_news`` is the one-stop entry: judge (cached) -> group ->
select -> rank-trim (only past the ceiling) -> summarize (cached).
Wired into the provider's collect() since 2026-08-15.

Two prompt sets share these mechanics (``ScreenPrompts``,
2026-08-16): ``COMPANY_PROMPTS`` (the default — per-company news, "is
it about this company?") and ``WORLD_PROMPTS`` (the world_news
provider — general market/world news, "is it about the macro backdrop,
and how much could it move the OVERALL market?").
Everything below the prompt layer — judgment parsing, caching,
grouping, ranking, selection — is prompt-set-blind.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from .cache_store import CacheStore, default_cache_store

from pydantic import BaseModel

from .llm_support import (
    active_tracker,
    request_structured,
    screen_summarizer,
)

#: Materiality is graded 0-5; out-of-range model output is clamped.
MATERIALITY_MIN = 0
MATERIALITY_MAX = 5

#: An event makes the card when its best article scores at least this.
INCLUDE_THRESHOLD = 3

#: The card's ceiling: when more bar-passing events exist, the rank
#: call orders them and the top MAX_EVENTS survive. Never a target — a
#: quiet week shows fewer, nothing is padded. 20 -> 30 (owner decision
#: 2026-09-18).
MAX_EVENTS = 30

#: One summary sentence may use at most this many words (prompt-level
#: guidance; the model is not hard-truncated).
SUMMARY_MAX_WORDS = 40

#: Articles per judge call; batches run in parallel threads.
JUDGE_BATCH_SIZE = 50

#: How many judge batches run concurrently.
_MAX_PARALLEL_BATCHES = 8

#: Cached judgments outlive any card window by a wide margin (the
#: window is a fixed constant — NEWS_WINDOW_BDAYS — never tied to the
#: user's hold time), then prune. Not a freshness TTL — a judgment
#: never goes stale; the article just stops being fetchable.
CACHE_MAX_AGE_DAYS = 35


_JUDGE_PROMPT = """You are screening news articles fetched for the US stock {symbol} ({company}).
For each numbered article you get the publish date, the outlet, the headline, and the feed's abstract.
Judge ONLY from this text — never guess beyond it.

For each article decide:
- about_company: 1 only if the article is substantially about this company — its business, products, financials, legal or regulatory matters, executives, or its stock specifically. 0 if the company is merely name-dropped: another company's story that mentions it, a market wrap-up or trading calendar that lists it among many, a broad listicle.
- materiality: integer 0-5 — how much this news could move this stock over the coming weeks:
  5 = major corporate event: merger or acquisition, earnings surprise, guidance change, large capital raise or buyback, major regulatory or legal action
  4 = significant company-specific development: major product launch, big contract win or loss, executive departure, credible large-partner news
  3 = meaningful but routine company news: normal product updates, mid-size deals, notable analyst action with new reasoning
  2 = minor or soft company news: small feature notes, minor partnerships, routine analyst reiterations
  1 = opinion, listicle, or commentary about the company with no new facts
  0 = not about the company

Answer with strict JSON only, no prose around it:
{answer_format}
Include every article number exactly once.

Articles:
{articles}"""

_ANSWER_COMPACT = (
    '{"articles": [[n, about_company, materiality], ...]}\n'
    "where each inner list is [article number, about_company (1 or 0), "
    "materiality (0-5)]."
)

_ANSWER_REASONED = (
    '{"articles": [[n, about_company, materiality, "reason"], ...]}\n'
    "where each inner list is [article number, about_company (1 or 0), "
    "materiality (0-5), reason (one short phrase)]."
)

_GROUP_PROMPT = """These news headlines were all judged relevant to the US stock {symbol} ({company}).
Group together the ones that cover the SAME underlying event or story — the same announcement, deal, lawsuit, product, or personnel change — even when different outlets word it differently. A headline with no sibling forms its own group.

Answer with strict JSON only, no prose around it:
{{"groups": [[1, 4, 9], [2], [3]]}}
Every headline number must appear in exactly one group.

Headlines:
{headlines}"""

_RANK_PROMPT = """These news events all concern the US stock {symbol} ({company}) and already passed an importance screen.
Rank them from MOST to LEAST likely to move this stock over the coming weeks.

Answer with strict JSON only, no prose around it:
{{"order": [n, n, ...]}}
listing every event number exactly once, most important first.

Events:
{headlines}"""

_SUMMARIZE_PROMPT = """You are writing one-line news card bullets for the US stock {symbol} ({company}).
For each numbered article you get the publish date, the outlet, the headline, and the feed's raw abstract. Abstracts are often messy — video-transcript dumps, press-release boilerplate, bare URLs, or several headlines glued together.
For each article write ONE plain-English sentence, at most {max_words} words, stating what happened, including the key figures when given. Use ONLY facts present in the given text — never add outside knowledge, opinion, or advice. If the abstract is unusable, restate the headline plainly.

Answer with strict JSON only, no prose around it:
{{"summaries": [[n, "one-sentence summary"], ...]}}
Include every article number exactly once.

Articles:
{articles}"""


# ---------------------------------------------------------------------------
# World-news prompt set (2026-08-16). The pipeline mechanics (judge ->
# group -> select -> rank -> summarize) are shared with company news;
# only the judgment lens differs: "is this about the macro/world
# backdrop, and how much could it move the OVERALL market?" instead of
# "is this about the company?". The compact judgment array keeps the
# same positional shape ([n, relevant, materiality]) so every parser
# and cache below is prompt-set-blind.
# ---------------------------------------------------------------------------

_WORLD_JUDGE_PROMPT = """You are screening general market/world news articles for a stock-trading backdrop report.
For each numbered article you get the publish date, the outlet, the headline, and the feed's abstract.
Judge ONLY from this text — never guess beyond it.

For each article decide:
- relevant: 1 only if the article is substantially about the macro/world backdrop — central banks and interest rates, inflation or employment data, government fiscal/trade/regulatory policy, geopolitics, energy or currency markets, or broad market-wide stress. 0 if it is a single company's story, sports or entertainment, personal-finance advice, a stock-picking listicle, or crypto chatter with no broad-market consequence (a crypto move counts only when big enough to hit overall risk appetite).
- materiality: integer 0-5 — how much this news could move the OVERALL stock market over the coming weeks:
  5 = major market-moving development: a central bank rate decision or clear policy shift, a big inflation or jobs surprise, war outbreak or major escalation, sweeping tariff or trade actions, systemic financial stress
  4 = significant backdrop change: an influential central-bank speech signaling a shift, major fiscal or regulatory moves, a sharp oil/currency move, a notable geopolitical development
  3 = meaningful but routine macro news: in-line data prints, scheduled meeting minutes, moderate policy developments
  2 = minor macro commentary or incremental follow-up with little new substance
  1 = opinion, outlook listicle, or a routine daily market wrap with no new facts
  0 = not about the macro/world backdrop

Answer with strict JSON only, no prose around it:
{answer_format}
Include every article number exactly once.

Articles:
{articles}"""

_WORLD_ANSWER_COMPACT = (
    '{"articles": [[n, relevant, materiality], ...]}\n'
    "where each inner list is [article number, relevant (1 or 0), "
    "materiality (0-5)]."
)

_WORLD_ANSWER_REASONED = (
    '{"articles": [[n, relevant, materiality, "reason"], ...]}\n'
    "where each inner list is [article number, relevant (1 or 0), "
    "materiality (0-5), reason (one short phrase)]."
)

_WORLD_GROUP_PROMPT = """These news headlines were all judged relevant to the macro/world market backdrop.
Group together the ones that cover the SAME underlying event or story — the same decision, data release, conflict development, or policy move — even when different outlets word it differently. A headline with no sibling forms its own group.

Answer with strict JSON only, no prose around it:
{{"groups": [[1, 4, 9], [2], [3]]}}
Every headline number must appear in exactly one group.

Headlines:
{headlines}"""

_WORLD_RANK_PROMPT = """These macro/world news events already passed an importance screen for a stock-trading backdrop report.
Rank them from MOST to LEAST likely to move the overall stock market over the coming weeks.

Answer with strict JSON only, no prose around it:
{{"order": [n, n, ...]}}
listing every event number exactly once, most important first.

Events:
{headlines}"""

_WORLD_SUMMARIZE_PROMPT = """You are writing one-line bullets for a macro/world news card in a stock-trading report.
For each numbered article you get the publish date, the outlet, the headline, and the feed's raw abstract. Abstracts are often messy — video-transcript dumps, boilerplate, bare URLs, or several headlines glued together.
For each article write ONE plain-English sentence, at most {max_words} words, stating what happened, including the key figures when given. Use ONLY facts present in the given text — never add outside knowledge, opinion, or advice. If the abstract is unusable, restate the headline plainly.

Answer with strict JSON only, no prose around it:
{{"summaries": [[n, "one-sentence summary"], ...]}}
Include every article number exactly once.

Articles:
{articles}"""


@dataclass(frozen=True)
class ScreenPrompts:
    """The four stage templates one screen run uses. ``judge`` gets
    ``{answer_format}`` substituted from the compact/reasoned pair;
    every template may also use ``{symbol}``/``{company}`` (unused
    placeholders passed to ``str.format`` are simply ignored — the
    world templates omit them)."""

    judge: str
    answer_compact: str
    answer_reasoned: str
    group: str
    rank: str
    summarize: str


#: The default: per-company news (the original pipeline).
COMPANY_PROMPTS = ScreenPrompts(
    judge=_JUDGE_PROMPT,
    answer_compact=_ANSWER_COMPACT,
    answer_reasoned=_ANSWER_REASONED,
    group=_GROUP_PROMPT,
    rank=_RANK_PROMPT,
    summarize=_SUMMARIZE_PROMPT,
)

#: The macro/world-backdrop lens (world_news provider).
WORLD_PROMPTS = ScreenPrompts(
    judge=_WORLD_JUDGE_PROMPT,
    answer_compact=_WORLD_ANSWER_COMPACT,
    answer_reasoned=_WORLD_ANSWER_REASONED,
    group=_WORLD_GROUP_PROMPT,
    rank=_WORLD_RANK_PROMPT,
    summarize=_WORLD_SUMMARIZE_PROMPT,
)


def _article_line(index: int, entry: Mapping[str, Any], with_summary: bool) -> str:
    title = entry.get("title") or ""
    publisher = entry.get("publisher") or "unknown outlet"
    published = entry.get("date") or "undated"
    summary = entry.get("summary") or "" if with_summary else ""
    body = f"{title} — {summary}" if summary and summary != title else title
    return f"[{index}] ({published}, {publisher}) {body}"


def build_judge_prompt(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    company: Optional[str] = None,
    include_reasons: bool = False,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> str:
    """The judge prompt: numbered headline+abstract lines.

    ``include_reasons`` adds a per-article audit phrase to the requested
    output — trials only; production skips it because judgment-typing
    time dominates the whole pipeline's latency.
    """
    return prompts.judge.format(
        symbol=symbol,
        company=company or symbol,
        answer_format=(
            prompts.answer_reasoned if include_reasons else prompts.answer_compact
        ),
        articles="\n".join(
            _article_line(i, entry, with_summary=True)
            for i, entry in enumerate(entries, start=1)
        ),
    )


def build_group_prompt(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    company: Optional[str] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> str:
    """The grouping prompt: headlines only — aboutness was already
    judged, and headlines suffice to recognize one story twice."""
    return prompts.group.format(
        symbol=symbol,
        company=company or symbol,
        headlines="\n".join(
            _article_line(i, entry, with_summary=False)
            for i, entry in enumerate(entries, start=1)
        ),
    )


def build_rank_prompt(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    company: Optional[str] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> str:
    """The ranking prompt: headlines only, like grouping — the finalists
    already carry importance grades; ranking is a comparative look."""
    return prompts.rank.format(
        symbol=symbol,
        company=company or symbol,
        headlines="\n".join(
            _article_line(i, entry, with_summary=False)
            for i, entry in enumerate(entries, start=1)
        ),
    )


def build_summarize_prompt(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    company: Optional[str] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> str:
    """The summarizing prompt: headline+abstract lines, one clean card
    sentence back per article."""
    return prompts.summarize.format(
        symbol=symbol,
        company=company or symbol,
        max_words=SUMMARY_MAX_WORDS,
        articles="\n".join(
            _article_line(i, entry, with_summary=True)
            for i, entry in enumerate(entries, start=1)
        ),
    )


# ---------------------------------------------------------------------------
# Reply forms (2026-08-25, owner request): every screen call declares
# the JSON shape it expects as a pydantic model. The model does double
# duty — the provider is asked to ENFORCE it while generating (schema
# mode, on models that support it), and ``request_structured`` CHECKS
# the reply against it, retrying once with the problem shown. The
# tolerant per-item cleaners below stay the last word on content: the
# forms only pin the wire shape, so a reply that passes them can still
# have out-of-range numbers handled item by item.
# ---------------------------------------------------------------------------


class _JudgeReplyForm(BaseModel):
    """``{"articles": [[n, about, materiality, reason?], ...]}``."""

    articles: List[List[Union[int, bool, str]]]


class _GroupReplyForm(BaseModel):
    """``{"groups": [[1-based article numbers], ...]}``."""

    groups: List[List[int]]


class _RankReplyForm(BaseModel):
    """``{"order": [1-based event numbers]}``."""

    order: List[int]


class _SummariesReplyForm(BaseModel):
    """``{"summaries": [[n, "one-sentence summary"], ...]}``."""

    summaries: List[List[Union[int, str]]]


def _clean_judgment(raw: Any, count: int) -> Optional[Dict[str, Any]]:
    """One model judgment validated, from the compact array
    ``[n, about, materiality, reason?]`` or a labeled dict. n must be in
    range, about_company a bool or 0/1, materiality clamped to the 0-5
    scale. Unusable -> None."""
    if isinstance(raw, Mapping):
        number = raw.get("n")
        about = raw.get("about_company")
        materiality = raw.get("materiality")
        reason = raw.get("reason")
    elif isinstance(raw, Sequence) and not isinstance(raw, str) and len(raw) >= 3:
        number, about, materiality = raw[0], raw[1], raw[2]
        reason = raw[3] if len(raw) >= 4 else None
    else:
        return None
    if not isinstance(number, int) or isinstance(number, bool):
        return None
    if not 1 <= number <= count:
        return None
    if not isinstance(about, bool):
        if about in (0, 1):
            about = bool(about)
        else:
            return None
    if isinstance(materiality, bool) or not isinstance(materiality, int):
        materiality = None
    else:
        materiality = max(MATERIALITY_MIN, min(MATERIALITY_MAX, materiality))
    return {
        "index": number - 1,
        "about_company": about,
        "materiality": materiality,
        "reason": str(reason or "").strip() or None,
        "from_model": True,
    }


def _kept_fallback(index: int) -> Dict[str, Any]:
    """The fail-soft judgment: no usable model judgment -> keep the
    article. ``from_model`` False keeps it out of the cache — a failure
    must never persist as fact."""
    return {
        "index": index,
        "about_company": True,
        "materiality": None,
        "reason": None,
        "from_model": False,
    }


def llm_judge_news(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    include_reasons: bool = False,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """Judge a batch of articles with one LLM call.

    Returns ``{"judgments": [...], "warnings": [...]}`` — one judgment
    per input entry, in input order: ``{"index", "about_company",
    "materiality", "reason", "from_model"}``. Every failure path
    degrades to keep-with-warning, never to silently dropped news.
    """
    if not entries:
        return {"judgments": [], "warnings": []}

    warnings: List[str] = []
    count = len(entries)
    prompt = build_judge_prompt(
        symbol, entries, company=company, include_reasons=include_reasons,
        prompts=prompts,
    )
    try:
        reply = request_structured(summarize, prompt, _JudgeReplyForm)
    except Exception as exc:
        return {
            "judgments": [_kept_fallback(i) for i in range(count)],
            "warnings": [f"news judge LLM call failed: {exc} — all articles kept"],
        }
    if reply.retried and reply.valid:
        warnings.append("news judge needed a retry — first reply was invalid")

    parsed = reply.parsed
    articles = parsed.get("articles") if isinstance(parsed, Mapping) else None
    by_index: Dict[int, Dict[str, Any]] = {}
    if isinstance(articles, list):
        for raw_judgment in articles:
            judgment = _clean_judgment(raw_judgment, count)
            if judgment is not None:
                # First judgment per article wins; duplicates are noise.
                by_index.setdefault(judgment["index"], judgment)
    if not by_index:
        return {
            "judgments": [_kept_fallback(i) for i in range(count)],
            "warnings": warnings
            + ["news judge returned no usable JSON — all articles kept"],
        }

    missing = count - len(by_index)
    if missing:
        warnings.append(
            f"news judge gave no judgment for {missing} article(s) — those kept"
        )
    judgments = [by_index.get(i) or _kept_fallback(i) for i in range(count)]
    return {"judgments": judgments, "warnings": warnings}


class NewsJudgmentCache:
    """Cache of per-article judgments and card summaries, keyed by
    article URL.

    One cache-store entry per symbol. Judgments and
    summaries are article-intrinsic, so there is no freshness TTL: an
    entry lives until its article's publish date is older than
    ``CACHE_MAX_AGE_DAYS`` (out of every possible card window), then is
    pruned on load. Summaries live in their own map — an article gets a
    summary only when it wins a card slot, so most judged articles never
    have one (and a summary-only entry must never masquerade as a
    judgment). Corrupt or unwritable cache degrades to a cold cache,
    never to a failed run (macro_economy cache convention).
    """

    version = 1

    def __init__(
        self,
        symbol: str,
        cache: Optional[CacheStore] = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._store = cache if cache is not None else default_cache_store()
        self._key = f"news_screen_{symbol.upper()}"
        self._today = today
        self._articles: Dict[str, Dict[str, Any]] = {}
        self._summaries: Dict[str, Dict[str, Any]] = {}
        self.load()

    @staticmethod
    def _fresh(
        section: Any, oldest: date
    ) -> Dict[str, Dict[str, Any]]:
        if not isinstance(section, Mapping):
            return {}
        return {
            url: dict(entry)
            for url, entry in section.items()
            if isinstance(entry, Mapping)
            and str(entry.get("date") or "") >= oldest.isoformat()
        }

    def load(self) -> None:
        try:
            raw = self._store.read(self._key)
            if not isinstance(raw, Mapping) or raw.get("version") != self.version:
                return
            oldest = self._today() - timedelta(days=CACHE_MAX_AGE_DAYS)
            self._articles = self._fresh(raw.get("articles"), oldest)
            # Older cache entries predate summaries; missing -> empty.
            self._summaries = self._fresh(raw.get("summaries"), oldest)
        except Exception:
            pass  # corrupt cache: re-judge, never fail on cache

    def get(self, url: Optional[str]) -> Optional[Dict[str, Any]]:
        return self._articles.get(url) if url else None

    def put(
        self,
        url: Optional[str],
        about_company: bool,
        materiality: Optional[int],
        published: Optional[str],
    ) -> None:
        if url:
            self._articles[url] = {
                "about": bool(about_company),
                "materiality": materiality,
                "date": published,
            }

    def get_summary(self, url: Optional[str]) -> Optional[str]:
        entry = self._summaries.get(url) if url else None
        text = entry.get("text") if entry else None
        return str(text) if text else None

    def put_summary(
        self, url: Optional[str], text: str, published: Optional[str]
    ) -> None:
        if url and text:
            self._summaries[url] = {"text": text, "date": published}

    def save(self) -> None:
        # The store never raises: a cold cache tomorrow is acceptable,
        # failing the run is not.
        self._store.write(
            self._key,
            {
                "version": self.version,
                "articles": self._articles,
                "summaries": self._summaries,
            },
        )


def judge_news_cached(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    include_reasons: bool = False,
    cache: Optional[NewsJudgmentCache] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """Judge all articles, reusing cached judgments and LLM-judging only
    the rest in parallel size-bounded batches.

    Returns ``{"judgments", "warnings", "from_cache", "judged"}``.
    Freshly judged articles are written back through ``cache`` (saved
    once at the end); fail-soft fallbacks are never cached.
    """
    judgments: List[Optional[Dict[str, Any]]] = [None] * len(entries)
    uncached: List[int] = []
    for position, entry in enumerate(entries):
        hit = cache.get(entry.get("url")) if cache else None
        if hit is not None:
            judgments[position] = {
                "index": position,
                "about_company": bool(hit.get("about")),
                "materiality": hit.get("materiality"),
                "reason": None,
                "from_model": True,
            }
        else:
            uncached.append(position)
    from_cache = len(entries) - len(uncached)

    warnings: List[str] = []
    if uncached:
        batches = [
            uncached[start:start + JUDGE_BATCH_SIZE]
            for start in range(0, len(uncached), JUDGE_BATCH_SIZE)
        ]

        # The run's LLM usage tracker lives in thread-local storage —
        # worker threads must re-activate it or their calls vanish from
        # the count (llm_support.active_tracker contract).
        tracker = active_tracker()

        def _judge_batch(positions: List[int]) -> Dict[str, Any]:
            batch = [entries[position] for position in positions]
            if tracker is None:
                return llm_judge_news(
                    symbol, batch, summarize=summarize, company=company,
                    include_reasons=include_reasons, prompts=prompts,
                )
            with tracker.activate():
                return llm_judge_news(
                    symbol, batch, summarize=summarize, company=company,
                    include_reasons=include_reasons, prompts=prompts,
                )

        if len(batches) == 1:
            outcomes = [_judge_batch(batches[0])]
        else:
            with ThreadPoolExecutor(
                max_workers=min(_MAX_PARALLEL_BATCHES, len(batches))
            ) as pool:
                outcomes = list(pool.map(_judge_batch, batches))

        for positions, outcome in zip(batches, outcomes):
            warnings.extend(outcome["warnings"])
            for position, judgment in zip(positions, outcome["judgments"]):
                placed = dict(judgment)
                placed["index"] = position
                judgments[position] = placed
                if cache and placed["from_model"]:
                    entry = entries[position]
                    cache.put(
                        entry.get("url"),
                        placed["about_company"],
                        placed["materiality"],
                        entry.get("date"),
                    )
        if cache:
            cache.save()

    return {
        "judgments": judgments,
        "warnings": warnings,
        "from_cache": from_cache,
        "judged": len(uncached),
    }


def llm_group_events(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """Group same-story articles with one small headline-only call.

    Returns ``{"groups": [[0-based indices]], "warnings": [...]}`` —
    every input index appears in exactly one group. Failure degrades to
    all-singletons (possible duplicate bullets, warned), never to
    dropped news.
    """
    if not entries:
        return {"groups": [], "warnings": []}
    if len(entries) == 1:
        return {"groups": [[0]], "warnings": []}

    count = len(entries)
    singletons = [[index] for index in range(count)]
    prompt = build_group_prompt(symbol, entries, company=company, prompts=prompts)
    try:
        reply = request_structured(summarize, prompt, _GroupReplyForm)
    except Exception as exc:
        return {
            "groups": singletons,
            "warnings": [f"news grouping LLM call failed: {exc} — no grouping"],
        }
    warnings: List[str] = []
    if reply.retried and reply.valid:
        warnings.append("news grouping needed a retry — first reply was invalid")

    parsed = reply.parsed
    raw_groups = parsed.get("groups") if isinstance(parsed, Mapping) else None
    if not isinstance(raw_groups, list):
        return {
            "groups": singletons,
            "warnings": warnings
            + ["news grouping returned no usable JSON — no grouping"],
        }

    seen: set = set()
    groups: List[List[int]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            continue
        members = []
        for number in raw_group:
            if (
                isinstance(number, int)
                and not isinstance(number, bool)
                and 1 <= number <= count
                and (number - 1) not in seen
            ):
                seen.add(number - 1)
                members.append(number - 1)
        if members:
            groups.append(members)
    # Anything the model forgot stays its own event — never dropped.
    missing = [index for index in range(count) if index not in seen]
    groups.extend([index] for index in missing)
    if missing:
        warnings.append(
            f"news grouping left {len(missing)} article(s) ungrouped — kept as"
            " separate events"
        )
    return {"groups": groups, "warnings": warnings}


def llm_rank_events(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """Order finalist events most-to-least important with one small
    headline-only call.

    Returns ``{"order": [0-based indices], "warnings": [...]}`` — a
    permutation of the input. Callers pass entries already in
    importance-score order, so every failure path degrades to the input
    order (score order), warned, never to dropped events. Batch-relative
    like grouping: never cached.
    """
    count = len(entries)
    fallback = list(range(count))
    if count <= 1:
        return {"order": fallback, "warnings": []}

    prompt = build_rank_prompt(symbol, entries, company=company, prompts=prompts)
    try:
        reply = request_structured(summarize, prompt, _RankReplyForm)
    except Exception as exc:
        return {
            "order": fallback,
            "warnings": [
                f"news ranking LLM call failed: {exc} — importance-score order kept"
            ],
        }
    warnings: List[str] = []
    if reply.retried and reply.valid:
        warnings.append("news ranking needed a retry — first reply was invalid")

    parsed = reply.parsed
    numbers = parsed.get("order") if isinstance(parsed, Mapping) else None
    order: List[int] = []
    seen: set = set()
    if isinstance(numbers, list):
        for number in numbers:
            if (
                isinstance(number, int)
                and not isinstance(number, bool)
                and 1 <= number <= count
                and (number - 1) not in seen
            ):
                seen.add(number - 1)
                order.append(number - 1)
    if not order:
        return {
            "order": fallback,
            "warnings": warnings
            + [
                "news ranking returned no usable JSON — importance-score order kept"
            ],
        }
    # Forgotten events keep their score-order position at the tail —
    # never dropped by a model omission.
    missing = [index for index in fallback if index not in seen]
    if missing:
        warnings.append(
            f"news ranking left {len(missing)} event(s) unranked — appended in"
            " importance-score order"
        )
    return {"order": order + missing, "warnings": warnings}


def llm_summarize_articles(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """One-sentence card summaries for a batch of articles, one call.

    Returns ``{"summaries": [str or None per entry], "warnings": [...]}``
    in input order. None means no usable summary — the caller falls back
    to the feed's own words, so a failure degrades the bullet's polish,
    never its presence.
    """
    if not entries:
        return {"summaries": [], "warnings": []}

    count = len(entries)
    prompt = build_summarize_prompt(
        symbol, entries, company=company, prompts=prompts
    )
    try:
        reply = request_structured(summarize, prompt, _SummariesReplyForm)
    except Exception as exc:
        return {
            "summaries": [None] * count,
            "warnings": [
                f"news summary LLM call failed: {exc} — feed abstracts shown verbatim"
            ],
        }
    warnings: List[str] = []
    if reply.retried and reply.valid:
        warnings.append("news summary needed a retry — first reply was invalid")

    parsed = reply.parsed
    raw_summaries = parsed.get("summaries") if isinstance(parsed, Mapping) else None
    texts: List[Optional[str]] = [None] * count
    if isinstance(raw_summaries, list):
        for pair in raw_summaries:
            if (
                isinstance(pair, list)
                and len(pair) >= 2
                and isinstance(pair[0], int)
                and not isinstance(pair[0], bool)
                and 1 <= pair[0] <= count
                and isinstance(pair[1], str)
                and pair[1].strip()
            ):
                # First summary per article wins; duplicates are noise.
                if texts[pair[0] - 1] is None:
                    texts[pair[0] - 1] = " ".join(pair[1].split())
    missing = sum(1 for text in texts if text is None)
    if missing == count:
        warnings.append(
            "news summary returned no usable JSON — feed abstracts shown verbatim"
        )
    elif missing:
        warnings.append(
            f"news summary missing for {missing} article(s) — those show the"
            " feed abstract verbatim"
        )
    return {"summaries": texts, "warnings": warnings}


def summarize_articles_cached(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    cache: Optional[NewsJudgmentCache] = None,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """Card summaries with the URL cache in front: a summary never
    changes once written, so only never-summarized articles hit the LLM.
    Only model-written summaries are cached — a fallback (None) must not
    persist as fact."""
    texts: List[Optional[str]] = [None] * len(entries)
    uncached: List[int] = []
    for position, entry in enumerate(entries):
        hit = cache.get_summary(entry.get("url")) if cache else None
        if hit is not None:
            texts[position] = hit
        else:
            uncached.append(position)

    warnings: List[str] = []
    if uncached:
        outcome = llm_summarize_articles(
            symbol,
            [entries[position] for position in uncached],
            summarize=summarize,
            company=company,
            prompts=prompts,
        )
        warnings = outcome["warnings"]
        for position, text in zip(uncached, outcome["summaries"]):
            texts[position] = text
            if cache and text:
                entry = entries[position]
                cache.put_summary(entry.get("url"), text, entry.get("date"))
        if cache:
            cache.save()
    return {
        "summaries": texts,
        "warnings": warnings,
        "from_cache": len(entries) - len(uncached),
        "summarized": len(uncached),
    }


def select_events(
    entries: Sequence[Mapping[str, Any]],
    judgments: Sequence[Mapping[str, Any]],
    threshold: int = INCLUDE_THRESHOLD,
) -> Dict[str, Any]:
    """Plain-code selection over screened articles — no further AI.

    ``judgments`` are judgments plus an ``event`` key (0-based index of
    the group's anchor article). Collapses each event group to its most
    important article (highest materiality; an abstract beats a bare
    headline, then newest, break ties) and keeps every event whose best
    score reaches the threshold — no fixed top-N. The ceiling trim
    lives in ``screen_news`` (rank-ordered). Unknown materiality (an
    LLM failure upstream) passes selection: fail-soft never hides news.

    Returns ``{"selected": [{"entry", "judgment", "materiality",
    "group_size"}], "mention_only": n, "below_threshold": n,
    "warnings": [...]}`` with ``selected`` ordered by materiality, then
    date, newest first.
    """
    warnings: List[str] = []
    groups: Dict[int, List[Mapping[str, Any]]] = {}
    mention_only = 0
    for judgment in judgments:
        if not judgment["about_company"]:
            mention_only += 1
            continue
        groups.setdefault(judgment["event"], []).append(judgment)

    events: List[Dict[str, Any]] = []
    for members in groups.values():
        scores = [
            member["materiality"]
            for member in members
            if member["materiality"] is not None
        ]

        def _representative_rank(member: Mapping[str, Any]):
            entry = entries[member["index"]]
            return (
                member["materiality"] if member["materiality"] is not None else -1,
                bool(entry.get("summary")),
                entry.get("date") or "",
                -member["index"],
            )

        best = max(members, key=_representative_rank)
        events.append(
            {
                "entry": entries[best["index"]],
                "judgment": best,
                "materiality": max(scores) if scores else None,
                "group_size": len(members),
            }
        )

    selected = [
        event
        for event in events
        if event["materiality"] is None or event["materiality"] >= threshold
    ]
    below_threshold = len(events) - len(selected)
    selected.sort(
        key=lambda event: (
            event["materiality"] if event["materiality"] is not None else -1,
            event["entry"].get("date") or "",
        ),
        reverse=True,
    )

    return {
        "selected": selected,
        "mention_only": mention_only,
        "below_threshold": below_threshold,
        "warnings": warnings,
    }


def screen_news(
    symbol: str,
    entries: Sequence[Mapping[str, Any]],
    summarize: Callable[[str], str] = screen_summarizer,
    company: Optional[str] = None,
    threshold: int = INCLUDE_THRESHOLD,
    max_events: int = MAX_EVENTS,
    cache: Optional[NewsJudgmentCache] = None,
    include_reasons: bool = False,
    prompts: ScreenPrompts = COMPANY_PROMPTS,
) -> Dict[str, Any]:
    """One-stop screen: judge (cached, parallel) -> group survivors
    (one small fresh call over the whole window) -> select -> rank-trim
    (only when the ceiling is exceeded) -> summarize winners (cached).

    Only articles that are about the company AND could make the card
    (materiality >= threshold, or unknown from a fail-soft) are worth a
    grouping look; the rest never surface, so grouping them would be
    wasted tokens. Likewise ranking runs only when there is a cut to
    make, and summaries are written only for the events actually shown.

    Returns select_events' shape plus ``trimmed``, ``judgments``,
    ``from_cache`` and ``judged`` counts, with all stages' warnings
    merged. Each selected event carries ``card_text`` — the model's
    one-sentence summary, or None when the feed's own words must serve.
    """
    judged = judge_news_cached(
        symbol,
        entries,
        summarize=summarize,
        company=company,
        include_reasons=include_reasons,
        cache=cache,
        prompts=prompts,
    )
    judgments = judged["judgments"]

    candidates = [
        judgment["index"]
        for judgment in judgments
        if judgment["about_company"]
        and (judgment["materiality"] is None or judgment["materiality"] >= threshold)
    ]
    grouping = llm_group_events(
        symbol,
        [entries[index] for index in candidates],
        summarize=summarize,
        company=company,
        prompts=prompts,
    )
    anchor_of: Dict[int, int] = {}
    for local_group in grouping["groups"]:
        anchor = candidates[local_group[0]]
        for local in local_group:
            anchor_of[candidates[local]] = anchor

    judgments = [
        {**judgment, "event": anchor_of.get(judgment["index"], judgment["index"])}
        for judgment in judgments
    ]
    selection = select_events(entries, judgments, threshold=threshold)
    selected = selection["selected"]

    # Ceiling: rank the finalists (comparative, reliable at this size)
    # and keep the top max_events. selected arrives in importance-score
    # order, which is exactly the fail-soft order if ranking fails.
    trim_warnings: List[str] = []
    trimmed = 0
    if len(selected) > max_events:
        ranking = llm_rank_events(
            symbol,
            [event["entry"] for event in selected],
            summarize=summarize,
            company=company,
            prompts=prompts,
        )
        trim_warnings.extend(ranking["warnings"])
        ranked = [selected[index] for index in ranking["order"]]
        trimmed = len(ranked) - max_events
        selected = ranked[:max_events]
        trim_warnings.append(
            f"busy news window: {trimmed} event(s) ranked below the top"
            f" {max_events} and trimmed"
        )

    summaries = summarize_articles_cached(
        symbol,
        [event["entry"] for event in selected],
        summarize=summarize,
        company=company,
        cache=cache,
        prompts=prompts,
    )
    selected = [
        {**event, "card_text": text}
        for event, text in zip(selected, summaries["summaries"])
    ]

    return {
        **selection,
        "selected": selected,
        "trimmed": trimmed,
        "judgments": judgments,
        "from_cache": judged["from_cache"],
        "judged": judged["judged"],
        "warnings": (
            judged["warnings"]
            + grouping["warnings"]
            + selection["warnings"]
            + trim_warnings
            + summaries["warnings"]
        ),
    }
