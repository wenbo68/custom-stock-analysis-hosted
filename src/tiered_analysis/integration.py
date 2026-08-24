# -*- coding: utf-8 -*-
"""Production wiring for tiered analysis.

This module makes the real connections the slices deliberately left
open, always as a CLIENT of existing DSA layers (boundary rule: never
import into or modify the decision path itself):

- ``dsa_bars_loader``: daily OHLCV bars for the technicals provider via
  ``DataFetcherManager`` (the existing multi-source failover layer).
- ``run_tiered_analysis``: the one-call orchestrator — collect the
  dimensions (four numeric + the textual company-events card), compute
  formula levels, run the chosen judge (depth 1 =
  the tiered package's own one-call quick judge since 2026-08-10; depth
  2 = the evidence-vote debate), compute the position size when the
  user's sizing settings are present, track the run's own LLM
  call/token usage, and log the deepest tier's recommendation into the
  existing decision-signal system. (The legacy tier-1 delegate to DSA's
  ``StockAnalysisPipeline`` is retired — the quick judge reads the same
  four dimensions the debate reads and sees the max hold time.)

Everything is injectable so tests stay offline; the defaults are the real
DSA layers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .cross_fields import enrich_cross_fields
from .earnings import EarningsInfo, earnings_from_dimensions
from .levels import (
    apply_adjustments,
    bases_from_dimensions,
    decisions_to_detail,
    decisions_to_sniper,
)
from .llm_support import LlmUsageTracker
from .plan_review import review_plan, sizing_detail_dict
from .quick_judge import QuickJudge
from .providers.base import (
    DimensionProvider,
    DimensionResult,
    Market,
)
from .providers.registry import detect_market, get_providers
from .providers.technicals import Bar, read_label, read_metric
from .run_gate import (
    expected_bar_date,
    market_for_symbol,
    staleness_stop_reason,
    trim_incomplete_bars,
)
from .schema import (
    DEFAULT_HOLD_WEEKS,
    HOLD_WEEKS_CHOICES,
    Action,
    Direction,
    Outlook,
    REWARD_GOAL_EPS,
    SizingSlots,
    TierReport,
    derive_action,
    reward_ratio,
)
from .settings import (
    SizingSettings,
    load_sizing_settings,
    merge_overrides,
    with_fallback_defaults,
)
from .signal_log import SignalLogResult, log_tier_report
from .sizing import SizingInputs, size_position
from .tiers import Tier2Stage, TierState

logger = logging.getLogger(__name__)

#: Calendar days of daily bars to request — comfortably covers the ~250
#: trading bars the 52-week high/low needs (weekends/holidays included).
BARS_CALENDAR_DAYS = 400


def dsa_bars_loader(symbol: str, manager: Any = None) -> List[Bar]:
    """Daily bars via DSA's multi-source data layer, oldest first."""
    if manager is None:
        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager()

    df, _source = manager.get_daily_data(symbol, days=BARS_CALENDAR_DAYS)
    if df is None or df.empty:
        return []

    frame = df.dropna(subset=["open", "high", "low", "close"])
    frame = frame.sort_values("date")
    bars = [
        Bar(
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            open=float(row["open"]),
            volume=float(row["volume"]) if row.get("volume") is not None else None,
            date=str(row["date"]),
        )
        for row in frame.to_dict("records")
    ]
    # Some vendors include today's half-finished bar during the trading
    # day; the analysis must only ever see completed sessions (run-gate
    # design, 2026-08-08). Unknown markets are left untrimmed.
    expected = expected_bar_date(market_for_symbol(symbol))
    return trim_incomplete_bars(bars, expected)


#: Supported analysis depths: 1 = the one-call quick judge (the tiered
#: package's own since 2026-08-10 — the legacy DSA blob is retired), 2 =
#: the evidence vote. Tier 3 is retired (outlook redesign, 2026-07-20).
SUPPORTED_DEPTHS = (1, 2)


