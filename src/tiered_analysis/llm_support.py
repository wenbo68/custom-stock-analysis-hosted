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

import inspect
import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel, ValidationError

from .providers.base import DimensionResult
from .run_context import RunSettings

logger = logging.getLogger(__name__)


class LlmConfigError(RuntimeError):
    """LLM configuration missing — callers surface this as a warning."""


#: Transcript rows older than this are pruned at server startup.
TRANSCRIPT_MAX_AGE_DAYS = 14

#: One transcript entry as a plain dict (the storage row's fields).
TranscriptWriter = Callable[[Dict[str, Any]], None]


class LlmTranscript:
    """Record of every LLM exchange in one run.

    One entry per call: stage, model, the full prompt and raw reply,
    token counts, duration, and the error when the call itself raised.
    Exists so a "returned no usable JSON" warning is diagnosable from
    stored evidence instead of a re-run (owner request 2026-08-25).

    Entries go through a ``writer`` — in production the run's rows in
    the ``tiered_run_transcripts`` table (``for_run``), in tests a list.
    ``discard()`` builds a transcript that counts entries and stores
    nothing (CLI runs, harnesses). Any writer failure disables the
    transcript for the rest of the run and is logged; a transcript must
    never fail an analysis (cache convention).
    """

    def __init__(self, run_id: str, writer: Optional[TranscriptWriter] = None) -> None:
        self._run_id = run_id
        self._writer = writer
        self._lock = threading.Lock()
        self._disabled = False
        self._entries = 0

    @classmethod
    def for_run(cls, run_id: str) -> "LlmTranscript":
        """The production transcript: rows keyed by the run's task id."""
        return cls(run_id, writer=_database_transcript_writer(run_id))

    @classmethod
    def discard(cls) -> "LlmTranscript":
        """Counts entries, stores nothing."""
        return cls("", writer=None)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def entries(self) -> int:
        return self._entries

    def record(
        self,
        *,
        stage: str,
        model: str,
        temperature: float,
        prompt: str,
        reply: Optional[str],
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        structured: Optional[str] = None,
    ) -> None:
        if self._disabled:
            return
        with self._lock:
            entry = {
                "task_id": self._run_id,
                "seq": self._entries + 1,
                "stage": stage,
                "model": model,
                "temperature": temperature,
                "duration_ms": duration_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                # Which reply enforcement the provider was asked for:
                # "schema" (exact shape), "json" (valid JSON, any keys),
                # or None (prompt-only).
                "structured": structured,
                "error": error,
                "prompt": prompt,
                "reply": reply,
            }
            try:
                if self._writer is not None:
                    self._writer(entry)
                self._entries += 1
            except Exception as exc:
                self._disabled = True
                logger.warning(
                    "LLM transcript write failed (%s) — transcript off for the"
                    " rest of this run",
                    exc,
                )


def _database_transcript_writer(run_id: str) -> TranscriptWriter:
    def write(entry: Dict[str, Any]) -> None:
        from src.storage import DatabaseManager, TieredRunTranscriptRecord

        with DatabaseManager.get_instance().get_session() as session:
            session.add(TieredRunTranscriptRecord(**entry))
            session.commit()

    return write


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

_UNKNOWN_STAGE = "unknown"

_active = threading.local()


class LlmUsageTracker:
    """Per-run LLM call/token counter, grouped by pipeline stage.

    The orchestrator activates one tracker for the run and opens a stage
    around each LLM-using step; ``default_summarizer`` reports into
    whichever tracker is active on the current thread. No tracker active
    (v1 call sites, tests with fake summarizers) → recording is a no-op.

    A ``transcript`` attached here rides the same activation into worker
    threads (they re-``activate()`` the tracker), so every real LLM call
    of the run lands in one file without extra plumbing.
    """

    def __init__(
        self,
        transcript: Optional[LlmTranscript] = None,
        settings: Optional[RunSettings] = None,
    ) -> None:
        self._stages: Dict[str, _StageUsage] = {}
        self._current: Optional[str] = None
        self.transcript = transcript
        #: The run's own model/keys (run_context) — rides the activation
        #: into worker threads exactly like the transcript does.
        self.settings = settings
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
                self._current or _UNKNOWN_STAGE, _StageUsage()
            )
            stage.calls += 1
            stage.prompt_tokens += int(prompt_tokens or 0)
            stage.completion_tokens += int(completion_tokens or 0)

    def current_stage(self) -> str:
        return self._current or _UNKNOWN_STAGE

    def to_detail(self) -> Dict[str, Any]:
        total = _StageUsage()
        for usage in self._stages.values():
            total.calls += usage.calls
            total.prompt_tokens += usage.prompt_tokens
            total.completion_tokens += usage.completion_tokens
        detail: Dict[str, Any] = {
            "stages": {name: u.as_dict() for name, u in self._stages.items()},
            "total": total.as_dict(),
            "scope": USAGE_SCOPE_NOTE,
        }
        # Only a transcript that actually holds entries is worth pointing
        # a reader at — zero-LLM runs (staleness stop) recorded nothing.
        if self.transcript is not None and self.transcript.entries > 0:
            detail["transcript_entries"] = self.transcript.entries
        return detail


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


