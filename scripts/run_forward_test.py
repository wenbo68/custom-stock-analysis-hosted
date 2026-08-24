# -*- coding: utf-8 -*-
"""Daily forward-test driver for tiered analysis.

One invocation per day (after US market close) does three things:

1. Runs the experiment grid — every watchlist symbol at every
   (depth, hold weeks) variant. The four dimension reports are fetched
   once per symbol and reused across all its variants (2026-08-13), so
   every cell judges the exact same snapshot. Each run's recommendation
   is logged as a decision signal automatically, stamped with a per-day
   trace id. An interrupted grid resumes for free: cells that already
   logged a signal today are skipped before any LLM call (``--force``
   re-runs them anyway; cells that ended with no signal are always
   retried).
2. Grades matured signals — the same scoring pass the server's
   background job runs, so no always-on server is needed.
3. Prints the scoreboards:
   - outlook by variant (quick/deep x hold weeks) and by conviction
     score band, on the shared grader's fixed ±2% band;
   - the same outlooks re-graded with a noise-scaled band (each
     stock's own daily wobble x sqrt(window)) plus the mean
     direction-adjusted return — the statistically fair columns;
   - trade plans vs reality (buy calls only): entry reached? stop or
     target struck first?
   - AI plan adjustments vs the untouched formula plan, paired on the
     runs where an adjustment actually survived.

The grid design (owner decisions 2026-08-10/11): a symmetric
quick/deep x 1/2/3-week grid over 8 symbols, one per behavior type.
Both judges read the same evidence, know the hold time, and score on
the same 0-10 scale, so every tier/hold cell is a clean counterpart.

Usage:
    .venv/bin/python scripts/run_forward_test.py
    .venv/bin/python scripts/run_forward_test.py --summary-only
    .venv/bin/python scripts/run_forward_test.py --check
    .venv/bin/python scripts/run_forward_test.py --check 2026-08-10
    .venv/bin/python scripts/run_forward_test.py AAPL NVDA
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

#: The fixed daily watchlist. Edit freely; each symbol costs
#: len(VARIANTS) runs per day.
#: One symbol per behavior type — momentum tech, volatile story stock,
#: defensive staple, oil cyclical, bank, healthcare defensive,
#: industrial cyclical, steady retail compounder — so one market-wide
#: day does not settle every bet at once, and buy calls (the only runs
#: that grade trade plans) accumulate faster (owner decision
#: 2026-08-11, extending the 4-symbol list of 2026-08-10).
WATCHLIST = ["NVDA", "TSLA", "KO", "XOM", "JPM", "UNH", "CAT", "COST"]

#: The experiment grid as (depth, hold_weeks) pairs. depth 1 = quick
#: (one-shot synthesis), depth 2 = deep (multi-persona debate).
VARIANTS: List[Tuple[int, int]] = [
    (2, 1), (2, 2), (2, 3),
    (1, 1), (1, 2), (1, 3),
]

BAR = "=" * 70


def variant_label(depth: int, hold_weeks: int) -> str:
    """Human name for one grid cell, e.g. ``deep-3w`` / ``quick-2w``."""
    tier = "deep" if depth == 2 else "quick"
    return f"{tier}-{hold_weeks}w"


def build_trace_id(run_date: str, symbol: str, depth: int, hold_weeks: int) -> str:
    """Per-day, per-variant identity for the signal log's dedup.

    Re-running the script the same day reuses the same trace, so the
    signal service updates the existing signal instead of logging a
    duplicate row. The column caps at 64 chars.
    """
    trace = f"fwdtest-{run_date}-{symbol.lower()}-d{depth}-h{hold_weeks}"
    return trace[:64]


def parse_trace_id(trace_id: str) -> Optional[Tuple[str, str, int, int]]:
    """Invert :func:`build_trace_id` -> (run_date, symbol, depth, hold).

    Returns None for traces that are not this script's (other tooling
    also writes decision signals).
    """
    parts = (trace_id or "").split("-")
    # fwdtest-YYYY-MM-DD-<symbol>-d<depth>-h<hold>
    if len(parts) < 7 or parts[0] != "fwdtest":
        return None
    depth_part, hold_part = parts[-2], parts[-1]
    if not (depth_part.startswith("d") and hold_part.startswith("h")):
        return None
    try:
        depth = int(depth_part[1:])
        hold_weeks = int(hold_part[1:])
    except ValueError:
        return None
    run_date = "-".join(parts[1:4])
    symbol = "-".join(parts[4:-2])
    if not symbol:
        return None
    return run_date, symbol, depth, hold_weeks


def check_runs(run_date: str) -> int:
    """Report what actually got logged for one day's grid.

    Lists every signal the script logged that day and flags grid cells
    with no signal. Exit code 1 when cells are missing, so a cron
    wrapper can alert on it.
    """
    from sqlalchemy import select

    from src.storage import DatabaseManager, DecisionSignalRecord

    prefix = f"fwdtest-{run_date}-"
    with DatabaseManager().get_session() as session:
        rows = list(session.execute(
            select(DecisionSignalRecord)
            .where(DecisionSignalRecord.trace_id.like(f"{prefix}%"))
            .order_by(DecisionSignalRecord.trace_id)
        ).scalars().all())

    print(f"Run check for {run_date}: {len(rows)} signal(s) logged.")
    found: Dict[Tuple[str, int, int], Any] = {}
    for row in rows:
        parsed = parse_trace_id(row.trace_id or "")
        if parsed is not None:
            found[(parsed[1], parsed[2], parsed[3])] = row
        print(
            f"  #{row.id} {row.stock_code:<8}"
            f"{variant_label(*parsed[2:]) if parsed else '?':<10}"
            f"{row.action:<8}entry {row.entry_low}-{row.entry_high} "
            f"stop {row.stop_loss} target {row.target_price} "
            f"[{row.status}] logged {row.created_at}"
        )

    missing = [
        (symbol, depth, hold)
        for symbol in WATCHLIST
        for depth, hold in VARIANTS
        if (symbol.lower(), depth, hold) not in found
    ]
    if missing:
        print(f"\n{len(missing)} grid cell(s) have no signal:")
        for symbol, depth, hold in missing:
            print(f"  {symbol} {variant_label(depth, hold)}")
        print(
            "A missing cell means the run failed, was never started, or "
            "ended with no usable direction (those are skipped by design) "
            "— the day's script output / cron log has the reason."
        )
        return 1
    print("Every watchlist grid cell has a signal.")
    return 0


def existing_trace_ids(run_date: str) -> set:
    """Trace ids of signals already logged for this day's grid — the
    resume set: a cell in here has a saved result, so re-running it
    would only spend tokens on a result the dedup layer discards."""
    from sqlalchemy import select

    from src.storage import DatabaseManager, DecisionSignalRecord

    prefix = f"fwdtest-{run_date}-"
    with DatabaseManager().get_session() as session:
        return {
            trace
            for (trace,) in session.execute(
                select(DecisionSignalRecord.trace_id)
                .where(DecisionSignalRecord.trace_id.like(f"{prefix}%"))
            )
        }


def make_shared_dimension_runner() -> Callable[..., Any]:
    """Production runner that fetches each symbol's dimensions ONCE.

    The four dimension reports are pure data downloads (no LLM), and the
    grid runs while the market is closed, so every variant of a symbol
    judges the exact same enriched snapshot — zero drift between the
    quick and deep cells, no repeated downloads (2026-08-13). A fetch
    that raises is not cached: the symbol's next cell retries it.
    """
    from src.tiered_analysis import integration

    snapshots: Dict[str, Any] = {}

    def runner(symbol: str, *, depth: int, hold_weeks: int, trace_id: str):
        if symbol not in snapshots:
            snapshots[symbol] = integration.collect_dimensions_once(symbol)
        return integration.run_tiered_analysis(
            symbol,
            depth=depth,
            hold_weeks=hold_weeks,
            trace_id=trace_id,
            providers=integration.precollected_providers(snapshots[symbol]),
            # Injected providers turn the staleness gate off by default
            # (test-harness convention); this is a production run with
            # real as-of dates, so keep the gate on. No cross_bars_loader:
            # the snapshot is already enriched.
            staleness_gate=True,
        )

    return runner


def run_grid(
    symbols: Sequence[str],
    variants: Sequence[Tuple[int, int]],
    run_date: str,
    runner: Optional[Callable[..., Any]] = None,
    skip_traces: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Run every symbol x variant; a failed run is recorded, never fatal.

    Cells whose trace id is in ``skip_traces`` are skipped without any
    LLM call — that is how an interrupted day resumes.
    """
    if runner is None:
        runner = make_shared_dimension_runner()
    from src.tiered_analysis.signal_log import debate_final_score, plan_provenance

    results: List[Dict[str, Any]] = []
    total = len(symbols) * len(variants)
    done = 0
    for symbol in symbols:
        for depth, hold_weeks in variants:
            done += 1
            label = variant_label(depth, hold_weeks)
            trace_id = build_trace_id(run_date, symbol, depth, hold_weeks)
            if skip_traces and trace_id in skip_traces:
                print(
                    f"[{done}/{total}] {symbol} {label}: already logged "
                    "today — skipped (resume; --force re-runs it)"
                )
                results.append({
                    "symbol": symbol, "variant": label, "ok": True,
                    "skipped": True,
                })
                continue
            started = time.monotonic()
            try:
                outcome = runner(
                    symbol,
                    depth=depth,
                    hold_weeks=hold_weeks,
                    trace_id=trace_id,
                )
            except Exception as exc:
                print(f"[{done}/{total}] {symbol} {label}: FAILED — {exc}")
                results.append({
                    "symbol": symbol, "variant": label, "ok": False,
                    "error": str(exc),
                })
                continue
            elapsed = time.monotonic() - started
            # final_report carries the verdict (the debate's on deep runs);
            # outcome.report is the foundation report, verdict-free at depth 2.
            report = outcome.final_report
            signal = outcome.signal
            _, plan_adjusted = plan_provenance(report)
            row = {
                "symbol": symbol,
                "variant": label,
                "ok": True,
                "direction": report.direction.value,
                "final_score": debate_final_score(report),
                "entry": report.levels.entry,
                "stop_loss": report.levels.stop_loss,
                "target": report.levels.take_profit,
                "plan_adjusted": plan_adjusted,
                "signal_id": getattr(signal, "signal_id", None),
                "signal_logged": bool(signal and signal.logged),
                "signal_reason": getattr(signal, "reason", None),
            }
            results.append(row)
            score_text = (
                f" (score {row['final_score']})"
                if row["final_score"] is not None else ""
            )
            signal_text = (
                f"signal #{row['signal_id']}"
                if row["signal_logged"]
                else f"signal NOT saved — {row['signal_reason']}"
            )
            plan_text = " [AI-adjusted plan]" if row["plan_adjusted"] else ""
            print(
                f"[{done}/{total}] {symbol} {label}: "
                f"{row['direction']}{score_text}, "
                f"entry {row['entry']} stop {row['stop_loss']} "
                f"target {row['target']}{plan_text} — {signal_text} "
                f"({elapsed:.0f}s)"
            )
    return results