@dataclass(frozen=True)
class TieredRunOutcome:
    """Everything one tiered run produced.

    ``report`` stays the tier-1/foundation report (it carries the
    dimension results the web cards render from); ``final_report`` is the
    deepest tier that ran — the same object at depth 1.
    """

    report: TierReport
    state: TierState
    signal: Optional[SignalLogResult]
    depth: int = 1
    final_report: Optional[TierReport] = None
    #: Sizing block (v2 slice 6): share count or explicit refusal reason.
    sizing: Optional[Dict[str, Any]] = None
    #: This run's own LLM call/token counts per stage (since 2026-08-10
    #: this includes the depth-1 quick judge; on older runs the tier-1
    #: blob ran inside the DSA pipeline and was billed there).
    llm_usage: Optional[Dict[str, Any]] = None
    #: Outlook redesign: the impersonal judgment + the personal action
    #: (outlook × ownership code table).
    outlook: Outlook = Outlook.UNKNOWN
    action: Action = Action.UNKNOWN
    #: Next earnings date, read from the fundamentals payload (display
    #: lives on the fundamentals card; the debate weighs the event risk).
    earnings: Optional[EarningsInfo] = None
    #: Retired display-only risk card (2026-07-22) — always None on new
    #: runs; the field survives so old consumers keep a stable shape.
    risk_card: Optional[list] = None
    #: Plan review (2026-07-22): structured per-column warnings for the
    #: trade-plan card — {"entry"|"stop_loss"|"take_profit"|"shares":
    #: [{"id", "values"}]}. None when the run produced no buy plan.
    plan_warnings: Optional[Dict[str, Any]] = None
    #: Max hold time in weeks (per-run input, 2026-08-08) — echoed back so
    #: the report can display the horizon the AI was judged against.
    hold_weeks: int = DEFAULT_HOLD_WEEKS

    def __post_init__(self) -> None:
        if self.final_report is None:
            object.__setattr__(self, "final_report", self.report)


def _collect_dimensions(
    providers: Sequence[DimensionProvider], symbol: str
) -> List[DimensionResult]:
    results: List[DimensionResult] = []
    for provider in providers:
        try:
            results.append(provider.collect(symbol))
        except Exception as exc:  # providers are fail-loud, but belt+braces
            results.append(
                DimensionResult(
                    dimension=provider.dimension,
                    kind=provider.kind,
                    warnings=[f"{provider.dimension} provider crashed: {exc}"],
                )
            )
    return results


def collect_dimensions_once(
    symbol: str, market: Optional[Market] = None
) -> List[DimensionResult]:
    """Collect + cross-enrich the dimensions with production wiring.

    For callers that run the same symbol several times back-to-back
    (the forward-test grid): fetch the data layer here once, then hand
    every run ``providers=precollected_providers(...)`` so each variant
    judges the exact same snapshot. Those runs must pass
    ``staleness_gate=True`` explicitly (injected providers switch the
    gate off by default) and no ``cross_bars_loader`` (enrichment
    already happened here; the canned results must pass through
    untouched).
    """
    if market is None:
        market = detect_market(symbol)
    providers = get_providers(market, bars_loader=dsa_bars_loader)
    dimensions = _collect_dimensions(providers, symbol)
    return enrich_cross_fields(dimensions, dsa_bars_loader)


class PrecollectedProvider(DimensionProvider):
    """Serves one already-collected DimensionResult unchanged."""

    def __init__(self, result: DimensionResult) -> None:
        self.dimension = result.dimension
        self.kind = result.kind
        self._result = result

    def supports(self, market: Market) -> bool:
        return True  # the data is fixed; market choice already happened

    def collect(self, symbol: str) -> DimensionResult:
        return self._result


def precollected_providers(
    dimensions: Sequence[DimensionResult],
) -> List[DimensionProvider]:
    """Wrap a collected snapshot for ``run_tiered_analysis(providers=...)``."""
    return [PrecollectedProvider(dim) for dim in dimensions]


def _technicals_atr(dimensions: Sequence[DimensionResult]) -> Optional[float]:
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            return read_metric(dim.payload, "volatility", "atr_14")
    return None


def _technicals_as_of(dimensions: Sequence[DimensionResult]) -> Optional[str]:
    """The "bars up to" date the technicals provider computed from.

    ``meta.as_of`` is a date STRING ("YYYY-MM-DD"), so it needs the label
    reader — ``read_metric`` drops anything non-numeric and would hand the
    staleness gate a permanent None (every run stopped, 2026-08-08).
    """
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            return read_label(dim.payload, "meta", "as_of")
    return None


