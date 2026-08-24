# -*- coding: utf-8 -*-
"""Tier-1 quick judge: one LLM call over the collected evidence.

Until 2026-08-10 the quick tier delegated to the legacy DSA one-blob
analysis, which gathered its own inputs and never saw the user's max
hold time. The owner is separating the tiered (alt) pipeline from the
legacy app, so the quick tier now runs the tiered package's own judge:
a single call that reads the SAME dimensions the deep debate
reads, judges them against the SAME hold horizon, and scores on the
SAME 0-10 scale with the same verdict cut-points (``debate.SELL_BELOW``
/ ``debate.HOLD_MAX``).

That makes quick vs deep a clean experiment: same evidence, same
horizon, same scale — one judge in one call versus the multi-persona
debate. The verdict travels on ``TierReport.debate_detail`` in a
distinct ``quick-1`` format so the signal logger picks up the score
(and score band) through the exact same door as the debate's.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .debate import direction_from_final
from .llm_support import (
    LlmConfigError,
    deterministic_summarizer,
    evidence_block,
    parse_llm_json,
)
from .providers.base import DimensionResult
from .schema import (
    Direction,
    SniperLevels,
    coerce_price,
    hold_weeks_text,
)

logger = logging.getLogger(__name__)

#: Stored-detail format marker (``report.debate_detail.format``). A
#: string, deliberately outside the debate's numeric format lineage —
#: the web's debate-tree renderers key on numeric formats and must
#: never try to render a quick verdict as a debate.
QUICK_DETAIL_FORMAT = "quick-1"

#: One honest retry: the judge runs at temperature 0, so a bare re-ask
#: would reproduce the same broken reply — the retry appends the
#: rejection reason to break the loop.
MAX_ATTEMPTS = 2

_PROMPT_TEMPLATE = """You are the sole analyst judging a swing trade on {symbol}.
The position would be held for up to {hold_text} (the user's chosen max
hold time) — judge every piece of evidence against that horizon.

Formula-computed plan levels: entry={entry}, backup={secondary_entry}, stop={stop_loss}, target={take_profit}

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

Weigh the bullish and bearish evidence for this horizon and reply with
JSON only:
{{"score": <number 0-10, up to 2 decimals>, "summary": "<3-6 plain sentences>"}}

Rules:
- "score" is your overall outlook for holding up to {hold_text}: below
  4 = bearish (exit region), 4-6 = neutral (wait region), above 6 =
  bullish (buy region). Use the full scale; reserve scores under 2 or
  over 8 for strong, well-supported cases.
- "summary" states the outlook and the strongest evidence both for and
  against it, in plain language a non-finance reader can follow.
- Any number you state in the summary must appear in the evidence
  above EXACTLY as displayed there; never invent or recompute numbers.
  Write values as plain numbers in the sentences — do not wrap them in
  quotation marks.
- No text outside the JSON object.
"""

_RETRY_TEMPLATE = """{prompt}
Your previous reply was rejected: {problem}
Reply again with ONLY the required JSON object.
"""


@dataclass(frozen=True)
class QuickVerdict:
    """The one-call judge's decision on the debate's 0-10 scale."""

    direction: Direction
    final_score: float
    summary: str


@dataclass(frozen=True)
class QuickResult:
    """Outcome of one quick-judge run — failures are warnings, never
    exceptions (the pipeline's fail-loud contract)."""

    verdict: Optional[QuickVerdict] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready verdict for ``report.debate_detail`` — the same
        ``verdict.final_score`` shape the signal logger reads from deep
        runs, under the quick format marker."""
        detail: Dict[str, Any] = {"format": QUICK_DETAIL_FORMAT}
        if self.verdict is not None:
            detail["verdict"] = {
                "direction": self.verdict.direction.value,
                "final_score": self.verdict.final_score,
            }
        return detail


def _parse_verdict(raw: str) -> Tuple[Optional[QuickVerdict], Optional[str]]:
    """Validate one reply; returns ``(verdict, None)`` or ``(None, why)``."""
    parsed = parse_llm_json(raw)
    if parsed is None:
        return None, "reply is not a JSON object"
    score = coerce_price(parsed.get("score"))
    if score is None or not 0.0 <= score <= 10.0:
        return None, f"score must be a number 0-10, got {parsed.get('score')!r}"
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None, "summary must be a non-empty string"
    score = round(score, 2)
    return (
        QuickVerdict(
            direction=direction_from_final(score),
            final_score=score,
            summary=summary.strip(),
        ),
        None,
    )


class QuickJudge:
    """One LLM call, one verdict; the summarizer is a test seam."""

    def __init__(
        self,
        summarizer: Callable[[str], str] = deterministic_summarizer,
    ) -> None:
        self._summarize = summarizer

    def run(
        self,
        symbol: str,
        dimensions: Sequence[DimensionResult],
        levels: SniperLevels,
        hold_weeks: int,
    ) -> QuickResult:
        prompt = _PROMPT_TEMPLATE.format(
            symbol=symbol,
            hold_text=hold_weeks_text(hold_weeks),
            entry=levels.entry,
            secondary_entry=levels.secondary_entry,
            stop_loss=levels.stop_loss,
            take_profit=levels.take_profit,
            evidence=evidence_block(dimensions, display=True),
        )
        warnings: List[str] = []
        attempt_prompt = prompt
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self._summarize(attempt_prompt)
            except LlmConfigError as exc:
                return QuickResult(warnings=warnings + [str(exc)])
            except Exception as exc:
                logger.warning("quick judge LLM call failed for %s: %s", symbol, exc)
                warnings.append(f"quick judge LLM call failed: {exc}")
                continue
            verdict, problem = _parse_verdict(raw)
            if verdict is not None:
                return QuickResult(verdict=verdict, warnings=warnings)
            warnings.append(f"quick judge reply rejected: {problem}")
            attempt_prompt = _RETRY_TEMPLATE.format(prompt=prompt, problem=problem)
        return QuickResult(
            warnings=warnings + ["quick judge produced no verdict — no outlook (re-run)"]
        )
