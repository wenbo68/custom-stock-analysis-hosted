# -*- coding: utf-8 -*-
"""Sector label -> ETF lookup: exact, aliased, and unknown labels."""
import pytest

from src.tiered_analysis.providers.sector_map import sector_etf_for


@pytest.mark.parametrize(
    "label,ticker",
    [
        ("Technology", "XLK"),
        ("Financial Services", "XLF"),
        ("Healthcare", "XLV"),
        ("Consumer Cyclical", "XLY"),
        ("Consumer Defensive", "XLP"),
        ("Energy", "XLE"),
        ("Industrials", "XLI"),
        ("Basic Materials", "XLB"),
        ("Utilities", "XLU"),
        ("Real Estate", "XLRE"),
        ("Communication Services", "XLC"),
    ],
)
def test_maps_all_eleven_yfinance_sectors(label, ticker):
    mapped = sector_etf_for(label)
    assert mapped is not None
    assert mapped[0] == ticker


@pytest.mark.parametrize(
    "gics,ticker",
    [
        ("Information Technology", "XLK"),
        ("Financials", "XLF"),
        ("Health Care", "XLV"),
        ("Consumer Discretionary", "XLY"),
        ("Consumer Staples", "XLP"),
        ("Materials", "XLB"),
    ],
)
def test_gics_spellings_alias_to_the_same_funds(gics, ticker):
    mapped = sector_etf_for(gics)
    assert mapped is not None
    assert mapped[0] == ticker


def test_matching_ignores_case_and_extra_whitespace():
    assert sector_etf_for("  consumer   CYCLICAL ")[0] == "XLY"


@pytest.mark.parametrize("label", [None, "", "Conglomerates", "Crypto", 42])
def test_unknown_or_missing_labels_return_none_never_a_guess(label):
    assert sector_etf_for(label) is None