#: Calendar days of bars the backfill requests per stock — comfortably
#: covers the volatility lookback (~70 trading bars) before the oldest
#: realistic anchor plus the grading window itself.
BACKFILL_CALENDAR_DAYS = 400


def backfill_daily_bars() -> None:
    """Fetch and store daily bars for every stock that has a logged signal.

    Standalone-app addition: the grader and the scoreboard read bars from
    the local ``stock_daily`` table, which in the parent project is filled
    by its classic daily pipeline. That pipeline did not move here, so this
    script fills the table itself before grading. One failed symbol only
    loses that symbol's grading for today; it never aborts the run.
    """
    from sqlalchemy import select

    from data_provider.base import DataFetcherManager
    from src.repositories.stock_repo import StockRepository
    from src.storage import DatabaseManager, DecisionSignalRecord

    with DatabaseManager().get_session() as session:
        codes = sorted({
            code
            for (code,) in session.execute(
                select(DecisionSignalRecord.stock_code).distinct()
            )
            if code
        })
    if not codes:
        return

    manager = DataFetcherManager()
    repo = StockRepository()
    saved = 0
    failed: List[str] = []
    for code in codes:
        try:
            df, source = manager.get_daily_data(code, days=BACKFILL_CALENDAR_DAYS)
            if df is None or df.empty:
                failed.append(code)
                continue
            repo.save_dataframe(df, code, source or "unknown")
            saved += 1
        except Exception as exc:  # noqa: BLE001 — per-symbol isolation
            print(f"bar backfill failed for {code}: {exc}")
            failed.append(code)
    line = f"Bar backfill: {saved}/{len(codes)} stocks updated."
    if failed:
        line += f" No data for: {', '.join(failed)}."
    print(line)