def _stopped_outcome(
    symbol: str,
    market: Market,
    dimensions: List[DimensionResult],
    depth: int,
    hold_weeks: int,
    tracker: LlmUsageTracker,
) -> TieredRunOutcome:
    """A run halted by the staleness gate: data cards only, no verdict.

    The outlook IS the whole user-facing story (owner decision
    2026-08-08): no analysis or plan sections exist, no message is shown,
    no signal is logged (direction stays UNKNOWN), and the stop reason
    lives in the server log only.
    """
    report = TierReport(
        tier=1,
        symbol=symbol,
        market=market,
        direction=Direction.UNKNOWN,
        dimensions=dimensions,
        hold_weeks=hold_weeks,
    )
    state = TierState(symbol=symbol, market=market, hold_weeks=hold_weeks)
    state.reports[1] = report
    state.dimensions = list(dimensions)
    return TieredRunOutcome(
        report=report,
        state=state,
        signal=None,
        depth=depth,
        final_report=report,
        sizing=None,
        llm_usage=tracker.to_detail(),
        outlook=Outlook.STOPPED,
        action=Action.UNKNOWN,
        hold_weeks=hold_weeks,
    )


#: The run-detail earnings block reads the same shared helper the plan
#: review's earnings gate uses (moved to earnings.py, 2026-07-27).
_earnings_from_dimensions = earnings_from_dimensions


def _sizing_block(
    final: TierReport,
    market: Market,
    settings: SizingSettings,
) -> Tuple[Dict[str, Any], SizingSlots]:
    """Deterministic sizing of the deepest tier's call (v2 slices 1+6).

    The engine runs even when settings are absent so the UI gets an
    explicit ``sizing_off`` refusal instead of a missing section.
    Outlook redesign: the tier-3 multiplier is gone — a bearish outlook
    on a held stock exits the FULL holding (reducing risk needs no
    permission), and the buy size comes from the formula + caps alone.
    """
    inputs = SizingInputs(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        entry=final.levels.entry,
        stop_loss=final.levels.stop_loss,
        direction=final.direction,
        market=market,
    )
    result = size_position(inputs)

    # A bearish outlook on a stock the user holds gets a concrete exit
    # size: the full holding. This needs no capital/risk settings — the
    # count IS the holding.
    ownership = settings.ownership
    sell_shares = None
    if final.direction is Direction.SELL and ownership > 0:
        sell_shares = ownership

    detail = sizing_detail_dict(
        settings, result, final.levels, ownership, sell_shares
    )

    if not result.is_sized:
        return detail, SizingSlots()
    return detail, SizingSlots(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        shares=float(result.shares),
    )


