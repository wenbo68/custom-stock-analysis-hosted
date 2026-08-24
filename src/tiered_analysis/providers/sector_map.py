# -*- coding: utf-8 -*-
"""Sector label -> US sector-ETF ticker for the sector-vs-market fields.

The technicals sector comparison needs a tradable price series standing
in for "the stock's sector". For US stocks that is the SPDR Select
Sector ETF family — eleven funds, one per GICS sector, each holding the
S&P 500 members of that sector.

The lookup key is the sector string the fundamentals profile fetch
reports (yfinance vocabulary, e.g. "Consumer Cyclical"); the GICS
spellings of the same sectors are aliased so a source switch does not
silently kill the field. Matching is case-insensitive on a normalized
form. An unknown label returns None — absent beats silently wrong: a
mis-mapped sector would produce a correct-looking number computed from
the wrong family (same hazard class as the registry's benchmark note).

US-only by design, like the benchmark registry: CN/HK sector indexes
need their own mapping and an index-daily fetch first (future slice).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

#: yfinance sector name -> (SPDR ETF ticker, display name).
_SECTOR_ETFS: Dict[str, Tuple[str, str]] = {
    "technology": ("XLK", "Technology Select Sector SPDR"),
    "financial services": ("XLF", "Financial Select Sector SPDR"),
    "healthcare": ("XLV", "Health Care Select Sector SPDR"),
    "consumer cyclical": ("XLY", "Consumer Discretionary Select Sector SPDR"),
    "consumer defensive": ("XLP", "Consumer Staples Select Sector SPDR"),
    "energy": ("XLE", "Energy Select Sector SPDR"),
    "industrials": ("XLI", "Industrial Select Sector SPDR"),
    "basic materials": ("XLB", "Materials Select Sector SPDR"),
    "utilities": ("XLU", "Utilities Select Sector SPDR"),
    "real estate": ("XLRE", "Real Estate Select Sector SPDR"),
    "communication services": ("XLC", "Communication Services Select Sector SPDR"),
}

#: GICS spellings of the same eleven sectors (some sources report these).
_GICS_ALIASES: Dict[str, str] = {
    "information technology": "technology",
    "financials": "financial services",
    "health care": "healthcare",
    "consumer discretionary": "consumer cyclical",
    "consumer staples": "consumer defensive",
    "materials": "basic materials",
    "communication": "communication services",
}


def _normalize(label: str) -> str:
    return " ".join(label.strip().lower().split())


def sector_etf_for(sector_label: Optional[str]) -> Optional[Tuple[str, str]]:
    """(ETF ticker, display name) for a sector label, or None when the
    label is missing or not one of the eleven known sectors."""
    if not sector_label or not isinstance(sector_label, str):
        return None
    key = _normalize(sector_label)
    key = _GICS_ALIASES.get(key, key)
    return _SECTOR_ETFS.get(key)
