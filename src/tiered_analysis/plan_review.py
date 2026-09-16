# -*- coding: utf-8 -*-
"""AI plan review (owner redesign 2026-07-22; check-adjust cycle same day).

The old display-only risk card is gone; its deterministic checks now do
something:

- **Adjustable checks** — liquidity (order > 5% of the average daily
  volume), volatility (typical daily swing > 4% of price) and
  stop-vs-support (stop resting at/above the nearest pivot low) feed an
  LLM call that may adjust the plan: trim the share count, move the
  stop, move the target. Every accepted adjustment carries a
  code-validated, link-cited reason (the same citation contract as the
  tier-2 debate).
- **The cycle** — an adjusted plan can trip a check the computed plan
  did not (a tightened stop raises the mechanical share count past the
  liquidity limit), so the PLAN-DEPENDENT checks (liquidity, stop vs
  support) re-run after every adjustment round, up to
  ``MAX_ADJUST_ROUNDS`` rounds. Volatility depends only on report data —
  no adjustment can change it — so it fires in round 1 as context and
  never counts against convergence. Converged (no plan-dependent check
  fires) → the cumulative adjustments stand. Not converged → every
  adjustment is discarded, the computed plan stands, and
  ``levels_detail["review_failures"]`` records what failed per round.
- **Warning checks** — the two overnight-gap scenarios and a
  reward-to-risk shortfall become structured per-column warnings on the
  trade-plan card. The backend ships numbers only; the frontend words
  them.

Everything degrades loudly: no LLM, unparseable reply, invalid links →
the computed plan stands and a warning says why.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from pydantic import BaseModel, Field

from .debate import (
    _NUMERIC_REASON_RE,
    _link_value_text,
    _payload_value,
    _value_in_text,
    _values_equal,
    value_pattern,
)
from .earnings import EARNINGS_WARNING_DAYS, EarningsInfo, earnings_from_dimensions
from .levels import (
    LEVEL_KEYS,
    AdjustmentProposal,
    BaseLevels,
    apply_adjustments,
    decisions_to_detail,
    decisions_to_sniper,
)
from .llm_support import (
    LlmConfigError,
    default_summarizer,
    display_value,
    evidence_block,
    parse_llm_json,
    summarize_with_schema,
)
from .providers.base import DimensionResult, Market
from .providers.technicals import read_label, read_metric
from .schema import (
    DEFAULT_HOLD_WEEKS,
    REWARD_GOAL_EPS,
    Direction,
    SizingSlots,
    SniperLevels,
    hold_weeks_text,
    reward_ratio,
)
from .settings import SizingSettings
from .sizing import SizingInputs, SizingResult, size_position

logger = logging.getLogger(__name__)

#: Order larger than this share of average daily volume is hard to exit
#: in one day without moving the price → the AI trims the share count.
ADV_FLAG_FRACTION = 0.05
#: Typical daily swing above this % of price → the AI reviews shares,
#: stop and target together.
VOLATILITY_FLAG_PCT = 4.0
#: How far past the stop the ATR gap scenario assumes the open lands.
GAP_ATR_MULTIPLE = 1.0

#: Adjustable targets the LLM may propose (the entry is formula-owned).
_ADJUSTABLE = ("stop_loss", "take_profit", "shares")

#: Checks whose condition depends on the plan itself (share count, stop
#: placement). Only these re-run each round and define convergence —
#: volatility depends on report data alone, so demanding it clear would
#: make every volatile stock fail all rounds and revert.
#: (v2 renamed stop_vs_swing_low → stop_vs_support: the reference level
#: is the nearest pivot low now, not the 20-day extreme. Stored runs
#: still carry the old id; the web words both.)
_PLAN_DEPENDENT_CHECKS = ("liquidity", "stop_vs_support")

#: Adjustment rounds the AI gets before the computed plan stands.
MAX_ADJUST_ROUNDS = 3


@dataclass(frozen=True)
class PlanReview:
    """Everything the review produced, ready for the run outcome."""

    levels: SniperLevels
    levels_detail: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    #: Structured per-column warnings for the trade-plan card:
    #: {"entry"|"stop_loss"|"take_profit"|"shares": [{"id", "values"}]}.
    plan_warnings: Optional[Dict[str, List[Dict[str, Any]]]] = None
    sizing_detail: Optional[Dict[str, Any]] = None
    sizing_slots: SizingSlots = field(default_factory=SizingSlots)


def _tech_payload(dimensions: Sequence[DimensionResult]) -> Dict[str, Any]:
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            return dim.payload
    return {}


def _size(
    levels: SniperLevels,
    direction: Direction,
    market: Market,
    settings: SizingSettings,
) -> Tuple[SizingInputs, SizingResult]:
    inputs = SizingInputs(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        entry=levels.entry,
        stop_loss=levels.stop_loss,
        direction=direction,
        market=market,
    )
    return inputs, size_position(inputs)


def sizing_detail_dict(
    settings: SizingSettings,
    result: SizingResult,
    levels: SniperLevels,
    shares: Optional[int] = None,
    risk_amount: Optional[float] = None,
    extra_notes: Sequence[str] = (),
) -> Dict[str, Any]:
    """The JSON sizing block; ``shares``/``risk_amount`` override the
    engine's numbers when the AI trimmed the count."""
    final_shares = result.shares if shares is None else shares
    final_risk = result.risk_amount if risk_amount is None else risk_amount
    position_value = (
        final_shares * levels.entry
        if final_shares is not None and levels.entry is not None
        else result.position_value
    )
    return {
        "enabled": settings.is_enabled,
        "shares": final_shares,
        "position_value": position_value,
        "risk_amount": final_risk,
        "loss_per_share": result.loss_per_share,
        "lot_size": result.lot_size,
        "reason_code": result.reason_code.value if result.reason_code else None,
        "refusal_reason": result.refusal_reason,
        "notes": list(result.notes) + list(settings.warnings) + list(extra_notes),
        "inputs": {
            "capital": settings.capital,
            "risk_fraction": settings.risk_fraction,
            "reward_risk": settings.reward_risk,
            "entry": levels.entry,
            "stop_loss": levels.stop_loss,
        },
    }


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Check:
    """One flagged deterministic check, phrased for the LLM prompt."""

    name: str
    text: str