def grade_matured_signals():
    """Score every signal whose grading window has data — same engine the
    server's background job uses. Returns the service for the summary."""
    from src.services.decision_signal_outcome_service import (
        DecisionSignalOutcomeService,
    )

    service = DecisionSignalOutcomeService()
    stats = service.run_outcomes(limit=500)
    print(
        f"\nGrading pass: {stats['created']} newly graded, "
        f"{stats['updated']} re-graded, {stats['skipped']} already done."
    )
    return service


def _signal_metadata(raw: Optional[str]) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def variant_key(row: Any, metadata: Dict[str, Any]) -> str:
    """Group label for one graded outcome: quick/deep + hold weeks.

    Old signals predating the hold-weeks input fall back to the graded
    horizon (e.g. ``deep-3d``) so they stay visible but separate.
    """
    tier = metadata.get("tier")
    tier_label = {1: "quick", 2: "deep"}.get(tier, "unknown")
    hold_weeks = metadata.get("hold_weeks")
    if hold_weeks:
        return f"{tier_label}-{hold_weeks}w"
    return f"{tier_label}-{getattr(row, 'horizon', '?')}"


def summarize_outcomes(
    rows: Sequence[Any],
    metadata_by_signal: Dict[int, Dict[str, Any]],
    aggregate: Callable[[List[Any]], Dict[str, Any]],
) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, Dict[str, Any]]]]:
    """Aggregate graded outcomes by variant and by conviction band."""
    by_variant: Dict[str, List[Any]] = defaultdict(list)
    by_band: Dict[str, List[Any]] = defaultdict(list)
    for row in rows:
        metadata = metadata_by_signal.get(int(row.signal_id), {})
        by_variant[variant_key(row, metadata)].append(row)
        band = metadata.get("score_band")
        if band:
            # Since 2026-08-10 the quick judge scores on the same 0-10
            # scale as the debate, so both tiers carry bands — keep the
            # tiers apart or the comparison is meaningless.
            tier_label = {1: "quick", 2: "deep"}.get(
                metadata.get("tier"), "unknown"
            )
            by_band[f"{tier_label} {band}"].append(row)
    variant_stats = sorted(
        (label, aggregate(bucket)) for label, bucket in by_variant.items()
    )
    band_stats = sorted(
        (label, aggregate(bucket)) for label, bucket in by_band.items()
    )
    return variant_stats, band_stats


