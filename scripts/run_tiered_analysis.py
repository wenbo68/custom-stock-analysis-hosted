# -*- coding: utf-8 -*-
"""Run tiered analysis v1 for one or more symbols (production wiring).

For each symbol this collects the four dimensions (technicals,
fundamentals, macro, positioning), runs the existing DSA analysis as tier 1,
and records the recommendation in the decision-signal system — visible in
the web app on the Decision Signals page.

Usage:
    .venv/bin/python scripts/run_tiered_analysis.py AAPL
    .venv/bin/python scripts/run_tiered_analysis.py AAPL NVDA 600519
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from src.tiered_analysis.integration import run_tiered_analysis  # noqa: E402

BAR = "=" * 62


def _print_outcome(symbol: str, outcome) -> None:
    report = outcome.report
    print(f"\n{BAR}")
    print(f"{symbol} — tier {report.tier} ({report.market.value})")
    print(BAR)
    print(f"direction:  {report.direction.value}")
    print(f"score:      {report.score}")
    levels = report.levels
    print(f"entry:      {levels.entry} / secondary {levels.secondary_entry}")
    print(f"stop loss:  {levels.stop_loss}   target: {levels.take_profit}")
    print("dimensions:")
    for dim in report.dimensions:
        print(f"  - {dim.dimension}: {len(dim.warnings)} warning(s)")
    for warning in report.warnings:
        print(f"warning: {warning}")
    if outcome.signal is None:
        print("signal log: skipped")
    elif outcome.signal.logged:
        print(f"signal log: saved (id={outcome.signal.signal_id}, "
              f"new={outcome.signal.created})")
    else:
        print(f"signal log: NOT saved — {outcome.signal.reason}")


def main() -> None:
    symbols = sys.argv[1:] or ["AAPL"]
    for symbol in symbols:
        try:
            outcome = run_tiered_analysis(symbol)
        except Exception as exc:
            print(f"\n{symbol}: run failed — {exc}")
            continue
        _print_outcome(symbol, outcome)

    print(f"\n{BAR}")
    print("View in browser: start the server (python main.py --serve),")
    print("open http://localhost:8000 and go to the Decision Signals page.")
    print(BAR)


if __name__ == "__main__":
    main()