def _flagged_checks(
    tech: Dict[str, Any],
    levels: SniperLevels,
    shares: Optional[int],
) -> List[_Check]:
    checks: List[_Check] = []
    stop = levels.stop_loss
    avg_volume = read_metric(tech, "volume", "avg_vol_60d")
    volatility = read_metric(tech, "volatility", "atr_pct")
    support = read_metric(tech, "levels", "support_1")
    close = read_metric(tech, "price", "close")
    sma_50 = read_metric(tech, "daily", "sma_50")

    if close is not None and sma_50 is not None and close <= sma_50:
        # Report-data check like volatility: it can never clear through
        # plan changes, so it must not join _PLAN_DEPENDENT_CHECKS.
        checks.append(_Check(
            "downtrend",
            f"the close ({display_value(close)}) is at or below the 50-day "
            f"average ({display_value(sma_50)}) — a counter-trend entry; "
            "review the stop, the target and the share count together and "
            "tighten what the downtrend threatens",
        ))
    if shares and avg_volume:
        fraction = shares / avg_volume
        if fraction > ADV_FLAG_FRACTION:
            checks.append(_Check(
                "liquidity",
                f"the planned {shares} shares are "
                f"{fraction * 100:.1f}% of the average daily volume "
                f"({display_value(avg_volume)}), above the "
                f"{ADV_FLAG_FRACTION:.0%} limit — propose a reduced "
                '"shares" so the order can exit in one day',
            ))
    if volatility is not None and volatility > VOLATILITY_FLAG_PCT:
        checks.append(_Check(
            "volatility",
            f"the typical daily swing is {display_value(volatility)}% of the "
            f"price (technicals.volatility.atr_pct), above the "
            f"{VOLATILITY_FLAG_PCT:g}% limit — review the share count, the "
            "stop and the target together and adjust what the volatility "
            "actually threatens",
        ))
    if stop is not None and support is not None and stop >= support:
        checks.append(_Check(
            "stop_vs_support",
            f"the stop {display_value(stop)} rests at or above the nearest "
            f"pivot support ({display_value(support)}), where a routine "
            'retest would trigger it — propose a "stop_loss" below that '
            "support level",
        ))
    return checks


#: The three scheduled market-wide events the macro report carries,
#: (payload key in macro_econ.events, warning "event" tag).
MACRO_EVENT_KEYS = (
    ("next_rate_decision_date", "rate_decision"),
    ("next_cpi_release_date", "inflation_data"),
    ("next_jobs_release_date", "employment_data"),
)