#: Volatility lookback: ~3 months of daily bars ending on the signal
#: day; forward_metrics falls back to the fixed band below its minimum.
VOLATILITY_LOOKBACK_BARS = 70

#: Band used when a stock has too little history for its own sigma —
#: the shared grader's fixed band, so the fallback is never novel.
FALLBACK_BAND_PCT = 2.0


def enrich_graded_rows(
    rows: Sequence[Any],
    records_by_id: Dict[int, Any],
    metadata_by_signal: Dict[int, Dict[str, Any]],
    history_closes: Callable[[str, Any, int], List[Any]],
    forward_bars: Callable[[str, Any, int], List[Any]],
) -> List[Dict[str, Any]]:
    """Join each graded outcome with its signal and compute the
    experiment's own metrics: noise-band re-grade, direction-adjusted
    return, and (for buy calls) the plan simulations.

    Data access is injected (``history_closes(code, anchor, n)`` /
    ``forward_bars(code, anchor, days)``) so the logic tests offline.
    """
    from src.tiered_analysis.forward_metrics import (
        classify_outcome,
        daily_volatility_pct,
        directional_return_pct,
        noise_band_pct,
        simulate_plan,
    )

    sigma_cache: Dict[Tuple[str, Any], Optional[float]] = {}
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        signal_id = int(row.signal_id)
        record = records_by_id.get(signal_id)
        metadata = metadata_by_signal.get(signal_id, {})
        entry: Dict[str, Any] = {
            "variant": variant_key(row, metadata),
            "action": getattr(row, "action", None),
            "completed": getattr(row, "eval_status", None) == "completed",
            "plan_adjusted": bool(metadata.get("plan_adjusted")),
        }
        code = getattr(record, "stock_code", None)
        anchor = getattr(row, "anchor_date", None)
        eval_days = getattr(row, "eval_window_days", None)
        return_pct = getattr(row, "stock_return_pct", None)
        direction = getattr(row, "direction_expected", None)

        if entry["completed"] and code and anchor and eval_days:
            cache_key = (code, anchor)
            if cache_key not in sigma_cache:
                sigma_cache[cache_key] = daily_volatility_pct(
                    history_closes(code, anchor, VOLATILITY_LOOKBACK_BARS)
                )
            band = noise_band_pct(sigma_cache[cache_key], eval_days)
            entry["band_fallback"] = band is None
            band = band if band is not None else FALLBACK_BAND_PCT
            entry["band_pct"] = band
            outcome, _ = classify_outcome(direction, return_pct, band)
            entry["noise_outcome"] = outcome
            entry["edge_pct"] = directional_return_pct(direction, return_pct)

        # Trade plans only mean anything on calls you would enter.
        if entry["action"] == "buy" and code and anchor and eval_days:
            bars = forward_bars(code, anchor, eval_days)
            window_done = len(bars) >= eval_days
            plan = metadata.get("plan") or {}
            plan_sim = simulate_plan(
                plan.get("entry", getattr(record, "entry_high", None)),
                plan.get("stop_loss", getattr(record, "stop_loss", None)),
                plan.get("take_profit", getattr(record, "target_price", None)),
                bars,
            )
            if plan_sim.status in ("open", "no_entry") and not window_done:
                entry["plan_status"] = "waiting"
            else:
                entry["plan_status"] = plan_sim.status
                entry["plan_return_pct"] = plan_sim.return_pct
            base = metadata.get("base_plan") or {}
            if entry["plan_adjusted"] and base and window_done:
                base_sim = simulate_plan(
                    base.get("entry"),
                    base.get("stop_loss"),
                    base.get("take_profit"),
                    bars,
                )
                entry["base_status"] = base_sim.status
                entry["base_return_pct"] = base_sim.return_pct
        enriched.append(entry)
    return enriched