def run_tiered_analysis(
    symbol: str,
    market: Optional[Market] = None,
    providers: Optional[Sequence[DimensionProvider]] = None,
    quick_judge: Optional[QuickJudge] = None,
    signal_logger: Callable[..., Any] = log_tier_report,
    log_signal: bool = True,
    trace_id: Optional[str] = None,
    depth: int = 1,
    sizing_settings: Optional[SizingSettings] = None,
    sizing_overrides: Optional[Mapping[str, Any]] = None,
    tier2_stage: Optional[Tier2Stage] = None,
    earnings_lookup: Optional[Callable[[str, Market], EarningsInfo]] = None,
    plan_summarizer: Optional[Callable[[str], str]] = None,
    cross_bars_loader: Optional[Callable[[str], List[Bar]]] = None,
    hold_weeks: int = DEFAULT_HOLD_WEEKS,
    staleness_gate: Optional[bool] = None,
) -> TieredRunOutcome:
    """Run one symbol at ``depth`` with full production wiring.

    Pipeline (plan-review redesign, 2026-07-22): data layer (four
    dimensions; fundamentals carries the next earnings date) → formula
    levels → the chosen judge (depth 1 = the tiered package's one-call
    quick judge; depth 2 = the evidence vote) → on a BUY
    verdict, the AI plan review (deterministic checks may trim shares /
    move stop / move target, with cited reasons, and produce the
    trade-plan card's structured warnings) → outlook + action (code
    table over ownership) → sizing. Unless ``log_signal`` is False, the
    deepest tier's recommendation lands in the decision-signal system.

    ``sizing_overrides`` may carry per-run ``capital`` / ``risk_fraction``
    / ``ownership`` values (the API's per-run override) on top of the
    saved settings. ``earnings_lookup`` is a test seam; production reads
    the date the fundamentals provider already fetched.
    ``cross_bars_loader`` is a test/demo seam: injected providers skip
    the cross-provider enrichment unless a loader is passed explicitly.
    """
    if depth not in SUPPORTED_DEPTHS:
        raise ValueError(f"depth must be one of {SUPPORTED_DEPTHS}, got {depth}")
    if hold_weeks not in HOLD_WEEKS_CHOICES:
        raise ValueError(
            f"hold_weeks must be one of {HOLD_WEEKS_CHOICES}, got {hold_weeks}"
        )
    if market is None:
        market = detect_market(symbol)
    # The staleness gate runs with production wiring only (injected
    # providers mean a test harness with canned as-of dates), unless the
    # caller opts in/out explicitly — same convention as cross-field
    # enrichment below.
    if staleness_gate is None:
        staleness_gate = providers is None
    # Cross-provider enrichment (sector comparison, implied/realized
    # ratio) runs only with production wiring: injected providers mean
    # a test harness whose canned payloads must pass through untouched
    # — unless the harness opts in with its own ``cross_bars_loader``.
    if providers is None:
        providers = get_providers(market, bars_loader=dsa_bars_loader)
        if cross_bars_loader is None:
            cross_bars_loader = dsa_bars_loader
    if sizing_settings is None:
        sizing_settings = load_sizing_settings()
    if sizing_overrides:
        sizing_settings = merge_overrides(
            sizing_settings,
            capital=sizing_overrides.get("capital"),
            risk_fraction=sizing_overrides.get("risk_fraction"),
            ownership=sizing_overrides.get("ownership"),
            reward_risk=sizing_overrides.get("reward_risk"),
        )
    # Every run sizes (owner decision 2026-07-24): missing capital/risk
    # fall back to the web form's defaults instead of disabling sizing.
    sizing_settings = with_fallback_defaults(sizing_settings)
    tracker = LlmUsageTracker()
    with tracker.activate():
        dimensions = _collect_dimensions(providers, symbol)
        dimensions = enrich_cross_fields(dimensions, cross_bars_loader)

        # STALENESS GATE (2026-08-08): stop BEFORE any LLM stage when the
        # newest completed bar predates the most recent completed trading
        # session — no analysis money is spent on yesterday's leftovers.
        # A clock-gate "run anyway" during the trading day expects the
        # PREVIOUS session's bar and passes here; only a lagging vendor
        # stops a run, and there is deliberately no override for that.
        if staleness_gate:
            stop_reason = staleness_stop_reason(
                _technicals_as_of(dimensions), market_for_symbol(symbol)
            )
            if stop_reason is not None:
                logger.warning(
                    "tiered run stopped for %s before LLM stages: %s",
                    symbol,
                    stop_reason,
                )
                return _stopped_outcome(
                    symbol, market, dimensions, depth, hold_weeks, tracker
                )

        # Formula-only levels: deterministic bases from the technicals
        # payload; the adjustment machinery runs with zero proposals so
        # the audit-trail shape (base/formula/inputs per level) stays.
        bases = bases_from_dimensions(
            dimensions, reward_risk=sizing_settings.reward_risk
        )
        decisions, adjust_warnings = apply_adjustments(
            bases, [], atr=_technicals_atr(dimensions)
        )
        level_warnings = list(bases.warnings) + adjust_warnings
        levels = decisions_to_sniper(decisions)
        levels_detail = decisions_to_detail(decisions, level_warnings)

        # The next earnings date rides in the fundamentals payload (the
        # provider fetched it); the injectable lookup is a test seam.
        earnings = (
            earnings_lookup(symbol, market)
            if earnings_lookup is not None
            else _earnings_from_dimensions(dimensions)
        )
        extra_warnings = level_warnings

        state = TierState(symbol=symbol, market=market, hold_weeks=hold_weeks)
        if depth == 1:
            # The quick judge (2026-08-10): the tiered package's own
            # one-call verdict over the same dimensions the debate
            # reads (all six since 2026-08-16, both news cards included),
            # judged against the same max hold time. No verdict
            # (LLM down, bad replies) → UNKNOWN direction, fail-loud
            # warnings, no fallback — same contract as the debate.
            with tracker.stage("tier1_quick"):
                quick = (quick_judge or QuickJudge()).run(
                    symbol, dimensions, levels, hold_weeks=hold_weeks
                )
            verdict = quick.verdict
            report = TierReport(
                tier=1,
                symbol=symbol,
                market=market,
                direction=verdict.direction if verdict else Direction.UNKNOWN,
                # The verdict is the 0-10 score in debate_detail; the
                # legacy sentiment-score/confidence columns stay empty
                # (same shape as tier-2 reports).
                confidence=None,
                score=None,
                narrative=verdict.summary if verdict else None,
                levels=levels,
                levels_detail=levels_detail,
                dimensions=dimensions,
                warnings=list(quick.warnings) + extra_warnings,
                debate_detail=quick.to_detail(),
            )
        else:
            # Depth 2 skips the one-blob call entirely: the debate is the
            # judge, so the foundation report is the data layer + levels
            # with no verdict of its own. That is the documented depth-2
            # contract, not a data problem — so no warning for it.
            report = TierReport(
                tier=1,
                symbol=symbol,
                market=market,
                        direction=Direction.UNKNOWN,
                levels=levels,
                levels_detail=levels_detail,
                dimensions=dimensions,
                warnings=extra_warnings,
            )
        state.reports[1] = report
        state.dimensions = list(dimensions)
        state.ownership = sizing_settings.ownership

        final = report
        if depth >= 2:
            with tracker.stage("tier2_debate"):
                final = (tier2_stage or Tier2Stage()).run(state)
            state.reports[2] = final

        # AI plan review (BUY verdicts only): the deterministic checks
        # may trim the share count or move stop/target with cited
        # reasons, and produce the plan card's structured warnings.
        review = None
        if final.direction is Direction.BUY and bases.get("entry") is not None:
            with tracker.stage("plan_adjust"):
                review = review_plan(
                    symbol, dimensions, bases, final.direction, market,
                    sizing_settings, ownership=sizing_settings.ownership,
                    summarizer=plan_summarizer, hold_weeks=hold_weeks,
                )

    plan_warnings: Optional[Dict[str, Any]] = None
    if review is not None:
        depth1_same = final is report
        # Review warnings land on the foundation report only (the plan
        # card's notes); the tier-2 card keeps its own warnings.
        report = replace(
            report,
            levels=review.levels,
            levels_detail=review.levels_detail,
            warnings=list(report.warnings) + list(review.warnings),
        )
        final = report if depth1_same else replace(
            final, levels=review.levels, levels_detail=review.levels_detail
        )
        state.reports[1] = report
        sizing_detail, sizing_slots = review.sizing_detail, review.sizing_slots
        plan_warnings = review.plan_warnings
    else:
        sizing_detail, sizing_slots = _sizing_block(final, market, sizing_settings)
    final = replace(final, sizing=sizing_slots, hold_weeks=hold_weeks)
    if not final.dimensions:
        # Tier-2 reports are built lean; the deepest report carries the
        # evidence so the signal ledger and consumers see it.
        final = replace(final, dimensions=list(dimensions))
    state.reports[final.tier] = final
    if final.tier == 1:
        report = final

    outlook = Outlook.from_direction(final.direction)
    # Buy now vs buy later (owner decision 2026-08-23): the final plan's
    # actual reward-to-risk against the user's goal — the same comparison
    # the plan card's reward-below-goal warning makes.
    ratio = reward_ratio(final.levels)
    plan_meets_goal = (
        ratio is None or ratio >= sizing_settings.reward_risk - REWARD_GOAL_EPS
    )
    action = derive_action(
        outlook, sizing_settings.ownership, plan_meets_goal=plan_meets_goal
    )

    signal: Optional[SignalLogResult] = None
    if log_signal:
        signal = signal_logger(final, trace_id=trace_id)

    return TieredRunOutcome(
        report=report,
        state=state,
        signal=signal,
        depth=depth,
        final_report=final,
        sizing=sizing_detail,
        llm_usage=tracker.to_detail(),
        outlook=outlook,
        action=action,
        earnings=earnings,
        plan_warnings=plan_warnings,
        hold_weeks=hold_weeks,
    )
