# -*- coding: utf-8 -*-
"""Market detection and provider routing for tiered analysis.

Market detection delegates to ``data_provider.base._market_tag`` — the
repo's single source of truth for symbol->market rules — imported lazily so
that the pure-math indicator modules stay importable without the heavy
data_provider dependency tree.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .base import DimensionProvider, Market
from .company_news import CompanyNewsProvider
from .fundamentals_us import FundamentalsUSProvider
from .macro_economy import MacroEconomyProvider
from .positioning import PositioningUSProvider
from .technicals import TechnicalsProvider
from .world_news import WorldNewsProvider



def detect_market(symbol: str) -> Market:
    """Map a symbol to its market family via the existing _market_tag rules."""
    from data_provider.base import _market_tag

    tag = _market_tag(symbol)
    try:
        return Market(tag)
    except ValueError:
        return Market.UNKNOWN


#: Benchmark index per market: (daily-data code, display name).
#:
#: US only for now. ``get_daily_data`` has explicit US-index routing
#: ("SPX" → ^GSPC via yfinance), but no index-daily routing for the
#: other markets — and their mood codes are actively dangerous through
#: the stock path: normalize_stock_code("sh000001") strips the prefix
#: into 000001 (Ping An Bank) and "HSI" is a real NYSE ticker. Absent
#: beats silently wrong: unmapped markets degrade to null regime /
#: relative-strength fields with a warning. Wiring CN/HK needs an
#: index-daily fetch first (future slice).
BENCHMARKS = {
    Market.US: ("SPX", "S&P 500"),
}


def benchmark_for(market: Market) -> Optional[tuple]:
    """(index code, display name) for the market's benchmark, or None."""
    return BENCHMARKS.get(market)


def get_providers(
    market: Market,
    bars_loader: Optional[Callable] = None,
) -> List[DimensionProvider]:
    """All dimension providers covering the given market.

    Six dimensions are registered: technicals (all markets),
    fundamentals (US), macro_economy (all markets, shared per-day cache),
    positioning (US: short interest / ownership / insiders / options),
    company_news (US: recent news coverage, textual), world_news
    (all markets: macro/world news backdrop, textual, shared per-day
    cache). (The opinion card was retired 2026-08-23 and removed
    2026-09-16: its analyst half lives on in the fundamentals
    estimate-revision fields.)

    ``bars_loader`` feeds the technicals provider (production passes the
    data_provider-backed loader; omitting it leaves the unwired default
    that fails loud). When a bars_loader is wired and the market has a
    benchmark, the same loader also feeds the market-regime and
    relative-strength fields with the benchmark index's bars.
    """
    benchmark = benchmark_for(market)
    if bars_loader is not None and benchmark is not None:
        index_code, index_name = benchmark
        technicals = TechnicalsProvider(
            bars_loader=bars_loader,
            index_bars_loader=lambda: bars_loader(index_code),
            benchmark_name=index_name,
        )
    elif bars_loader is not None:
        technicals = TechnicalsProvider(bars_loader=bars_loader)
    else:
        technicals = TechnicalsProvider()
    # List order is display order on the report pages: technicals,
    # fundamentals, positioning, macro, company events, then world
    # news. (Opinion sat between macro and company news until its
    # 2026-08-23 retirement — restore it there if it ever returns.)
    #
    # The same bars_loader that feeds technicals also feeds the
    # fundamentals earnings-day-move fields (realized reaction around
    # past reports); without one those fields stay None with a warning.
    fundamentals = (
        FundamentalsUSProvider(bars_loader=bars_loader)
        if bars_loader is not None
        else FundamentalsUSProvider()
    )
    candidates: List[DimensionProvider] = [
        technicals,
        fundamentals,
        PositioningUSProvider(),
        MacroEconomyProvider(),
        CompanyNewsProvider(),
        WorldNewsProvider(),
    ]
    return [provider for provider in candidates if provider.supports(market)]
