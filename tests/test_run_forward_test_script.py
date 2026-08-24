# -*- coding: utf-8 -*-
"""Offline tests for scripts/run_forward_test.py (the daily forward-test
driver): grid contract, trace identity, failure tolerance, grouping."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

run_forward_test = importlib.import_module("run_forward_test")


def test_grid_variants_are_valid_pipeline_inputs():
    from src.tiered_analysis.integration import SUPPORTED_DEPTHS
    from src.tiered_analysis.schema import HOLD_WEEKS_CHOICES

    for depth, hold_weeks in run_forward_test.VARIANTS:
        assert depth in SUPPORTED_DEPTHS
        assert hold_weeks in HOLD_WEEKS_CHOICES


def test_trace_ids_are_unique_per_day_symbol_and_variant():
    traces = {
        run_forward_test.build_trace_id(day, symbol, depth, hold)
        for day in ("2026-08-08", "2026-08-09")
        for symbol in ("AAPL", "600519")
        for depth, hold in run_forward_test.VARIANTS
    }
    assert len(traces) == 2 * 2 * len(run_forward_test.VARIANTS)


def test_trace_id_fits_the_64_char_column():
    trace = run_forward_test.build_trace_id(
        "2026-08-08", "AVERYLONGTICKERSYMBOLNAMEXXXXXXXXXXXXXXXXXXXXXXXXXXX", 2, 4
    )
    assert len(trace) <= 64


def test_parse_trace_id_inverts_build_trace_id():
    trace = run_forward_test.build_trace_id("2026-08-08", "AAPL", 2, 3)
    assert run_forward_test.parse_trace_id(trace) == ("2026-08-08", "aapl", 2, 3)


def test_parse_trace_id_rejects_foreign_traces():
    assert run_forward_test.parse_trace_id("alert-rule-abc123") is None
    assert run_forward_test.parse_trace_id("") is None
    assert run_forward_test.parse_trace_id("fwdtest-2026-08-08-aapl") is None


def test_variant_label_names_quick_and_deep():
    assert run_forward_test.variant_label(2, 1) == "deep-1w"
    assert run_forward_test.variant_label(1, 2) == "quick-2w"


def _fake_outcome():
    # The script must read final_report (the verdict-carrying report on
    # deep runs); the foundation report is verdict-free at depth 2.
    verdict_report = SimpleNamespace(
        direction=SimpleNamespace(value="buy"),
        debate_detail={"verdict": {"final_score": 7.5}},
        levels=SimpleNamespace(
            entry=100.0, stop_loss=95.0, take_profit=110.0
        ),
        levels_detail=None,
    )
    foundation_report = SimpleNamespace(
        direction=SimpleNamespace(value="unknown"),
        debate_detail=None,
        levels=verdict_report.levels,
        levels_detail=None,
    )
    return SimpleNamespace(
        report=foundation_report,
        final_report=verdict_report,
        signal=SimpleNamespace(
            logged=True, signal_id=42, created=True, reason=None
        ),
    )


def test_run_grid_threads_variant_inputs_into_the_runner():
    calls = []

    def runner(symbol, *, depth, hold_weeks, trace_id):
        calls.append((symbol, depth, hold_weeks, trace_id))
        return _fake_outcome()

    results = run_forward_test.run_grid(
        ["AAPL"], [(2, 1), (1, 2)], "2026-08-08", runner=runner
    )

    assert calls == [
        ("AAPL", 2, 1, "fwdtest-2026-08-08-aapl-d2-h1"),
        ("AAPL", 1, 2, "fwdtest-2026-08-08-aapl-d1-h2"),
    ]
    assert all(row["ok"] for row in results)
    assert results[0]["final_score"] == 7.5
    assert results[0]["signal_id"] == 42


def test_run_grid_flags_ai_adjusted_plans():
    outcome = _fake_outcome()
    outcome.final_report.levels_detail = {"levels": {
        "entry": {"base": 100.0, "final": 100.0},
        "stop_loss": {"base": 93.0, "final": 95.0},  # AI moved the stop
        "take_profit": {"base": 110.0, "final": 110.0},
    }}

    results = run_forward_test.run_grid(
        ["AAPL"], [(2, 1)], "2026-08-08", runner=lambda *a, **k: outcome
    )

    assert results[0]["plan_adjusted"] is True


def test_run_grid_resumes_by_skipping_already_logged_cells():
    calls = []

    def runner(symbol, *, depth, hold_weeks, trace_id):
        calls.append(trace_id)
        return _fake_outcome()

    already_done = {run_forward_test.build_trace_id("2026-08-08", "AAPL", 2, 1)}
    results = run_forward_test.run_grid(
        ["AAPL"], [(2, 1), (1, 2)], "2026-08-08",
        runner=runner, skip_traces=already_done,
    )

    # The finished cell never reaches the runner (no tokens spent).
    assert calls == ["fwdtest-2026-08-08-aapl-d1-h2"]
    assert results[0]["skipped"] is True
    assert results[0]["ok"] is True
    assert "skipped" not in results[1]


def test_run_grid_without_skip_set_runs_everything():
    calls = []

    def runner(symbol, **kwargs):
        calls.append(symbol)
        return _fake_outcome()

    run_forward_test.run_grid(
        ["AAPL"], [(2, 1), (1, 2)], "2026-08-08", runner=runner
    )
    assert len(calls) == 2


def test_run_grid_records_a_failed_run_and_keeps_going():
    def runner(symbol, **kwargs):
        if symbol == "BAD":
            raise RuntimeError("provider down")
        return _fake_outcome()

    results = run_forward_test.run_grid(
        ["BAD", "AAPL"], [(2, 2)], "2026-08-08", runner=runner
    )

    assert [row["ok"] for row in results] == [False, True]
    assert "provider down" in results[0]["error"]


def test_shared_runner_fetches_each_symbols_dimensions_once(monkeypatch):
    from src.tiered_analysis import integration

    fetched = []
    dims = [SimpleNamespace(dimension="technicals", kind="numeric")]

    def fake_collect(symbol, market=None):
        fetched.append(symbol)
        return dims

    ran = []

    def fake_run(symbol, **kwargs):
        ran.append((symbol, kwargs["depth"], kwargs["hold_weeks"]))
        # The gate must stay on despite injected providers, and every
        # provider must serve the shared snapshot unchanged.
        assert kwargs["staleness_gate"] is True
        assert [p.collect(symbol) for p in kwargs["providers"]] == dims
        return _fake_outcome()

    monkeypatch.setattr(integration, "collect_dimensions_once", fake_collect)
    monkeypatch.setattr(integration, "run_tiered_analysis", fake_run)

    runner = run_forward_test.make_shared_dimension_runner()
    runner("NVDA", depth=2, hold_weeks=1, trace_id="t1")
    runner("NVDA", depth=1, hold_weeks=2, trace_id="t2")
    runner("KO", depth=1, hold_weeks=1, trace_id="t3")

    assert fetched == ["NVDA", "KO"]  # one fetch per symbol, not per cell
    assert len(ran) == 3


def test_shared_runner_retries_a_failed_fetch(monkeypatch):
    import pytest

    from src.tiered_analysis import integration

    attempts = []

    def flaky_collect(symbol, market=None):
        attempts.append(symbol)
        if len(attempts) == 1:
            raise RuntimeError("network down")
        return [SimpleNamespace(dimension="technicals", kind="numeric")]

    monkeypatch.setattr(integration, "collect_dimensions_once", flaky_collect)
    monkeypatch.setattr(
        integration, "run_tiered_analysis",
        lambda symbol, **kwargs: _fake_outcome(),
    )

    runner = run_forward_test.make_shared_dimension_runner()
    with pytest.raises(RuntimeError):
        runner("NVDA", depth=2, hold_weeks=1, trace_id="t1")
    # The failure was not cached: the symbol's next cell refetches.
    runner("NVDA", depth=1, hold_weeks=1, trace_id="t2")
    assert attempts == ["NVDA", "NVDA"]


def test_variant_key_prefers_hold_weeks_and_falls_back_to_horizon():
    row = SimpleNamespace(horizon="3d")
    assert run_forward_test.variant_key(row, {"tier": 2, "hold_weeks": 4}) == "deep-4w"
    assert run_forward_test.variant_key(row, {"tier": 1, "hold_weeks": 2}) == "quick-2w"
    assert run_forward_test.variant_key(row, {"tier": 2}) == "deep-3d"
    assert run_forward_test.variant_key(row, {}) == "unknown-3d"


def _outcome_row(
    signal_id=1,
    horizon="5d",
    action="buy",
    direction="up",
    return_pct=8.0,
    eval_status="completed",
    eval_days=5,
):
    return SimpleNamespace(
        signal_id=signal_id,
        horizon=horizon,
        action=action,
        direction_expected=direction,
        stock_return_pct=return_pct,
        eval_status=eval_status,
        eval_window_days=eval_days,
        anchor_date="2026-08-10",
    )


def _record(entry_high=100.0, stop_loss=95.0, target_price=110.0):
    return SimpleNamespace(
        stock_code="AAPL",
        entry_high=entry_high,
        stop_loss=stop_loss,
        target_price=target_price,
    )


def _flat_history(code, anchor, n):
    # ~0.5% daily wobble -> noise band ~= 0.5 * sqrt(5) ~= 1.1% at 5d
    closes, price = [], 100.0
    for i in range(n):
        price *= 1.005 if i % 2 else 0.995
        closes.append(price)
    return closes


def test_enrich_reclassifies_with_the_stock_specific_band():
    rows = [_outcome_row(return_pct=1.5)]  # inside ±2%, outside ~1.1%
    records = {1: _record()}
    metadata = {1: {"tier": 2, "hold_weeks": 1}}

    enriched = run_forward_test.enrich_graded_rows(
        rows, records, metadata,
        history_closes=_flat_history,
        forward_bars=lambda code, anchor, days: [],
    )

    entry = enriched[0]
    assert entry["variant"] == "deep-1w"
    assert entry["band_pct"] < 2.0  # the calm stock earned a tighter band
    assert entry["noise_outcome"] == "hit"  # 1.5% beats its own noise
    assert entry["edge_pct"] == 1.5


def test_enrich_simulates_the_saved_plan_for_buy_calls():
    bars = [
        SimpleNamespace(low=99.0, high=101.0, close=100.5),
        SimpleNamespace(low=100.0, high=111.0, close=110.0),
    ]
    rows = [_outcome_row(eval_days=2)]
    records = {1: _record()}
    metadata = {1: {
        "tier": 2, "hold_weeks": 1,
        "plan": {"entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
    }}

    enriched = run_forward_test.enrich_graded_rows(
        rows, records, metadata,
        history_closes=_flat_history,
        forward_bars=lambda code, anchor, days: bars,
    )

    assert enriched[0]["plan_status"] == "target"
    assert enriched[0]["plan_return_pct"] == 10.0


def test_enrich_marks_unfinished_plan_windows_as_waiting():
    bars = [SimpleNamespace(low=99.0, high=101.0, close=100.5)]  # 1 of 5 days
    rows = [_outcome_row(eval_days=5, eval_status="unable", return_pct=None)]
    records = {1: _record()}
    metadata = {1: {"tier": 1, "hold_weeks": 1}}

    enriched = run_forward_test.enrich_graded_rows(
        rows, records, metadata,
        history_closes=_flat_history,
        forward_bars=lambda code, anchor, days: bars,
    )

    assert enriched[0]["plan_status"] == "waiting"
    assert "noise_outcome" not in enriched[0]


def test_enrich_pairs_adjusted_and_formula_plans():
    # Adjusted stop 97 survives to the target; formula stop 99.5 is hit.
    bars = [
        SimpleNamespace(low=100.0, high=101.0, close=100.5),
        SimpleNamespace(low=99.0, high=101.0, close=100.0),
        SimpleNamespace(low=100.0, high=111.0, close=110.0),
    ]
    rows = [_outcome_row(eval_days=3)]
    records = {1: _record()}
    metadata = {1: {
        "tier": 2, "hold_weeks": 1,
        "plan": {"entry": 100.0, "stop_loss": 97.0, "take_profit": 110.0},
        "base_plan": {"entry": 100.0, "stop_loss": 99.5, "take_profit": 110.0},
        "plan_adjusted": True,
    }}

    enriched = run_forward_test.enrich_graded_rows(
        rows, records, metadata,
        history_closes=_flat_history,
        forward_bars=lambda code, anchor, days: bars,
    )

    entry = enriched[0]
    assert entry["plan_status"] == "target"
    assert entry["base_status"] == "stop"

    _, adjustments = run_forward_test.summarize_plans(enriched)
    assert adjustments["pairs"] == 1
    assert adjustments["comparable"] == 1
    assert adjustments["better"] == 1


def test_summarize_noise_excludes_holds_from_the_edge_column():
    entries = [
        {"variant": "deep-1w", "noise_outcome": "hit", "edge_pct": 5.0},
        {"variant": "deep-1w", "noise_outcome": "miss", "edge_pct": -3.0},
        {"variant": "deep-1w", "noise_outcome": "hit", "edge_pct": None},  # hold
    ]
    stats = run_forward_test.summarize_noise(entries)
    assert stats == [("deep-1w", {
        "n": 3, "hit": 2, "miss": 1, "neutral": 0,
        "hit_rate_pct": 66.7, "avg_edge_pct": 1.0, "edge_n": 2,
        "fallback_bands": 0,
    })]


def test_summarize_outcomes_groups_by_variant_and_conviction_band():
    rows = [
        SimpleNamespace(signal_id=1, horizon="5d"),
        SimpleNamespace(signal_id=2, horizon="10d"),
        SimpleNamespace(signal_id=3, horizon="10d"),
    ]
    metadata = {
        1: {"tier": 2, "hold_weeks": 1, "score_band": "6-8"},
        2: {"tier": 2, "hold_weeks": 2, "score_band": "6-8"},
        3: {"tier": 1, "hold_weeks": 2, "score_band": "6-8"},
    }

    variant_stats, band_stats = run_forward_test.summarize_outcomes(
        rows, metadata, aggregate=len
    )

    assert dict(variant_stats) == {"deep-1w": 1, "deep-2w": 1, "quick-2w": 1}
    # Bands keep the tiers apart — quick and deep 6-8 are different claims.
    assert dict(band_stats) == {"deep 6-8": 2, "quick 6-8": 1}