def _record_transcript(
    tracker: Optional[LlmUsageTracker], **entry: Any
) -> None:
    """One transcript line via the active tracker, stage-attributed.

    No tracker or no transcript (tests, v1 call sites) → no-op, matching
    ``record_llm_usage``.
    """
    if tracker is None or tracker.transcript is None:
        return
    tracker.transcript.record(stage=tracker.current_stage(), **entry)


#: Schema sentinel for reply shapes whose KEYS are decided at run time
#: (the debate's one-vote-per-bullet-id forms): the provider is asked to
#: guarantee syntactically valid JSON, but the exact keys stay a
#: pydantic-and-retry concern — no portable decode-time schema can name
#: keys that don't exist until the run.
JSON_REPLY = "json"


def _response_format_for(resolved: str, schema: Any) -> Optional[Any]:
    """Translate a caller's expected-reply schema into litellm's
    ``response_format`` — or None when this model can't enforce it.

    ``schema`` is a pydantic model class (the provider then only
    generates JSON matching that exact shape) or ``JSON_REPLY`` (the
    provider guarantees valid JSON, any keys). Any doubt — unknown
    model, capability-lookup error — degrades to None: the prompt still
    asks for JSON, exactly the pre-enforcement behavior.
    """
    import litellm

    try:
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            if litellm.supports_response_schema(model=resolved):
                return schema
            schema = JSON_REPLY  # model can't take a schema; plain JSON mode
        if schema == JSON_REPLY:
            supported = litellm.get_supported_openai_params(model=resolved)
            if supported and "response_format" in supported:
                return {"type": "json_object"}
    except Exception:
        return None
    return None


def _summarize(
    prompt: str,
    temperature: float,
    model: Optional[str] = None,
    schema: Any = None,
) -> str:
    from .run_context import llm_api_key, llm_model

    resolved = (model or llm_model() or "").strip()
    if not resolved:
        raise LlmConfigError(
            "no LLM model configured: the run carries none and "
            "LITELLM_MODEL is not set"
        )
    # The run's own key (a signed-in user's) goes to litellm explicitly;
    # without one litellm reads the provider's standard variable.
    api_key = llm_api_key()
    import litellm

    response_format = (
        _response_format_for(resolved, schema) if schema is not None else None
    )
    enforcement: Optional[str] = None
    if response_format is not None:
        enforcement = (
            "schema" if isinstance(response_format, type) else "json"
        )

    tracker = active_tracker()
    started = time.monotonic()

    def _call(fmt: Optional[Any]) -> Any:
        kwargs: Dict[str, Any] = {}
        if fmt is not None:
            kwargs["response_format"] = fmt
        if api_key:
            kwargs["api_key"] = api_key
        return litellm.completion(
            model=resolved,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            **kwargs,
        )

    try:
        try:
            response = _call(response_format)
        except Exception as exc:
            # A provider that rejects the enforcement request itself
            # (HTTP 400) gets one plain call — enforcement is an
            # upgrade and must never break what worked before it.
            if (
                response_format is not None
                and type(exc).__name__ == "BadRequestError"
            ):
                logger.warning(
                    "structured output rejected by %s (%s) — retrying "
                    "without enforcement",
                    resolved,
                    exc,
                )
                enforcement = None
                response = _call(None)
            else:
                raise
    except Exception as exc:
        # The failed exchange is exactly what a transcript exists for.
        _record_transcript(
            tracker,
            model=resolved,
            temperature=temperature,
            prompt=prompt,
            reply=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=repr(exc),
            structured=enforcement,
        )
        raise
    usage = getattr(response, "usage", None)
    record_llm_usage(
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )
    raw = response.choices[0].message.content or ""
    _record_transcript(
        tracker,
        model=resolved,
        temperature=temperature,
        prompt=prompt,
        reply=raw,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        duration_ms=int((time.monotonic() - started) * 1000),
        structured=enforcement,
    )
    return raw


