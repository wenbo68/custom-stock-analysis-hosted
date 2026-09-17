# -*- coding: utf-8 -*-
"""Run tiered analysis v1 for one or more symbols (production wiring).

For each symbol this collects the dimensions (technicals, fundamentals,
macro, positioning, news), runs the chosen judge, and prints the outlook
and trade plan.

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
    print(f"entry:      {levels.entry}")
    print(f"stop loss:  {levels.stop_loss}   target: {levels.take_profit}")
    print("dimensions:")
    for dim in report.dimensions:
        print(f"  - {dim.dimension}: {len(dim.warnings)} warning(s)")
    for warning in report.warnings:
        print(f"warning: {warning}")


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
    print("For the full report with history, start the server")
    print("(./start-server.sh) and run the ticker from the web page.")
    print(BAR)


if __name__ == "__main__":
    main()