def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def summarize_noise(
    entries: Sequence[Dict[str, Any]],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Noise-band re-grade + mean direction-adjusted return, by variant."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if entry.get("noise_outcome") is not None:
            groups[entry["variant"]].append(entry)
    stats = []
    for label, bucket in sorted(groups.items()):
        hit = sum(1 for e in bucket if e["noise_outcome"] == "hit")
        miss = sum(1 for e in bucket if e["noise_outcome"] == "miss")
        neutral = sum(1 for e in bucket if e["noise_outcome"] == "neutral")
        edges = [
            e["edge_pct"] for e in bucket if e.get("edge_pct") is not None
        ]
        stats.append((label, {
            "n": len(bucket),
            "hit": hit,
            "miss": miss,
            "neutral": neutral,
            "hit_rate_pct": (
                round(hit / (hit + miss) * 100, 1) if hit + miss else None
            ),
            "avg_edge_pct": _mean(edges),
            "edge_n": len(edges),
            "fallback_bands": sum(
                1 for e in bucket if e.get("band_fallback")
            ),
        }))
    return stats


def summarize_plans(
    entries: Sequence[Dict[str, Any]],
) -> Tuple[List[Tuple[str, Dict[str, Any]]], Dict[str, Any]]:
    """Plan-vs-reality by variant, plus the paired adjusted-vs-formula
    comparison pooled across variants (adjustments are rare)."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if entry.get("plan_status") is not None:
            groups[entry["variant"]].append(entry)
    stats = []
    for label, bucket in sorted(groups.items()):
        counts = {
            status: sum(1 for e in bucket if e["plan_status"] == status)
            for status in (
                "target", "stop", "open", "no_entry", "ambiguous",
                "waiting", "invalid",
            )
        }
        returns = [
            e["plan_return_pct"] for e in bucket
            if e.get("plan_return_pct") is not None
        ]
        stats.append((label, {
            "n": len(bucket),
            **counts,
            "avg_return_pct": _mean(returns),
        }))

    pairs = [
        e for e in entries
        if e.get("base_status") is not None
        and e.get("plan_status") not in (None, "waiting")
    ]
    comparable = [
        e for e in pairs
        if e.get("plan_return_pct") is not None
        and e.get("base_return_pct") is not None
    ]
    adjustments = {
        "pairs": len(pairs),
        "comparable": len(comparable),
        "adjusted_avg_pct": _mean(
            [e["plan_return_pct"] for e in comparable]
        ),
        "formula_avg_pct": _mean(
            [e["base_return_pct"] for e in comparable]
        ),
        "better": sum(
            1 for e in comparable
            if e["plan_return_pct"] > e["base_return_pct"]
        ),
        "worse": sum(
            1 for e in comparable
            if e["plan_return_pct"] < e["base_return_pct"]
        ),
        "tie": sum(
            1 for e in comparable
            if e["plan_return_pct"] == e["base_return_pct"]
        ),
    }
    return stats, adjustments


def _print_stats_table(title: str, stats: List[Tuple[str, Dict[str, Any]]]) -> None:
    print(f"\n{title}")
    if not stats:
        print("  (no graded outcomes yet — signals grade once their hold "
              "window has passed)")
        return
    header = (
        f"  {'group':<12}{'graded':>7}{'wins':>6}{'losses':>8}{'flat':>6}"
        f"{'waiting':>9}{'hit rate':>10}{'avg return':>12}"
    )
    print(header)
    for label, agg in stats:
        hit_rate = (
            f"{agg['hit_rate_pct']}%" if agg["hit_rate_pct"] is not None else "-"
        )
        avg_return = (
            f"{agg['avg_stock_return_pct']}%"
            if agg["avg_stock_return_pct"] is not None else "-"
        )
        print(
            f"  {label:<12}{agg['completed']:>7}{agg['hit']:>6}"
            f"{agg['miss']:>8}{agg['neutral']:>6}{agg['unable']:>9}"
            f"{hit_rate:>10}{avg_return:>12}"
        )


def _print_noise_table(stats: List[Tuple[str, Dict[str, Any]]]) -> None:
    print(
        "\nNoise-adjusted — same outcomes, but the band is each stock's "
        "own wobble x sqrt(window):"
    )
    if not stats:
        print("  (no completed outcomes yet)")
        return
    print(
        f"  {'group':<12}{'graded':>7}{'wins':>6}{'losses':>8}{'flat':>6}"
        f"{'hit rate':>10}{'avg edge':>10}"
    )
    fallbacks = 0
    for label, agg in stats:
        hit_rate = (
            f"{agg['hit_rate_pct']}%" if agg["hit_rate_pct"] is not None else "-"
        )
        edge = (
            f"{agg['avg_edge_pct']:+}%"
            if agg["avg_edge_pct"] is not None else "-"
        )
        fallbacks += agg["fallback_bands"]
        print(
            f"  {label:<12}{agg['n']:>7}{agg['hit']:>6}{agg['miss']:>8}"
            f"{agg['neutral']:>6}{hit_rate:>10}{edge:>10}"
        )
    print(
        "  'avg edge' = mean return earned by following the calls (sell "
        "calls flip sign; holds excluded — they predict no direction)."
    )
    if fallbacks:
        print(
            f"  {fallbacks} outcome(s) used the fixed ±{FALLBACK_BAND_PCT}% "
            "band (not enough price history for the stock's own wobble)."
        )


def _print_plan_tables(
    stats: List[Tuple[str, Dict[str, Any]]], adjustments: Dict[str, Any]
) -> None:
    print(
        "\nTrade plans vs reality — buy calls only (a plan is only a "
        "trade if you would enter):"
    )
    if not stats:
        print("  (no graded buy calls yet)")
    else:
        print(
            f"  {'group':<12}{'buys':>6}{'target':>8}{'stop':>6}{'open':>6}"
            f"{'no-entry':>10}{'unclear':>9}{'waiting':>9}{'avg return':>12}"
        )
        for label, agg in stats:
            avg = (
                f"{agg['avg_return_pct']:+}%"
                if agg["avg_return_pct"] is not None else "-"
            )
            print(
                f"  {label:<12}{agg['n']:>6}{agg['target']:>8}"
                f"{agg['stop']:>6}{agg['open']:>6}{agg['no_entry']:>10}"
                f"{agg['ambiguous'] + agg['invalid']:>9}{agg['waiting']:>9}"
                f"{avg:>12}"
            )
        print(
            "  target/stop = which line the price struck first; open = "
            "entered but neither struck (graded at the window's last "
            "close); unclear = one day crossed both lines, daily bars "
            "cannot order that."
        )

    print("\nAI plan adjustments vs the formula plan (paired, same runs):")
    if not adjustments["pairs"]:
        print(
            "  (no adjusted plans graded yet — adjustments only happen "
            "when a plan check fires on a buy call)"
        )
        return
    adjusted_avg = (
        f"{adjustments['adjusted_avg_pct']:+}%"
        if adjustments["adjusted_avg_pct"] is not None else "-"
    )
    formula_avg = (
        f"{adjustments['formula_avg_pct']:+}%"
        if adjustments["formula_avg_pct"] is not None else "-"
    )
    print(
        f"  {adjustments['pairs']} adjusted plan(s) graded, "
        f"{adjustments['comparable']} with a comparable paired return: "
        f"adjusted avg {adjusted_avg} vs formula avg {formula_avg} — "
        f"adjusted better {adjustments['better']}, worse "
        f"{adjustments['worse']}, tied {adjustments['tie']}."
    )


def print_summary(service) -> None:
    """The scoreboards: all tiered-analysis outcomes graded so far."""
    from src.services.decision_signal_outcome_service import (
        DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
        DEFAULT_STATS_STATUSES,
        DecisionSignalOutcomeService,
    )
    from src.tiered_analysis.signal_log import SOURCE_AGENT

    rows = [
        row
        for row in service.repo.list_stats_rows(
            engine_version=DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
            horizons=None,
            statuses=list(DEFAULT_STATS_STATUSES),
        )
        if row.source_agent == SOURCE_AGENT
    ]
    signal_ids = sorted({int(row.signal_id) for row in rows})
    records_by_id = {
        int(signal.id): signal
        for signal in service.signal_repo.list_by_ids(signal_ids)
    }
    metadata_by_signal = {
        signal_id: _signal_metadata(record.metadata_json)
        for signal_id, record in records_by_id.items()
    }
    # The service's own aggregator keeps hit-rate semantics identical to
    # the stats API (hit rate = wins / (wins + losses); flat excluded).
    variant_stats, band_stats = summarize_outcomes(
        rows, metadata_by_signal, DecisionSignalOutcomeService._aggregate
    )
    enriched = enrich_graded_rows(
        rows,
        records_by_id,
        metadata_by_signal,
        history_closes=lambda code, anchor, n: [
            bar.close for bar in service.stock_repo.get_history_bars(
                code=code, end_date=anchor, limit=n
            )
        ],
        forward_bars=lambda code, anchor, days: service.stock_repo.get_forward_bars(
            code=code, analysis_date=anchor, eval_window_days=days
        ),
    )
    print(f"\n{BAR}")
    print("Forward-test scoreboard (all tiered runs graded so far)")
    print(BAR)
    _print_stats_table(
        "By variant — does the deep tier beat quick? which hold works best?"
        " (shared grader, fixed ±2% band)",
        variant_stats,
    )
    _print_stats_table(
        "By conviction band — do the AI's 8-10 calls beat its 6-8 calls?",
        band_stats,
    )
    _print_noise_table(summarize_noise(enriched))
    plan_stats, adjustments = summarize_plans(enriched)
    _print_plan_tables(plan_stats, adjustments)
    print(
        "\n'waiting' counts signals the grader could not score yet, mostly "
        "because their hold window has not finished. Judge nothing under "
        "~30 graded per group."
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the daily tiered forward-test grid, grade matured "
        "signals, and print the scoreboard."
    )
    parser.add_argument(
        "symbols", nargs="*",
        help=f"watchlist override (default: {' '.join(WATCHLIST)})",
    )
    parser.add_argument(
        "--summary-only", action="store_true",
        help="skip today's LLM runs; just grade matured signals and show "
        "the scoreboard (costs no LLM tokens)",
    )
    parser.add_argument(
        "--check", nargs="?", const="today", metavar="DATE",
        help="verify a day's runs: list that day's logged signals and "
        "flag missing grid cells (default: today, or pass YYYY-MM-DD)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-run grid cells even if they already logged a signal "
        "today (default: skip them, so an interrupted day resumes "
        "without re-spending tokens)",
    )
    parser.add_argument(
        "--no-backfill", action="store_true",
        help="skip the daily-bar fetch before grading (offline mode; "
        "grading then only sees bars already stored)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    symbols = args.symbols or WATCHLIST
    run_date = date.today().isoformat()

    if args.check:
        check_date = run_date if args.check == "today" else args.check
        return check_runs(check_date)

    if not args.summary_only:
        grid_text = ", ".join(variant_label(d, h) for d, h in VARIANTS)
        print(f"Forward test {run_date}: {len(symbols)} symbols x "
              f"[{grid_text}] = {len(symbols) * len(VARIANTS)} runs")
        skip_traces = set() if args.force else existing_trace_ids(run_date)
        if skip_traces:
            print(f"Resume: {len(skip_traces)} cell(s) already logged a "
                  "signal today and will be skipped.")
        results = run_grid(symbols, VARIANTS, run_date, skip_traces=skip_traces)
        failures = [row for row in results if not row["ok"]]
        if failures:
            print(f"\n{len(failures)} run(s) failed — they simply log no "
                  "signal today; tomorrow's run tries again.")

    if not args.no_backfill:
        backfill_daily_bars()
    service = grade_matured_signals()
    print_summary(service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
