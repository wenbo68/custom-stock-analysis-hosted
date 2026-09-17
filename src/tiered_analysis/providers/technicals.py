# -*- coding: utf-8 -*-
"""Deterministic technical indicators — v2 envelope payload (2026-07-27).

Pure Python over OHLCV bars — no numpy/pandas, no network. Fetching is
decoupled: ``TechnicalsProvider`` receives a ``bars_loader`` callable so the
indicator core stays reproducible and offline-testable.

v2 design (TODO.md "technical fields — FINAL"):

- **Envelope format** — every published metric ships as
  ``{"name", "explanation", "value"}`` so the LLM stages and the UI share
  one source of truth about what a number means. Citations address the
  envelope path (``technicals.daily.rsi_14``) and resolve to ``value``.
- **Composites swallow their ingredients** — correlated fields get
  double-counted by an LLM as independent evidence (stack + structure +
  slope + trend reads as four confirmations of one fact), so judgments
  ship only as their composite label. Ingredients live in code and, for
  a *neutral* label, in the explanation text — a neutral reading
  collapses two opposite situations and only its inputs distinguish them.
- **Coordinates stay** — price levels (the one-year high, the 50/200-day
  averages, pivot support/resistance) are not confirmations of anything;
  they are the numbers a plan is written against, and cutting them would
  force the model into arithmetic.
- No composite 0-100 score, and no pre-computed reward:risk — both would
  pre-answer judgments other stages own (score retired 2026-07-26).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .base import (
    Citation,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
    note_fields,
)

RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

#: One trading year — the landmark window (1y range, worst day) and the
#: honest-coverage line for the daily series.
YEAR_BARS = 253
#: Weekly bars below this make the weekly structure read unreliable.
WEEKLY_BARS_TARGET = 60
#: Bars needed for the minimum viable set (RSI/ATR need period + 1).
MIN_HISTORY_BARS = max(RSI_PERIOD, ATR_PERIOD) + 1
#: Daily returns needed before a worst-day extreme means anything.
MIN_RETURNS_FOR_TAIL = 20

#: Moving-average windows. Weekly 10/20 is a deliberate swing-scale choice
#: (TODO.md 2026-07-27): 30w+ are position-trading rulers, and whipsaw from
#: the faster pair is damped because the pivot structure must agree before
#: the trend label turns directional.
WEEKLY_SMA_FAST = 10
WEEKLY_SMA_SLOW = 20
DAILY_SMA_FAST = 20
DAILY_SMA_MID = 50
DAILY_SMA_LONG = 200

#: Pivot detection: a bar whose high/low exceeds this many bars on each side.
PIVOT_FRINGE = 2
#: Daily pivots scan this window (~6 months) for structure and levels.
DAILY_PIVOT_LOOKBACK = 120

#: ATR trend compares now vs this many bars ago, with a ±10% dead band.
ATR_TREND_LOOKBACK = 20
ATR_TREND_BAND = 0.10
#: Weekly ATR approximation: daily ATR × √5 (five sessions per week).
WEEKLY_ATR_FACTOR = math.sqrt(5.0)

#: MACD histogram direction compares now vs this many bars ago.
HIST_DIRECTION_BARS = 3
#: Momentum label RSI bands (strong above / weak below).
MOMENTUM_RSI_STRONG = 55
MOMENTUM_RSI_WEAK = 45

#: Relative-strength windows in trading days (~1 month / ~3 months).
RS_WINDOW_1M = 21
RS_WINDOW_3M = 63

#: Volume comparison windows (bars).
VOLUME_BASE_BARS = 60
VOLUME_RECENT_BARS = 5

#: Typical pullback: median of the last N completed pivot-high→pivot-low
#: dips, needing at least MIN pairs to mean anything.
TYPICAL_PULLBACK_MAX_PAIRS = 5
TYPICAL_PULLBACK_MIN_PAIRS = 2

#: Envelope keys — the shape every published metric ships in. v2 runs
#: (2026-07-29) add "interpretation" (how to read the number) next to
#: "explanation" (what the number is); runs stored before that date
#: carry only the required three keys, so both shapes stay valid.
ENVELOPE_KEYS = frozenset({"name", "explanation", "value"})
ENVELOPE_KEYS_ALL = ENVELOPE_KEYS | {"interpretation"}

#: Metrics allowed to be None without downgrading coverage:
#: benchmark-dependent fields degrade gracefully when the index fetch
#: fails; volume is source-dependent; pivot levels can be legitimately
#: absent (a close at its extreme has no pivot beyond it); as_of depends
#: on the loader shipping dates.
OPTIONAL_METRICS = frozenset({
    "meta.as_of",
    "market.regime",
    "market.rs_1m",
    "market.rs_3m",
    "market.rs_label",
    "volume.avg_vol_60d",
    "volume.avg_vol_5d",
    "volume.vol_ratio_5_60",
    "levels.support_1",
    "levels.resistance_1",
    "levels.support_dist_atr",
    "levels.resistance_dist_atr",
    "volatility.typical_pullback_atr",
})

#: Payload paths ("group.key") each history/benchmark shortfall note is
#: about, so the report page can show the note beside the field itself.
YEAR_WINDOW_FIELDS = (
    "price.high_1y",
    "price.low_1y",
    "price.range_pct_1y",
    "volatility.worst_day_pct_1y",
)
WEEKLY_FIELDS = ("weekly.sma_10w", "weekly.stretch_10w_atr", "weekly.trend")
BENCHMARK_FIELDS = (
    "market.regime", "market.rs_1m", "market.rs_3m", "market.rs_label",
)


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar; only the fields the indicators need."""

    high: float
    low: float
    close: float
    open: Optional[float] = None
    volume: Optional[float] = None
    date: Optional[str] = None


# ---------------------------------------------------------------------------
# Envelope helpers (shared with every payload consumer)
# ---------------------------------------------------------------------------


def make_metric(
    name: str,
    explanation: str,
    value: Any,
    interpretation: Optional[str] = None,
) -> Dict[str, Any]:
    """One published metric: the LLM and the UI read the same words.

    ``explanation`` says what the number is; ``interpretation`` says how
    to read it as a trader. The key is present only when text was given,
    so pre-2026-07-29 consumers keep seeing the shape they know.
    """
    metric: Dict[str, Any] = {"name": name, "explanation": explanation}
    if interpretation is not None:
        metric["interpretation"] = interpretation
    metric["value"] = value
    return metric


