# -*- coding: utf-8 -*-
"""Cross-provider fields (TODO.md truth 2026-08-04).

Two report fields need an ingredient from a *different* provider than
the one that owns them, so they are computed here, in one enrichment
pass over the collected DimensionResults — providers stay independent
and offline-testable:

- **Sector comparison** (technicals "market vs sector vs stock" group):
  the computation is pure price math, but choosing *which* sector ETF to
  price requires the sector label the fundamentals profile fetch
  already carries. The stock's and the benchmark's returns are reused
  from the receipts technicals just computed (guaranteed consistent
  with the displayed numbers); only the sector ETF's bars are a new
  fetch.
- **Implied/realized report-move ratio** (positioning options group):
  positioning's options-implied report-day move divided by
  fundamentals' realized 4-quarter average move.

Every failure degrades to None-valued envelopes plus a warning — a
missing sector label or a dead ETF fetch must not sink the stock's own
report (same contract as the benchmark fields).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .providers.base import DimensionResult, note_fields
from .providers.sector_map import sector_etf_for
from .providers.technicals import (
    RS_WINDOW_1M,
    RS_WINDOW_3M,
    make_metric,
    pct_change,
    read_label,
    read_metric,
    relative_strength_label,
)

#: New market-group key order (truth spec): market trend, then sector vs
#: market, then stock vs market, then stock vs sector.
_MARKET_GROUP_ORDER = (
    "regime",
    "rs_sector_1m", "rs_sector_3m", "sector_vs_market_label",
    "rs_1m", "rs_3m", "rs_label",
    "rs_stock_sector_1m", "rs_stock_sector_3m", "stock_vs_sector_label",
)

_SECTOR_KEYS = (
    "rs_sector_1m", "rs_sector_3m", "sector_vs_market_label",
    "rs_stock_sector_1m", "rs_stock_sector_3m", "stock_vs_sector_label",
)

RATIO_KEY = "report_move_ratio_implied_4q"


def enrich_cross_fields(
    dimensions: Sequence[DimensionResult],
    bars_loader: Optional[Callable[[str], Sequence[Any]]],
) -> List[DimensionResult]:
    """The collected results with the cross-provider fields added.

    ``bars_loader`` None (test harnesses that inject providers) skips
    enrichment entirely so canned payloads pass through untouched.
    """
    if bars_loader is None:
        return list(dimensions)
    by_dim = {result.dimension: result for result in dimensions}
    fundamentals = by_dim.get("fundamentals")

    enriched: List[DimensionResult] = []
    for result in dimensions:
        if result.dimension == "technicals":
            enriched.append(
                _with_sector_fields(result, fundamentals, bars_loader)
            )
        elif result.dimension == "positioning":
            enriched.append(_with_report_move_ratio(result, fundamentals))
        else:
            enriched.append(result)
    return enriched


# ---------------------------------------------------------------------------
# Sector comparison fields
# ---------------------------------------------------------------------------


def _sector_envelopes(
    values: Dict[str, Any], sector_text: str
) -> Dict[str, Any]:
    """The six sector-comparison envelopes; ``values`` may be all-None."""
    joint_read = (
        "Read together with the sector's own performance: leading a "
        "sector that is itself leading the market is the strongest "
        "setup; beating a falling sector only means falling slower."
    )
    return {
        "rs_sector_1m": make_metric(
            "1m return diff (sector vs market)",
            f"The stock's sector ({sector_text}) return minus the "
            f"market's return over the last {RS_WINDOW_1M} trading days "
            "(about 1 month), in percentage points.",
            values.get("rs_sector_1m"),
            interpretation=(
                "Positive = the sector is leading the market; swing "
                "moves in leading sectors run further and pull back "
                "shallower."
            ),
        ),
        "rs_sector_3m": make_metric(
            "3m return diff (sector vs market)",
            f"The stock's sector ({sector_text}) return minus the "
            f"market's return over the last {RS_WINDOW_3M} trading days "
            "(about 3 months), in percentage points.",
            values.get("rs_sector_3m"),
            interpretation=(
                "Positive = the sector is leading the market; fighting "
                "a lagging sector cuts the win rate even on a clean "
                "chart."
            ),
        ),
        "sector_vs_market_label": make_metric(
            "sector performance relative to market",
            "leader = the sector beat the market over both the 1-month "
            "and 3-month windows; laggard = lost to it over both; else "
            f"neutral. Sector: {sector_text}.",
            values.get("sector_vs_market_label"),
            interpretation=(
                "The middle layer between the market and the single "
                "stock: a leading sector is a tailwind for longs in it."
            ),
        ),
        "rs_stock_sector_1m": make_metric(
            "1m return diff (stock vs sector)",
            "The stock's return minus its sector's return "
            f"({sector_text}) over the last {RS_WINDOW_1M} trading days, "
            "in percentage points.",
            values.get("rs_stock_sector_1m"),
            interpretation=joint_read,
        ),
        "rs_stock_sector_3m": make_metric(
            "3m return diff (stock vs sector)",
            "The stock's return minus its sector's return "
            f"({sector_text}) over the last {RS_WINDOW_3M} trading days, "
            "in percentage points.",
            values.get("rs_stock_sector_3m"),
            interpretation=joint_read,
        ),
        "stock_vs_sector_label": make_metric(
            "stock performance relative to sector",
            "leader = the stock beat its own sector over both windows; "
            "laggard = lost to it over both; else neutral. Sector: "
            f"{sector_text}.",
            values.get("stock_vs_sector_label"),
            interpretation=(
                "Distinguishes a genuinely strong stock from one being "
                "carried by a hot sector — a laggard inside a leading "
                "sector is the weakest member of a strong club."
            ),
        ),
    }


def _sector_returns(
    bars_loader: Callable[[str], Sequence[Any]], etf_ticker: str
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """(1m return, 3m return, error) for the sector ETF."""
    try:
        bars = list(bars_loader(etf_ticker))
    except Exception as exc:
        return None, None, f"sector ETF {etf_ticker} bars unavailable: {exc}"
    closes = [bar.close for bar in bars]
    ret_1m = pct_change(closes, RS_WINDOW_1M)
    ret_3m = pct_change(closes, RS_WINDOW_3M)
    if ret_1m is None and ret_3m is None:
        return None, None, (
            f"sector ETF {etf_ticker} history too short "
            f"({len(closes)} bars)"
        )
    return ret_1m, ret_3m, None


def _with_sector_fields(
    technicals: DimensionResult,
    fundamentals: Optional[DimensionResult],
    bars_loader: Callable[[str], Sequence[Any]],
) -> DimensionResult:
    payload = technicals.payload
    market_group = payload.get("market") if payload else None
    if not isinstance(market_group, dict) or "regime" not in market_group:
        return technicals  # not a v2 technicals payload

    formulas = dict(technicals.formulas or {})
    warnings = list(technicals.warnings)
    field_notes = {
        path: list(notes)
        for path, notes in (technicals.field_notes or {}).items()
    }
    sector_paths = tuple(f"market.{key}" for key in _SECTOR_KEYS)

    sector = (
        read_label(fundamentals.payload, "meta", "sector")
        if fundamentals is not None and fundamentals.payload
        else None
    )
    mapped = sector_etf_for(sector)

    rs_1m_inputs = formulas.get("market.rs_1m", {}).get("inputs", {})
    rs_3m_inputs = formulas.get("market.rs_3m", {}).get("inputs", {})
    stock_1m = rs_1m_inputs.get("stock_return_1m")
    index_1m = rs_1m_inputs.get("index_return_1m")
    stock_3m = rs_3m_inputs.get("stock_return_3m")
    index_3m = rs_3m_inputs.get("index_return_3m")

    values: Dict[str, Any] = {}
    sector_text = sector or "unknown"
    if sector is None:
        note_fields(
            warnings, field_notes,
            "sector unknown (fundamentals carries no sector label); "
            "sector comparison fields absent",
            sector_paths,
        )
    elif mapped is None:
        note_fields(
            warnings, field_notes,
            f"sector '{sector}' has no sector-ETF mapping (US sectors "
            "only for now); sector comparison fields absent",
            sector_paths,
        )
    elif index_1m is None and index_3m is None:
        note_fields(
            warnings, field_notes,
            "sector comparison needs the market benchmark returns, "
            "which are absent; sector comparison fields absent",
            sector_paths,
        )
    else:
        etf_ticker, etf_name = mapped
        sector_text = f"{sector}, via the {etf_name} ETF ({etf_ticker})"
        etf_1m, etf_3m, error = _sector_returns(bars_loader, etf_ticker)
        if error is not None:
            note_fields(
                warnings, field_notes,
                f"{error}; sector comparison fields absent",
                sector_paths,
            )
        else:
            def diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
                if a is None or b is None:
                    return None
                return round(a - b, 2)

            values = {
                "rs_sector_1m": diff(etf_1m, index_1m),
                "rs_sector_3m": diff(etf_3m, index_3m),
                "rs_stock_sector_1m": diff(stock_1m, etf_1m),
                "rs_stock_sector_3m": diff(stock_3m, etf_3m),
            }
            values["sector_vs_market_label"] = relative_strength_label(
                values["rs_sector_1m"], values["rs_sector_3m"]
            )
            values["stock_vs_sector_label"] = relative_strength_label(
                values["rs_stock_sector_1m"], values["rs_stock_sector_3m"]
            )
            label_branches = [
                {"label": "leader", "condition": "diff_1m > 0 && diff_3m > 0"},
                {"label": "laggard", "condition": "diff_1m < 0 && diff_3m < 0"},
                {"label": "neutral", "condition": None},
            ]
            receipt_rows = (
                ("market.rs_sector_1m",
                 "sector_return_1m − index_return_1m",
                 {"sector_return_1m": etf_1m, "index_return_1m": index_1m},
                 None),
                ("market.rs_sector_3m",
                 "sector_return_3m − index_return_3m",
                 {"sector_return_3m": etf_3m, "index_return_3m": index_3m},
                 None),
                ("market.sector_vs_market_label", None,
                 {"diff_1m": values["rs_sector_1m"],
                  "diff_3m": values["rs_sector_3m"]},
                 label_branches),
                ("market.rs_stock_sector_1m",
                 "stock_return_1m − sector_return_1m",
                 {"stock_return_1m": stock_1m, "sector_return_1m": etf_1m},
                 None),
                ("market.rs_stock_sector_3m",
                 "stock_return_3m − sector_return_3m",
                 {"stock_return_3m": stock_3m, "sector_return_3m": etf_3m},
                 None),
                ("market.stock_vs_sector_label", None,
                 {"diff_1m": values["rs_stock_sector_1m"],
                  "diff_3m": values["rs_stock_sector_3m"]},
                 label_branches),
            )
            for path, formula, inputs, branches in receipt_rows:
                if any(value is None for value in inputs.values()):
                    continue
                entry: Dict[str, Any] = {"inputs": inputs}
                if formula is not None:
                    entry["formula"] = formula
                if branches is not None:
                    entry["branches"] = branches
                formulas[path] = entry

    sector_envelopes = _sector_envelopes(values, sector_text)
    merged = {**market_group, **sector_envelopes}
    new_market = {
        key: merged[key] for key in _MARKET_GROUP_ORDER if key in merged
    }
    # Anything outside the known order (future keys) keeps its place at
    # the end rather than being dropped.
    for key, value in merged.items():
        if key not in new_market:
            new_market[key] = value

    return replace(
        technicals,
        payload={**payload, "market": new_market},
        formulas=formulas or None,
        warnings=warnings,
        field_notes=field_notes or None,
    )


# ---------------------------------------------------------------------------
# Implied vs realized report-move ratio
# ---------------------------------------------------------------------------


def _with_report_move_ratio(
    positioning: DimensionResult,
    fundamentals: Optional[DimensionResult],
) -> DimensionResult:
    payload = positioning.payload
    options = payload.get("options") if payload else None
    if not isinstance(options, dict) or "implied_report_move_pct" not in options:
        return positioning  # not a v2 positioning payload

    implied = read_metric(payload, "options", "implied_report_move_pct")
    realized = (
        read_metric(fundamentals.payload, "quarterly_report",
                    "reaction_avg_abs_pct")
        if fundamentals is not None and fundamentals.payload
        else None
    )
    ratio = (
        round(implied / realized, 2)
        if implied is not None and realized
        else None
    )

    # A blank ratio names exactly which ingredient was missing this run,
    # so the report page can link straight to the blank ingredient row
    # (owner request 2026-08-23) instead of a generic "needs both" text.
    warnings = list(positioning.warnings)
    field_notes = {
        path: list(notes)
        for path, notes in (positioning.field_notes or {}).items()
    }
    ratio_path = f"options.{RATIO_KEY}"
    if ratio is None:
        if implied is None:
            note_fields(
                warnings, field_notes,
                "implied report-day move missing — report-move ratio "
                "(implied vs 4q avg) omitted",
                (ratio_path,),
            )
        if not realized:
            note_fields(
                warnings, field_notes,
                "realized 4q average report-day move missing or zero — "
                "report-move ratio (implied vs 4q avg) omitted",
                (ratio_path,),
            )

    envelope = make_metric(
        "quarterly report day price change magnitude ratio "
        "(implied vs 4q avg)",
        "The options-implied move for the next report day divided by "
        "the realized average move of the last 4 report days. 1.0 = "
        "options price exactly the usual jump.",
        ratio,
        interpretation=(
            "Well above 1 = the market is braced for a bigger-than-"
            "usual report reaction; well below 1 = unusually calm "
            "expectations."
        ),
    )
    formulas = dict(positioning.formulas or {})
    if ratio is not None:
        formulas[f"options.{RATIO_KEY}"] = {
            "formula": "implied_report_move_pct / reaction_avg_abs_pct",
            "inputs": {
                "implied_report_move_pct": implied,
                "reaction_avg_abs_pct": realized,
            },
        }
    return replace(
        positioning,
        payload={**payload, "options": {**options, RATIO_KEY: envelope}},
        formulas=formulas or None,
        warnings=warnings,
        field_notes=field_notes or None,
    )
