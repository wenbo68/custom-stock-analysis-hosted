# -*- coding: utf-8 -*-
"""Shared plumbing for the tiered package's own LLM calls (v2).

Used by the level adjuster (slice 3) and the tier-2 debate (slice 4).
These calls are owned by the tiered package — Tier 1's synthesis happens
inside DSA's decision path, which this package never modifies.

The evidence helpers implement the anchoring contract: LLM claims may only
reference collected evidence — a dimension payload key path that actually
resolves (``technicals.rsi_14``).
"""
from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .providers.base import DimensionResult


class LlmConfigError(RuntimeError):
    """LLM configuration missing — callers surface this as a warning."""


@dataclass
class _StageUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


#: What the usage numbers cover — stored with them so a reader of an old
#: run is never left guessing. Since 2026-08-10 every LLM stage (the
#: tier-1 quick judge, the debate, the plan review) is a tiered-package
#: call and counted; on older runs the tier-1 blob ran inside the DSA
#: pipeline and was billed there.
USAGE_SCOPE_NOTE = (
    "all tiered-package LLM calls; on runs before 2026-08-10 the tier-1 "
    "synthesis ran inside the DSA pipeline and is not counted"
)

_UNATTRIBUTED_STAGE = "unattributed"

_active = threading.local()


class LlmUsageTracker:
    """Per-run LLM call/token counter, grouped by pipeline stage.

    The orchestrator activates one tracker for the run and opens a stage
    around each LLM-using step; ``default_summarizer`` reports into
    whichever tracker is active on the current thread. No tracker active
    (v1 call sites, tests with fake summarizers) → recording is a no-op.
    """

    def __init__(self) -> None:
        self._stages: Dict[str, _StageUsage] = {}
        self._current: Optional[str] = None
        # Debate stages run two LLM calls in parallel threads; both report
        # into the same tracker.
        self._lock = threading.Lock()

    @contextmanager
    def activate(self):
        previous = getattr(_active, "tracker", None)
        _active.tracker = self
        try:
            yield self
        finally:
            _active.tracker = previous

    @contextmanager
    def stage(self, name: str):
        previous = self._current
        self._current = name
        try:
            yield
        finally:
            self._current = previous

    def record(
        self, prompt_tokens: Optional[int], completion_tokens: Optional[int]
    ) -> None:
        with self._lock:
            stage = self._stages.setdefault(
                self._current or _UNATTRIBUTED_STAGE, _StageUsage()
            )
            stage.calls += 1
            stage.prompt_tokens += int(prompt_tokens or 0)
            stage.completion_tokens += int(completion_tokens or 0)

    def to_detail(self) -> Dict[str, Any]:
        total = _StageUsage()
        for usage in self._stages.values():
            total.calls += usage.calls
            total.prompt_tokens += usage.prompt_tokens
            total.completion_tokens += usage.completion_tokens
        return {
            "stages": {name: u.as_dict() for name, u in self._stages.items()},
            "total": total.as_dict(),
            "scope": USAGE_SCOPE_NOTE,
        }


def record_llm_usage(
    prompt_tokens: Optional[int], completion_tokens: Optional[int]
) -> None:
    """Report one LLM call to the active tracker, if any."""
    tracker = getattr(_active, "tracker", None)
    if tracker is not None:
        tracker.record(prompt_tokens, completion_tokens)


def active_tracker() -> Optional["LlmUsageTracker"]:
    """The tracker active on this thread, or None.

    The tracker lives in thread-local storage, so code that fans LLM calls
    out to worker threads (the debate's parallel stages) must capture it
    here and re-``activate()`` it inside each worker — otherwise those
    calls silently vanish from the run's usage numbers.
    """
    return getattr(_active, "tracker", None)


def _summarize(prompt: str, temperature: float, model: Optional[str] = None) -> str:
    import os

    resolved = (model or os.getenv("LITELLM_MODEL") or "").strip()
    if not resolved:
        raise LlmConfigError(
            "LITELLM_MODEL is not set; tiered-analysis LLM stages need the "
            "repo's standard LLM configuration"
        )
    import litellm

    response = litellm.completion(
        model=resolved,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    usage = getattr(response, "usage", None)
    record_llm_usage(
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )
    return response.choices[0].message.content or ""


def default_summarizer(prompt: str) -> str:
    # Temperature 0 everywhere (owner decision 2026-08-23): every LLM
    # stage of a run should repeat as closely as the API allows.
    return _summarize(prompt, temperature=0.0)


def screen_summarizer(prompt: str) -> str:
    """Summarizer for the news screen's classification chores.

    ``NEWS_SCREEN_MODEL`` (a faster, cheaper model — screening is
    is-this-about-the-company bookkeeping, not analysis) when set, the
    standard ``LITELLM_MODEL`` otherwise: unconfigured keeps working,
    configured speeds it up. Temperature 0 like every other stage.
    """
    import os

    model = (os.getenv("NEWS_SCREEN_MODEL") or "").strip() or None
    return _summarize(prompt, temperature=0.0, model=model)


def deterministic_summarizer(prompt: str) -> str:
    """Zero-temperature summarizer: the scored tier-2 debate uses it so the
    same evidence grades the same way on every run."""
    return _summarize(prompt, temperature=0.0)


def parse_llm_json(raw: str) -> Optional[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def display_value(value: Any) -> str:
    """One number, formatted exactly as the web report pages show it.

    A Python port of the frontend's ``formatValue`` (termHelpers.ts): whole
    numbers stay whole, decimals get 2 places, millions/billions/trillions
    are worded. The v7 debate shows the AI this rendering, requires cited
    values to match it, and checks the claim sentence for the same string —
    so the report page, the sentence, and the check all carry one number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value).strip()
    magnitude = abs(value)
    if magnitude >= 1e12:
        return f"{value / 1e12:.2f} trillion"
    if magnitude >= 1e9:
        return f"{value / 1e9:.2f} billion"
    if magnitude >= 1e6:
        return f"{value / 1e6:.2f} million"
    if float(value) == int(value):
        return str(int(value))
    return f"{value:.2f}"


def display_payload(node: Any) -> Any:
    """A payload copy with every numeric leaf replaced by its display
    string — what the v7 debate prompts show instead of raw floats."""
    if isinstance(node, dict):
        return {key: display_payload(value) for key, value in node.items()}
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return node
    return display_value(node)


def evidence_block(dimensions: Sequence[DimensionResult], display: bool = False) -> str:
    """The evidence bundle LLM stages may cite, with the ref grammar shown.

    ``display=True`` (the v7 debate) renders numeric leaves as their
    report-page display strings so the model cites what the user sees.
    """
    blocks: List[str] = []
    for dim in dimensions:
        if dim.payload:
            payload = display_payload(dim.payload) if display else dim.payload
            blocks.append(
                f"[{dim.dimension} payload — cite as \"{dim.dimension}.<key>\"]\n"
                + json.dumps(payload, ensure_ascii=False, default=str)
            )
    return "\n\n".join(blocks) if blocks else "(no evidence collected)"
