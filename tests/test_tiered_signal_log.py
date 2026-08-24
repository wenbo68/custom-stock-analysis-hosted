# -*- coding: utf-8 -*-
"""Offline tests for the tier-report signal log adapter (slice 6).

Slice 6 does NOT build a parallel recommendation log: DSA already has the
decision_signals table (+ outcome evaluation job that fetches the forward
price path). The adapter under test converts a TierReport into a valid
decision-signal payload and submits it via DecisionSignalService as a
client. The run's warnings ride in data_quality_summary, which the
existing web signals page already renders (coverage grades retired
2026-08-19).

The end-to-end tests write through the REAL DecisionSignalService into an
isolated temp sqlite DB (repo's established fixture pattern) — that is
what verifies our payload satisfies the service's enum contracts.
"""
from __future__ import annotations

import json
import os

import pytest

from src.tiered_analysis.providers.base import (
    Citation,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.signal_log import (
    SignalLogResult,
    build_signal_payload,
    coerce_confidence,
    log_tier_report,
)


def _dimension(name="technicals", kind=SourceKind.NUMERIC,
               payload=None, citations=None):
    return DimensionResult(
        dimension=name,
        kind=kind,
        payload=payload if payload is not None else {"score": 62},
        citations=citations,
    )


def _report(**overrides):
    fields = dict(
        tier=1,
        symbol="AAPL",
        market=Market.US,
        direction=Direction.BUY,
        confidence="0.72",
        score=83,
        levels=SniperLevels(
            entry=210.0, secondary_entry=205.5, stop_loss=198.0, take_profit=232.0
        ),
        narrative="Uptrend intact; buy pullbacks.",
        dimensions=[_dimension()],
        warnings=[],
    )
    fields.update(overrides)
    return TierReport(**fields)


class TestCoerceConfidence:
    def test_fraction_passes_through(self):
        assert coerce_confidence("0.72") == pytest.approx(0.72)
        assert coerce_confidence(0.5) == pytest.approx(0.5)

    def test_percent_scale_is_normalized(self):
        assert coerce_confidence(83) == pytest.approx(0.83)
        assert coerce_confidence("100") == pytest.approx(1.0)

    def test_text_and_out_of_range_become_none(self):
        assert coerce_confidence("高") is None
        assert coerce_confidence(None) is None
        assert coerce_confidence(-3) is None
        assert coerce_confidence(250) is None


class TestBuildSignalPayload:
    def test_happy_path_mapping(self):
        payload, skip = build_signal_payload(_report(), trace_id="trace-1")
        assert skip is None
        assert payload["stock_code"] == "AAPL"
        assert payload["market"] == "us"
        assert payload["source_type"] == "agent"
        assert payload["source_agent"] == "tiered_analysis"
        assert payload["trigger_source"] == "tiered_analysis"
        assert payload["trace_id"] == "trace-1"
        assert payload["action"] == "buy"
        assert payload["confidence"] == pytest.approx(0.72)
        assert payload["score"] == 83
        # entry_low/high are the sorted pair of the two entry levels
        assert payload["entry_low"] == pytest.approx(205.5)
        assert payload["entry_high"] == pytest.approx(210.0)
        assert payload["stop_loss"] == pytest.approx(198.0)
        assert payload["target_price"] == pytest.approx(232.0)
        assert payload["reason"] == "Uptrend intact; buy pullbacks."
        assert payload["metadata"]["tier"] == 1
        assert payload["metadata"]["sizing_empty"] is True

    def test_filled_sizing_slots_reach_metadata(self):
        # Slice 6: the ledger records the position the user actually saw.
        from src.tiered_analysis.schema import SizingSlots

        report = _report(sizing=SizingSlots(capital=100000.0,
                                            risk_fraction=0.01, shares=83.0))
        payload, _ = build_signal_payload(report)
        assert payload["metadata"]["sizing_empty"] is False
        assert payload["metadata"]["sizing"] == {
            "capital": 100000.0, "risk_fraction": 0.01, "shares": 83.0,
        }

    def test_zero_shares_is_recorded_not_omitted(self):
        from src.tiered_analysis.schema import SizingSlots

        report = _report(sizing=SizingSlots(capital=100000.0,
                                            risk_fraction=0.01, shares=0.0))
        payload, _ = build_signal_payload(report)
        assert payload["metadata"]["sizing"]["shares"] == 0.0

    def test_data_quality_summary_is_only_the_warnings_list(self):
        # Coverage grades are retired (2026-08-19): no level, no coverage,
        # no per-dimension badges — the summary is exactly the warnings.
        payload, _ = build_signal_payload(
            _report(warnings=["one source degraded", "one page blocked"])
        )
        assert payload["data_quality_summary"] == {
            "warnings": ["one source degraded", "one page blocked"],
        }

    def test_evidence_is_actionable_gates_on_kind_and_payload(self):
        # is_actionable is the only numeric gate now: NUMERIC with a
        # payload is actionable; a NUMERIC dimension whose payload is
        # missing is not; TEXTUAL never is.
        report = _report(dimensions=[
            _dimension("technicals"),  # NUMERIC + payload
            DimensionResult(dimension="fundamentals",
                            kind=SourceKind.NUMERIC, payload=None),
            DimensionResult(dimension="sentiment",
                            kind=SourceKind.TEXTUAL,
                            narrative="Sentiment: mixed."),
        ])
        payload, _ = build_signal_payload(report)
        flags = {e["dimension"]: e["is_actionable"]
                 for e in payload["evidence"]["dimensions"]}
        assert flags == {
            "technicals": True,
            "fundamentals": False,
            "sentiment": False,
        }
        # and no evidence entry carries a coverage badge any more
        assert all(
            "coverage" not in e for e in payload["evidence"]["dimensions"]
        )

    def test_sentiment_citations_land_in_evidence(self):
        citation = Citation(
            source_name="Reuters", url="https://reuters.example/x",
            title="Reuters", snippet="quote",
        )
        report = _report(dimensions=[
            _dimension("sentiment", kind=SourceKind.TEXTUAL,
                       payload=None,
                       citations=[citation]),
        ])
        payload, _ = build_signal_payload(report)
        entries = payload["evidence"]["dimensions"]
        assert entries[0]["dimension"] == "sentiment"
        assert entries[0]["citations"] == ["https://reuters.example/x"]
        # TEXTUAL never feeds sizing; the flag must survive into evidence.
        assert entries[0]["is_actionable"] is False

    def test_dimension_payloads_and_narrative_land_in_evidence(self):
        # The web signal detail must show the full four-dimension reports.
        citation = Citation(
            source_name="Reuters", url="https://reuters.example/x",
            title="Reuters", snippet="quote",
        )
        report = _report(dimensions=[
            _dimension("fundamentals", payload={"growth": {"revenue_yoy_pct": 6.4}}),
            DimensionResult(
                dimension="sentiment", kind=SourceKind.TEXTUAL,
                narrative="Sentiment: mixed. Two-sided news flow.",
                citations=[citation],
                warnings=["one page blocked"],
            ),
        ])
        payload, _ = build_signal_payload(report)
        entries = {e["dimension"]: e for e in payload["evidence"]["dimensions"]}
        assert entries["fundamentals"]["payload"] == {
            "growth": {"revenue_yoy_pct": 6.4}
        }
        assert "payload" not in entries["sentiment"]  # textual has none
        assert entries["sentiment"]["narrative"].startswith("Sentiment: mixed")
        assert entries["sentiment"]["warnings"] == ["one page blocked"]

    def test_urlless_citation_falls_back_to_source_name(self):
        # Numeric sources (e.g. price bars) cite a source name, not a URL —
        # evidence must never contain a bare null.
        citation = Citation(source_name="ohlcv-bars")
        report = _report(dimensions=[
            _dimension("technicals", citations=[citation]),
        ])
        payload, _ = build_signal_payload(report)
        assert payload["evidence"]["dimensions"][0]["citations"] == ["ohlcv-bars"]

    def test_warnings_are_capped(self):
        report = _report(warnings=[f"warning {i}" for i in range(50)])
        payload, _ = build_signal_payload(report)
        assert len(payload["data_quality_summary"]["warnings"]) == 20

    def test_unknown_direction_is_skipped(self):
        payload, skip = build_signal_payload(_report(direction=Direction.UNKNOWN))
        assert payload is None
        assert "direction" in skip

    def test_unknown_market_is_skipped(self):
        payload, skip = build_signal_payload(_report(market=Market.UNKNOWN))
        assert payload is None
        assert "market" in skip

    def test_final_plan_always_rides_in_metadata(self):
        payload, _ = build_signal_payload(_report())
        assert payload["metadata"]["plan"] == {
            "entry": 210.0, "stop_loss": 198.0, "take_profit": 232.0,
        }

    def test_base_plan_and_adjusted_flag_from_the_audit_trail(self):
        detail = {"levels": {
            "entry": {"base": 210.0, "final": 210.0},
            "stop_loss": {"base": 195.0, "final": 198.0},  # AI moved it
            "take_profit": {"base": 232.0, "final": 232.0},
        }}
        payload, _ = build_signal_payload(_report(levels_detail=detail))
        assert payload["metadata"]["base_plan"] == {
            "entry": 210.0, "stop_loss": 195.0, "take_profit": 232.0,
        }
        assert payload["metadata"]["plan_adjusted"] is True

    def test_untouched_plan_is_not_flagged_adjusted(self):
        detail = {"levels": {
            "entry": {"base": 210.0, "final": 210.0},
            "stop_loss": {"base": 198.0, "final": 198.0},
            "take_profit": {"base": 232.0, "final": 232.0},
        }}
        payload, _ = build_signal_payload(_report(levels_detail=detail))
        assert payload["metadata"]["plan_adjusted"] is False

    def test_no_audit_trail_means_no_base_plan_keys(self):
        payload, _ = build_signal_payload(_report())
        assert "base_plan" not in payload["metadata"]
        assert "plan_adjusted" not in payload["metadata"]

    def test_missing_levels_stay_none(self):
        payload, skip = build_signal_payload(_report(levels=SniperLevels()))
        assert skip is None
        assert payload["entry_low"] is None
        assert payload["entry_high"] is None
        assert payload["stop_loss"] is None
        assert payload["target_price"] is None


class TestLogTierReport:
    def test_logs_via_injected_service(self):
        captured = {}

        class FakeService:
            def create_signal(self, payload):
                captured.update(payload)
                return {"item": {"id": 42}, "created": True}

        result = log_tier_report(_report(), service=FakeService())
        assert isinstance(result, SignalLogResult)
        assert result.logged is True
        assert result.signal_id == 42
        assert result.created is True
        assert captured["stock_code"] == "AAPL"

    def test_skip_reports_are_not_sent(self):
        class ExplodingService:
            def create_signal(self, payload):
                raise AssertionError("must not be called")

        result = log_tier_report(
            _report(direction=Direction.UNKNOWN), service=ExplodingService()
        )
        assert result.logged is False
        assert "direction" in result.reason

    def test_service_failure_never_raises(self):
        class BrokenService:
            def create_signal(self, payload):
                raise RuntimeError("db locked")

        result = log_tier_report(_report(), service=BrokenService())
        assert result.logged is False
        assert "db locked" in result.reason


@pytest.fixture()
def isolated_db(tmp_path):
    """Repo-standard isolated sqlite DB (see tests/test_decision_signal_service.py)."""
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "tiered_signal_log.db"
    os.environ["DATABASE_PATH"] = str(db_path)
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


class TestEndToEndWithRealService:
    def test_payload_satisfies_real_service_contract(self, isolated_db):
        from sqlalchemy import select

        from src.storage import DecisionSignalRecord

        result = log_tier_report(_report(), trace_id="tier-e2e-1")
        assert result.logged is True, result.reason
        assert result.created is True

        with isolated_db.get_session() as session:
            row = session.execute(select(DecisionSignalRecord)).scalars().one()
        assert row.stock_code == "AAPL"
        assert row.market == "us"
        assert row.source_type == "agent"
        assert row.source_agent == "tiered_analysis"
        assert row.action == "buy"
        assert row.status == "active"  # outcome job picks up active signals
        assert row.entry_low == pytest.approx(205.5)
        assert row.target_price == pytest.approx(232.0)
        quality = json.loads(row.data_quality_summary_json)
        # warnings-only contract survives the round-trip through the DB
        assert quality == {"warnings": []}

    def test_same_report_twice_is_not_duplicated(self, isolated_db):
        first = log_tier_report(_report(), trace_id="tier-dup-1")
        second = log_tier_report(_report(), trace_id="tier-dup-1")
        assert first.logged is True and first.created is True
        assert second.logged is True
        assert second.created is False  # existing signal reused, no dup row


class TestScoreBand:
    """The five score groups (owner decision 2026-08-08), aligned with
    the debate's sell (<4) and buy (>6) verdict cutoffs."""

    @pytest.mark.parametrize(
        "score,band",
        [
            (0, "0-2"), (1.99, "0-2"),
            (2, "2-4"), (3.99, "2-4"),
            (4, "4-6"), (6, "4-6"),
            (6.01, "6-8"), (8, "6-8"),
            (8.01, "8-10"), (10, "8-10"),
        ],
    )
    def test_band_edges(self, score, band):
        from src.tiered_analysis.signal_log import score_band

        assert score_band(score) == band

    def test_out_of_range_and_missing_are_none(self):
        from src.tiered_analysis.signal_log import score_band

        assert score_band(None) is None
        assert score_band(-1) is None
        assert score_band(11) is None
        assert score_band("garbage") is None


class TestForwardTestMetadata:
    """hold_weeks / horizon / final_score land on the payload (2026-08-08)."""

    def test_hold_weeks_sets_horizon_and_metadata(self):
        report = _report(hold_weeks=3)
        payload, skip = build_signal_payload(report)
        assert skip is None
        assert payload["horizon"] == "15d"
        assert payload["metadata"]["hold_weeks"] == 3
        assert payload["metadata"]["horizon_days"] == 15

    def test_no_hold_weeks_means_no_horizon(self):
        payload, _ = build_signal_payload(_report())
        assert "horizon" not in payload
        assert "hold_weeks" not in payload["metadata"]

    def test_debate_final_score_and_band_recorded(self):
        report = _report(
            tier=2,
            debate_detail={"verdict": {"final_score": 7.37}},
        )
        payload, _ = build_signal_payload(report)
        assert payload["metadata"]["final_score"] == pytest.approx(7.37)
        assert payload["metadata"]["score_band"] == "6-8"

    def test_no_debate_verdict_means_no_final_score(self):
        payload, _ = build_signal_payload(_report())
        assert "final_score" not in payload["metadata"]
        assert "score_band" not in payload["metadata"]