def default_summarizer(prompt: str, schema: Any = None) -> str:
    # Temperature 0 everywhere (owner decision 2026-08-23): every LLM
    # stage of a run should repeat as closely as the API allows.
    return _summarize(prompt, temperature=0.0, schema=schema)


def screen_summarizer(prompt: str, schema: Any = None) -> str:
    """Summarizer for the news screen's classification chores.

    A faster, cheaper model — screening is is-this-about-the-company
    bookkeeping, not analysis: the run's own sub model, else its main
    model, else the server's ``NEWS_SCREEN_MODEL``; None falls through
    to the standard ``LITELLM_MODEL`` so unconfigured keeps working.
    See ``run_context.llm_sub_model``. Temperature 0 like every stage.
    """
    from .run_context import llm_sub_model

    return _summarize(prompt, temperature=0.0, model=llm_sub_model(), schema=schema)


def deterministic_summarizer(prompt: str, schema: Any = None) -> str:
    """Zero-temperature summarizer: the scored tier-2 debate uses it so the
    same evidence grades the same way on every run."""
    return _summarize(prompt, temperature=0.0, schema=schema)


def summarize_with_schema(
    summarize: Callable[..., str], prompt: str, schema: Any
) -> str:
    """Call a summarizer, passing the expected reply schema when it
    accepts one.

    The package's real summarizers take ``schema`` and turn it into
    provider-enforced structured output; injected plain ``(prompt)``
    callables (test fakes, older seams) are called the old way — the
    schema is an upgrade, never a new requirement on the seam.
    """
    if schema is not None:
        try:
            parameters = inspect.signature(summarize).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "schema" in parameters or any(
            p.kind is inspect.Parameter.VAR_KEYWORD
            for p in parameters.values()
        ):
            return summarize(prompt, schema=schema)
    return summarize(prompt)


@dataclass
class StructuredReply:
    """Outcome of one schema-checked LLM request (with one retry)."""

    #: The LAST reply parsed to a dict — None when it wasn't JSON at
    #: all. Handed back even when invalid so callers' tolerant salvage
    #: paths still see whatever came back.
    parsed: Optional[dict]
    #: Whether the last reply passed the pydantic form.
    valid: bool
    #: Whether a second call was made.
    retried: bool
    #: Why the last invalid reply was rejected (None when valid).
    problem: Optional[str]


_STRUCTURED_RETRY_TEMPLATE = (
    "{prompt}\n\nYour previous reply was invalid: {problem}\n"
    "Reply again, following the JSON shape exactly. JSON only."
)


def _validation_problem(exc: ValidationError) -> str:
    """A short retry-friendly reading of a pydantic failure."""
    parts = []
    for error in exc.errors()[:3]:
        where = ".".join(str(piece) for piece in error.get("loc", ()))
        parts.append(f"{where or 'reply'}: {error.get('msg', 'invalid')}")
    return "; ".join(parts) or "reply failed validation"


def request_structured(
    summarize: Callable[..., str],
    prompt: str,
    reply_model: Type[BaseModel],
) -> StructuredReply:
    """One LLM call validated against a pydantic form, with ONE retry
    that shows the model what was wrong (the debate's convention — at
    temperature 0 a bare re-ask would reproduce the same reply).

    Belt and suspenders: the provider is asked to ENFORCE the shape
    while generating (``summarize_with_schema``, when the model supports
    it) and the reply is CHECKED here regardless — a reply that fails
    the form triggers the retry. Exceptions from the call itself
    propagate unretried: transport failures keep their existing
    per-caller fallbacks.
    """
    attempt_prompt = prompt
    parsed: Optional[dict] = None
    problem: Optional[str] = None
    for attempt in range(2):
        raw = summarize_with_schema(summarize, attempt_prompt, reply_model)
        parsed = parse_llm_json(raw)
        if parsed is None:
            problem = "the reply was not a JSON object"
        else:
            try:
                reply_model.model_validate(parsed)
                return StructuredReply(
                    parsed=parsed,
                    valid=True,
                    retried=attempt > 0,
                    problem=None,
                )
            except ValidationError as exc:
                problem = _validation_problem(exc)
        attempt_prompt = _STRUCTURED_RETRY_TEMPLATE.format(
            prompt=prompt, problem=problem
        )
    return StructuredReply(
        parsed=parsed, valid=False, retried=True, problem=problem
    )


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