def macro_event_from_dimensions(
    dimensions: Sequence[DimensionResult],
    today: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """The soonest scheduled macro event inside the warning window.

    A Fed decision / CPI print / jobs report inside the hold window is
    market-wide gap risk the way earnings is single-stock gap risk; it
    reuses EARNINGS_WARNING_DAYS (owner decision, TODO.md hold-window
    note). Returns {"event", "next_date", "days_until"} or None.
    """
    import datetime as _dt

    payload = next(
        (dim.payload for dim in dimensions
         if dim.dimension == "macro_econ" and dim.payload),
        None,
    )
    if payload is None:
        return None
    if today is None:
        today = _dt.date.today()
    best: Optional[Dict[str, Any]] = None
    for key, event in MACRO_EVENT_KEYS:
        date_str = read_label(payload, "events", key)
        if not date_str:
            continue
        try:
            event_date = _dt.date.fromisoformat(date_str[:10])
        except ValueError:
            continue
        days = (event_date - today).days
        if 0 <= days <= EARNINGS_WARNING_DAYS and (
            best is None or days < best["days_until"]
        ):
            best = {"event": event, "next_date": date_str, "days_until": days}
    return best


def build_plan_warnings(
    tech: Dict[str, Any],
    levels: SniperLevels,
    shares: Optional[int],
    risk_amount: Optional[float],
    reward_goal: float,
    earnings: Optional[EarningsInfo] = None,
    macro_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """The structured per-column warnings (numbers only, no wording)."""
    warnings: Dict[str, List[Dict[str, Any]]] = {
        "entry": [], "stop_loss": [], "take_profit": [], "shares": [],
    }
    entry, stop, target = levels.entry, levels.stop_loss, levels.take_profit
    atr = read_metric(tech, "volatility", "atr_14")
    worst_day_pct = read_metric(tech, "volatility", "worst_day_pct_1y")
    close = read_metric(tech, "price", "close")
    sma_50 = read_metric(tech, "daily", "sma_50")

    if entry is not None and close is not None and sma_50 is not None \
            and close <= sma_50:
        warnings["entry"].append({
            "id": "downtrend",
            "values": {"close": close, "sma_50": sma_50},
        })

    # Earnings gate (2026-07-27, closing the gap the spec review found):
    # a plan whose hold window straddles the next report gets a
    # code-computed warning — technicals do not survive earnings. A
    # warning, not a refusal, consistent with every other plan check
    # (the warning row carries the judgment, the user decides).
    if entry is not None and earnings is not None and earnings.is_near:
        warnings["entry"].append({
            "id": "earnings_soon",
            "values": {
                "days_until": earnings.days_until,
                "next_date": earnings.next_date,
                "warning_days": EARNINGS_WARNING_DAYS,
            },
        })

    # Macro-event gate: the market-wide mirror of the earnings gate — a
    # rate decision / CPI print / jobs report inside the hold window is
    # gap risk for every stock, same warning-not-refusal contract.
    if entry is not None and macro_event is not None:
        warnings["entry"].append({
            "id": "macro_event_soon",
            "values": {
                **macro_event,
                "warning_days": EARNINGS_WARNING_DAYS,
            },
        })

    sized = shares is not None and shares > 0
    if sized and entry is not None and stop is not None and atr:
        atr_open = stop - GAP_ATR_MULTIPLE * atr
        atr_loss = shares * (entry - atr_open)
        warnings["stop_loss"].append({
            "id": "gap_atr",
            "values": {
                "entry": entry, "stop_loss": stop, "shares": shares,
                "atr_14": atr, "gap_atr_multiple": GAP_ATR_MULTIPLE,
                "atr_open": atr_open, "atr_loss": atr_loss,
                "loss_at_stop": risk_amount,
                "atr_extra": (
                    atr_loss - risk_amount if risk_amount is not None else None
                ),
            },
        })
        if worst_day_pct is not None:
            # worst_day_pct_1y is a PERCENT (-16.97), not a fraction — it
            # is divided by 100 before it multiplies a price.
            worst_open = entry * (1.0 + worst_day_pct / 100.0)
            if worst_open < stop:
                worst_loss = shares * (entry - worst_open)
                warnings["stop_loss"].append({
                    "id": "gap_worst",
                    "values": {
                        "entry": entry, "stop_loss": stop, "shares": shares,
                        "worst_day_pct": worst_day_pct,
                        "worst_open": worst_open,
                        "worst_loss": worst_loss,
                        "loss_at_stop": risk_amount,
                        "worst_extra": (
                            worst_loss - risk_amount
                            if risk_amount is not None else None
                        ),
                    },
                })
    ratio = reward_ratio(levels)
    if ratio is not None:
        if ratio < reward_goal - REWARD_GOAL_EPS:
            warnings["take_profit"].append({
                "id": "reward_below_goal",
                "values": {
                    "entry": entry, "stop_loss": stop, "take_profit": target,
                    "ratio": ratio, "goal": reward_goal,
                },
            })
    return warnings


# ---------------------------------------------------------------------------
# The LLM adjustment call
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """You are the risk reviewer of a swing-trade BUY plan for {symbol}.
The position will be held for up to {hold_text} (the user's chosen max
hold time) — judge every risk against that horizon.

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

The computed plan (deterministic formulas):
- entry = {entry} ({entry_formula})
- stop_loss = {stop_loss} ({stop_formula})
- take_profit = {take_profit} ({target_formula})
- shares = {base_shares} (capital × risk fraction ÷ (entry − stop_loss))
{round_note}
Deterministic checks flagged these problems:
{checks}

Propose adjustments that fix ONLY the flagged problems. Rules (all
checked mechanically by code):
- Reply with JSON only:
  {{"adjustments": [{{"target": "stop_loss" | "take_profit" | "shares",
    "value": <number>,
    "reasons": [{{"check": "<flagged check name>",
      "text": "<one sentence>",
      "links": [{{"ref": "technicals.volatility.atr_pct", "value": "4.3"}}]}}]}}]}}
- At most one adjustment per target. An empty list is a valid answer if
  no change genuinely helps.
- Each reasons entry explains ONE flagged problem this adjustment fixes:
  "check" is that problem's name copied exactly from the flagged list
  above; "text" is one plain sentence. One entry per flagged problem —
  never invent a check name, never repeat one within an adjustment.
- "shares" may only go DOWN from {trim_baseline}.
- A price move must stay within 1 ATR ({atr}) of its computed value, and
  keep stop_loss < entry < take_profit.
- Each text must state every report number it relies on EXACTLY as the
  report above displays it, each cited in that entry's "links" with
  {{"ref": the leaf field, "value": the displayed value}}. Plain
  sentences only — never paste refs or link JSON into the text.
- Never point at a report metric by name alone: write its name AND its
  displayed value, cited in "links" (e.g. "the one-year high (461.62)").
  Do not state numbers you cannot cite — the only uncited numbers
  allowed are your proposed value, that target's computed value, and
  the thresholds quoted in the flagged checks. No market lore that the
  report does not carry."""

_FIX_TEMPLATE = """{prompt}

Your previous reply had citation problems that code could not verify:
{errors}

Send the corrected JSON (same shape). Fix every listed problem: point
each ref at the right leaf field, copy the value exactly as the report
displays it, and make sure the reason text contains that value."""


#: Number tokens a reason is accountable for: decimals, percentages, and
#: integers of 3+ digits. One- and two-digit integers are grammar
#: ("2-day", "the 52-week high", "20-day low"), not report values.
_REASON_NUMBER_RE = re.compile(r"\d+\.\d+\s?%?|\d+(?:\.\d+)?\s?%|\d{3,}")

#: Numbers the flagged-check texts quote as fixed rules — restating a
#: threshold needs no citation (there is no report row for it).
_THRESHOLD_DISPLAYS = (
    f"{ADV_FLAG_FRACTION:.0%}",
    f"{VOLATILITY_FLAG_PCT:g}%",
)


def _uncited_number_errors(
    text: str,
    where: str,
    allowed_values: Sequence[str],
) -> List[str]:
    """Every number the reason states must be accounted for: a cited link
    value, the adjustment's own value or base, or a check threshold.
    Naming a metric without its cited number is what this kills — the
    reader must get the name AND the value, and the value must jump to
    its source row."""
    remainder = text
    for allowed in allowed_values:
        if allowed and any(char.isdigit() for char in allowed):
            remainder = value_pattern(allowed).sub(" ", remainder)
    return [
        f"{where}: the number {token!r} has no citation — every report "
        "value must be written exactly as the report displays it and "
        "cited in links; the only uncited numbers allowed are this "
        "adjustment's own value, its computed base, and the flagged "
        "thresholds"
        for token in _REASON_NUMBER_RE.findall(remainder)
    ]


def _link_errors(
    links: Sequence[Dict[str, Any]],
    sentence: str,
    where: str,
    dimensions: Sequence[DimensionResult],
) -> List[str]:
    errors: List[str] = []
    for link in links:
        ref = str(link.get("ref", "")).strip()
        if not ref:
            errors.append(f"{where}: link without a ref")
            continue
        resolves, actual = _payload_value(ref, dimensions)
        if not resolves:
            errors.append(
                f"{where} link {ref!r}: does not resolve to a single report value"
            )
            continue
        expected = display_value(actual)
        claimed = _link_value_text(link.get("value"))
        if not _values_equal(claimed, expected):
            errors.append(
                f"{where} link {ref!r}: claimed value {claimed!r} must be "
                f"copied exactly as the report displays it: {expected!r}"
            )
            continue
        if not _value_in_text(expected, sentence):
            errors.append(
                f"{where} link {ref!r}: the value {expected!r} must appear "
                "in the reason exactly as the report displays it"
            )
    if _NUMERIC_REASON_RE.search(sentence) and not links:
        errors.append(f"{where}: the reason states a number — cite it with a link")
    return errors


def _parse_reasons(
    item: Dict[str, Any],
    where: str,
    allowed_checks: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """One adjustment's reasons list: [{check, text, links}] validated
    against the flagged check names (the UI's deterministic keywords)."""
    raw = item.get("reasons")
    if not isinstance(raw, list) or not raw:
        return [], [f'{where}: a non-empty "reasons" list is required']
    reasons: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen_checks: set = set()
    for index, entry in enumerate(raw):
        entry_where = f"{where} reason {index + 1}"
        if not isinstance(entry, dict):
            errors.append(f"{entry_where}: not an object")
            continue
        check = str(entry.get("check", "")).strip()
        if check not in allowed_checks:
            errors.append(
                f"{entry_where}: check must be one of the flagged names "
                f"({', '.join(allowed_checks)})"
            )
            continue
        if check in seen_checks:
            errors.append(f"{entry_where}: duplicate check {check!r}")
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            errors.append(f"{entry_where}: text is required")
            continue
        links = entry.get("links")
        links = (
            [link for link in links if isinstance(link, dict)]
            if isinstance(links, list)
            else []
        )
        seen_checks.add(check)
        reasons.append({"check": check, "text": text, "links": links})
    return reasons, errors


# Reply form (2026-08-25, owner request): the exact JSON shape the
# review asks for, handed to the provider for decode-time enforcement
# (structured output mode, on models that support it). The stricter
# content checks below — allowed targets, citation links, the fix
# round — stay the validators; this form only pins the wire shape.
class _PlanLinkForm(BaseModel):
    """One citation: ``{"ref": "...", "value": ...}``."""

    ref: str
    value: Union[float, str, None] = None


class _PlanReasonForm(BaseModel):
    check: str
    text: str
    links: List[_PlanLinkForm] = Field(default_factory=list)


class _PlanAdjustmentForm(BaseModel):
    # Mirrors _ADJUSTABLE — Literal needs the strings spelled out.
    target: Literal["stop_loss", "take_profit", "shares"]
    value: float
    reasons: List[_PlanReasonForm] = Field(default_factory=list)


class _PlanReplyForm(BaseModel):
    """``{"adjustments": [...]}`` — empty list means "no change helps"."""

    adjustments: List[_PlanAdjustmentForm] = Field(default_factory=list)


def _parse_adjustments(
    parsed: Optional[dict],
    allowed_checks: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(usable adjustment dicts, shape errors)."""
    if parsed is None:
        return [], ["reply was not valid JSON"]
    raw = parsed.get("adjustments")
    if not isinstance(raw, list):
        return [], ['reply carries no "adjustments" list']
    usable: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set = set()
    for index, item in enumerate(raw):
        where = f"adjustment {index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{where}: not an object")
            continue
        target = str(item.get("target", "")).strip()
        if target not in _ADJUSTABLE:
            errors.append(
                f"{where}: target must be one of {', '.join(_ADJUSTABLE)}"
            )
            continue
        if target in seen:
            errors.append(f"{where}: duplicate target {target!r}")
            continue
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{where}: value must be a number")
            continue
        reasons, reason_errors = _parse_reasons(item, where, allowed_checks)
        if reason_errors:
            errors.extend(reason_errors)
            continue
        seen.add(target)
        usable.append({
            "target": target, "value": float(value), "reasons": reasons,
        })
    return usable, errors


def _request_adjustments(
    symbol: str,
    dimensions: Sequence[DimensionResult],
    bases: BaseLevels,
    base_shares: Optional[int],
    trim_baseline: Optional[int],
    checks: Sequence[_Check],
    atr: Optional[float],
    summarizer: Callable[[str], str],
    round_note: str = "",
    extra_allowed: Sequence[str] = (),
    hold_weeks: int = DEFAULT_HOLD_WEEKS,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """One call + one fix round; returns (adjustments, warnings).

    ``trim_baseline`` is the current round's mechanical share count (the
    reduction-only floor for a shares proposal); ``round_note`` describes
    the current plan on rounds after the first; ``extra_allowed`` lists
    displayed values (the current plan's numbers) a reason may state
    without a citation — they have no report row to link to.
    """

    def basis(key: str) -> Tuple[str, str]:
        b = bases.get(key)
        return (
            (display_value(b.value), b.formula) if b is not None else ("—", "no base")
        )

    entry_v, entry_f = basis("entry")
    stop_v, stop_f = basis("stop_loss")
    target_v, target_f = basis("take_profit")
    prompt = _PROMPT_TEMPLATE.format(
        symbol=symbol,
        hold_text=hold_weeks_text(hold_weeks),
        evidence=evidence_block(dimensions, display=True),
        entry=entry_v, entry_formula=entry_f,
        stop_loss=stop_v, stop_formula=stop_f,
        take_profit=target_v, target_formula=target_f,
        base_shares=base_shares if base_shares is not None else "—",
        trim_baseline=trim_baseline if trim_baseline is not None else "—",
        round_note=round_note,
        checks="\n".join(f"- {check.name}: {check.text}" for check in checks),
        atr=display_value(atr) if atr is not None else "—",
    )

    allowed_checks = [check.name for check in checks]
    base_displays = {
        "stop_loss": stop_v, "take_profit": target_v,
        "shares": (
            display_value(trim_baseline) if trim_baseline is not None else "—"
        ),
    }

    def reason_link_errors(adjustment: Dict[str, Any]) -> List[str]:
        target = adjustment["target"]
        allowed_always = [
            display_value(adjustment["value"]),
            base_displays.get(target, "—"),
            *_THRESHOLD_DISPLAYS,
            *extra_allowed,
        ]
        problems: List[str] = []
        for reason in adjustment["reasons"]:
            where = f'adjustment "{target}" ({reason["check"]})'
            problems.extend(_link_errors(
                reason["links"], reason["text"], where, dimensions,
            ))
            cited = [
                _link_value_text(link.get("value"))
                for link in reason["links"]
                if link.get("value") is not None
            ]
            problems.extend(_uncited_number_errors(
                reason["text"], where, cited + allowed_always,
            ))
        return problems

    warnings: List[str] = []
    adjustments, errors = _parse_adjustments(
        parse_llm_json(summarize_with_schema(summarizer, prompt, _PlanReplyForm)),
        allowed_checks,
    )
    for adjustment in adjustments:
        errors.extend(reason_link_errors(adjustment))
    if errors:
        fix_prompt = _FIX_TEMPLATE.format(
            prompt=prompt, errors="\n".join(f"- {error}" for error in errors)
        )
        adjustments, errors = _parse_adjustments(
            parse_llm_json(
                summarize_with_schema(summarizer, fix_prompt, _PlanReplyForm)
            ),
            allowed_checks,
        )
        kept: List[Dict[str, Any]] = []
        for adjustment in adjustments:
            link_problems = reason_link_errors(adjustment)
            if link_problems:
                warnings.append(
                    f"plan-review adjustment for {adjustment['target']} dropped "
                    f"— citations unfixable: {'; '.join(link_problems)}"
                )
            else:
                kept.append(adjustment)
        adjustments = kept
        warnings.extend(
            f"plan-review reply problem: {error}" for error in errors
        )
    return adjustments, warnings


# ---------------------------------------------------------------------------
# The whole review
# ---------------------------------------------------------------------------


def _shares_detail(
    base_inputs: SizingInputs,
    base_result: SizingResult,
    final_inputs: SizingInputs,
    final_result: SizingResult,
    ai_shares: Optional[int],
    ai_reasons: Sequence[Dict[str, Any]],
    rejection: Optional[str],
) -> Dict[str, Any]:
    """The trade-plan card's shares column, in the level-detail shape.

    base = the count from the computed levels; adjusted = what the run
    actually uses when that changed (levels moved and/or the AI trimmed
    it). Every adjusted count also ships ``adjusted_inputs`` (the final
    levels the mechanical recompute used) and ``mechanical`` (the count
    that recompute produced, before any AI trim) so the frontend can
    always open with the arithmetic receipt (owner decision 2026-07-22).
    """
    base = base_result.shares
    final = ai_shares if ai_shares is not None else final_result.shares
    adjusted = final if final is not None and final != base else None
    detail: Dict[str, Any] = {
        "base": base,
        "formula": (
            "capital × risk_fraction ÷ (entry − stop_loss)"
            if base is not None else None
        ),
        "inputs": {
            "capital": base_inputs.capital,
            "risk_fraction": base_inputs.risk_fraction,
            "entry": base_inputs.entry,
            "stop_loss": base_inputs.stop_loss,
        } if base is not None else None,
        "adjusted": adjusted,
        "reasons": (
            [dict(reason) for reason in ai_reasons]
            if adjusted is not None else []
        ),
        "evidence": [],
        "rejection": rejection,
        "final": final,
    }
    if adjusted is not None:
        detail["adjusted_inputs"] = {
            "capital": final_inputs.capital,
            "risk_fraction": final_inputs.risk_fraction,
            "entry": final_inputs.entry,
            "stop_loss": final_inputs.stop_loss,
        }
        detail["mechanical"] = final_result.shares
    return detail


@dataclass(frozen=True)
class _RoundPlan:
    """One round's fully-evaluated plan: cumulative adjustments applied
    to the bases, mechanical share recompute, AI trim verdict."""

    decisions: Dict[str, Any]
    adjust_warnings: List[str]
    levels: SniperLevels
    inputs: SizingInputs
    result: SizingResult
    ai_shares: Optional[int]
    ai_reasons: Tuple[Dict[str, Any], ...]
    shares_rejection: Optional[str]

    @property
    def shares(self) -> Optional[int]:
        return self.ai_shares if self.ai_shares is not None else self.result.shares


def _merge_proposals(
    merged: Dict[str, Dict[str, Any]],
    adjustments: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Fold one round's adjustments into the cumulative set (new dict).

    A later round's value replaces the earlier one for the same target;
    reasons merge — an earlier reason survives unless the new round
    re-explains the same check (one bullet per check in the UI).
    """
    combined = dict(merged)
    for adjustment in adjustments:
        target = adjustment["target"]
        reasons = list(adjustment["reasons"])
        previous = combined.get(target)
        if previous is not None:
            fresh_checks = {reason["check"] for reason in reasons}
            reasons = [
                reason for reason in previous["reasons"]
                if reason["check"] not in fresh_checks
            ] + reasons
        combined[target] = {"value": adjustment["value"], "reasons": reasons}
    return combined


def review_plan(
    symbol: str,
    dimensions: Sequence[DimensionResult],
    bases: BaseLevels,
    direction: Direction,
    market: Market,
    settings: SizingSettings,
    summarizer: Optional[Callable[[str], str]] = None,
    hold_weeks: int = DEFAULT_HOLD_WEEKS,
) -> PlanReview:
    """Run the check-adjust cycle and produce the final plan block.

    Only called for BUY verdicts (there is nothing to size or adjust on
    a hold/sell). Up to ``MAX_ADJUST_ROUNDS`` rounds: flag → the AI
    adjusts → the plan-dependent checks re-run on the adjusted plan.
    Converged (no plan-dependent check fires) → the cumulative
    adjustments stand. Not converged (a check still fires after the last
    round, or the AI answers "no change helps" while one fires) → every
    adjustment is discarded, the computed plan stands, and
    ``levels_detail["review_failures"]`` lists what failed per round.
    LLM outages keep the computed plan with a warning, as before.
    """
    tech = _tech_payload(dimensions)
    atr = read_metric(tech, "volatility", "atr_14")
    earnings = earnings_from_dimensions(dimensions)
    warnings: List[str] = []

    # The computed plan: base levels, base share count.
    base_decisions, base_adj_warnings = apply_adjustments(bases, [], atr=atr)
    warnings.extend(base_adj_warnings)
    base_levels = decisions_to_sniper(base_decisions)
    base_inputs, base_result = _size(base_levels, direction, market, settings)

    def evaluate(merged: Dict[str, Dict[str, Any]]) -> _RoundPlan:
        """Apply the cumulative proposals to the bases and size the result."""
        price_proposals = [
            AdjustmentProposal(
                level=key, value=item["value"], reasons=tuple(item["reasons"]),
            )
            for key, item in merged.items()
            if key in LEVEL_KEYS
        ]
        decisions, adjust_warnings = apply_adjustments(
            bases, price_proposals, atr=atr
        )
        levels = decisions_to_sniper(decisions)
        inputs, result = _size(levels, direction, market, settings)

        # The AI's share trim: reductions only (vs this round's mechanical
        # recompute), floored to the lot size.
        ai_shares: Optional[int] = None
        ai_reasons: Tuple[Dict[str, Any], ...] = ()
        rejection: Optional[str] = None
        proposal = merged.get("shares")
        if proposal is not None:
            lot = result.lot_size
            proposed = int(math.floor(proposal["value"] / lot)) * lot
            mechanical = result.shares
            if mechanical is None:
                rejection = "no computed share count exists to adjust"
            elif proposed <= 0:
                rejection = (
                    f"proposed count {proposal['value']:g} rounds down to "
                    "zero — a trim cannot erase the position"
                )
            elif proposed >= mechanical:
                rejection = (
                    f"proposed count {proposed} is not below the computed "
                    f"{mechanical} — shares may only be trimmed"
                )
            else:
                ai_shares = proposed
                ai_reasons = tuple(proposal["reasons"])
        return _RoundPlan(
            decisions=decisions,
            adjust_warnings=adjust_warnings,
            levels=levels,
            inputs=inputs,
            result=result,
            ai_shares=ai_shares,
            ai_reasons=ai_reasons,
            shares_rejection=rejection,
        )

    checks = _flagged_checks(tech, base_levels, base_result.shares)

    merged: Dict[str, Dict[str, Any]] = {}
    plan = _RoundPlan(
        decisions=base_decisions, adjust_warnings=[], levels=base_levels,
        inputs=base_inputs, result=base_result,
        ai_shares=None, ai_reasons=(), shares_rejection=None,
    )
    review_failures: List[Dict[str, Any]] = []
    converged = True

    if checks:
        converged = False
        prompt_checks = checks
        for round_no in range(1, MAX_ADJUST_ROUNDS + 1):
            round_note = ""
            extra_allowed: List[str] = []
            if round_no > 1:
                # Rounds after the first describe the current plan; its
                # numbers have no report row, so they may go uncited.
                current = {
                    "stop_loss": (
                        display_value(plan.levels.stop_loss)
                        if plan.levels.stop_loss is not None else "—"
                    ),
                    "take_profit": (
                        display_value(plan.levels.take_profit)
                        if plan.levels.take_profit is not None else "—"
                    ),
                    "shares": (
                        display_value(plan.shares)
                        if plan.shares is not None else "—"
                    ),
                }
                round_note = (
                    "Your earlier accepted adjustments were applied; the plan "
                    f"currently stands at stop_loss = {current['stop_loss']}, "
                    f"take_profit = {current['take_profit']}, shares = "
                    f"{current['shares']}. The checks below were re-run "
                    "against this CURRENT plan. New adjustments replace your "
                    "earlier ones for the same target and must still obey "
                    "every rule against the computed bases above.\n"
                )
                extra_allowed = list(current.values()) + (
                    [display_value(base_result.shares)]
                    if base_result.shares is not None else []
                )
            try:
                adjustments, request_warnings = _request_adjustments(
                    symbol, dimensions, bases,
                    base_result.shares, plan.result.shares,
                    prompt_checks, atr,
                    summarizer or default_summarizer,
                    round_note=round_note, extra_allowed=extra_allowed,
                    hold_weeks=hold_weeks,
                )
            except LlmConfigError as exc:
                warnings.append(f"plan review skipped: {exc}")
                converged = not review_failures
                break
            except Exception as exc:  # LLM transport failures degrade loudly
                logger.warning(
                    "plan review LLM call failed for %s: %s", symbol, exc
                )
                warnings.append(f"plan review LLM call failed: {exc}")
                # No completed-but-flagged round yet → plain outage, keep
                # the computed plan without the failure verdict.
                converged = not review_failures
                break
            warnings.extend(
                f"round {round_no}: {warning}" for warning in request_warnings
            )
            if not adjustments:
                # The AI's answer is "no change helps". Terminal: a failure
                # if a plan-dependent check is firing, done otherwise.
                dependent = [
                    check for check in prompt_checks
                    if check.name in _PLAN_DEPENDENT_CHECKS
                ]
                if dependent:
                    review_failures.append({
                        "round": round_no,
                        "checks": [check.name for check in dependent],
                    })
                else:
                    converged = True
                break
            merged = _merge_proposals(merged, adjustments)
            plan = evaluate(merged)
            flagged = [
                check
                for check in _flagged_checks(tech, plan.levels, plan.shares)
                if check.name in _PLAN_DEPENDENT_CHECKS
            ]
            if not flagged:
                converged = True
                break
            review_failures.append({
                "round": round_no,
                "checks": [check.name for check in flagged],
            })
            prompt_checks = flagged

    if converged:
        # Only the final plan's guardrail verdicts surface — intermediate
        # rounds' rejections were superseded by later proposals.
        warnings.extend(plan.adjust_warnings)
        if plan.shares_rejection is not None:
            warnings.append(
                f"adjustment for shares rejected: {plan.shares_rejection}"
            )
        review_failures = []
    else:
        warnings.append(
            "plan review did not converge: the adjusted plan still tripped "
            "risk checks after every round, so all adjustments were "
            "discarded and the computed plan stands"
        )
        plan = _RoundPlan(
            decisions=base_decisions, adjust_warnings=[], levels=base_levels,
            inputs=base_inputs, result=base_result,
            ai_shares=None, ai_reasons=(), shares_rejection=None,
        )

    decisions = plan.decisions
    levels = plan.levels
    final_inputs, final_result = plan.inputs, plan.result
    ai_shares, ai_reasons = plan.ai_shares, plan.ai_reasons
    shares_rejection = plan.shares_rejection

    final_shares = ai_shares if ai_shares is not None else final_result.shares
    final_risk = (
        final_shares * final_result.loss_per_share
        if final_shares is not None and final_result.loss_per_share is not None
        else final_result.risk_amount
    )

    trim_notes = (
        [f"share count trimmed by the AI plan review: "
         f"{final_result.shares} → {ai_shares}"]
        if ai_shares is not None else []
    )
    sizing_detail = sizing_detail_dict(
        settings, final_result, levels,
        shares=final_shares, risk_amount=final_risk, extra_notes=trim_notes,
    )
    slots = (
        SizingSlots(
            capital=settings.capital,
            risk_fraction=settings.risk_fraction,
            shares=float(final_shares),
        )
        if final_shares is not None and final_shares > 0
        else SizingSlots()
    )

    levels_detail = decisions_to_detail(decisions, list(bases.warnings) + warnings)
    levels_detail["levels"]["shares"] = _shares_detail(
        base_inputs, base_result, final_inputs, final_result,
        ai_shares, ai_reasons, shares_rejection,
    )
    if review_failures:
        # Not converged: the UI turns every adjusted cell into a blue
        # "keep" whose modal words these per-round failures.
        levels_detail["review_failures"] = review_failures

    plan_warnings = build_plan_warnings(
        tech, levels, final_shares, final_risk, settings.reward_risk,
        earnings=earnings,
        macro_event=macro_event_from_dimensions(dimensions),
    )

    return PlanReview(
        levels=levels,
        levels_detail=levels_detail,
        warnings=warnings,
        plan_warnings=plan_warnings,
        sizing_detail=sizing_detail,
        sizing_slots=slots,
    )