def is_envelope(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    keys = set(node.keys())
    return ENVELOPE_KEYS <= keys <= ENVELOPE_KEYS_ALL


def metric_value(node: Any) -> Any:
    """The value behind a node: envelopes unwrap, everything else passes."""
    return node.get("value") if is_envelope(node) else node


def read_metric(payload: Optional[Dict[str, Any]], group: str, key: str) -> Optional[float]:
    """Numeric metric out of a v2 payload; None when absent or non-numeric."""
    if not payload:
        return None
    node = payload.get(group)
    if not isinstance(node, dict):
        return None
    value = metric_value(node.get(key))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def read_label(payload: Optional[Dict[str, Any]], group: str, key: str) -> Optional[str]:
    """String metric out of a v2 payload; None when absent."""
    if not payload:
        return None
    node = payload.get(group)
    if not isinstance(node, dict):
        return None
    value = metric_value(node.get(key))
    return value if isinstance(value, str) else None


def technicals_as_of(dimensions: Sequence[DimensionResult]) -> Optional[str]:
    """The "bars up to" date the technicals provider computed from —
    the last COMPLETED session the analysis judged ("YYYY-MM-DD").

    ``meta.as_of`` is a date STRING, so it needs the label reader —
    ``read_metric`` drops anything non-numeric and would hand the
    staleness gate a permanent None (every run stopped, 2026-08-08).
    Shared by the staleness gate and the signal log's grading anchor,
    so both always mean the same session.
    """
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            return read_label(dim.payload, "meta", "as_of")
    return None


# ---------------------------------------------------------------------------
# Indicator math (single values)
# ---------------------------------------------------------------------------


def compute_sma(closes: List[float], period: int) -> Optional[float]:
    """Simple moving average of the most recent ``period`` closes."""
    if period <= 0 or len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """EMA aligned to input; None until the seed SMA at index period-1."""
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    series: List[Optional[float]] = [None] * (period - 1)
    ema = sum(values[:period]) / period
    series.append(ema)
    multiplier = 2.0 / (period + 1)
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        series.append(ema)
    return series


def compute_ema(closes: List[float], period: int) -> Optional[float]:
    """Exponential moving average (SMA-seeded) of the close series."""
    series = _ema_series(closes, period)
    return series[-1] if series else None


def wilder_averages(
    closes: List[float], period: int = RSI_PERIOD
) -> Optional[Tuple[float, float]]:
    """Wilder's smoothed (average gain, average loss) — the two numbers
    the RSI formula divides; exposed so the UI receipt can plug them in."""
    if period <= 0 or len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    return avg_gain, avg_loss


def compute_wilder_rsi(closes: List[float], period: int = RSI_PERIOD) -> Optional[float]:
    """RSI with Wilder smoothing; needs ``period + 1`` closes.

    A series with zero average gain and zero average loss is neutral (50).
    """
    averages = wilder_averages(closes, period)
    if averages is None:
        return None
    avg_gain, avg_loss = averages
    if avg_loss == 0.0 and avg_gain == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd_histogram_series(
    closes: List[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> Tuple[Optional[float], List[float]]:
    """(latest MACD line, histogram series) — the two MACD facts v2 keeps.

    The raw MACD/signal lines are internal computation now: the histogram
    plus the line's sign carry everything the momentum label needs, and
    publishing the operands alongside the reading double-counts them.
    """
    if len(closes) < slow + signal - 1:
        return None, []
    fast_series = _ema_series(closes, fast)
    slow_series = _ema_series(closes, slow)
    macd_line = [
        f - s
        for f, s in zip(fast_series, slow_series)
        if f is not None and s is not None
    ]
    signal_series = _ema_series(macd_line, signal)
    histogram = [
        m - s for m, s in zip(macd_line, signal_series) if s is not None
    ]
    if not histogram:
        return None, []
    return macd_line[-1], histogram


def compute_atr(bars: Sequence[Bar], period: int = ATR_PERIOD) -> Optional[float]:
    """Average True Range with Wilder smoothing; needs ``period + 1`` bars.

    True range includes gaps: max(high-low, |high-prev_close|, |low-prev_close|).
    """
    if period <= 0 or len(bars) < period + 1:
        return None
    true_ranges: List[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        bar = bars[i]
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
        )
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def compute_swing_high(bars: Sequence[Bar], lookback: int) -> Optional[float]:
    """Highest traded high of the last ``lookback`` bars."""
    if not bars or lookback <= 0:
        return None
    return max(bar.high for bar in bars[-lookback:])


def compute_swing_low(bars: Sequence[Bar], lookback: int) -> Optional[float]:
    """Lowest traded low of the last ``lookback`` bars."""
    if not bars or lookback <= 0:
        return None
    return min(bar.low for bar in bars[-lookback:])


def compute_avg_volume(bars: Sequence[Bar], lookback: int) -> Optional[float]:
    """Mean daily volume over the last ``lookback`` bars; None when the
    data source ships no volume."""
    if not bars or lookback <= 0:
        return None
    volumes = [
        bar.volume
        for bar in bars[-lookback:]
        if bar.volume is not None and bar.volume > 0
    ]
    if not volumes:
        return None
    return sum(volumes) / len(volumes)


def compute_worst_day_pct_1y(
    closes: List[float], lookback: int = YEAR_BARS
) -> Optional[float]:
    """Worst single daily return (close-to-close) over the last trading
    year, AS A PERCENT — the honest "how bad has one day actually gotten"
    number the gap-risk check stresses with.

    Returns a percent (-16.97), never a raw fraction, and honours
    ``lookback`` so a field named for one year cannot quietly report the
    worst day of everything the loader fetched (both corrections
    2026-07-26). Needs at least MIN_RETURNS_FOR_TAIL returns; with fewer
    observations the extreme is noise, so None (loud) beats a fake number.
    """
    detail = worst_day_detail(closes, lookback)
    return detail[0] if detail is not None else None


def worst_day_detail(
    closes: List[float], lookback: int = YEAR_BARS
) -> Optional[Tuple[float, float, float]]:
    """(worst-day percent, close the day before, close that day) — the
    ingredients the UI receipt plugs into the worst-day formula."""
    if lookback <= 0:
        return None
    window = closes[-(lookback + 1):]
    if len(window) < MIN_RETURNS_FOR_TAIL + 1:
        return None
    days = [
        (window[i] / window[i - 1] - 1.0, window[i - 1], window[i])
        for i in range(1, len(window))
        if window[i - 1] > 0
    ]
    if len(days) < MIN_RETURNS_FOR_TAIL:
        return None
    worst = min(days, key=lambda day: day[0])
    return round(worst[0] * 100.0, 2), worst[1], worst[2]


def pct_change(closes: List[float], bars_back: int) -> Optional[float]:
    """Close-to-close change over ``bars_back`` bars, in percent."""
    if bars_back <= 0 or len(closes) < bars_back + 1:
        return None
    then = closes[-(bars_back + 1)]
    if then <= 0:
        return None
    return round((closes[-1] / then - 1.0) * 100.0, 2)


# ---------------------------------------------------------------------------
# Weekly resample, pivots, structure, trends
# ---------------------------------------------------------------------------


def _week_key(date: str) -> Optional[Tuple[int, int]]:
    """ISO (year, week) of a YYYY-MM-DD date string; None when unparseable."""
    try:
        import datetime as _dt

        iso = _dt.date.fromisoformat(date[:10]).isocalendar()
        return iso[0], iso[1]
    except (ValueError, TypeError):
        return None


def resample_weekly(bars: Sequence[Bar]) -> List[Bar]:
    """Daily bars grouped into weekly bars, oldest first.

    Groups by ISO calendar week when dates are present and parseable;
    otherwise falls back to fixed chunks of five counted from the most
    recent bar (so the newest weekly bar is always complete-as-loaded).
    """
    if not bars:
        return []
    groups: List[List[Bar]] = []
    keys = [_week_key(bar.date) if bar.date else None for bar in bars]
    if all(key is not None for key in keys):
        current_key: Optional[Tuple[int, int]] = None
        for bar, key in zip(bars, keys):
            if key != current_key:
                groups.append([])
                current_key = key
            groups[-1].append(bar)
    else:
        chunk: List[Bar] = []
        for bar in reversed(bars):
            chunk.append(bar)
            if len(chunk) == 5:
                groups.append(list(reversed(chunk)))
                chunk = []
        if chunk:
            groups.append(list(reversed(chunk)))
        groups.reverse()

    weekly: List[Bar] = []
    for group in groups:
        volumes = [b.volume for b in group if b.volume is not None]
        weekly.append(
            Bar(
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                open=group[0].open,
                volume=sum(volumes) if volumes else None,
                date=group[-1].date,
            )
        )
    return weekly


def find_pivots(
    bars: Sequence[Bar], fringe: int = PIVOT_FRINGE
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """(pivot highs, pivot lows) as (index, price), oldest first.

    A pivot high is a bar whose high strictly exceeds the highs of the
    ``fringe`` bars on each side (mirrored for lows). Strictness means a
    flat shelf produces no pivot — honest, since a shelf has no single
    turning bar.
    """
    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []
    for i in range(fringe, len(bars) - fringe):
        window = list(bars[i - fringe:i]) + list(bars[i + 1:i + fringe + 1])
        if all(bars[i].high > b.high for b in window):
            highs.append((i, bars[i].high))
        if all(bars[i].low < b.low for b in window):
            lows.append((i, bars[i].low))
    return highs, lows


def pivot_structure(
    highs: Sequence[Tuple[int, float]],
    lows: Sequence[Tuple[int, float]],
) -> Optional[str]:
    """Structure from the last two pivot highs and lows; None below that."""
    if len(highs) < 2 or len(lows) < 2:
        return None
    higher_highs = highs[-1][1] > highs[-2][1]
    higher_lows = lows[-1][1] > lows[-2][1]
    if higher_highs and higher_lows:
        return "higher highs and lows"
    if not higher_highs and not higher_lows:
        return "lower highs and lows"
    return "sideways"


def ma_stack(
    close: float, fast_ma: Optional[float], slow_ma: Optional[float]
) -> Optional[str]:
    """"up" when close > fast MA > slow MA, "down" mirrored, else "mixed"."""
    if fast_ma is None or slow_ma is None:
        return None
    if close > fast_ma > slow_ma:
        return "up"
    if close < fast_ma < slow_ma:
        return "down"
    return "mixed"


def combined_trend(stack: Optional[str], structure: Optional[str]) -> Optional[str]:
    """MA check + pivot structure; they must agree for a directional label."""
    if stack is None or structure is None:
        return None
    if stack == "up" and structure == "higher highs and lows":
        return "bullish"
    if stack == "down" and structure == "lower highs and lows":
        return "bearish"
    return "neutral"


def _trend_explanation(
    label: Optional[str],
    stack: Optional[str],
    structure: Optional[str],
    fast: str,
    slow: str,
) -> str:
    """Method text, per the explanation style rule (TODO.md 2026-07-27):
    an agreeing label gets method only — re-listing each ingredient's
    reading would smuggle the double-counting back in as prose. A neutral
    label states which ingredient said what, because neutral collapses
    two opposite situations that only the ingredients distinguish."""
    method = (
        f"Combined from the {fast}/{slow} moving-average check and the "
        "pivot structure; both must agree for a directional label."
    )
    if label == "neutral":
        method += (
            f" Here they disagree: the moving-average check reads "
            f"{stack}, the pivot structure reads {structure}."
        )
    elif label is None:
        missing = "moving averages" if stack is None else "pivot structure"
        method += f" Not enough history to compute the {missing}."
    return method


def momentum_label(
    rsi: Optional[float],
    histogram: Sequence[float],
    macd_line: Optional[float],
) -> Optional[str]:
    """One label resolving RSI and MACD together (v2: the label swallows
    RSI slope, histogram value/direction and the zero-line boolean).

    strong: RSI > 55, histogram rising, MACD line above zero.
    weak: RSI < 45, histogram falling, MACD line below zero.
    fading: RSI > 55 but histogram falling (strength draining).
    basing: RSI < 45 but histogram rising (strength building).
    """
    if rsi is None or macd_line is None:
        return None
    if len(histogram) < HIST_DIRECTION_BARS + 1:
        return None
    rising = histogram[-1] > histogram[-1 - HIST_DIRECTION_BARS]
    if rsi > MOMENTUM_RSI_STRONG:
        if rising and macd_line > 0:
            return "strong"
        if not rising:
            return "fading"
    if rsi < MOMENTUM_RSI_WEAK:
        if not rising and macd_line < 0:
            return "weak"
        if rising:
            return "basing"
    return "neutral"


def atr_trend(bars: Sequence[Bar], lookback: int = ATR_TREND_LOOKBACK) -> Optional[str]:
    """ATR now vs ``lookback`` bars ago with a ±10% dead band."""
    now = compute_atr(bars)
    then = compute_atr(bars[:-lookback]) if len(bars) > lookback else None
    if now is None or then is None or then <= 0:
        return None
    change = now / then - 1.0
    if change > ATR_TREND_BAND:
        return "expanding"
    if change < -ATR_TREND_BAND:
        return "contracting"
    return "stable"


def nearest_support(
    lows: Sequence[Tuple[int, float]], close: float
) -> Optional[float]:
    """Highest pivot low strictly below the close."""
    below = [price for _, price in lows if price < close]
    return max(below) if below else None


def nearest_resistance(
    highs: Sequence[Tuple[int, float]], close: float
) -> Optional[float]:
    """Lowest pivot high strictly above the close."""
    above = [price for _, price in highs if price > close]
    return min(above) if above else None


def typical_pullback_atr(
    highs: Sequence[Tuple[int, float]],
    lows: Sequence[Tuple[int, float]],
    atr: Optional[float],
) -> Optional[float]:
    """Median depth of recent completed pullbacks, in ATR units.

    A completed pullback is a pivot high followed by the next pivot low
    after it. Uses the last TYPICAL_PULLBACK_MAX_PAIRS pairs and needs at
    least TYPICAL_PULLBACK_MIN_PAIRS — the field exists to stop a stop
    from landing inside normal noise, and one dip is not "normal"."""
    if atr is None or atr <= 0:
        return None
    depths: List[float] = []
    for high_index, high_price in highs:
        following = [
            low_price for low_index, low_price in lows if low_index > high_index
        ]
        if not following:
            continue
        depth = high_price - following[0]
        if depth > 0:
            depths.append(depth / atr)
    depths = depths[-TYPICAL_PULLBACK_MAX_PAIRS:]
    if len(depths) < TYPICAL_PULLBACK_MIN_PAIRS:
        return None
    ordered = sorted(depths)
    mid = len(ordered) // 2
    median = (
        ordered[mid]
        if len(ordered) % 2
        else (ordered[mid - 1] + ordered[mid]) / 2.0
    )
    return round(median, 2)


# ---------------------------------------------------------------------------
# Benchmark-relative fields (regime, relative strength)
# ---------------------------------------------------------------------------


def relative_strength_pct(
    closes: List[float], index_closes: List[float], window: int
) -> Optional[float]:
    """Stock return minus index return over ``window`` bars, in points."""
    stock = pct_change(closes, window)
    index = pct_change(index_closes, window)
    if stock is None or index is None:
        return None
    return round(stock - index, 2)


def relative_strength_label(
    rs_1m: Optional[float], rs_3m: Optional[float]
) -> Optional[str]:
    """leader / laggard / neutral from the 1-month and 3-month reads."""
    if rs_1m is None or rs_3m is None:
        return None
    if rs_1m > 0 and rs_3m > 0:
        return "leader"
    if rs_1m < 0 and rs_3m < 0:
        return "laggard"
    return "neutral"


def regime_read(index_closes: List[float]) -> Optional[Dict[str, Any]]:
    """The benchmark regime: label + its ingredients (for the explanation
    text and the UI receipt — the label is the only published field)."""
    if not index_closes:
        return None
    close = index_closes[-1]
    sma_long = compute_sma(index_closes, DAILY_SMA_LONG)
    window = index_closes[-YEAR_BARS:]
    low, high = min(window), max(window)
    if sma_long is None or high <= low:
        return None
    range_pct = (close - low) / (high - low) * 100.0
    above = close > sma_long
    if above and range_pct > 50.0:
        label = "bullish"
    elif not above and range_pct < 50.0:
        label = "bearish"
    else:
        label = "mixed"
    return {
        "label": label,
        "above_200d": above,
        "range_pct": round(range_pct, 0),
        "close": close,
        "sma_200": sma_long,
    }


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _unwired_bars_loader(symbol: str) -> List[Bar]:
    """Placeholder loader until the tier pipeline wires a real data source."""
    raise RuntimeError(
        "technicals bars_loader not wired yet; inject one built on the "
        "existing data_provider multi-source layer"
    )


class TechnicalsProvider(DimensionProvider):
    """NUMERIC technicals for any market (indicators are market-agnostic).

    ``index_bars_loader`` (optional) feeds the market-regime and
    relative-strength fields with benchmark index bars; when it is absent
    or fails, those fields are None with a warning — a benchmark outage
    must not sink the stock's own report.
    """

    dimension = "technicals"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        bars_loader: Callable[[str], List[Bar]] = _unwired_bars_loader,
        source_name: str = "ohlcv-bars",
        index_bars_loader: Optional[Callable[[], List[Bar]]] = None,
        benchmark_name: str = "benchmark index",
    ) -> None:
        self._bars_loader = bars_loader
        self._source_name = source_name
        self._index_bars_loader = index_bars_loader
        self._benchmark_name = benchmark_name

    def supports(self, market: Market) -> bool:
        return True

    def collect(self, symbol: str) -> DimensionResult:
        warnings: List[str] = []
        # A failed bars fetch still ships the card's shape — every
        # indicator blank (the compute helpers all self-guard on empty
        # history) with the warning saying why; degradation lives on
        # the fields, never on a card-level grade (2026-08-19).
        try:
            bars = list(self._bars_loader(symbol))
        except Exception as exc:  # fail-loud as structured blanks
            bars = []
            warnings.append(f"bars_loader failed for {symbol}: {exc}")
        if bars and len(bars) < MIN_HISTORY_BARS:
            warnings.append(
                f"insufficient history for {symbol}: "
                f"{len(bars)} bars < {MIN_HISTORY_BARS} required for the"
                " minimum indicator set"
            )

        field_notes: Dict[str, List[str]] = {}
        payload, formulas = self._build_payload(bars, warnings, field_notes)

        missing = [
            f"{group}.{key}"
            for group, metrics in payload.items()
            for key, envelope in metrics.items()
            if metric_value(envelope) is None
            and f"{group}.{key}" not in OPTIONAL_METRICS
        ]
        if missing:
            note_fields(
                warnings, field_notes,
                f"indicators lacking history: {', '.join(sorted(missing))}",
                sorted(missing),
            )
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            payload=payload,
            citations=[Citation(source_name=self._source_name)],
            warnings=warnings,
            formulas=formulas or None,
            field_notes=field_notes or None,
        )

    # -- payload assembly ---------------------------------------------------

    def _build_payload(
        self,
        bars: List[Bar],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        closes = [bar.close for bar in bars]
        # No bars at all (total fetch failure): every metric below reads
        # None and the payload ships all-blank — the card keeps its
        # shape, the notes say why (2026-08-19).
        close = closes[-1] if closes else None
        weekly_bars = resample_weekly(bars)
        weekly_closes = [bar.close for bar in weekly_bars]

        if len(bars) < YEAR_BARS:
            note_fields(
                warnings, field_notes,
                f"only {len(bars)} daily bars (<{YEAR_BARS}): the one-year "
                "fields cover the history that exists",
                YEAR_WINDOW_FIELDS,
            )
        if len(weekly_bars) < WEEKLY_BARS_TARGET:
            note_fields(
                warnings, field_notes,
                f"only {len(weekly_bars)} weekly bars "
                f"(<{WEEKLY_BARS_TARGET}): the weekly structure read is "
                "unreliable",
                WEEKLY_FIELDS,
            )

        atr = compute_atr(bars)
        atr_pct = (
            _round(atr / close * 100.0) if atr is not None and close > 0 else None
        )
        rsi = _round(compute_wilder_rsi(closes))
        macd_line, histogram = macd_histogram_series(closes)

        # Daily trend: 20/50 stack + pivot structure over ~6 months.
        sma_fast_d = compute_sma(closes, DAILY_SMA_FAST)
        sma_mid_d = compute_sma(closes, DAILY_SMA_MID)
        sma_long_d = compute_sma(closes, DAILY_SMA_LONG)
        daily_window = bars[-DAILY_PIVOT_LOOKBACK:]
        daily_offset = len(bars) - len(daily_window)
        daily_highs, daily_lows = find_pivots(daily_window)
        daily_highs = [(i + daily_offset, p) for i, p in daily_highs]
        daily_lows = [(i + daily_offset, p) for i, p in daily_lows]
        daily_stack = ma_stack(close, sma_fast_d, sma_mid_d)
        daily_struct = pivot_structure(daily_highs, daily_lows)
        daily_trend = combined_trend(daily_stack, daily_struct)

        # Weekly trend: 10/20-week stack + weekly pivot structure.
        sma_fast_w = compute_sma(weekly_closes, WEEKLY_SMA_FAST)
        sma_slow_w = compute_sma(weekly_closes, WEEKLY_SMA_SLOW)
        weekly_highs, weekly_lows = find_pivots(weekly_bars)
        weekly_stack = ma_stack(close, sma_fast_w, sma_slow_w)
        weekly_struct = pivot_structure(weekly_highs, weekly_lows)
        weekly_trend = combined_trend(weekly_stack, weekly_struct)
        weekly_atr = atr * WEEKLY_ATR_FACTOR if atr is not None else None

        stretch_10w = (
            _round((close - sma_fast_w) / weekly_atr)
            if sma_fast_w is not None and weekly_atr
            else None
        )
        stretch_50d = (
            _round((close - sma_mid_d) / atr)
            if sma_mid_d is not None and atr
            else None
        )
        stretch_200d = (
            _round((close - sma_long_d) / atr)
            if sma_long_d is not None and atr
            else None
        )

        high_1y = compute_swing_high(bars, YEAR_BARS)
        low_1y = compute_swing_low(bars, YEAR_BARS)
        range_pct = (
            _round((close - low_1y) / (high_1y - low_1y) * 100.0, 1)
            if high_1y is not None and low_1y is not None and high_1y > low_1y
            else None
        )

        avg_vol_60 = compute_avg_volume(bars, VOLUME_BASE_BARS)
        avg_vol_5 = compute_avg_volume(bars, VOLUME_RECENT_BARS)
        vol_ratio = (
            _round(avg_vol_5 / avg_vol_60)
            if avg_vol_5 is not None and avg_vol_60
            else None
        )

        support = nearest_support(daily_lows, close)
        resistance = nearest_resistance(daily_highs, close)
        support_dist = (
            _round((close - support) / atr) if support is not None and atr else None
        )
        resistance_dist = (
            _round((resistance - close) / atr)
            if resistance is not None and atr
            else None
        )
        pullback = typical_pullback_atr(daily_highs, daily_lows, atr)

        regime, rs_1m, rs_3m, rs_label, bench_receipts = (
            self._benchmark_fields(closes, warnings, field_notes)
        )

        # Receipt ingredients (UI formulas): values the formulas divide
        # that are not payload fields themselves.
        close_5d_ago = closes[-6] if len(closes) >= 6 else None
        rsi_parts = wilder_averages(closes)
        worst_detail = worst_day_detail(closes)
        worst_day = worst_detail[0] if worst_detail is not None else None
        macd_hist_direction = (
            ("rising" if histogram[-1] > histogram[-1 - HIST_DIRECTION_BARS]
             else "falling")
            if len(histogram) >= HIST_DIRECTION_BARS + 1
            else None
        )
        atr_then = (
            compute_atr(bars[:-ATR_TREND_LOOKBACK])
            if len(bars) > ATR_TREND_LOOKBACK
            else None
        )

        payload: Dict[str, Dict[str, Any]] = {
            "meta": {
                "as_of": make_metric(
                    "bars up to",
                    "Date of the last completed daily bar.",
                    # Some loaders ship "YYYY-MM-DD 00:00:00"; the date part
                    # is the fact.
                    bars[-1].date[:10] if bars and bars[-1].date else None,
                    interpretation=(
                        "Data older than a couple of sessions should not "
                        "anchor a plan."
                    ),
                ),
                "bars_daily": make_metric(
                    "daily bars",
                    "Daily bars loaded.",
                    len(bars),
                    interpretation=(
                        f"Below {YEAR_BARS} the one-year fields only cover "
                        "the history that exists."
                    ),
                ),
                "bars_weekly": make_metric(
                    "weekly bars",
                    "Weekly bars resampled from the daily history.",
                    len(weekly_bars),
                    interpretation=(
                        f"Below {WEEKLY_BARS_TARGET} the weekly structure "
                        "read is unreliable."
                    ),
                ),
            },
            "market": {
                "regime": regime,
                "rs_1m": rs_1m,
                "rs_3m": rs_3m,
                "rs_label": rs_label,
            },
            "price": {
                "close": make_metric(
                    "closing price",
                    "Last daily closing price.",
                    _round(close),
                    interpretation=(
                        "The anchor every distance below is measured from."
                    ),
                ),
                "chg_5d_pct": make_metric(
                    "5d price change",
                    "Closing-price change over the last 5 trading days, "
                    "in %.",
                    pct_change(closes, 5),
                    interpretation=(
                        "A large move means the easy entry may already be "
                        "gone."
                    ),
                ),
                "high_1y": make_metric(
                    "1y highest price",
                    "Highest traded price of the last year.",
                    _round(high_1y),
                    interpretation=(
                        "The most-watched resistance landmark; a target "
                        "above it needs breakout logic, not pullback "
                        "logic."
                    ),
                ),
                "low_1y": make_metric(
                    "1y lowest price",
                    "Lowest traded price of the last year.",
                    _round(low_1y),
                    interpretation=(
                        "The floor of the one-year range — how far the "
                        "market has actually let this stock fall in a "
                        "year."
                    ),
                ),
                "range_pct_1y": make_metric(
                    "current price ranking (1y range)",
                    "Where the close sits in its one-year range, as a "
                    "position out of 100: 0/100 = at the low, 100/100 = "
                    "at the high.",
                    range_pct,
                    interpretation=(
                        "About 80/100 and above = strength near the highs "
                        "(breakout territory); about 20/100 and below = "
                        "weakness near the lows (knife-catching "
                        "territory)."
                    ),
                ),
            },
            "volume": {
                # 5d before 60d (TODO.md order 2026-07-31): the recent
                # read first, then the baseline it is compared against.
                "avg_vol_5d": make_metric(
                    "5d avg volume",
                    "Mean daily share volume over the last 5 bars.",
                    _round(avg_vol_5, 0),
                    interpretation=(
                        "The recent-activity read the volume ratio "
                        "compares against the 60-day baseline."
                    ),
                ),
                "avg_vol_60d": make_metric(
                    "60d avg volume",
                    "Mean daily share volume over the last 60 bars.",
                    _round(avg_vol_60, 0),
                    interpretation=(
                        "The liquidity baseline an order size is judged "
                        "against."
                    ),
                ),
                "vol_ratio_5_60": make_metric(
                    "volume ratio (5d/60d)",
                    "Average volume of the last 5 bars over the 60-bar "
                    "average.",
                    vol_ratio,
                    interpretation=(
                        "Above about 1.5 on a breakout = confirmed; below "
                        "about 0.7 = suspect move."
                    ),
                ),
            },
            "volatility": {
                "atr_14": make_metric(
                    "14d ATR",
                    "Average true range over 14 days, in price units — "
                    "the typical daily move.",
                    _round(atr),
                    interpretation=(
                        "The unit for stops and sizing: distances "
                        "measured in ATRs compare fairly across stocks."
                    ),
                ),
                "atr_pct": make_metric(
                    "14d ATR (% of closing price)",
                    "The typical daily move as a percent of price, "
                    "comparable across stocks.",
                    atr_pct,
                    interpretation=(
                        "Above about 6% is a high-volatility name — "
                        "consider smaller size."
                    ),
                ),
                "atr_trend": make_metric(
                    "ATR trend",
                    f"ATR now vs {ATR_TREND_LOOKBACK} bars ago (±10% dead "
                    "band): expanding, contracting or stable.",
                    atr_trend(bars),
                    interpretation=(
                        "Expanding = widen stops and shrink size; "
                        "contracting = a squeeze that often precedes a "
                        "move."
                    ),
                ),
                "typical_pullback_atr": make_metric(
                    "typical price drop (6m range)",
                    "Median depth of the last few completed pullbacks "
                    "(pivot high to the next pivot low, scanned over the "
                    f"last {DAILY_PIVOT_LOOKBACK} trading days ≈ 6 "
                    "months), in ATR units.",
                    pullback,
                    interpretation=(
                        "A stop closer than this sits inside normal "
                        "noise."
                    ),
                ),
                "worst_day_pct_1y": make_metric(
                    "worst price drop (1y range)",
                    "Worst close-to-close daily return of the last year, "
                    "in %.",
                    worst_day,
                    interpretation=(
                        "Gap risk: how far an overnight surprise has "
                        "actually blown through this stock's stops."
                    ),
                ),
            },
            "weekly": {
                "sma_10w": make_metric(
                    "10w SMA",
                    "10-week simple moving average.",
                    _round(sma_fast_w),
                    interpretation=(
                        "The intermediate trend line the weekly stretch "
                        "is measured from; holding above it keeps a swing "
                        "uptrend intact."
                    ),
                ),
                "stretch_10w_atr": make_metric(
                    "diff (closing price vs 10w SMA)",
                    "Distance of the close from the 10-week average, in "
                    "weekly ATR units (weekly ATR ≈ daily ATR × √5).",
                    stretch_10w,
                    interpretation=(
                        "Above about +1.5 = extended, wait for a "
                        "pullback; -0.5 to +1 in an uptrend = "
                        "pullback-buy zone."
                    ),
                ),
                "trend": make_metric(
                    "trend (SMA + pivots)",
                    _trend_explanation(
                        weekly_trend, weekly_stack, weekly_struct,
                        f"{WEEKLY_SMA_FAST}-week", f"{WEEKLY_SMA_SLOW}-week",
                    ),
                    weekly_trend,
                    interpretation=(
                        "Daily signals should only generate trades in "
                        "this direction; against it, the best plan is no "
                        "trade."
                    ),
                ),
            },
            "daily": {
                # Truth order (2026-08-04): each average directly followed
                # by its distance diff.
                "sma_50": make_metric(
                    "50d SMA",
                    "50-day simple moving average.",
                    _round(sma_mid_d),
                    interpretation=(
                        "The classic swing pullback level — dip-buys "
                        "near it are the standard swing entry."
                    ),
                ),
                "stretch_50d_atr": make_metric(
                    "diff (closing price vs 50d SMA)",
                    "Distance of the close from the 50-day average, in "
                    "ATR units.",
                    stretch_50d,
                    interpretation=(
                        "-1 to +1 in an uptrend = pullback entry zone; "
                        "above +3 = extended, chasing."
                    ),
                ),
                "sma_200": make_metric(
                    "200d SMA",
                    "200-day simple moving average — the most-watched "
                    "long-term line in finance.",
                    _round(sma_long_d),
                    interpretation=(
                        "Acts as support or resistance whatever the "
                        "holding period; below it, longs are "
                        "counter-trend."
                    ),
                ),
                "stretch_200d_atr": make_metric(
                    "diff (closing price vs 200d SMA)",
                    "Distance of the close from the 200-day average, in "
                    "ATR units.",
                    stretch_200d,
                    interpretation=(
                        "Positive = long-term uptrend intact; negative = "
                        "below the long-term line, longs are "
                        "counter-trend."
                    ),
                ),
                "trend": make_metric(
                    "trend (SMA + pivots)",
                    _trend_explanation(
                        daily_trend, daily_stack, daily_struct,
                        f"{DAILY_SMA_FAST}-day", f"{DAILY_SMA_MID}-day",
                    ),
                    daily_trend,
                    interpretation=(
                        "The direction filter for entries — pullback "
                        "buys work best when this agrees with the weekly "
                        "trend."
                    ),
                ),
                "rsi_14": make_metric(
                    "14d RSI",
                    "14-day relative strength index — a 0-100 speed "
                    "gauge of recent gains versus losses.",
                    rsi,
                    interpretation=(
                        "Above 70 = risen too fast, below 30 = fallen "
                        "too fast, 50 neutral. In strong trends it can "
                        "stay pinned high — do not auto-fade it."
                    ),
                ),
                "momentum": make_metric(
                    "momentum",
                    "One label resolving RSI and MACD together: strong "
                    f"(RSI > {MOMENTUM_RSI_STRONG}, MACD histogram rising, "
                    "MACD line above zero), weak (the mirror image), "
                    "fading (price strong but the histogram falling), "
                    "basing (price weak but the histogram rising), else "
                    "neutral.",
                    momentum_label(rsi, histogram, macd_line),
                    interpretation=(
                        "strong supports entries; fading warns the move "
                        "is running out of fuel while price still looks "
                        "fine; basing flags an early turn."
                    ),
                ),
            },
            "levels": {
                "support_1": make_metric(
                    "nearest support",
                    "Nearest pivot low below the close.",
                    _round(support),
                    interpretation=(
                        "A stop belongs below a level like this, not at "
                        "an arbitrary percent."
                    ),
                ),
                "support_dist_atr": make_metric(
                    "diff (closing price vs nearest support)",
                    "How far the close sits above the nearest support, "
                    "in ATR units.",
                    support_dist,
                    interpretation=(
                        "Small = the floor is affordably close (a stop "
                        "under it is cheap); large = a stop under "
                        "support risks more than a typical setup "
                        "should."
                    ),
                ),
                "resistance_1": make_metric(
                    "nearest resistance",
                    "Nearest pivot high above the close.",
                    _round(resistance),
                    interpretation=(
                        "The first target candidate — expect selling "
                        "there."
                    ),
                ),
                "resistance_dist_atr": make_metric(
                    "diff (nearest resistance vs closing price)",
                    "How far the nearest resistance sits above the "
                    "close, in ATR units.",
                    resistance_dist,
                    interpretation=(
                        "The room to run before the first ceiling — "
                        "small means the easy gain is nearly used up."
                    ),
                ),
            },
        }

        formulas = self._build_formulas(
            payload,
            close_5d_ago=close_5d_ago,
            low_1y=low_1y,
            high_1y=high_1y,
            sma_10w=sma_fast_w,
            rsi_parts=rsi_parts,
            avg_vol_5=avg_vol_5,
            avg_vol_60=avg_vol_60,
            worst_detail=worst_detail,
            bench_receipts=bench_receipts,
            weekly_stack=weekly_stack,
            weekly_struct=weekly_struct,
            daily_stack=daily_stack,
            daily_struct=daily_struct,
            macd_hist_direction=macd_hist_direction,
            macd_line=macd_line,
            atr_then=atr_then,
        )
        return payload, formulas

    @staticmethod
    def _build_formulas(
        payload: Dict[str, Dict[str, Any]],
        *,
        close_5d_ago: Optional[float],
        low_1y: Optional[float],
        high_1y: Optional[float],
        sma_10w: Optional[float],
        rsi_parts: Optional[Tuple[float, float]],
        avg_vol_5: Optional[float],
        avg_vol_60: Optional[float],
        worst_detail: Optional[Tuple[float, float, float]],
        bench_receipts: Dict[str, Dict[str, Any]],
        weekly_stack: Optional[str],
        weekly_struct: Optional[str],
        daily_stack: Optional[str],
        daily_struct: Optional[str],
        macd_hist_direction: Optional[str],
        macd_line: Optional[float],
        atr_then: Optional[float],
    ) -> Dict[str, Any]:
        """UI receipts, keyed "group.key": formula words + this run's
        plugged-in inputs — the levels-table pattern. One-outcome
        formulas ship a "formula" string; rules with several possible
        outcomes ship "branches" instead — one {label, condition} per
        outcome, the catch-all with condition None — so the UI renders
        one line per outcome (owner format 2026-07-28). Conditions spell
        every ingredient as its input token with an explicit comparator
        ("rsi_14 > 55", "macd_hist = rising") so the UI can swap tokens
        for the exact on-screen names. The frontend picks the plugged
        style from the ingredients: all numeric → numbers substitute in
        place per branch line; any word ingredient → the pairs fold into
        the result line ("= neutral: 14d RSI = 49.31 && …"). Aggregate
        fields whose ingredients are whole series (a 50-close average)
        get words only, no inputs.
        A receipt is published only when its metric has a value and
        every input is present — a partial receipt would show broken
        arithmetic."""
        formulas: Dict[str, Any] = {}

        def add(
            path: str,
            formula: Optional[str] = None,
            inputs: Optional[Dict[str, Any]] = None,
            digits: int = 2,
            branches: Optional[List[Dict[str, Optional[str]]]] = None,
        ) -> None:
            group, key = path.split(".")
            if metric_value(payload.get(group, {}).get(key)) is None:
                return
            plugged: Dict[str, Any] = {}
            for var, value in (inputs or {}).items():
                if value is None:
                    return
                plugged[var] = (
                    round(value, digits)
                    if isinstance(value, (int, float))
                    else value
                )
            entry: Dict[str, Any] = {"inputs": plugged}
            if formula is not None:
                entry["formula"] = formula
            if branches is not None:
                entry["branches"] = branches
            formulas[path] = entry

        add(
            "market.regime",
            inputs=bench_receipts.get("regime"),
            branches=[
                {"label": "bullish",
                 "condition": "index_close > index_sma_200 && "
                              "index_range_pct > 50"},
                {"label": "bearish",
                 "condition": "index_close < index_sma_200 && "
                              "index_range_pct < 50"},
                {"label": "mixed", "condition": None},
            ],
        )
        add(
            "market.rs_1m",
            "stock_return_1m − index_return_1m",
            bench_receipts.get("rs_1m"),
        )
        add(
            "market.rs_3m",
            "stock_return_3m − index_return_3m",
            bench_receipts.get("rs_3m"),
        )
        add(
            "market.rs_label",
            inputs=bench_receipts.get("rs_label"),
            branches=[
                {"label": "leader",
                 "condition": "rs_1m > 0 && rs_3m > 0"},
                {"label": "laggard",
                 "condition": "rs_1m < 0 && rs_3m < 0"},
                {"label": "neutral", "condition": None},
            ],
        )
        close = read_metric(payload, "price", "close")
        atr = read_metric(payload, "volatility", "atr_14")
        sma_50 = read_metric(payload, "daily", "sma_50")
        add(
            "price.chg_5d_pct",
            "(close − close_5d_ago) / close_5d_ago × 100",
            {"close": close, "close_5d_ago": close_5d_ago},
        )
        add(
            "price.range_pct_1y",
            # The UI shows the value as a position out of 100 ("30/100"),
            # so the receipt names the rounding that gets there.
            "(close − low_1y) / (high_1y − low_1y) × 100, "
            "rounded to a position out of 100",
            {"close": close, "low_1y": low_1y, "high_1y": high_1y},
        )
        add(
            "price.high_1y",
            f"the highest traded price of the last {YEAR_BARS} daily bars",
        )
        add(
            "price.low_1y",
            f"the lowest traded price of the last {YEAR_BARS} daily bars",
        )
        trend_branches = [
            {"label": "bullish",
             "condition": "ma_stack = up && "
                          "pivot_structure = higher highs and lows"},
            {"label": "bearish",
             "condition": "ma_stack = down && "
                          "pivot_structure = lower highs and lows"},
            {"label": "neutral", "condition": None},
        ]
        add(
            "weekly.trend",
            inputs={"ma_stack": weekly_stack,
                    "pivot_structure": weekly_struct},
            branches=trend_branches,
        )
        add(
            "weekly.sma_10w",
            f"the sum of the last {WEEKLY_SMA_FAST} weekly closes"
            f" / {WEEKLY_SMA_FAST}",
        )
        add(
            "weekly.stretch_10w_atr",
            "(close − sma_10w) / (atr_14 × √5)",
            {"close": close, "sma_10w": sma_10w, "atr_14": atr},
        )
        add(
            "daily.trend",
            inputs={"ma_stack": daily_stack,
                    "pivot_structure": daily_struct},
            branches=trend_branches,
        )
        add(
            "daily.sma_50",
            f"the sum of the last {DAILY_SMA_MID} daily closes"
            f" / {DAILY_SMA_MID}",
        )
        add(
            "daily.stretch_50d_atr",
            "(close − sma_50) / atr_14",
            {"close": close, "sma_50": sma_50, "atr_14": atr},
        )
        add(
            "daily.sma_200",
            f"the sum of the last {DAILY_SMA_LONG} daily closes"
            f" / {DAILY_SMA_LONG}",
        )
        add(
            "daily.stretch_200d_atr",
            "(close − sma_200) / atr_14",
            {"close": close,
             "sma_200": read_metric(payload, "daily", "sma_200"),
             "atr_14": atr},
        )
        add(
            "daily.momentum",
            inputs={
                "rsi_14": read_metric(payload, "daily", "rsi_14"),
                "macd_hist": macd_hist_direction,
                "macd_line": macd_line,
            },
            branches=[
                {"label": "strong",
                 "condition": f"rsi_14 > {MOMENTUM_RSI_STRONG} && "
                              "macd_hist = rising && macd_line > 0"},
                {"label": "weak",
                 "condition": f"rsi_14 < {MOMENTUM_RSI_WEAK} && "
                              "macd_hist = falling && macd_line < 0"},
                {"label": "fading",
                 "condition": f"rsi_14 > {MOMENTUM_RSI_STRONG} && "
                              "macd_hist = falling"},
                {"label": "basing",
                 "condition": f"rsi_14 < {MOMENTUM_RSI_WEAK} && "
                              "macd_hist = rising"},
                {"label": "neutral", "condition": None},
            ],
        )
        if rsi_parts is not None and rsi_parts[1] > 0:
            add(
                "daily.rsi_14",
                "100 − 100 / (1 + avg_gain_14 / avg_loss_14)",
                {"avg_gain_14": rsi_parts[0], "avg_loss_14": rsi_parts[1]},
                digits=4,
            )
        add(
            "volatility.atr_14",
            f"the Wilder-smoothed average of the last {ATR_PERIOD} daily "
            "true ranges (a day's true range = its high − low, widened to "
            "include any gap from the previous close)",
        )
        add(
            "volatility.atr_pct",
            "atr_14 / close × 100",
            {"atr_14": atr, "close": close},
        )
        add(
            "volatility.atr_trend",
            inputs={"atr_14": atr, "atr_20_bars_ago": atr_then},
            branches=[
                {"label": "expanding",
                 "condition": f"atr_14 > {1 + ATR_TREND_BAND:.2f} × "
                              "atr_20_bars_ago"},
                {"label": "contracting",
                 "condition": f"atr_14 < {1 - ATR_TREND_BAND:.2f} × "
                              "atr_20_bars_ago"},
                {"label": "stable", "condition": None},
            ],
        )
        add(
            "volume.avg_vol_60d",
            f"the sum of the last {VOLUME_BASE_BARS} daily volumes"
            f" / {VOLUME_BASE_BARS}",
        )
        add(
            "volume.avg_vol_5d",
            f"the sum of the last {VOLUME_RECENT_BARS} daily volumes"
            f" / {VOLUME_RECENT_BARS}",
        )
        add(
            "volume.vol_ratio_5_60",
            "avg_vol_5d / avg_vol_60d",
            {"avg_vol_5d": avg_vol_5, "avg_vol_60d": avg_vol_60},
            digits=0,
        )
        add(
            "levels.support_1",
            "the highest pivot low below the close, scanning the last "
            f"{DAILY_PIVOT_LOOKBACK} days (a pivot low = a day whose low "
            f"undercuts the {PIVOT_FRINGE} days on each side)",
        )
        add(
            "levels.resistance_1",
            "the lowest pivot high above the close, scanning the last "
            f"{DAILY_PIVOT_LOOKBACK} days (a pivot high = a day whose "
            f"high tops the {PIVOT_FRINGE} days on each side)",
        )
        add(
            "levels.support_dist_atr",
            "(close − nearest_support) / atr_14",
            {"close": close,
             "nearest_support": read_metric(payload, "levels", "support_1"),
             "atr_14": atr},
        )
        resistance_value = read_metric(payload, "levels", "resistance_1")
        add(
            "levels.resistance_dist_atr",
            "(nearest_resistance − close) / atr_14",
            {"nearest_resistance": resistance_value,
             "close": close,
             "atr_14": atr},
        )
        add(
            "volatility.typical_pullback_atr",
            "median depth of the completed pullbacks of the last "
            f"{DAILY_PIVOT_LOOKBACK} trading days "
            "(each pivot high − the next pivot low) / atr_14",
            {"atr_14": atr},
        )
        if worst_detail is not None:
            add(
                "volatility.worst_day_pct_1y",
                "(worst_close − prev_close) / prev_close × 100",
                {"worst_close": worst_detail[2],
                 "prev_close": worst_detail[1]},
                digits=4,
            )
        return formulas

    def _benchmark_fields(
        self,
        closes: List[float],
        warnings: List[str],
        field_notes: Dict[str, List[str]],
    ) -> Tuple[
        Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
        Dict[str, Dict[str, Any]],
    ]:
        """(regime, rs_1m, rs_3m, rs_label, receipt inputs) — envelopes
        with None values + a warning when the benchmark is unwired or
        its fetch fails; the last element maps "rs_1m" / "rs_3m" /
        "rs_label" / "regime" to that receipt's plugged-in inputs (a key
        is absent when its ingredients are)."""
        regime_name = "market trend"
        rs_1m_name = "1m return diff (stock vs market)"
        rs_name = "3m return diff (stock vs market)"
        rs_label_name = "stock performance relative to market"
        rs_1m_explanation = (
            "Stock return minus benchmark return over the last "
            f"{RS_WINDOW_1M} trading days (about 1 month), in percentage "
            "points."
        )
        rs_explanation = (
            "Stock return minus benchmark return over the last "
            f"{RS_WINDOW_3M} trading days (about 3 months), in percentage "
            "points."
        )
        rs_interpretation = "Positive = leading the market."
        label_explanation = (
            "leader = outperforming the benchmark over both 1 and 3 "
            "months; laggard = underperforming over both; else neutral."
        )
        label_interpretation = (
            "Prefer longs in leaders — a laggard long needs an explicit "
            "catalyst from the other reports."
        )
        regime_interpretation = (
            "Most stocks follow the tape: in a bearish regime demand "
            "stronger setups and smaller size."
        )

        def _absent(reason: str) -> Tuple[Any, ...]:
            note_fields(warnings, field_notes, reason, BENCHMARK_FIELDS)
            return (
                make_metric(
                    regime_name,
                    f"What the overall market is doing. {reason}.",
                    None,
                    interpretation=regime_interpretation,
                ),
                make_metric(
                    rs_1m_name, rs_1m_explanation, None,
                    interpretation=rs_interpretation,
                ),
                make_metric(
                    rs_name, rs_explanation, None,
                    interpretation=rs_interpretation,
                ),
                make_metric(
                    rs_label_name, label_explanation, None,
                    interpretation=label_interpretation,
                ),
                {},
            )

        if self._index_bars_loader is None:
            return _absent("benchmark index not configured for this market")
        try:
            index_bars = list(self._index_bars_loader())
        except Exception as exc:
            return _absent(f"benchmark index bars unavailable: {exc}")
        index_closes = [bar.close for bar in index_bars]
        regime = regime_read(index_closes)
        rs_1m = relative_strength_pct(closes, index_closes, RS_WINDOW_1M)
        rs_3m = relative_strength_pct(closes, index_closes, RS_WINDOW_3M)
        if regime is None and rs_3m is None:
            return _absent(
                f"benchmark index history too short "
                f"({len(index_closes)} bars)"
            )

        if regime is not None:
            position = "above" if regime["above_200d"] else "below"
            regime_env = make_metric(
                regime_name,
                f"What the overall market is doing, from the benchmark "
                f"index ({self._benchmark_name}): {position} its 200-day "
                f"average and at {regime['range_pct']:.0f}% of its "
                "one-year range.",
                regime["label"],
                interpretation=regime_interpretation,
            )
        else:
            note_fields(
                warnings, field_notes,
                "benchmark index history too short for the regime read",
                ("market.regime",),
            )
            regime_env = make_metric(
                regime_name,
                "What the overall market is doing. Benchmark history too "
                "short for the 200-day regime read.",
                None,
                interpretation=regime_interpretation,
            )
        receipts: Dict[str, Dict[str, Any]] = {}
        stock_return_1m = pct_change(closes, RS_WINDOW_1M)
        index_return_1m = pct_change(index_closes, RS_WINDOW_1M)
        if stock_return_1m is not None and index_return_1m is not None:
            receipts["rs_1m"] = {
                "stock_return_1m": stock_return_1m,
                "index_return_1m": index_return_1m,
            }
        stock_return_3m = pct_change(closes, RS_WINDOW_3M)
        index_return_3m = pct_change(index_closes, RS_WINDOW_3M)
        if stock_return_3m is not None and index_return_3m is not None:
            receipts["rs_3m"] = {
                "stock_return_3m": stock_return_3m,
                "index_return_3m": index_return_3m,
            }
        if rs_1m is not None and rs_3m is not None:
            receipts["rs_label"] = {"rs_1m": rs_1m, "rs_3m": rs_3m}
        if regime is not None:
            receipts["regime"] = {
                "index_close": regime["close"],
                "index_sma_200": regime["sma_200"],
                "index_range_pct": regime["range_pct"],
            }
        return (
            regime_env,
            make_metric(
                rs_1m_name, rs_1m_explanation, rs_1m,
                interpretation=rs_interpretation,
            ),
            make_metric(
                rs_name, rs_explanation, rs_3m,
                interpretation=rs_interpretation,
            ),
            make_metric(
                rs_label_name,
                label_explanation,
                relative_strength_label(rs_1m, rs_3m),
                interpretation=label_interpretation,
            ),
            receipts,
        )
