import type { UiLanguage } from './uiText';

// Vocabulary for tiered-analysis dimension payloads (backend keys stay
// snake_case on purpose — see api/tiered.ts). Each entry has the compact
// label shown in the table (`short`) and the plain-language definition
// shown in the hover/click popup (`full`). Entries may also carry
// `interp` — how to read the number as a trader; when present the popup
// renders "Meaning: … / Interpretation: …" as two blocks (owner format
// 2026-07-29) — and `blank` — why this field can be empty, shown in the
// modal behind the "n/a" placeholder (owner request 2026-07-31).
// Labels follow the field names in TODO.md; tooltip text is written in
// everyday words per the owner's plain-English rule (2026-07-29).
// Unknown keys fall back to the raw key with no popup.
export interface MetricEntry {
  short: string;
  full: string;
  interp?: string;
  blank?: string;
}

const en: Record<string, MetricEntry> = {
  // ---- technicals ----
  close: {
    short: 'Closing price',
    full: "The last price the stock traded at on the most recent trading day.\nUnit: the stock's own currency (USD for US stocks).",
    interp: 'The starting point — every distance in this report (to supports, averages, targets) is measured from this price.',
  },
  bars_count: {
    short: 'Bars',
    full: 'How many trading days of price history were used for these calculations.',
  },
  sma_20: {
    short: 'SMA 20',
    full: 'The average closing price of the last 20 trading days ("SMA" = simple moving average).\nAveraging smooths out day-to-day noise so the short-term direction is easier to see.',
  },
  sma_60: {
    short: 'SMA 60',
    full: 'The average closing price of the last 60 trading days — the medium-term trend line.',
  },
  ema_12: {
    short: 'EMA 12',
    full: 'An average of the last 12 days of prices where the newest days count the most ("EMA" = exponential moving average).',
  },
  ema_26: {
    short: 'EMA 26',
    full: 'The same idea over 26 days — a slower-moving average used together with EMA 12.',
  },
  rsi_14: {
    short: '14d RSI',
    full: 'A 0-to-100 gauge of how fast the price has been rising or falling lately ("RSI" = relative strength index, 14 days).\nAbove 70 = rose unusually fast; below 30 = fell unusually fast; near 50 = calm.',
    interp: 'Careful: in strong uptrends it can sit above 70 for weeks — a high reading alone is not a sell signal.',
    blank: 'Fewer than about 15 days of price history were loaded.',
  },
  macd: {
    short: 'MACD',
    full: 'A momentum gauge built by comparing a fast price average with a slow one ("MACD" = moving average convergence divergence).\nWhen the fast average pulls ahead, upward push is building.',
  },
  signal: {
    short: 'Signal',
    full: 'A smoothed average of the MACD line.\nThe MACD line crossing above or below it is a common buy/sell trigger.',
  },
  histogram: {
    short: 'Histogram',
    full: 'MACD line minus signal line.\nPositive and growing = upward push building; negative = the push is fading.',
  },
  atr_14: {
    short: '14d ATR',
    full: "The size of a normal day's price move for this stock ('ATR' = average true range, 14 days).\nUnit: the stock's currency — an ATR of $19 means a typical day moves the price about $19.",
    interp: 'The ruler for stops and position sizes: distances measured in ATRs compare fairly between calm stocks and jumpy ones.',
    blank: 'Fewer than about 15 days of price history were loaded.',
  },
  volatility_pct: {
    short: 'Volatility %',
    full: 'The normal daily move (14d ATR) as a percent of the price.\nAbove ~4% counts as a jumpy, high-volatility stock — the plan review may shrink the position or widen the stop.',
  },
  swing_low_20: {
    short: 'Swing low 20',
    full: 'The lowest price actually traded in the last 20 trading days — a floor buyers have already defended once.\nUsed as a support anchor for the entry price.',
  },
  bias_20: {
    short: 'Bias 20',
    full: 'How far the price sits above or below its own 20-day average, in %.\nWhen it stretches far from the average, it tends to snap back toward it.',
  },
  swing_high_20: {
    short: 'Swing high 20',
    full: 'The highest price actually traded in the last 20 trading days — a ceiling sellers have already defended once.\nUsed as a resistance anchor for the target.',
  },
  swing_low_60: {
    short: 'Swing low 60',
    full: 'The lowest price traded in the last 60 trading days — a deeper, older floor than the 20-day low.\nJoins the support candidates for the entry.',
  },
  swing_high_60: {
    short: 'Swing high 60',
    full: 'The highest price traded in the last 60 trading days — a wider ceiling than the 20-day high.',
  },
  high_52w: {
    short: '52w high',
    full: 'The highest price in the loaded history (about a year) — the strongest ceiling reference.',
  },
  low_52w: {
    short: '52w low',
    full: 'The lowest price in the loaded history (about a year).',
  },
  avg_volume_20: {
    short: 'Avg volume 20',
    full: 'The average number of shares traded per day over the last 20 trading days.\nUsed to judge whether a position could be sold in one day without pushing the price down.',
  },
  worst_day_pct_1y: {
    short: 'Worst price drop (1y range)',
    full: "The single worst one-day drop of the past year, measured from one day's closing price to the next.\nUnit: percent, negative — e.g. -14.5 means that day lost 14.5%.",
    interp: 'Shows how far one overnight surprise (bad earnings, bad news) can jump the price straight past a stop-loss.',
    blank: 'Less than about a month of price history was loaded — too few days to report a meaningful worst drop.',
  },
  worst_day_1y: {
    short: 'Worst day 1y',
    full: 'Retired field old runs still carry: the same statistic written as a fraction (-0.17 meaning -17%), and scanned over all loaded history rather than one year. New runs publish worst_day_pct_1y instead.',
  },
  worst_day_5pct: {
    short: 'Worst 5% day',
    full: 'Retired statistic old runs still carry: the daily drop only the worst 5% of days exceeded.',
  },
  score: {
    short: 'Tech score',
    full: 'Retired field old runs still carry: a code-computed 0-100 technical score. New runs omit it — handing the AI a finished verdict made it anchor on the number instead of reading the fields.',
  },

  // ---- technicals v2 groups + fields (2026-07-27; regrouped 2026-07-28) ----
  market: {
    short: 'Market vs sector vs stock',
    full: "The three-layer read: what the market is doing, whether this stock's sector (industry family) is leading or lagging the market, and whether the stock is leading or lagging both.",
  },
  regime: {
    short: 'Market trend',
    full: 'Is the overall market — not this stock — healthy? Judged on the benchmark index (S&P 500 for US stocks): is the index above its own 200-day average price, and is it in the upper or lower half of its one-year range?\nValues: bullish / bearish / mixed.',
    interp: "Most stocks follow the market. Buying in a bearish market usually fails even when this stock's own chart looks good — demand a stronger setup and use a smaller position.",
    blank: 'This market has no benchmark index set up, or the index data failed to load.',
  },
  rs_sector_1m: {
    short: '1m return diff (sector vs market)',
    full: "The return of the stock's sector (its industry family, measured via the sector's ETF — a fund holding the sector's big stocks) minus the market's return over the last month.\nUnit: percentage points.",
    interp: 'Positive = the sector is leading the market. Swing moves in leading sectors run further and pull back shallower.',
    blank: "The sector is unknown or has no sector ETF mapped (US sectors only for now), the market benchmark is unavailable, or the sector ETF's data failed to load.",
  },
  rs_sector_3m: {
    short: '3m return diff (sector vs market)',
    full: "The return of the stock's sector (via its sector ETF) minus the market's return over the last 3 months.\nUnit: percentage points.",
    interp: 'Positive = the sector is leading the market. Fighting a lagging sector cuts the win rate even on a clean chart.',
    blank: "The sector is unknown or has no sector ETF mapped (US sectors only for now), the market benchmark is unavailable, or the sector ETF's data failed to load.",
  },
  sector_vs_market_label: {
    short: 'Sector performance relative to market',
    full: "A one-word verdict from the two sector numbers above: leader = the sector beat the market over both the 1-month and 3-month windows; laggard = lost to it over both; neutral = mixed.",
    interp: 'The middle layer between the market and the single stock — a leading sector is a tailwind for longs in it.',
    blank: 'The two sector return-difference numbers above are blank, so there is nothing to conclude from.',
  },
  rs_stock_sector_1m: {
    short: '1m return diff (stock vs sector)',
    full: "The stock's return minus its own sector's return over the last month.\nUnit: percentage points.",
    interp: 'Read together with the sector rows: positive in a leading sector = leading the family; positive in a falling sector = only falling slower than it.',
    blank: 'The sector comparison is unavailable (see the sector rows above), so this diff cannot be computed.',
  },
  rs_stock_sector_3m: {
    short: '3m return diff (stock vs sector)',
    full: "The stock's return minus its own sector's return over the last 3 months.\nUnit: percentage points.",
    interp: 'Read together with the sector rows: positive in a leading sector = leading the family; positive in a falling sector = only falling slower than it.',
    blank: 'The sector comparison is unavailable (see the sector rows above), so this diff cannot be computed.',
  },
  stock_vs_sector_label: {
    short: 'Stock performance relative to sector',
    full: 'A one-word verdict: leader = the stock beat its own sector over both the 1-month and 3-month windows; laggard = lost to it over both; neutral = mixed.',
    interp: 'Separates a genuinely strong stock from one carried by a hot sector — a laggard inside a leading sector is the weakest member of a strong club.',
    blank: 'The stock-vs-sector diffs above are blank, so there is nothing to conclude from.',
  },
  relative_strength: {
    short: 'Relative strength',
    full: 'Is this stock doing better or worse than the market itself?',
  },
  price: {
    short: 'Stock price',
    full: 'The current price and where it sits in its own recent history.',
  },
  weekly: {
    short: 'Weekly timeframe',
    full: 'The zoomed-out view (one bar = one week). It sets the direction — trades should only go this way.',
  },
  daily: {
    short: 'Daily timeframe',
    full: 'The zoomed-in view (one bar = one day) — used to time the entry and write the trade plan.',
  },
  volatility: {
    short: 'Volatility',
    full: 'How jumpy this stock is — the ruler that stops and position sizes are measured with.',
  },
  volume: {
    short: 'Volume',
    full: 'How much is actually traded — can an order get in and out easily, and is a move backed by real buying?',
  },
  levels: {
    short: 'Levels',
    full: "Actual prices from the stock's past turning points — where the entry, stop and target anchor.",
  },
  risk: {
    short: 'Risk',
    full: "How bad this stock's bad days actually get.",
  },
  bars_daily: {
    short: 'Daily bars',
    full: "How many days of price history were loaded (one 'bar' = one trading day).\nUnit: a count; the target is 300.",
    interp: 'Below about 253 (one trading year), the one-year fields only cover the history that exists.',
  },
  bars_weekly: {
    short: 'Weekly bars',
    full: 'How many weeks of history, built by combining the daily data.\nUnit: a count; the target is 60.',
    interp: 'With fewer than 60, the weekly trend read is shaky.',
  },
  rs_1m: {
    short: '1m return diff (stock vs market)',
    full: "The stock's return over the last month minus the market's return over the same month: +5 means it beat the market by 5 points.\nUnit: percentage points; usually between -20 and +20.",
    interp: 'Positive = leading the market; negative = lagging it.',
    blank: 'This market has no benchmark index set up, the index data failed to load, or there is less than a month of history.',
  },
  rs_3m: {
    short: '3m return diff (stock vs market)',
    full: "The stock's return over the last 3 months minus the market's return over the same window: +5 means it beat the market by 5 points, -20 means it lost to it by 20.\nUnit: percentage points; usually between -30 and +30.",
    interp: 'Positive = leading the market; negative = lagging it.',
    blank: 'This market has no benchmark index set up, the index data failed to load, or there is less than 3 months of history.',
  },
  rs_label: {
    short: 'Stock performance relative to market',
    full: 'A one-word verdict from the two stock-vs-market numbers: leader = beat the market over both the 1-month and 3-month windows; laggard = lost to it over both; neutral = mixed.',
    interp: 'Prefer buying leaders — buying a laggard needs a clear reason from the other reports.',
    blank: 'The two return-difference numbers above are blank (no benchmark set up or the index data failed to load), so there is nothing to conclude from.',
  },
  chg_5d_pct: {
    short: '5d price change',
    full: 'How much the price moved over the last 5 trading days.\nUnit: percent; usually -15 to +15.',
    interp: 'A big jump means the cheap entry may already be gone.',
    blank: 'Fewer than 6 days of price history were loaded.',
  },
  range_pct_1y: {
    short: 'Current price ranking (1y range)',
    full: "Where today's price sits inside its past-year range, as a position out of 100.\n0/100 = at the year's low, 100/100 = at the year's high.",
    interp: 'Above ~80/100 = strong but risky to chase; below ~20/100 = a falling knife unless it is clearly bottoming out.',
    blank: "\"1y highest price\" and \"1y lowest price\" are unavailable (too little history), or they are equal so a position can't be computed.",
  },
  high_1y: {
    short: '1y highest price',
    full: "The highest price touched in the last year.\nUnit: the stock's currency.",
    interp: 'Prices often stall just below the old high — people who bought there are waiting to sell once they break even. A target above it assumes the stock pushes into new-high ground, which is a harder trade than buying a dip.',
  },
  low_1y: {
    short: '1y lowest price',
    full: "The lowest price touched in the last year — the floor of the one-year range.\nUnit: the stock's currency.",
    interp: 'How far the market has actually let this stock fall in a year.',
  },
  trend: {
    short: 'Trend (SMA + pivots)',
    full: "The overall direction, from two independent checks that must agree: (1) is the price above or below its own average lines (SMA), and (2) are the chart's recent peaks and dips ('pivots') stepping higher or lower?\nValues: bullish / bearish / neutral (neutral = the two checks disagree).",
    interp: 'The direction filter: trades should only go the way the weekly trend points, and dip-buying works best when the daily and weekly trends agree.',
    blank: 'One of the two checks (average lines, or recent peaks and dips) has too little history to answer.',
  },
  sma_10w: {
    short: '10w SMA',
    full: "The average price of the last 10 weeks.\nUnit: the stock's currency.",
    interp: 'The medium-term trend line; holding above it keeps a swing uptrend intact.',
    blank: 'Fewer than 10 weeks of price history were loaded.',
  },
  stretch_10w_atr: {
    short: 'Diff (closing price vs 10w SMA)',
    full: 'How far the price is above (+) or below (-) its 10-week average, measured in normal weekly moves (ATR units).\nRange: usually -4 to +4.',
    interp: 'Above ~+1.5 = stretched too far, wait for a dip; -0.5 to +1 in an uptrend = a good dip-buy zone.',
    blank: 'The "10w SMA" or the normal-move gauge ("14d ATR") is unavailable because the history is too short.',
  },
  sma_50: {
    short: '50d SMA',
    full: "The average price of the last 50 trading days.\nUnit: the stock's currency.",
    interp: 'Rising stocks often dip back to this line before continuing — the classic buy-the-dip level.',
    blank: 'Fewer than 50 days of price history were loaded.',
  },
  stretch_50d_atr: {
    short: 'Diff (closing price vs 50d SMA)',
    full: 'How far the price is above (+) or below (-) its 50-day average, in normal daily moves (ATR units).\nRange: usually -5 to +5.',
    interp: '-1 to +1 in an uptrend = a good entry zone; above +3 = chasing.',
    blank: 'The "50d SMA" or the normal-move gauge ("14d ATR") is unavailable because the history is too short.',
  },
  stretch_200d_atr: {
    short: 'Diff (closing price vs 200d SMA)',
    full: 'How far the price is above (+) or below (-) its 200-day average, in normal daily moves (ATR units).',
    interp: 'Positive = the long-term uptrend is intact; negative = the price is below the long-term line, so buying is against the long-term trend.',
    blank: 'The "200d SMA" or the normal-move gauge ("14d ATR") is unavailable because the history is too short.',
  },
  sma_200: {
    short: '200d SMA',
    full: "The average price of the last 200 trading days — the most-watched line in finance.\nUnit: the stock's currency.",
    interp: 'Price above it = long-term healthy; the line itself often acts as a floor or ceiling. Below it, buying is fighting the long-term tide.',
    blank: 'Fewer than 200 days of price history were loaded.',
  },
  momentum: {
    short: 'Momentum',
    full: 'A one-word verdict combining the RSI and MACD gauges:\nstrong = pushing up hard; weak = pushing down; fading = price still high but the push is dying; basing = price still low but the push is building; neutral = neither.',
    interp: 'strong supports new buys; fading warns the move is running out of fuel while the price still looks fine; basing flags an early turn upward.',
    blank: 'The "14d RSI" row or the MACD histogram behind it is unavailable because the history is too short.',
  },
  atr_pct: {
    short: '14d ATR (% of closing price)',
    full: 'The normal daily move as a percent of the price — lets you compare a $10 stock with a $500 stock.\nUnit: percent; typically 1 to 6.',
    interp: 'Above ~6 = a wild stock; consider a smaller position.',
    blank: 'Fewer than about 15 days of price history were loaded, so the normal daily move cannot be measured.',
  },
  atr_trend: {
    short: 'ATR trend',
    full: 'Is the daily jumpiness growing or shrinking compared with about a month ago?\nValues: expanding / contracting / stable (changes within ±10% count as stable).',
    interp: 'Expanding = widen the stop and buy fewer shares; contracting = the stock is coiling up, and a big move often follows.',
    blank: 'The history is too short to compare the normal daily move with a month ago.',
  },
  avg_vol_60d: {
    short: '60d avg volume',
    full: 'The average number of shares traded per day over about 3 months.\nUnit: shares (often millions).',
    interp: 'The liquidity baseline: whether a position can get in and out without moving the price.',
    blank: 'Fewer than 60 days of price history were loaded.',
  },
  avg_vol_5d: {
    short: '5d avg volume',
    full: 'The average number of shares traded per day over the last week.\nUnit: shares.',
    interp: 'The recent-activity read that the volume ratio compares against the 3-month normal.',
    blank: 'Fewer than 5 days of price history were loaded.',
  },
  vol_ratio_5_60: {
    short: 'Volume ratio (5d/60d)',
    full: "This week's average volume versus the 3-month normal.\nUnit: a ratio; usually 0.5 to 2, where 1.0 = normal.",
    interp: 'Above ~1.5 while the price pushes through a ceiling = real interest confirms the move; below ~0.7 = the move is suspect.',
    blank: 'One of the two volume averages it is built from is unavailable (history too short).',
  },
  support_1: {
    short: 'Nearest support',
    full: "The nearest price BELOW today's where buyers stepped in before (a past dip-bottom).\nUnit: the stock's currency.",
    interp: 'A protective stop-loss belongs just below a level like this, not at a random percent.',
    blank: 'The price is at its lowest point in about 6 months — there is no past floor beneath it.',
  },
  support_dist_atr: {
    short: 'Diff (closing price vs nearest support)',
    full: 'How far the price sits above the nearest support, in normal daily moves (ATR units).',
    interp: 'Small = the floor is affordably close, so a stop under it is cheap; large = a stop under support risks more than a typical setup should.',
    blank: 'There is no "Nearest support" below (price at its ~6-month low), or the normal-move gauge ("14d ATR") is unavailable.',
  },
  resistance_1: {
    short: 'Nearest resistance',
    full: "The nearest price ABOVE today's where sellers showed up before (a past peak).\nUnit: the stock's currency.",
    interp: 'The first realistic profit target — expect selling there.',
    blank: 'The price is at its highest point in about 6 months — there is no past ceiling above it.',
  },
  resistance_dist_atr: {
    short: 'Diff (nearest resistance vs closing price)',
    full: 'How far the nearest resistance sits above the price, in normal daily moves (ATR units).',
    interp: 'The room to run before the first ceiling — small means the easy gain is nearly used up.',
    blank: 'There is no "Nearest resistance" above (price at its ~6-month high), or the normal-move gauge ("14d ATR") is unavailable.',
  },
  typical_pullback_atr: {
    short: 'Typical price drop (6m range)',
    full: "How deep this stock's normal dips have been over the last ~6 months — from each local top down to the next local bottom — measured in normal daily moves (ATR units).\nRange: usually 1 to 5.",
    interp: 'If a stop is closer than this, ordinary wiggling will hit it even when the trade idea is right.',
    blank: 'Fewer than 2 completed dips were found in the last ~6 months, so there is no typical depth to report.',
  },

  // ---- fundamentals (regrouped 2026-07-31; labels follow TODO.md; legacy keys kept for old stored runs) ----
  sector: {
    short: 'Sector',
    full: "The broad group of companies this one belongs to (e.g. Technology, Energy).\nFetched from Yahoo Finance, which picks it from a fixed standard list — it is not made up per company.",
    interp: 'The ratios in this report only mean something compared against similar companies. The sector also says which big-picture numbers matter most: oil prices for energy names, interest rates for growth tech.',
    blank: "Yahoo Finance's company profile was unavailable or did not carry a sector for this ticker.",
  },
  industry: {
    short: 'Industry',
    full: 'The finer group inside the sector (e.g. Semiconductors inside Technology). Also fetched from a fixed list.',
    interp: "The exact peer group this company's numbers should be compared against.",
    blank: "Yahoo Finance's company profile was unavailable or did not carry an industry for this ticker.",
  },
  quarterly_report: {
    short: 'Quarterly report',
    full: "The company's report calendar and how the stock has actually behaved around past reports — the single-stock event risk.",
  },
  beats_4q: {
    short: '4q EPS beat estimate history',
    full: 'Out of the last 4 quarterly reports, how many times earnings per share (EPS) came in at or above what analysts expected (e.g. 3/4).',
    interp: 'Companies that consistently beat expectations get the benefit of the doubt going into a report; habitual missers lose it.',
    blank: 'No past report history was available, or none of the past reports had an analyst estimate to compare against.',
  },
  avg_surprise_pct_4q: {
    short: '4q avg diff (EPS vs estimate)',
    full: 'On average, how far above or below the analyst estimate the reported EPS landed, across those 4 reports.\nUnit: percent.',
    interp: 'Says whether the company tends to clear the bar analysts set — not how the stock reacts. Read it together with the report-day move below.',
    blank: 'No past report history was available, or the reports had no analyst estimates to measure against.',
  },
  reaction_avg_abs_pct: {
    short: '4q avg report day price change magnitude',
    full: "How big the stock's price move around each of the last 4 reports actually was, on average, ignoring direction (measured from the closing price before the report to the closing price after).\nUnit: percent.",
    interp: 'The real event risk: a stock that routinely moves ±10% on report day needs a different plan than one that moves ±2%.',
    blank: 'Fewer than 2 past reports fall inside the loaded price history, so there is no meaningful average.',
  },
  reaction_worst_pct: {
    short: '4q worst report day price drop',
    full: 'The single worst drop around those same reports.\nUnit: percent, negative.',
    interp: 'How badly holding through a report has actually gone recently.',
    blank: 'Fewer than 2 past reports fall inside the loaded price history.',
  },
  eps_rev_30d_pct: {
    short: '30d EPS estimate change',
    full: "Whether analysts have been raising or cutting their earnings-per-share forecast for the current quarter — the change in the average forecast versus 30 days ago.\nUnit: percent.",
    interp: 'The direction analysts are moving next quarter’s earnings bar. Rising forecasts tend to precede price drift over the following weeks; cuts are the more reliable side, since analysts cut slowly and reluctantly. Around ±1% is noise.',
    blank: 'No analyst estimates were available, or the 30-days-ago estimate was so close to zero that a percent change would be meaningless.',
  },
  eps_up_revisions_30d: {
    short: '30d analysts that increased EPS estimates',
    full: 'How many analysts raised their earnings-per-share forecast for the current quarter in the last 30 days.',
    interp: 'How many analysts moved, not how far — a forecast change backed by one analyst is a single view; backed by five or six, a consensus is shifting.',
    blank: 'Yahoo Finance published no revision counts for this stock.',
  },
  eps_down_revisions_30d: {
    short: '30d analysts that decreased EPS estimates',
    full: 'How many analysts cut their earnings-per-share forecast for the current quarter in the last 30 days.',
    interp: 'Read beside the up count: high in both directions means genuine disagreement the estimate-change percent alone hides; 0 and 0 means no analyst touched the forecast in a month, so treat the estimate-based fields with extra caution.',
    blank: 'Yahoo Finance published no revision counts for this stock.',
  },
  // Old stored runs only (swapped to the 30d field on 2026-08-23).
  eps_rev_90d_pct: {
    short: '90d EPS estimate change',
    full: "Old runs only: whether analysts have been raising or cutting their earnings-per-share forecast for the current quarter — the change in the average forecast versus 90 days ago.\nUnit: percent.",
    interp: 'Rising forecasts tend to pull the price up over weeks; cuts are a headwind even when the chart looks good.',
    blank: 'No analyst estimates were available, or the 90-days-ago estimate was so close to zero that a percent change would be meaningless.',
  },
  // Dividend fields: old runs only (the group was dropped from the
  // TODO.md final field list on 2026-07-31).
  dividend: {
    short: 'Dividend',
    full: 'Old runs only: the scheduled cash payout to shareholders — a small, known event that nudges the price on a set date.',
  },
  days_until_dividend: {
    short: 'Days until next dividend payment',
    full: 'Old runs only: how many days from today until the company next pays its dividend.',
    interp: 'The cash arrives on this date, but the price dips earlier: on the ex-dividend date the stock starts trading without the payout and opens lower by roughly the dividend amount.',
    blank: 'The company pays no dividend, or no payment date is scheduled yet.',
  },
  dividend_amount_est: {
    short: 'Estimated dividend amount',
    full: 'Old runs only: the most recent dividend payment per share — the best available guess for the next one.\nUnit: USD.',
    interp: 'Small versus the stock price = a minor scheduled dip around the ex-dividend date; a large payout can clip a tight stop on its own.',
    blank: 'The company pays no dividend, or Yahoo Finance had no record of the last payment.',
  },
  // Legacy group keys (old stored runs only; regrouped away 2026-07-31).
  profile: {
    short: 'Profile',
    full: 'Old runs only: this group merged into Meta info. What kind of company this is.',
  },
  earnings: {
    short: 'Earnings events',
    full: "Old runs only: this group was renamed Quarterly report. The company's report calendar and how the stock behaved around past reports.",
  },
  ex_dividend_date: {
    short: 'Ex-dividend date',
    full: 'Old runs only (replaced by the Dividend group): the date the stock starts trading without its next dividend payment. That morning the price mechanically opens lower by roughly the dividend amount.',
    interp: 'A small, scheduled gap down that can clip a tight stop on a long position.',
  },
  growth: {
    short: 'Growth',
    full: 'Quarterly growth from the latest official SEC filings — the freshest read on whether the business is expanding.',
  },
  revenue_yoy_q: {
    short: 'Quarterly sales (YoY)',
    full: "The latest quarter's sales compared with the same quarter last year.\nUnit: percent.",
    interp: 'Positive and rising = an expanding business; the direction of change matters more than the level.',
    blank: "The SEC filings were unavailable, or there is no same-quarter-last-year sales figure to compare against.",
  },
  revenue_growth_trend: {
    short: 'Growth trend (sales)',
    full: 'Whether that sales growth sped up or slowed compared with the quarter before.\nValues: accelerating / slowing / steady (changes smaller than 2 percentage points count as steady).',
    interp: 'Speeding-up growth is the classic fuel for multi-week rallies; slowing growth often ends them even while growth is still positive.',
    blank: 'Needs the previous quarter\'s growth rate too — blank when "Quarterly sales (YoY)" is unavailable for either quarter.',
  },
  eps_yoy_q: {
    short: 'Quarterly EPS (YoY)',
    full: "The latest quarter's earnings per share (EPS — the quarter's earnings divided by the share count) compared with the same quarter last year.\nUnit: percent.",
    interp: 'Can differ from sales growth when margins or the share count change — share buybacks boost it, issuing new shares drags it.',
    blank: "The SEC filings were unavailable, there is no same-quarter-last-year EPS, or last year's EPS was so close to zero (under $0.05) that a percent change would be meaningless.",
  },
  eps_growth_trend: {
    short: 'Growth trend (EPS)',
    full: 'Whether EPS growth sped up or slowed versus the quarter before.\nValues: accelerating / slowing / steady (same 2-point buffer).',
    interp: 'The market pays for the change in direction, not the level.',
    blank: 'Needs the previous quarter\'s growth rate too — blank when "Quarterly EPS (YoY)" is unavailable for either quarter.',
  },
  profitability: {
    short: 'Profitability',
    full: 'How much of each dollar of sales the company keeps as earnings, and whether those earnings turn into real cash.',
  },
  gross_margin_pct: {
    short: 'Gross earnings to sales',
    full: 'The percent of each sales dollar left after the direct cost of making the product (latest fiscal year).',
    interp: 'High or rising = the company can charge premium prices; falling = competition or rising costs are biting.',
    blank: 'The SEC filings were unavailable, or the company reports no separate "gross profit" line (common for banks), or the figure is from a different year than the sales figure.',
  },
  operating_margin_pct: {
    short: 'Operating earnings to sales',
    full: 'The percent of sales left after all the costs of running the business — salaries, marketing, rent — but before interest and taxes (latest fiscal year).',
    interp: 'The efficiency number the market judges at each report; a break in its trend moves the stock.',
    blank: 'The SEC filings were unavailable, or there is no operating-earnings figure from the same year as the sales figure.',
  },
  roe_pct: {
    short: 'Earnings to equity',
    full: "The year's earnings as a percent of the shareholders' money tied up in the business (equity).",
    interp: 'Staying around 15% or higher marks a quality business; very low or negative means the business burns money.',
    blank: 'The SEC filings were unavailable, or there is no earnings or equity figure from the same fiscal year.',
  },
  fcf: {
    short: 'Free cash flow',
    full: 'The cash the company actually generated after paying its running costs and equipment spending. Covers the last 12 months when the filings allow it, otherwise the latest fiscal year.\nUnit: USD.',
    interp: 'Positive and close to reported earnings = the earnings are real. Reported earnings with negative cash flow is a red flag.',
    blank: 'The SEC filings were unavailable, or the operating-cash and equipment-spending figures do not cover the same period (mixing periods would fabricate a number).',
  },
  fcf_to_earnings_pct: {
    short: 'Free cash flow to earnings',
    full: "Free cash flow as a percent of the same period's earnings.\nUnit: percent.",
    interp: 'Near or above 100% = the reported earnings arrive as real cash; far below 100% for years = the earnings may exist on paper only.',
    blank: 'Earnings were zero or negative (dividing by a loss would read backwards), or no earnings figure covers the same period as the free cash flow.',
  },
  balance: {
    short: 'Balance',
    full: 'What the company owns versus what it owes — its financial strength.',
  },
  current_ratio: {
    short: 'Assets to liabilities (short term)',
    full: "Short-term assets divided by short-term bills — can the company pay what's due within a year (latest fiscal year)?",
    interp: 'Above about 1.5 is comfortable; below 1 hints at a cash crunch, where bad news hits twice as hard.',
    blank: 'The SEC filings were unavailable, or the short-term assets and liabilities figures are not both available for the same fiscal year.',
  },
  debt_to_equity: {
    short: 'Liabilities to equity (total)',
    full: "Everything the company owes compared with the shareholders' money (equity) — how much it runs on borrowed money.",
    interp: 'Heavy borrowing makes moves bigger both ways and hurts most when interest rates are high; compare it against companies in the same industry.',
    blank: 'The SEC filings were unavailable, or the total-liabilities and equity figures are not both available for the same fiscal year.',
  },
  meta: {
    short: 'Meta info',
    full: "Background about this report's data — what it describes, where it comes from, and how fresh it is.",
  },
  entity_name: {
    short: 'Company',
    full: 'The company name on the official SEC filings.',
    interp: 'Confirms the filings really belong to the ticker being analyzed.',
    blank: 'The SEC filings for this ticker could not be loaded.',
  },
  period_end: {
    short: 'Annual data up to',
    full: 'The end date of the fiscal year the yearly figures (the Balance and Profitability ratios) come from.',
    interp: 'If this is nearly a year old, treat those numbers as stale background, not fresh news.',
    blank: 'The SEC filings for this ticker could not be loaded.',
  },
  period_end_q: {
    short: 'Quarterly data up to',
    full: 'The end date of the quarter the quarterly growth numbers come from.',
    interp: 'Right after an annual report, the latest quarterly filing can lag a full quarter — check this date before treating the growth numbers as fresh.',
    blank: 'The SEC filings for this ticker could not be loaded, or they contain no usable quarterly figures.',
  },
  valuation: {
    short: 'Valuation',
    full: "How expensive the stock is compared with the company's earnings and sales.",
  },
  market_cap: {
    short: 'Market cap',
    full: "The total value of all the company's shares.\nUnit: USD.",
    interp: 'Giant companies grind; small ones jump and squeeze harder. Also sets how much trading liquidity to expect.',
    blank: "Yahoo Finance's market data for this ticker was unavailable.",
  },
  ps_ttm: {
    short: 'Price to sales',
    full: "The company's total market value divided by the last 12 months of sales.",
    interp: 'The valuation gauge for money-losing companies, where price to earnings means nothing.',
    blank: "Yahoo Finance's market data was unavailable, or the company has no sales to divide by.",
  },
  pe_ttm: {
    short: 'Trailing price to earnings',
    full: 'The share price divided by the last 12 months of earnings per share. Roughly: how many years of current earnings you pay for the stock.',
    interp: 'High = big expectations already in the price, so good news is needed just to hold the level; low = cheap, or the market expects decline.',
    blank: "The company lost money over the last 12 months (the ratio is undefined for losses), or Yahoo Finance's market data was unavailable.",
  },
  pe_forward: {
    short: 'Forward price to earnings',
    full: 'The share price divided by the earnings analysts expect over the NEXT 12 months.',
    interp: 'Well below the trailing number = analysts expect earnings to grow; above it = they expect them to shrink.',
    blank: "Analysts forecast a loss, no analysts cover the stock, or Yahoo Finance's market data was unavailable.",
  },
  // Legacy fundamentals keys (old stored runs only).
  balance_sheet: {
    short: 'Balance sheet',
    full: 'Old runs only: this group was renamed Balance. What the company owns versus what it owes.',
  },
  basis: {
    short: 'Basis',
    full: 'Old runs only (retired 2026-07-31): the report types behind the numbers — 10-K = the audited yearly filing, 10-Q = the quarterly filing, both filed with the SEC (the US markets regulator).',
  },
  // Legacy fundamentals keys (old stored runs only; retired 2026-07-29).
  revenue_yoy_pct: {
    short: 'Revenue YoY %',
    full: 'Retired field old runs still carry: annual revenue growth vs. the prior fiscal year. New runs publish quarterly growth instead.',
  },
  net_income_yoy_pct: {
    short: 'Net income YoY %',
    full: 'Retired field old runs still carry: annual bottom-line profit growth vs. the prior fiscal year.',
  },
  eps_yoy_pct: {
    short: 'EPS YoY %',
    full: 'Retired field old runs still carry: annual earnings-per-share growth vs. the prior fiscal year.',
  },
  net_margin_pct: {
    short: 'Net margin %',
    full: 'Retired field old runs still carry: % of revenue left as final profit after everything. Mostly duplicated the operating margin plus one-off noise.',
  },
  cash: {
    short: 'Cash',
    full: 'Retired field old runs still carry: cash and cash-like holdings on hand, in USD. A raw dollar figure with no scale context.',
  },
  pb: {
    short: 'P/B',
    full: 'Retired field old runs still carry: share price ÷ accounting net worth per share. Only informative for banks and asset-heavy names.',
  },

  // ---- report-event fields shared with the plan warnings ----
  next_earnings_date: {
    short: 'Next quarterly report date',
    full: 'The date the company next reports its quarterly results.',
    interp: "A report while you hold the stock means the price can jump straight past your stop overnight — exit before it, or size the position for it. The plan's report warning fires within a week of this date.",
    blank: 'No upcoming report is scheduled yet, or the calendar lookup failed.',
  },
  days_until_earnings: {
    short: 'Days until report',
    full: 'Old runs only: how many days from today until that report. New runs compute this from the date instead of storing it.',
    interp: 'A small number = the event risk is live now; a big number = a free window to trade in.',
  },

  // ---- macro economy ----
  region: {
    short: 'Region',
    full: 'Which economy these numbers describe.',
  },
  as_of: {
    short: 'As of',
    full: 'The date this block of data describes — lagged sources (macro series, short-interest reports) carry it so stale numbers are never mistaken for today\'s.',
    interp: 'Data older than a couple of sessions should not anchor a plan.',
    blank: 'The price data came back without a date attached, so there is no way to say how fresh it is. Treat the numbers in this section as unverified for freshness.',
  },
  rates: {
    short: 'Rates',
    full: 'Interest rates set by the central bank and the bond market.',
  },
  fed_funds_rate_pct: {
    short: 'Fed funds %',
    full: 'The US central bank’s base interest rate.\nHigher rates cool the economy and usually pressure stock prices.',
  },
  treasury_10y_pct: {
    short: '10Y yield %',
    full: 'Yield on 10-year US government bonds — the benchmark long-term interest rate.',
  },
  treasury_2y_pct: {
    short: '2Y yield %',
    full: 'Yield on 2-year US government bonds — tracks where markets expect rates to go soon.',
  },
  curve_10y_2y_pct: {
    short: '10Y−2Y spread',
    full: '10-year yield minus 2-year yield.\nBelow zero (an “inverted curve”) is a classic recession warning.',
  },
  inflation: {
    short: 'Inflation',
    full: 'How fast consumer prices are rising — the number that drives what the central bank does with interest rates.',
  },
  cpi_yoy_pct: {
    short: 'Consumer price index (YoY)',
    full: 'How much everyday prices rose versus the same month last year — the inflation rate.\nUnit: percent.',
    interp: 'Central banks aim for about 2%. Hot readings push interest rates up (bad for stocks); cooling readings make rate cuts possible.',
    blank: 'The inflation series failed to load, or there is no year-ago month to compare against.',
  },
  cpi_yoy_trend: {
    short: 'Consumer price index (YoY) trend',
    full: 'The inflation rate now versus about 3 months ago: up, down or flat (small wiggles count as flat).',
    interp: 'Down = price pressure easing, rate cuts closer; up = pressure building, rates stay high or rise.',
    blank: 'Not enough inflation history to compare against 3 months ago.',
  },
  employment: {
    short: 'Employment',
    full: 'Job-market health — the other half of what the central bank watches.',
  },
  unemployment_rate_pct: {
    short: 'Unemployment rate',
    full: 'Share of the workforce without a job.\nUnit: percent.',
    interp: 'Low = strong economy but keeps rates high; a fast rise is the classic recession signal.',
    blank: 'The unemployment series failed to load.',
  },
  unemployment_trend: {
    short: 'Unemployment rate trend',
    full: 'Unemployment now versus about 3 months ago: up, down or flat (small wiggles count as flat).',
    interp: 'Up is the hard recession gauge moving the wrong way — the direction matters more than the level.',
    blank: 'Not enough unemployment history to compare against 3 months ago.',
  },
  interest_rates: {
    short: 'Interest rates',
    full: 'The one rate the central bank sets directly, plus the change the market has already priced in.',
  },
  official_rate_pct: {
    short: 'Official interest rate',
    full: 'The one rate the central bank sets directly (in the US, the federal funds rate) — the base price of money. Everything else in this report is priced by markets, not set by anyone.',
    interp: 'Changes only at scheduled decisions (~8 a year). High or rising = pressure on stock valuations; cuts = fuel for stocks.',
    blank: 'The official-rate series failed to load.',
  },
  diff_2y_vs_official_pp: {
    short: 'Diff (2y gov bond yield vs official interest rate)',
    full: "The 2-year government bond yield minus the official rate.\nThe 2y is roughly the market's expected average official rate over the next two years, so this gap is the rate change the market has priced in.\nUnit: percentage points.",
    interp: 'Negative = rate cuts priced in (the more negative, the bigger the expected easing); positive = hikes priced in; near zero = the central bank is expected to sit still.',
    blank: 'The 2-year yield or the "Official interest rate" series failed to load.',
  },
  bonds: {
    short: 'Bonds',
    full: 'Market-priced government and company bond yields — a yield is the return locked in by buying at today’s traded price, so these move every trading day.',
  },
  gov10y_yield_pct: {
    short: '10y gov bond yield',
    full: "The return locked in by lending to the government for 10 years at today's traded bond price — the market's long-term interest rate. Payments on bonds already owned never change; this is the deal offered to a buyer today.\nUnit: percent.",
    interp: 'The guaranteed alternative competing with stocks: the higher it sits, the less future profits are worth today — far-future (growth) profits get hit hardest.',
    blank: 'The 10-year yield series failed to load.',
  },
  gov10y_trend: {
    short: '10y gov bond yield trend',
    full: 'The 10-year yield now versus about 3 months ago: up, down or flat (small wiggles count as flat).',
    interp: 'Up = valuation pressure actively building while a trade is held — a headwind for growth-stock longs; down = support.',
    blank: 'Not enough 10-year yield history to compare against 3 months ago.',
  },
  yield_diff_10y_2y_pp: {
    short: 'Yield diff (10y gov bond vs 2y gov bond)',
    full: '10-year yield minus 2-year yield.\nUnit: percentage points.',
    interp: 'Negative (short rates above long) is the classic recession warning: the market expects cuts because trouble is coming.',
    blank: 'The 10y-minus-2y series failed to load.',
  },
  yield_diff_10y_2y_trend: {
    short: 'Yield diff (10y gov bond vs 2y gov bond) trend',
    full: 'The 10y-vs-2y gap now versus about 3 months ago: up, down or flat (small wiggles count as flat).',
    interp: 'The recession dial’s direction: down = sliding toward or deeper into warning; up = climbing back out, often a regime change.',
    blank: 'Not enough 10y-vs-2y history to compare against 3 months ago.',
  },
  yield_diff_hy_gov_pp: {
    short: 'Yield diff (high-yield company bond vs gov bond)',
    full: "The extra yield investors demand for risky ('junk') company bonds over government bonds of the same maturity. Matching maturities cancels the rate environment out, leaving pure default fear — traders call this the high-yield credit spread.\nUnit: percentage points.",
    interp: 'Tight and stable = lenders relaxed, a risk-on backdrop; widening = credit stress building, often before stocks react.',
    blank: 'The high-yield spread series failed to load.',
  },
  yield_diff_hy_gov_trend: {
    short: 'Yield diff (high-yield company bond vs gov bond) trend',
    full: 'The credit spread now versus about 3 months ago: up, down or flat (small wiggles count as flat).',
    interp: 'Up (widening) is the early credit-stress warning light; down = fear draining out.',
    blank: 'Not enough high-yield spread history to compare against 3 months ago.',
  },
  markets: {
    short: 'Markets',
    full: 'Market-wide gauges: expected turbulence, oil, and the dollar.',
  },
  vix: {
    short: 'Implied market volatility',
    full: 'The expected size of overall market (S&P 500) swings over the next month, priced from index options — the “fear index” (VIX). The market-wide sibling of the per-stock implied volatility in positioning.',
    interp: 'Under ~15 = calm; 20+ = nervous; 30+ = stress. In high-volatility regimes use smaller size and wider stops.',
    blank: 'The volatility index series failed to load.',
  },
  wti_oil_usd: {
    short: 'Crude oil price',
    full: 'The US benchmark oil price (WTI), in USD per barrel.',
    interp: 'A direct driver for energy and transport names — the level sets their world regardless of trend.',
    blank: 'The oil price series failed to load.',
  },
  oil_trend: {
    short: 'Crude oil price trend',
    full: 'The oil price now versus about 3 months ago: up, down or flat (small percent moves count as flat).',
    interp: 'Sustained rises feed future inflation readings (oil moves daily, inflation reports monthly) and weigh on the whole market.',
    blank: 'Not enough oil price history to compare against 3 months ago.',
  },
  dollar_trend: {
    short: 'Dollar strength trend',
    full: "The dollar's value against a basket of trading-partner currencies, now versus about 3 months ago: up, down or flat. Only the direction is shown — the index level itself is an arbitrary-basket number nobody can read.",
    interp: "A fast-rising dollar shrinks US multinationals' foreign earnings and often accompanies risk-off; a falling dollar supports risk appetite.",
    blank: 'Not enough dollar index history to compare against 3 months ago.',
  },
  events: {
    short: 'Events',
    full: 'The scheduled announcements that can move the whole market on one morning — the market-wide version of an earnings date.',
  },
  next_cpi_release_date: {
    short: 'Next inflation data date',
    full: 'The scheduled date of the next consumer-price (CPI) release.',
    interp: 'A market-wide gap risk: inside a holding window, every stock can jump on this number.',
    blank: 'The release calendar failed to load or has no upcoming date.',
  },
  next_jobs_release_date: {
    short: 'Next employment data date',
    full: 'The scheduled date of the next jobs report (unemployment release).',
    interp: 'A market-wide gap risk: inside a holding window, every stock can jump on this number.',
    blank: 'The release calendar failed to load or has no upcoming date.',
  },
  next_rate_decision_date: {
    short: 'Next official interest rate date',
    full: 'The scheduled date of the next central-bank rate decision (in the US, the FOMC statement day).',
    interp: 'The biggest scheduled market-wide event — inside a holding window it is gap risk for every stock.',
    blank: 'The published decision calendar has run out — it needs extending with the next year’s schedule.',
  },
  inflation_data_up_to: {
    short: 'Inflation data up to',
    full: 'The month the latest consumer-price reading describes. Inflation data is published monthly with a delay.',
    interp: 'Can be four to six weeks old — it describes that month, not today.',
    blank: 'The inflation series failed to load.',
  },
  employment_data_up_to: {
    short: 'Employment data up to',
    full: 'The month the latest unemployment reading describes. Jobs data is published monthly with a delay.',
    interp: 'Can be four to six weeks old — it describes that month, not today.',
    blank: 'The unemployment series failed to load.',
  },
  // Retired macro keys (old stored runs only).
  labor: {
    short: 'Labor',
    full: 'Job-market health.',
  },
  dollar_index_broad: {
    short: 'Dollar index',
    full: 'Strength of the US dollar against a basket of other currencies.',
  },
  observation_dates: {
    short: 'Data dates',
    full: 'The date of each underlying data point (some series update monthly, others daily).',
  },

  // ---- positioning (v2 truth 2026-08-01; retired keys kept for stored runs) ----
  short_interest: {
    short: 'Short interest',
    full: 'Shares sold short — borrowed and sold by investors betting the price will fall (shorts). To exit, a short must buy the shares back. FINRA publishes this twice a month, about two weeks late; the report date is "short interest up to" in the meta group.',
  },
  ownership_as_of: {
    short: 'Ownership structure up to',
    full: 'The quarter end the fund-ownership figures describe. Big funds report holdings once a quarter (a "13F" filing), up to 45 days after the quarter closes.',
    interp: 'The ownership block can describe positioning from 3–4.5 months ago — read it as background, never as current buying or selling.',
    blank: 'The institutional-holders table failed to load or carried no filing dates.',
  },
  short_interest_as_of: {
    short: 'Short interest up to',
    full: 'The date the short-interest figures were measured — they publish twice a month, about two weeks late.',
    interp: 'If the price has moved sharply since this date, the shorts it describes may already have bought back and left — discount the block.',
    blank: 'Yahoo did not publish the short-interest report date.',
  },
  options_bets_through: {
    short: 'Options betting up to',
    full: 'The furthest option expiration date included in the puts-to-calls sums. Unlike the two dates above, this one points forward: the options data itself is fresh as of this report.',
    interp: 'How far into the future the summed bets run — a near date means the ratios read only the next few weeks of positioning, not the whole board.',
    blank: 'The options fetch failed or no listed options were found for this stock.',
  },
  ownership: {
    short: 'Ownership structure',
    full: 'How the shares are distributed — who holds the stock and how concentrated it is. From quarterly 13F fund filings (up to 45 days late) and the Yahoo summary.',
  },
  institutional_pct: {
    short: 'Institutional ownership',
    full: 'Percent of the company held by professional funds (mutual funds, pensions, ETFs), from their quarterly 13F filings.',
    interp: "Roughly 30–90% is healthy sponsorship. Very low = funds can't or won't own it — a quality/liquidity red flag; very high = fully discovered, who's left to buy?",
    blank: 'Yahoo did not publish this figure for the stock.',
  },
  institutional_diff_q_pp: {
    short: 'Institutional ownership diff (current vs prev quarter)',
    full: 'Old stored runs only (retired field): how much the fund-ownership percentage rose or fell versus the previous quarterly filing, in percentage points.',
    interp: 'Funds adding supports rallies; funds trimming caps them — but filings lag up to 45 days, so background context, not current flow.',
    blank: "Retired field — no reliable free source publishes the prior-quarter aggregate (Yahoo's per-holder change figures proved unreliable). New runs no longer carry it.",
  },
  top10_institutions_pct: {
    short: 'Top-10 institutional ownership',
    full: 'The combined stake of the ten largest fund holders. Insiders are not part of this table — it counts funds only.',
    interp: "Concentration risk: if a third of the company sits with ten funds, one fund's exit is a surprise down day — argues for smaller size or a wider stop.",
    blank: 'The institutional-holders table failed to load or carried no stake percentages.',
  },
  insider_pct: {
    short: 'Insider ownership',
    full: "Percent held by the company's insiders — its executives, board directors, and anyone owning more than 10% — the people required by law to report their trades.",
    interp: "High = management's own wealth rides on the stock, and those locked-up shares shrink the float below what it looks like — bigger swings both ways.",
    blank: 'Yahoo did not publish this figure for the stock.',
  },
  float_shares: {
    short: 'Float',
    full: 'The number of shares actually available to trade — total shares minus locked-up insider and strategic stakes.',
    interp: 'A small float moves and squeezes harder in both directions: size smaller, expect gaps. Also the denominator behind the short-interest block.',
    blank: 'Yahoo did not publish this figure for the stock.',
  },
  short_pct_of_float: {
    short: 'Shorted shares to float',
    full: 'Of the shares actually available to trade (the float), the percent that has been borrowed and sold by investors betting the price will fall.',
    interp: 'Under ~3% is normal; ~10%+ is a crowded bear trade; 20%+ is squeeze territory — good news can force shorts to buy back at once and spike the price. Expect violent moves both ways.',
    blank: 'Yahoo published neither the percentage nor the shares-short and "Float" numbers needed to compute it.',
  },
  days_to_cover: {
    short: 'Shorted shares to avg daily volume',
    full: 'Shorted shares divided by average daily trading volume — how many full days of normal trading the shorts would need to buy everything back. Unit: days.',
    interp: '1–2 days = shorts can exit quietly; 5+ = their own buying pushes the price while they exit, so squeezes run further.',
    blank: 'Yahoo did not publish this figure for the stock.',
  },
  change_vs_prior_month_pct: {
    short: 'Shorted shares diff (current vs prev report)',
    full: 'Percent change in shorted shares versus the previous twice-monthly report.',
    interp: 'Direction beats level: rising = bears pressing the bet; falling = shorts already giving up and buying back, which itself supports the price.',
    blank: 'Yahoo did not publish the current or the prior-report shares-short count.',
  },
  shares_short: {
    short: 'Shares short',
    full: 'Old stored runs only (retired field): the raw number of shares sold short. Only meaningful relative to the float — the percentage row is the interpretable one.',
  },
  shares_outstanding: {
    short: 'Shares outstanding',
    full: 'Old stored runs only (retired field): total shares the company has issued. The float is the tradable reality.',
  },
  insider_activity_6m: {
    short: 'Insider trades (6m)',
    full: "Open-market buys and sells by the company's insiders over the last six months, from SEC Form 4 filings. Stock awards, option exercises and gifts are excluded — only trades made with insiders' own money reveal conviction.",
  },
  buy_count: {
    short: '6m total insider buys',
    full: 'How many times insiders bought their own stock on the open market in the last six months (awards, option exercises and gifts excluded).',
    interp: 'The strongest signal in this report: insiders sell for many reasons but buy for exactly one. Even one or two real buys tilt bullish.',
    blank: 'Yahoo returned no insider transaction rows — an empty table could be a source outage, so it is never shown as "0 trades".',
  },
  sell_count: {
    short: '6m total insider sells',
    full: 'How many times insiders sold on the open market in the same window (awards, option exercises and gifts excluded).',
    interp: 'Scattered selling is routine (taxes, diversification); many different insiders selling in a tight cluster is the warning shape.',
    blank: 'Yahoo returned no insider transaction rows — an empty table could be a source outage, so it is never shown as "0 trades".',
  },
  net_shares: {
    short: 'Net shares',
    full: 'Old stored runs only (retired field): shares bought minus sold. Not comparable across stocks with different prices — the money diff is.',
  },
  net_value_usd: {
    short: '6m money diff (insider buys vs sells)',
    full: 'Dollars insiders spent buying minus dollars they took out selling, over those same open-market trades. Positive = net buying.',
    interp: 'The bottom line of insider conviction, comparable across stocks: clearly positive = bullish tell; a large negative during a rally = management cashing out into strength.',
    blank: 'Yahoo returned no insider transaction rows — an empty table could be a source outage, so it is never shown as a zero.',
  },
  options: {
    short: 'Options',
    full: 'Side bets stacked on the stock: a put profits if the price falls (a down-bet or insurance), a call profits if it rises. The freshest block here — updated daily, while the share-based blocks lag weeks to months.',
  },
  put_call_oi_ratio: {
    short: 'Puts to calls (held)',
    full: "All outstanding put contracts divided by all outstanding call contracts — the positions people currently hold, accumulated over past weeks, not just today's trades. Summed over the nearest expirations.",
    interp: '~0.7–1.0 is typical. Well above 1 = heavy downside bets or hedging; very low = one-sided bullishness — complacency, bad news hits hardest then.',
    blank: 'The source published missing or zero open interest — a zero side is indistinguishable from missing data, so no ratio is shown.',
  },
  put_call_volume_ratio: {
    short: 'Puts to calls (traded today)',
    full: "The same ratio using only contracts traded today — today's fresh flow, not the standing positions.",
    interp: 'When today\'s flow diverges from the held ratio above, sentiment is turning right now — the held ratio is the climate, this is the weather.',
    blank: 'The source published missing or zero volume — a zero side is indistinguishable from missing data, so no ratio is shown.',
  },
  total_open_interest: {
    short: 'Total held options',
    full: 'Total option contracts currently held open (puts plus calls) over the covered expirations — not the number of listed option products, and not trading volume.',
    interp: 'A trust meter for the two ratios above: big = a liquid, well-watched options market whose ratios mean something; tiny = the ratios are noise — ignore the group.',
    blank: 'The source published missing or zero open interest, so no total is shown.',
  },
  expirations_covered: {
    short: 'Expirations',
    full: 'Old stored runs only (retired field): how many expiration dates the sums covered. New runs publish the "options betting up to" date instead.',
  },
  implied_vol_pct: {
    short: 'Implied stock volatility',
    full: "The size of yearly move the options market is pricing in, in %, read from option prices near the current stock price (at-the-money) — CBOE's 30-day figure. Options far from the current price are not counted: their prices carry distortions.",
    interp: "The market's fear gauge for this one stock: high = insurance is expensive, turbulence expected — wider stops, smaller size. The raw level means little alone; every stock has its own normal.",
    blank: 'CBOE published no 30-day implied volatility for this stock.',
  },
  implied_vol_rank_1y: {
    short: 'Implied stock volatility ranking (1y range)',
    full: "Old stored runs only (retired field): where today's implied volatility sits inside its own one-year range: 0 = the calmest the options market has been on this stock all year, 100 = the most braced-for-impact.",
    interp: 'Near the top = an event or storm is priced in, gaps likely — shrink size or wait; near the bottom = calm expected, orderly moves.',
    blank: 'Retired field — it needs a year of implied-volatility history, which no free source publishes. New runs no longer carry it.',
  },
  implied_report_move_pct: {
    short: 'Implied quarterly report day price change magnitude',
    full: 'The size of price jump the options market prices in for the next quarterly report, in % — from the at-the-money call + put prices on the first expiration after the report date. Unsigned: option prices say how BIG the jump should be, not which way (read it as ±).\nPublished only when the report is within ~3 weeks — further out, option prices mostly reflect ordinary drift, not the report jump.',
    interp: 'Compare it to the stop distance: an implied ±9% move against a 5% stop means the gap jumps the stop — exit before the report or size so the full move is survivable.',
    blank: 'Shown only when the next quarterly report is within ~3 weeks (further out, option prices mostly reflect ordinary drift, not the report jump) — and it needs the report date plus usable at-the-money quotes on the first expiration after it.',
  },
  report_move_ratio_implied_4q: {
    short: 'Quarterly report day price change magnitude ratio (implied vs 4q avg)',
    full: "The options-implied move for the next report day divided by the realized average move of the last 4 report days (from the fundamentals report). 1.0 = options price exactly the usual jump.\nUnit: a multiple (×).",
    interp: 'Well above 1 = the market is braced for a bigger-than-usual report reaction; well below 1 = unusually calm expectations.',
    blank: 'Old stored runs only: needs both "Implied quarterly report day price change magnitude" (shown only when the quarterly report is within ~3 weeks) and "4q avg report day price change magnitude" from fundamentals — at least one was blank. Newer runs name the missing one here.',
  },

  // ---- opinion (numeric card 2026-08-18: analyst + crowd sentiment measures) ----
  analyst: {
    short: 'Analyst opinion',
    full: "What professional Wall Street research firms currently think — their buy/hold/sell ratings, 12-month price targets, and this week's rating changes. From Yahoo Finance.",
    interp: 'Informed opinion, not fact: analysts skew bullish as a group, and their targets chase the price as often as they lead it.',
  },
  crowd: {
    short: 'Crowd chatter',
    full: 'How much — and how positively — retail traders on Reddit are talking about this stock, measured by two public trackers: ApeWisdom (mention counts and a buzz rank) and Tradestie (WallStreetBets comment tone).',
    interp: 'The least reliable group in the report: read it as attention and crowding, never as direction on its own.',
  },
  firms_total: {
    short: 'Firms rating the stock',
    full: 'How many research firms currently publish a buy/hold/sell rating on this stock.',
    interp: 'More firms = a better-watched stock and a steadier consensus; below ~5 the counts are a few voices, not a chorus.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  strong_buy_firms: {
    short: 'Strong-buy ratings',
    full: 'How many of those firms rate the stock strong buy this month.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  buy_firms: {
    short: 'Buy ratings',
    full: 'How many firms rate the stock buy this month.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  hold_firms: {
    short: 'Hold ratings',
    full: 'How many firms rate the stock hold this month.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  sell_firms: {
    short: 'Sell ratings',
    full: 'How many firms rate the stock sell this month.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  strong_sell_firms: {
    short: 'Strong-sell ratings',
    full: 'How many firms rate the stock strong sell this month.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  buy_rating_pct: {
    short: 'Buy share of ratings',
    full: 'The percent of rating firms on buy or strong buy this month.\nUnit: %.',
    interp: 'Professional opinion, not a fact about the business — analysts skew bullish as a group, so read the level against the drift field below it.',
    blank: 'The consensus feed failed, or too few firms cover this stock to publish counts.',
  },
  buy_rating_change_1m_pp: {
    short: 'Buy share drift, 1 month',
    full: 'How many percentage points the buy share moved versus a month ago (positive = analysts warming up).\nUnit: percentage points.',
    interp: 'The direction of drift often matters more than the level — a falling buy share on a rising stock is a quiet warning.',
    blank: 'Needs both this month and last month in the consensus feed.',
  },
  price_target_mean: {
    short: 'Average price target',
    full: "The average of the firms' 12-month price targets.\nUnit: USD.",
    interp: 'A slow-moving opinion: targets chase the price as often as they lead it.',
    blank: 'Yahoo published no targets, or the analyst source fell back to Finnhub (which has none on the free tier).',
  },
  price_target_high: {
    short: 'Highest price target',
    full: "The most bullish firm's 12-month price target.\nUnit: USD.",
    blank: 'Yahoo published no targets, or the analyst source fell back to Finnhub (which has none on the free tier).',
  },
  price_target_low: {
    short: 'Lowest price target',
    full: "The most bearish firm's 12-month price target.\nUnit: USD.",
    blank: 'Yahoo published no targets, or the analyst source fell back to Finnhub (which has none on the free tier).',
  },
  target_vs_price_pct: {
    short: 'Average target vs price',
    full: 'How far the average price target sits from the current price (positive = target above the price).\nUnit: %.',
    interp: 'A big positive gap reads bullish only if the targets are fresh — after a crash the gap is huge simply because targets have not caught down yet.',
    blank: 'Needs both "Average price target" and a current price from the same feed.',
  },
  upgrades_count: {
    short: 'Rating upgrades',
    full: 'How many firms raised their rating in the last 7 trading days.',
    interp: 'Fresh upgrades lean bullish; clusters usually follow earnings.',
    blank: 'The rating-actions feed failed, or the Finnhub backup was used (it has no action history).',
  },
  downgrades_count: {
    short: 'Rating downgrades',
    full: 'How many firms cut their rating in the last 7 trading days.',
    interp: 'Fresh downgrades lean bearish — and often land with a price-target cut attached.',
    blank: 'The rating-actions feed failed, or the Finnhub backup was used (it has no action history).',
  },
  initiations_count: {
    short: 'New coverage started',
    full: 'How many firms started covering the stock in the last 7 trading days (first-time ratings).',
    interp: 'New coverage means new professional attention — mildly bullish regardless of the opening grade.',
    blank: 'The rating-actions feed failed, or the Finnhub backup was used (it has no action history).',
  },
  reddit_mentions: {
    short: 'Reddit mentions, 24h',
    full: "How many times the last 24 hours of posts and comments on Reddit's big investing boards named this stock (ApeWisdom's count).",
    interp: 'Attention, not direction: a spike means retail traders are suddenly watching — crowded in both directions, expect noisier moves.',
    blank: "The stock is not on ApeWisdom's most-discussed list (too little chatter to register), or the fetch failed.",
  },
  reddit_mentions_24h_ago: {
    short: 'Reddit mentions, prior 24h',
    full: 'The same mention count for the 24 hours before that — the baseline the current count is judged against.',
    blank: "The stock is not on ApeWisdom's most-discussed list (too little chatter to register), or the fetch failed.",
  },
  reddit_upvotes: {
    short: 'Reddit upvotes, 24h',
    full: 'Total upvotes on the posts behind those mentions — how much the chatter resonated.',
    blank: "The stock is not on ApeWisdom's most-discussed list (too little chatter to register), or the fetch failed.",
  },
  reddit_rank: {
    short: 'Reddit buzz rank',
    full: "This stock's place on ApeWisdom's most-mentioned list right now (1 = the most talked-about ticker).",
    interp: 'Single digits = a main-character stock today; a fast rank climb is the clearest crowd-attention signal in this group.',
    blank: "The stock is not on ApeWisdom's most-discussed list (too little chatter to register), or the fetch failed.",
  },
  reddit_rank_24h_ago: {
    short: 'Reddit buzz rank, prior 24h',
    full: 'The same rank a day earlier — compare to see the climb or fade.',
    blank: "The stock is not on ApeWisdom's most-discussed list (too little chatter to register), or the fetch failed.",
  },
  wsb_sentiment_score: {
    short: 'WallStreetBets comment tone',
    full: "Tradestie's word-scoring of today's WallStreetBets comments about this stock: above 0 = bullish wording dominates, below 0 = bearish (roughly -1 to +1).",
    interp: "The least reliable number in this report — one forum's mood, scored by word choice. Direction color at most; never a reason on its own.",
    blank: 'The stock is not among the ~50 most-discussed WallStreetBets tickers today, or the fetch failed.',
  },
  wsb_comments: {
    short: 'WallStreetBets comments',
    full: "How many WallStreetBets comments mentioned the stock in today's scan (only the ~50 most-discussed tickers make the list).",
    blank: 'The stock is not among the ~50 most-discussed WallStreetBets tickers today, or the fetch failed.',
  },
};

const zh: Record<string, MetricEntry> = {
  close: {
    short: '收盘价',
    full: '最近一个交易日的最后成交价。\n单位：股票自身的货币（美股为美元）。',
    interp: '一切的起点——本报告中所有距离（到支撑、均线、目标价）都从这个价格量起。',
  },
  bars_count: { short: 'K线数', full: '本次计算使用了多少个交易日的历史数据。' },
  sma_20: {
    short: 'SMA 20',
    full: '最近20个交易日收盘价的平均值（SMA = 简单移动平均线）。\n取平均能滤掉日常噪音，让短期方向更容易看清。',
  },
  sma_60: {
    short: 'SMA 60',
    full: '最近60个交易日收盘价的平均值——中期趋势线。',
  },
  ema_12: { short: 'EMA 12', full: '最近12天价格的加权平均，越新的日子权重越大（EMA = 指数移动平均线）。' },
  ema_26: { short: 'EMA 26', full: '同样的算法放到26天——较慢的均线，与 EMA 12 搭配使用。' },
  rsi_14: {
    short: 'RSI 14',
    full: '衡量近期价格涨跌快慢的0到100仪表（RSI = 相对强弱指标，14天）。\n高于70 = 涨得异常快；低于30 = 跌得异常快；接近50 = 平静。',
    interp: '注意：强势上涨中它可以在70上方停留数周——单看读数高不是卖出信号。',
    blank: '载入的价格历史不足约15天。',
  },
  macd: {
    short: 'MACD',
    full: '通过对比一条快均线和一条慢均线得到的动量仪表。\n快线甩开慢线时，说明上涨的推力在积累。',
  },
  signal: { short: '信号线', full: 'MACD 线再取一次平均。\nMACD 线上穿或下穿它是常见的买卖触发信号。' },
  histogram: { short: '柱状值', full: 'MACD 线减信号线。\n为正且扩大 = 上涨推力增强；为负 = 推力衰减。' },
  atr_14: {
    short: 'ATR 14',
    full: '这只股票平常一天的波动幅度（ATR = 平均真实波幅，14天）。\n单位：股票的货币——ATR 为 $19 表示正常一天价格大约动 $19。',
    interp: '止损距离和仓位大小的尺子：用 ATR 度量的距离，在温和股票和暴躁股票之间可以公平比较。',
    blank: '载入的价格历史不足约15天。',
  },
  volatility_pct: {
    short: '波动率 %',
    full: '正常单日波幅（14日ATR）占价格的百分比。\n超过约 4% 算高波动股——计划审查可能因此减仓或放宽止损。',
  },
  swing_low_20: {
    short: '20日低点',
    full: '最近20个交易日实际成交过的最低价——买方已经防守过一次的底部。\n用作买入价的支撑锚点。',
  },
  bias_20: { short: '乖离率 20', full: '价格偏离自身20日均线的百分比。\n偏离过大往往会向均线回归。' },
  swing_high_20: {
    short: '20日高点',
    full: '最近20个交易日实际成交过的最高价——卖方已经防守过一次的顶部。\n用作目标价的阻力锚点。',
  },
  swing_low_60: {
    short: '60日低点',
    full: '最近60个交易日的最低成交价——比20日低点更深、更早的底部，参与买入价的支撑候选。',
  },
  swing_high_60: {
    short: '60日高点',
    full: '最近60个交易日的最高成交价——比20日高点更宽的顶部。',
  },
  high_52w: { short: '52周高点', full: '已加载历史（约一年）中的最高价——最强的顶部参考。' },
  low_52w: { short: '52周低点', full: '已加载历史（约一年）中的最低价。' },
  avg_volume_20: {
    short: '20日均量',
    full: '最近20个交易日平均每天成交的股数。\n用于判断仓位能否在一天内卖出而不把价格砸下去。',
  },
  worst_day_pct_1y: {
    short: '最差单日跌幅（一年区间）',
    full: '过去一年最糟糕的单日跌幅，按前一天收盘价到当天收盘价计算。\n单位：百分比，负数——如 -14.5 表示那天跌了 14.5%。',
    interp: '说明一次隔夜坏消息（差财报、坏新闻）实际能把价格越过止损打到多远。',
    blank: '载入的价格历史不足约一个月——天数太少，最差单日没有意义。',
  },
  worst_day_1y: {
    short: '年内最差单日',
    full: '旧运行保留的已退役字段：同一统计量，但以小数表示（-0.17 表示 -17%），且扫描了全部已加载历史而非仅一年。新运行改用 worst_day_pct_1y。',
  },
  worst_day_5pct: {
    short: '最差5%单日',
    full: '旧运行保留的已退役统计：仅最差 5% 的交易日才会超过的单日跌幅。',
  },
  score: {
    short: '技术评分',
    full: '旧运行保留的已退役字段：由代码算出的 0-100 技术面总分。新运行不再输出——把现成结论交给 AI 会让它锚定这个数字，而不是自己读取各项指标。',
  },

  // ---- technicals v2 分组与字段（2026-07-27；2026-07-28 重新分组）----
  market: { short: '大盘 vs 板块 vs 个股', full: '三层视角：大盘处于什么状态、这只股票所在的板块（行业家族）是领先还是落后大盘、个股又相对两者表现如何。' },
  rs_sector_1m: {
    short: '对比大盘的板块表现（1月）',
    full: '这只股票所在板块（用板块ETF——持有该板块大型股票的基金——来衡量）最近一个月的收益减去大盘同期收益。\n单位：百分点。',
    interp: '为正 = 板块领先大盘。领先板块中的波段行情走得更远、回调更浅。',
    blank: '板块未知或没有对应的板块ETF（目前仅支持美股板块）、大盘基准不可用，或板块ETF数据加载失败。',
  },
  rs_sector_3m: {
    short: '对比大盘的板块表现（3月）',
    full: '这只股票所在板块（用板块ETF衡量）最近3个月的收益减去大盘同期收益。\n单位：百分点。',
    interp: '为正 = 板块领先大盘。逆着落后板块做多，即使图形干净，胜率也会下降。',
    blank: '板块未知或没有对应的板块ETF（目前仅支持美股板块）、大盘基准不可用，或板块ETF数据加载失败。',
  },
  sector_vs_market_label: {
    short: '板块相对大盘表现',
    full: '由上面两个板块数字得出的一词结论：leader（领先）= 1个月和3个月都跑赢大盘；laggard（落后）= 都跑输；neutral = 混合。',
    interp: '大盘与个股之间的中间层——领先的板块是板块内多头的顺风。',
    blank: '上面两个板块对比数字为空，无从得出结论。',
  },
  rs_stock_sector_1m: {
    short: '对比板块的个股表现（1月）',
    full: '这只股票最近一个月的收益减去它自己板块的同期收益。\n单位：百分点。',
    interp: '要和板块自身的表现一起读：在领先板块中为正 = 家族里的领跑者；在下跌板块中为正 = 只是跌得比家族慢。',
    blank: '板块对比不可用（见上方板块行），无法计算该差值。',
  },
  rs_stock_sector_3m: {
    short: '对比板块的个股表现（3月）',
    full: '这只股票最近3个月的收益减去它自己板块的同期收益。\n单位：百分点。',
    interp: '要和板块自身的表现一起读：在领先板块中为正 = 家族里的领跑者；在下跌板块中为正 = 只是跌得比家族慢。',
    blank: '板块对比不可用（见上方板块行），无法计算该差值。',
  },
  stock_vs_sector_label: {
    short: '个股相对板块表现',
    full: '一词结论：leader（领先）= 1个月和3个月都跑赢自己的板块；laggard（落后）= 都跑输；neutral = 混合。',
    interp: '区分真正强势的个股和被火热板块抬起来的个股——领先板块里的落后者，是强队里最弱的队员。',
    blank: '上面的个股对比板块数字为空，无从得出结论。',
  },
  rs_1m: {
    short: '对比大盘（1月）',
    full: '这只股票最近一个月的收益减去大盘同期收益：+5 表示跑赢大盘5个百分点。\n单位：百分点；通常在 -20 到 +20 之间。',
    interp: '为正 = 领先大盘；为负 = 落后大盘。',
    blank: '该市场未接入基准指数、指数数据加载失败，或历史数据不足一个月。',
  },
  low_1y: {
    short: '一年最低价',
    full: '过去一年触及的最低价——一年区间的地板。\n单位：股票的货币。',
    interp: '市场在一年里实际让这只股票跌到过的位置。',
  },
  avg_vol_5d: {
    short: '5日均量',
    full: '最近一周平均每天成交的股数。\n单位：股。',
    interp: '量比中的近期活跃度读数，用来和3个月的正常水平对比。',
    blank: '载入的价格历史不足5天。',
  },
  sma_10w: {
    short: '10周均线',
    full: '最近10周价格的平均值。\n单位：股票的货币。',
    interp: '中期趋势线；守在它上方，波段上升趋势就还成立。',
    blank: '载入的价格历史不足10周。',
  },
  regime: {
    short: '大盘趋势',
    full: '整体市场（不是这只股票）健康吗？用基准指数（美股为标普500）判断：指数是否在自己200日均价上方、处于一年区间的上半段还是下半段。\n取值：bullish（多头）/ bearish（空头）/ mixed（混合）。',
    interp: '多数个股跟着大盘走。大盘转空时，就算这只股票自己的图形再好，买入也多半失败——要求更强的形态、用更小的仓位。',
    blank: '该市场未接入基准指数，或指数数据加载失败。',
  },
  relative_strength: { short: '相对强度', full: '这只股票的表现比大盘本身好还是差？' },
  price: { short: '股价', full: '当前价格，以及它在自身近期历史中的位置。' },
  weekly: { short: '周线时间框架', full: '拉远的视角（一根K线=一周）。它决定方向——交易只应顺着它的方向做。' },
  daily: { short: '日线时间框架', full: '拉近的视角（一根K线=一天）——用来把握买点、撰写交易计划。' },
  volatility: { short: '波动', full: '这只股票有多蹦跶——止损和仓位大小用它做尺子。' },
  volume: { short: '成交量', full: '实际交易有多活跃——订单能否轻松进出，行情背后有没有真金白银。' },
  levels: { short: '价位', full: '来自股票过去转折点的真实价格——买入、止损、目标价的锚点。' },
  risk: { short: '风险', full: '这只股票糟糕的日子究竟有多糟。' },
  bars_daily: {
    short: '日线数量',
    full: '已载入多少天的价格历史（一根“K线”=一个交易日）。\n单位：个数；目标是300。',
    interp: '少于约253（一个交易年）时，一年期字段只覆盖已有的历史。',
  },
  bars_weekly: {
    short: '周线数量',
    full: '由日线数据合成的周线数量。\n单位：个数；目标是60。',
    interp: '少于60时，周线趋势的判断不太可靠。',
  },
  rs_3m: {
    short: '对比大盘（3月）',
    full: '这只股票最近3个月的收益减去大盘同期收益：+5 表示跑赢5个百分点，-20 表示跑输20个百分点。\n单位：百分点；通常在 -30 到 +30 之间。',
    interp: '为正 = 领先大盘；为负 = 落后大盘。',
    blank: '该市场未接入基准指数、指数数据加载失败，或历史数据不足3个月。',
  },
  rs_label: {
    short: '个股相对大盘表现',
    full: '由个股对比大盘的两个数字得出的一词结论：leader（领先者）= 1个月和3个月都跑赢大盘；laggard（落后者）= 都跑输；neutral = 混合。',
    interp: '优先买领先者——买落后者需要其他报告给出明确的理由。',
    blank: '上面两个对比大盘的数字为空（未接入基准指数或指数数据加载失败），无从得出结论。',
  },
  chg_5d_pct: {
    short: '5日涨跌幅',
    full: '最近5个交易日价格变动了多少。\n单位：百分比；通常在 -15 到 +15。',
    interp: '涨幅太大意味着便宜的买点可能已经错过。',
    blank: '载入的价格历史不足6天。',
  },
  range_pct_1y: {
    short: '当前价格排位（一年区间）',
    full: '今天的价格在过去一年区间里的位置，按满分100表示。\n0/100 = 一年最低点，100/100 = 一年最高点。',
    interp: '约80/100以上 = 强势但追高有风险；约20/100以下 = 除非明确在筑底，否则是接飞刀。',
    blank: '一年最高价和最低价不可用（历史太短），或两者相等而无法计算排位。',
  },
  high_1y: {
    short: '一年最高价',
    full: '过去一年触及的最高价。\n单位：股票的货币。',
    interp: '价格常在旧高点下方停滞——当年在那里买入的人正等着解套卖出。目标价定在它上方，等于假设股价能闯进新高区，那比逢低买入更难。',
  },
  trend: {
    short: '趋势（均线+转折点）',
    full: '整体方向，由两个必须一致的独立检查得出：（1）价格在自己的均线上方还是下方；（2）图上近期的高点和低点在抬高还是降低。\n取值：bullish / bearish / neutral（neutral = 两个检查不一致）。',
    interp: '方向过滤器：交易只应顺着周线趋势的方向做，日线逢低买入在两个时间框架一致时效果最好。',
    blank: '两个检查（均线、近期高低点）中有一个因历史数据不足而无法回答。',
  },
  stretch_10w_atr: {
    short: '收盘价与10周均线的距离',
    full: '价格在10周均线上方（+）或下方（−）多远，用正常单周波动（ATR）作单位。\n范围：通常 -4 到 +4。',
    interp: '约+1.5以上 = 拉得太远，等回调；上升趋势中 -0.5 到 +1 = 不错的逢低买入区。',
    blank: '历史太短，10周均线或正常波动尺（ATR 14）不可用。',
  },
  sma_50: {
    short: '50日均线',
    full: '最近50个交易日价格的平均值。\n单位：股票的货币。',
    interp: '上涨中的股票常回踩这条线后再继续——经典的逢低买入位。',
    blank: '载入的价格历史不足50天。',
  },
  stretch_50d_atr: {
    short: '收盘价与50日均线的距离',
    full: '价格在50日均线上方（+）或下方（−）多远，用正常单日波动（ATR）作单位。\n范围：通常 -5 到 +5。',
    interp: '上升趋势中 -1 到 +1 = 不错的买入区；+3 以上 = 追高。',
    blank: '历史太短，50日均线或正常波动尺（ATR 14）不可用。',
  },
  stretch_200d_atr: {
    short: '收盘价与200日均线的距离',
    full: '价格在200日均线上方（+）或下方（−）多远，用正常单日波动（ATR）作单位。',
    interp: '为正 = 长期上升趋势成立；为负 = 价格在长期趋势线下方，做多是逆长期趋势。',
    blank: '历史太短，200日均线或正常波动尺（ATR 14）不可用。',
  },
  sma_200: {
    short: '200日均线',
    full: '最近200个交易日价格的平均值——金融市场最受关注的一条线。\n单位：股票的货币。',
    interp: '价格在它上方 = 长期健康；这条线本身常充当地板或天花板。价格在它下方时买入，是在逆着长期大潮。',
    blank: '载入的价格历史不足200天。',
  },
  momentum: {
    short: '动量',
    full: '综合 RSI 与 MACD 的一词结论：\nstrong = 猛力上推；weak = 向下压；fading = 价格还高但推力在消失；basing = 价格还低但推力在积累；neutral = 都不明显。',
    interp: 'strong 支持买入；fading 警告价格看着还行但燃料快耗尽；basing 提示可能正在早期转势向上。',
    blank: '历史太短，它背后的 RSI 或 MACD 不可用。',
  },
  atr_pct: {
    short: '14日ATR（占价格%）',
    full: '正常单日波动占价格的百分比——让 $10 的股票能和 $500 的股票比较。\n单位：百分比；通常 1 到 6。',
    interp: '超过约6 = 很暴躁的股票，考虑用更小的仓位。',
    blank: '载入的价格历史不足约15天，无法测量正常单日波动。',
  },
  atr_trend: {
    short: 'ATR 趋势',
    full: '和大约一个月前相比，日常波动在变大还是变小？\n取值：expanding（扩大）/ contracting（收缩）/ stable（±10%以内算稳定）。',
    interp: '扩大 = 放宽止损、少买一些；收缩 = 股票在蓄力，之后常有大动作。',
    blank: '历史太短，无法和一个月前的正常波动做比较。',
  },
  avg_vol_60d: {
    short: '60日均量',
    full: '约3个月内平均每天成交的股数。\n单位：股（常以百万计）。',
    interp: '流动性基线：判断仓位能否顺利进出而不影响价格。',
    blank: '载入的价格历史不足60天。',
  },
  vol_ratio_5_60: {
    short: '量比（5日/60日）',
    full: '本周平均成交量和3个月正常水平的比值。\n单位：比率；通常 0.5 到 2，1.0 = 正常。',
    interp: '价格突破天花板时高于约1.5 = 真实买盘确认行情；低于约0.7 = 这波行情存疑。',
    blank: '构成它的两个均量之一不可用（历史太短）。',
  },
  support_1: {
    short: '最近支撑位',
    full: '今天价格下方最近的、买方曾经进场的价位（过去的一个回调底部）。\n单位：股票的货币。',
    interp: '保护性止损应放在这类价位的下方一点，而不是随便选个百分比。',
    blank: '价格正处于约6个月来的最低点——下方已没有过去的地板。',
  },
  support_dist_atr: {
    short: '收盘价与最近支撑位的距离',
    full: '价格在最近支撑位上方多远，用正常单日波动（ATR）作单位。',
    interp: '小 = 地板离得近、把止损放在它下方成本低；大 = 止损放在支撑下方的风险超出常规。',
    blank: '下方没有支撑位（价格处于约6个月低点），或正常波动尺（ATR 14）不可用。',
  },
  resistance_1: {
    short: '最近阻力位',
    full: '今天价格上方最近的、卖方曾经出现的价位（过去的一个高点）。\n单位：股票的货币。',
    interp: '第一个现实的止盈目标——预计那里会出现卖压。',
    blank: '价格正处于约6个月来的最高点——上方已没有过去的天花板。',
  },
  resistance_dist_atr: {
    short: '最近阻力位与收盘价的距离',
    full: '最近阻力位在价格上方多远，用正常单日波动（ATR）作单位。',
    interp: '碰到第一个天花板之前还有多少空间——数值小说明容易赚的部分已经不多。',
    blank: '上方没有阻力位（价格处于约6个月高点），或正常波动尺（ATR 14）不可用。',
  },
  typical_pullback_atr: {
    short: '典型回调深度（6个月区间）',
    full: '最近约6个月里，这只股票正常回调的深度——从每个局部顶点跌到随后的局部底部——用正常单日波动（ATR）作单位。\n范围：通常 1 到 5。',
    interp: '止损比它还近的话，正常的来回晃动就会把你震出去，哪怕交易思路是对的。',
    blank: '最近约6个月里找到的完整回调不足2次，没有"典型深度"可报。',
  },

  // ---- fundamentals（2026-07-31 重新分组；标签对齐 TODO.md；旧运行的字段保留在末尾）----
  sector: {
    short: '行业板块',
    full: '公司所属的大类（如科技、能源）。\n取自 Yahoo Finance，从固定的标准清单里选出——不是随意编写的。',
    interp: '本报告里的各项比率只有跟同类公司比才有意义。板块还决定哪些大环境数字对它最重要：能源公司看油价，成长型科技看利率。',
    blank: 'Yahoo Finance 的公司资料不可用，或没有给这只股票标注板块。',
  },
  industry: {
    short: '细分行业',
    full: '板块内更细的分类（如科技板块里的半导体）。同样取自固定清单。',
    interp: '这家公司的数字应该对照的确切同行群体。',
    blank: 'Yahoo Finance 的公司资料不可用，或没有给这只股票标注细分行业。',
  },
  quarterly_report: {
    short: '季度财报',
    full: '公司的财报日程，以及股价在过去财报前后的真实表现——个股层面的事件风险。',
  },
  beats_4q: {
    short: '近4季EPS超预期记录',
    full: '最近4次季报中，每股利润（EPS）达到或超过分析师预期的次数（如 3/4）。',
    interp: '持续超预期的公司在财报前会得到市场的信任加分；习惯性不及预期的则相反。',
    blank: '没有可用的历史财报记录，或过去的财报没有分析师预期可作对比。',
  },
  avg_surprise_pct_4q: {
    short: '近4季平均差值（EPS对比预期）',
    full: '这4次财报中，实际 EPS 平均比分析师预期高出或低出多少。\n单位：百分比。',
    interp: '只说明公司是否常越过分析师定的门槛——不代表股价怎么反应。请和下面的财报日波动一起看。',
    blank: '没有可用的历史财报记录，或这些财报没有分析师预期可作衡量。',
  },
  reaction_avg_abs_pct: {
    short: '近4季财报日平均波动幅度',
    full: '最近4次财报前后股价实际动了多大，取平均、不分方向（按财报前的收盘价到财报后的收盘价计算）。\n单位：百分比。',
    interp: '真实的事件风险：财报日常动±10%的股票和只动±2%的股票，需要完全不同的计划。',
    blank: '落在已载入价格历史内的过去财报不足2次，平均值没有意义。',
  },
  reaction_worst_pct: {
    short: '近4季财报日最差跌幅',
    full: '这几次财报前后最糟的一次下跌。\n单位：百分比，负数。',
    interp: '最近抱着仓位过财报，实际最惨的结果是什么样。',
    blank: '落在已载入价格历史内的过去财报不足2次。',
  },
  eps_rev_30d_pct: {
    short: '30天EPS预期变化',
    full: '分析师最近在上调还是下调本季度的每股利润预测——平均预测值相比30天前的变化。\n单位：百分比。',
    interp: '分析师正把下季度的利润门槛往哪个方向挪。预测上调往往先于随后数周的股价上行；下调更可信——分析师下调时总是又慢又不情愿。±1%左右只是噪音。',
    blank: '没有可用的分析师预期，或30天前的预测值太接近零，百分比变化没有意义。',
  },
  eps_up_revisions_30d: {
    short: '30天上调EPS预期的分析师数',
    full: '过去30天内，有多少位分析师上调了本季度的每股利润预测。',
    interp: '看的是有多少人动了，而不是动了多远——只有一位分析师支撑的预期变化只是一家之言；有五六位支撑，就是共识在移动。',
    blank: 'Yahoo Finance 没有发布这只股票的预期调整人数。',
  },
  eps_down_revisions_30d: {
    short: '30天下调EPS预期的分析师数',
    full: '过去30天内，有多少位分析师下调了本季度的每股利润预测。',
    interp: '和上调人数一起看：两边人数都多说明分析师之间存在真实分歧，仅看预期变化百分比会掩盖这一点；两边都是0说明一个月没人动过预测，所有基于预期的字段都要多加小心。',
    blank: 'Yahoo Finance 没有发布这只股票的预期调整人数。',
  },
  // 仅旧运行（2026-08-23 换成30天字段）。
  eps_rev_90d_pct: {
    short: '90天EPS预期变化',
    full: '仅旧运行：分析师最近在上调还是下调本季度的每股利润预测——平均预测值相比90天前的变化。\n单位：百分比。',
    interp: '预测上调往往在数周内推高股价；下调是逆风，图形再好也一样。',
    blank: '没有可用的分析师预期，或90天前的预测值太接近零，百分比变化没有意义。',
  },
  // 股息字段：仅旧运行（2026-07-31 从 TODO.md 最终清单移除）。
  dividend: {
    short: '股息',
    full: '仅旧运行：公司定期发给股东的现金——一个日期已知的小事件，会在固定日子影响股价。',
  },
  days_until_dividend: {
    short: '距下次股息发放天数',
    full: '仅旧运行：从今天到公司下次发放股息还有多少天。',
    interp: '现金在这一天到账，但价格更早就会下调：在除息日（股票开始不带这期股息交易的日子），股价会低开大约股息的金额。',
    blank: '公司不派股息，或尚未排定下次发放日期。',
  },
  dividend_amount_est: {
    short: '预计股息金额',
    full: '仅旧运行：最近一次每股派发的股息——对下一次的最佳估计。\n单位：美元。',
    interp: '相对股价很小 = 除息日附近的一次小幅下调；金额大的派息本身就可能击中紧止损。',
    blank: '公司不派股息，或 Yahoo Finance 没有上次派息的记录。',
  },
  // 旧运行保留的分组（2026-07-31 重新分组后不再使用）。
  profile: { short: '公司概况', full: '仅旧运行：该分组已并入基本信息。这是家什么样的公司。' },
  earnings: {
    short: '财报事件',
    full: '仅旧运行：该分组已改名为季度财报。公司的财报日程与股价在过去财报前后的表现。',
  },
  ex_dividend_date: {
    short: '除息日',
    full: '仅旧运行（已由股息分组替代）：股票开始不带下一期股息交易的日期。那天早上，价格会机械性地低开大约股息的金额。',
    interp: '一个已排好日期的小幅跳空低开，可能击中做多的紧止损。',
  },
  growth: { short: '成长性', full: '取自最新 SEC 官方季报的季度增长——业务是否在扩张的最新读数。' },
  revenue_yoy_q: {
    short: '季度营收（同比）',
    full: '最新季度的营收与去年同一季度相比的增长率（同比 = 和去年同期比）。\n单位：百分比。',
    interp: '为正且上升 = 业务在扩张；变化的方向比数字本身更重要。',
    blank: 'SEC 财报不可用，或没有去年同季度的营收可作对比。',
  },
  revenue_growth_trend: {
    short: '增速趋势（营收）',
    full: '这个营收增速与上一季度相比是加快了还是放慢了。\n取值：accelerating（加速）/ slowing（放缓）/ steady（变化不到2个百分点算平稳）。',
    interp: '增速加快是数周级行情的经典燃料；增速放缓即使仍在增长，也常终结行情。',
    blank: '还需要上一季度的增速——两个季度中任一季的同比营收对比不可用时留空。',
  },
  eps_yoy_q: {
    short: '季度EPS（同比）',
    full: '最新季度的每股利润（EPS = 当季利润除以股份数）与去年同一季度相比的增长率。\n单位：百分比。',
    interp: '当利润率或股本变化时会和营收增速不同——回购推高它，增发新股拖累它。',
    blank: 'SEC 财报不可用、没有去年同季度的 EPS，或去年同期 EPS 太接近零（低于 $0.05），百分比变化没有意义。',
  },
  eps_growth_trend: {
    short: '增速趋势（EPS）',
    full: 'EPS 的增速与上一季度相比是加快还是放慢。\n取值：accelerating / slowing / steady（同样的2个百分点缓冲）。',
    interp: '市场付钱买的是方向的变化，不是水平。',
    blank: '还需要上一季度的增速——两个季度中任一季的同比 EPS 对比不可用时留空。',
  },
  profitability: { short: '盈利能力', full: '每一元营收公司能留下多少利润，以及这些利润有没有变成真金白银。' },
  gross_margin_pct: {
    short: '毛利润比营收',
    full: '每一元营收中，扣掉直接生产成本后剩下的比例（最新财年）。',
    interp: '高或上升 = 公司能卖出溢价；下降 = 竞争或成本压力在啃食利润。',
    blank: 'SEC 财报不可用、公司没有单列"毛利润"科目（银行类常见），或该数字与营收不在同一财年。',
  },
  operating_margin_pct: {
    short: '营业利润比营收',
    full: '再扣掉运营开支——工资、营销、房租——之后剩下的营收比例，未计利息和税（最新财年）。',
    interp: '市场在每次财报时最看重的效率指标；它的趋势一旦拐弯，股价会有反应。',
    blank: 'SEC 财报不可用，或没有与营收同一财年的营业利润数字。',
  },
  roe_pct: {
    short: '利润比股东资金',
    full: '全年利润占股东投入资金（净资产）的百分比。',
    interp: '长期保持约15%以上是优质企业的标志；极低或为负说明这门生意在烧钱。',
    blank: 'SEC 财报不可用，或利润和股东资金不在同一财年。',
  },
  fcf: {
    short: '自由现金流',
    full: '公司付完运营开销和设备投入后，实际赚到手的现金。财报数据允许时覆盖最近12个月，否则为最新财年。\n单位：美元。',
    interp: '为正且接近账面利润 = 利润是真的。账面盈利但现金流为负，是危险信号。',
    blank: 'SEC 财报不可用，或经营现金流与设备投入两个数字覆盖的期间不一致（混用期间会造出假数字）。',
  },
  fcf_to_earnings_pct: {
    short: '自由现金流比利润',
    full: '自由现金流占同期利润的百分比。\n单位：百分比。',
    interp: '接近或超过100% = 账面利润确实变成了现金；常年远低于100% = 利润可能只存在于纸面上。',
    blank: '利润为零或为负（除以亏损会得出方向相反的数字），或没有覆盖同一期间的利润数字。',
  },
  balance: { short: '资产负债', full: '公司拥有什么、欠什么——它的财务实力。' },
  current_ratio: {
    short: '资产比负债（短期）',
    full: '短期资产除以短期账单——公司付得起一年内到期的钱吗（最新财年）？',
    interp: '约1.5以上比较从容；低于1提示现金紧张——这种时候坏消息的伤害会加倍。',
    blank: 'SEC 财报不可用，或短期资产和短期负债没有同一财年的完整数字。',
  },
  debt_to_equity: {
    short: '负债比股东资金（总体）',
    full: '公司欠的所有钱和股东投入资金的比值——公司有多依赖借来的钱运转。',
    interp: '高负债让涨跌都被放大，利率高的时候伤害最大；要和同行业公司比较。',
    blank: 'SEC 财报不可用，或总负债和股东资金没有同一财年的完整数字。',
  },
  meta: { short: '基本信息', full: '本报告数据的背景——它描述什么、来自哪里、有多新。' },
  entity_name: {
    short: '公司名称',
    full: 'SEC 官方备案上的公司名称。',
    interp: '用来确认这些财报数据确实属于正在分析的这只股票。',
    blank: '这只股票的 SEC 财报无法加载。',
  },
  period_end: {
    short: '年度数据截至',
    full: '年度数字（资产负债与盈利能力各比率）所来自的财年截止日期。',
    interp: '如果已经接近一年前，就把那些数字当作陈旧的背景信息，而不是新消息。',
    blank: '这只股票的 SEC 财报无法加载。',
  },
  period_end_q: {
    short: '季度数据截至',
    full: '季度增长数字所来自的季度截止日期。',
    interp: '年报刚发布后，最新季报可能滞后整整一个季度——把增长当作新鲜数据前先看这个日期。',
    blank: '这只股票的 SEC 财报无法加载，或其中没有可用的季度数字。',
  },
  valuation: { short: '估值', full: '相对公司的利润和营收，这只股票贵不贵。' },
  market_cap: {
    short: '总市值',
    full: '公司全部股份的总价值。\n单位：美元。',
    interp: '巨头走势平缓；小公司跳空和轧空更猛。也决定了能指望多少交易流动性。',
    blank: 'Yahoo Finance 上这只股票的市场数据不可用。',
  },
  ps_ttm: {
    short: '价格比营收',
    full: '公司总市值除以过去12个月的营收。',
    interp: '亏损公司的估值尺子——那种情况下价格比利润没有意义。',
    blank: 'Yahoo Finance 的市场数据不可用，或公司没有营收可作除数。',
  },
  pe_ttm: {
    short: '价格比利润（过去12月）',
    full: '股价除以过去12个月的每股利润。粗略地说：买下当前利润要付几年的价钱。',
    interp: '高 = 大量预期已经在价格里，好消息只够维持现状；低 = 便宜，或市场预期业绩下滑。',
    blank: '公司过去12个月是亏损的（亏损时这个比率没有定义），或 Yahoo Finance 的市场数据不可用。',
  },
  pe_forward: {
    short: '价格比利润（未来12月）',
    full: '股价除以分析师预期的未来12个月每股利润。',
    interp: '明显低于"过去12月"那个数字 = 分析师预期利润增长；高于它 = 预期萎缩。',
    blank: '分析师预测亏损、没有分析师覆盖这只股票，或 Yahoo Finance 的市场数据不可用。',
  },
  // 旧运行保留的已退役字段。
  balance_sheet: { short: '资产负债表', full: '仅旧运行：该分组已改名为资产负债。公司拥有什么、欠什么。' },
  basis: {
    short: '报表类型',
    full: '仅旧运行（2026-07-31 退役）：数字背后的报表类型——10-K = 经审计的年报，10-Q = 季报，都是向 SEC（美国证券监管机构）提交的官方文件。',
  },
  revenue_yoy_pct: { short: '营收同比 %', full: '旧运行保留的已退役字段：年报营收同比增速。新运行改用季度增长。' },
  net_income_yoy_pct: { short: '净利同比 %', full: '旧运行保留的已退役字段：年报净利润同比增速。' },
  eps_yoy_pct: { short: 'EPS 同比 %', full: '旧运行保留的已退役字段：年报每股收益同比增速。' },
  net_margin_pct: { short: '净利率 %', full: '旧运行保留的已退役字段：最终利润占收入的比例。与营业利润率高度重复，另含一次性损益噪音。' },
  cash: { short: '现金', full: '旧运行保留的已退役字段：持有的现金及等价物（美元）。缺乏规模参照的原始数字。' },
  pb: { short: '市净率', full: '旧运行保留的已退役字段：股价÷每股账面净资产。只对银行等重资产行业有参考意义。' },

  next_earnings_date: {
    short: '下次季度财报日期',
    full: '公司下一次公布季度业绩的日期。',
    interp: '持仓期间有财报，意味着价格可能一夜之间跳空越过你的止损——要么提前离场，要么按它调整仓位。距这个日期一周以内会触发交易计划的财报警告。',
    blank: '尚未排定下次财报，或财报日历查询失败。',
  },
  days_until_earnings: {
    short: '距财报天数',
    full: '仅旧运行：从今天到那次财报还有多少天。新运行改为直接由日期计算，不再存储。',
    interp: '数字小 = 事件风险已经临近；数字大 = 一段可以放心交易的窗口。',
  },
  region: { short: '地区', full: '这些数据描述的是哪个经济体。' },
  as_of: {
    short: '数据日期',
    full: '本组数据对应的日期——宏观序列、空头持仓报告等滞后数据都带上它，避免把旧数据当成今天的。',
    interp: '超过两三个交易日的数据不应作为计划的主要依据。',
    blank: '行情数据没有带日期，无法判断新旧程度。本节数字的时效性未经核实，请谨慎对待。',
  },
  rates: { short: '利率', full: '由央行和债券市场决定的利率水平。' },
  fed_funds_rate_pct: {
    short: '联邦基金利率 %',
    full: '美国央行的基准利率。\n利率越高，经济降温，通常也会压制股价。',
  },
  treasury_10y_pct: { short: '10年期收益率 %', full: '10年期美国国债收益率——长期利率的基准。' },
  treasury_2y_pct: { short: '2年期收益率 %', full: '2年期美国国债收益率——反映市场对短期利率走向的预期。' },
  curve_10y_2y_pct: {
    short: '10Y−2Y 利差',
    full: '10年期减2年期收益率。\n低于零（“倒挂”）是经典的衰退预警信号。',
  },
  inflation: { short: '通胀', full: '消费者物价上涨的速度——央行调整利率的核心依据。' },
  cpi_yoy_pct: {
    short: '消费者物价指数（同比）',
    full: '日常物价相比去年同月上涨了多少——即通胀率。\n单位：百分比。',
    interp: '央行的目标约为 2%。数据偏热会推高利率（对股票不利）；降温则让降息成为可能。',
    blank: '通胀序列加载失败，或没有去年同月的数据可比。',
  },
  cpi_yoy_trend: {
    short: '消费者物价指数（同比）趋势',
    full: '通胀率与约3个月前相比：up（上行）/ down（下行）/ flat（持平，小幅波动算持平）。',
    interp: '下行 = 物价压力缓解、降息更近；上行 = 压力累积、利率维持高位或继续上调。',
    blank: '通胀历史不足，无法与3个月前比较。',
  },
  employment: { short: '就业', full: '就业市场的健康状况——央行关注的另一半。' },
  unemployment_rate_pct: {
    short: '失业率',
    full: '劳动人口中没有工作的比例。\n单位：百分比。',
    interp: '低 = 经济强劲但利率难降；快速上升是经典的衰退信号。',
    blank: '失业率序列加载失败。',
  },
  unemployment_trend: {
    short: '失业率趋势',
    full: '失业率与约3个月前相比：up（上行）/ down（下行）/ flat（持平，小幅波动算持平）。',
    interp: '上行 = 硬性衰退指标正朝坏的方向走——方向比水平更重要。',
    blank: '失业率历史不足，无法与3个月前比较。',
  },
  interest_rates: { short: '利率', full: '央行直接设定的那一个利率，以及市场已经提前定价的变化。' },
  official_rate_pct: {
    short: '官方利率',
    full: '央行直接设定的利率（美国为联邦基金利率）——资金的基础价格。本报告的其他字段都由市场定价，不由任何人设定。',
    interp: '只在计划中的议息会议（每年约8次）变动。偏高或上行 = 压制股票估值；降息 = 股市的燃料。',
    blank: '官方利率序列加载失败。',
  },
  diff_2y_vs_official_pp: {
    short: '2年期国债收益率与官方利率之差',
    full: '2年期政府债券收益率减官方利率。\n2年期收益率约等于市场对未来两年官方利率平均值的预期，因此这个差值就是市场已经定价的利率变化。\n单位：百分点。',
    interp: '为负 = 已定价降息（越负预期降幅越大）；为正 = 已定价加息；接近零 = 预期央行按兵不动。',
    blank: '2年期收益率或官方利率序列加载失败。',
  },
  bonds: { short: '债券', full: '由市场定价的政府与公司债券收益率——收益率是按今天成交价买入并持有到期锁定的回报，因此每个交易日都在变。' },
  gov10y_yield_pct: {
    short: '10年期国债收益率',
    full: '按今天的债券成交价把钱借给政府10年所锁定的回报——市场的长期利率。已持有债券的票息不会变；这是今天买入者拿到的条件。\n单位：百分比。',
    interp: '与股票竞争的保底选择：它越高，未来利润在今天越不值钱——越远期的（成长股）利润受伤越重。',
    blank: '10年期收益率序列加载失败。',
  },
  gov10y_trend: {
    short: '10年期国债收益率趋势',
    full: '10年期收益率与约3个月前相比：up（上行）/ down（下行）/ flat（持平，小幅波动算持平）。',
    interp: '上行 = 持仓期间估值压力正在累积——对成长股多头是逆风；下行 = 支撑。',
    blank: '10年期收益率历史不足，无法与3个月前比较。',
  },
  yield_diff_10y_2y_pp: {
    short: '收益率差（10年期 vs 2年期国债）',
    full: '10年期收益率减2年期收益率。\n单位：百分点。',
    interp: '为负（短端高于长端，即“倒挂”）是经典的衰退预警：市场预期因经济出问题而降息。',
    blank: '10年-2年利差序列加载失败。',
  },
  yield_diff_10y_2y_trend: {
    short: '收益率差（10年期 vs 2年期国债）趋势',
    full: '10年-2年利差与约3个月前相比：up（上行）/ down（下行）/ flat（持平）。',
    interp: '衰退表盘的走向：下行 = 滑向或加深预警；上行 = 走出倒挂，常意味着大环境转换。',
    blank: '10年-2年利差历史不足，无法与3个月前比较。',
  },
  yield_diff_hy_gov_pp: {
    short: '收益率差（高收益公司债 vs 国债）',
    full: '投资者持有高风险（“垃圾级”）公司债相对同期限政府债券额外要求的收益率。期限配对抵消了利率环境的影响，剩下的就是纯粹的违约恐惧——交易员称之为高收益信用利差。\n单位：百分点。',
    interp: '窄且稳定 = 放贷者放松、市场偏好风险；走阔 = 信用压力累积，常常先于股市反应。',
    blank: '高收益利差序列加载失败。',
  },
  yield_diff_hy_gov_trend: {
    short: '收益率差（高收益公司债 vs 国债）趋势',
    full: '信用利差与约3个月前相比：up（上行）/ down（下行）/ flat（持平）。',
    interp: '上行（走阔）是信用压力的早期警示灯；下行 = 恐惧消退。',
    blank: '高收益利差历史不足，无法与3个月前比较。',
  },
  markets: { short: '市场情绪', full: '市场层面的仪表：预期波动、油价与美元。' },
  vix: {
    short: '隐含市场波动',
    full: '由指数期权定价的、未来一个月大盘（标普500）波动幅度的预期——即“恐慌指数”（VIX）。与持仓报告里的个股隐含波动是同类指标的市场版。',
    interp: '约15以下 = 平静；20以上 = 紧张；30以上 = 危机模式。高波动环境下应缩小仓位、放宽止损。',
    blank: '波动指数序列加载失败。',
  },
  wti_oil_usd: {
    short: '原油价格',
    full: '美国基准原油价格（WTI），美元/桶。',
    interp: '能源和运输类股票的直接驱动因素——无论趋势如何，价位本身决定它们的处境。',
    blank: '油价序列加载失败。',
  },
  oil_trend: {
    short: '原油价格趋势',
    full: '油价与约3个月前相比：up（上行）/ down（下行）/ flat（持平，小幅百分比波动算持平）。',
    interp: '持续上行会传导进未来的通胀数据（油价每天变，通胀每月报），并拖累整个市场。',
    blank: '油价历史不足，无法与3个月前比较。',
  },
  dollar_trend: {
    short: '美元强弱趋势',
    full: '美元相对一篮子贸易伙伴货币的价值，与约3个月前相比：up（走强）/ down（走弱）/ flat（持平）。只展示方向——指数本身的数值是任意篮子单位，无法直接解读。',
    interp: '美元快速走强会压缩美国跨国公司的海外收益，且常伴随避险情绪；走弱则支撑风险偏好。',
    blank: '美元指数历史不足，无法与3个月前比较。',
  },
  events: { short: '事件', full: '可能在同一个早晨撼动整个市场的排期公告——相当于市场层面的财报日。' },
  next_cpi_release_date: {
    short: '下次通胀数据日期',
    full: '下一次消费者物价（CPI）数据的排期发布日。',
    interp: '市场层面的跳空风险：在持仓窗口内，所有股票都可能因这个数字跳动。',
    blank: '发布日历加载失败，或没有已排期的日期。',
  },
  next_jobs_release_date: {
    short: '下次就业数据日期',
    full: '下一次就业报告（失业率数据）的排期发布日。',
    interp: '市场层面的跳空风险：在持仓窗口内，所有股票都可能因这个数字跳动。',
    blank: '发布日历加载失败，或没有已排期的日期。',
  },
  next_rate_decision_date: {
    short: '下次官方利率日期',
    full: '下一次央行利率决议的排期日（美国为 FOMC 声明日）。',
    interp: '最大的排期市场事件——落在持仓窗口内时，对所有股票都是跳空风险。',
    blank: '已发布的决议日程表已用尽——需要补充下一年的日程。',
  },
  inflation_data_up_to: {
    short: '通胀数据截至',
    full: '最新消费者物价读数所描述的月份。通胀数据按月发布且有延迟。',
    interp: '可能是四到六周前的情况——它描述那个月，不是今天。',
    blank: '通胀序列加载失败。',
  },
  employment_data_up_to: {
    short: '就业数据截至',
    full: '最新失业率读数所描述的月份。就业数据按月发布且有延迟。',
    interp: '可能是四到六周前的情况——它描述那个月，不是今天。',
    blank: '失业率序列加载失败。',
  },
  // 已退役的宏观键（仅旧运行）。
  labor: { short: '就业', full: '就业市场的健康状况。' },
  dollar_index_broad: { short: '美元指数', full: '美元相对一篮子其他货币的强弱。' },
  observation_dates: {
    short: '数据日期',
    full: '每个数据点各自的日期（有的按月更新，有的按日更新）。',
  },

  // ---- positioning（v2 真源 2026-08-01；已退役键为旧运行保留）----
  short_interest: {
    short: '空头持仓',
    full: '被卖空的股份——投资者借入并卖出、押注股价下跌（空头）。空头要离场必须把股份买回来。FINRA 每月发布两次，约滞后两周；报告日期见基本信息组的「空头数据截至」。',
  },
  ownership_as_of: {
    short: '持股结构截至',
    full: '基金持股数据描述的季度末。大型基金每季度申报一次持仓（13F 申报），最晚可在季度结束后 45 天才提交。',
    interp: '持股结构组描述的可能是 3–4.5 个月前的仓位——只能当背景看，绝不能当成基金现在正在买或卖。',
    blank: '机构持股表加载失败，或表中没有申报日期。',
  },
  short_interest_as_of: {
    short: '空头数据截至',
    full: '空头数据的测量日期——每月发布两次，约滞后两周。',
    interp: '如果这个日期之后股价已大幅波动，数据里的空头可能早已回补离场——应降低整组数据的权重。',
    blank: 'Yahoo 未公布空头报告日期。',
  },
  options_bets_through: {
    short: '期权押注至',
    full: '认沽/认购合计所覆盖的最远期权到期日。与上面两个日期不同，它指向未来：期权数据本身截至本报告是新鲜的。',
    interp: '说明这些押注延伸到多远的未来——日期很近意味着比率只反映未来几周的仓位，不代表整个期权市场。',
    blank: '期权数据获取失败，或该股票没有挂牌期权。',
  },
  ownership: {
    short: '持股结构',
    full: '股份如何分布——谁持有这只股票、持仓有多集中。来自季度 13F 基金申报（最多滞后 45 天）和 Yahoo 摘要。',
  },
  institutional_pct: {
    short: '机构持股',
    full: '专业基金（公募基金、养老金、ETF）按季度 13F 申报的持股比例。',
    interp: '约 30–90% 是健康的机构参与度。极低 = 基金不能或不愿持有——质量/流动性红旗；极高 = 已被充分发掘，还有谁来接盘？',
    blank: 'Yahoo 未公布该股票的这项数据。',
  },
  institutional_diff_q_pp: {
    short: '机构持股变化（本季 vs 上季）',
    full: '仅旧的存档运行（已下线字段）：基金持股比例相对上一季度申报升降了多少个百分点。',
    interp: '基金加仓支撑上涨，减仓压制上涨——但申报最多滞后 45 天，只能当背景，不代表当前资金流向。',
    blank: '已下线字段——没有可靠的免费数据源公布上季度的机构持股总比例（Yahoo 的单一持有人变化数据被证实不可靠）。新的运行不再包含此字段。',
  },
  top10_institutions_pct: {
    short: '前十大机构持股',
    full: '前十大基金股东的合计持股。内部人不在此表内——只统计基金。',
    interp: '集中度风险：如果公司三分之一的股份握在十家基金手里，任何一家离场就是毫无征兆的大跌一天——应降低仓位或放宽止损。',
    blank: '机构持股表加载失败，或表中没有持股比例。',
  },
  insider_pct: {
    short: '内部人持股',
    full: '公司内部人的持股比例——高管、董事会成员及持股超 10% 的股东，即法律要求申报交易的人。',
    interp: '高 = 管理层身家与股价绑定，且这些锁定筹码使实际流通盘比看上去更小——双向波动都更大。',
    blank: 'Yahoo 未公布该股票的这项数据。',
  },
  float_shares: {
    short: '流通盘',
    full: '实际可交易的股份数——总股本减去内部人及战略持股等锁定部分。',
    interp: '流通盘小 = 双向波动和轧空都更猛烈：仓位要更小，并预期跳空。它也是空头持仓组各比率的分母。',
    blank: 'Yahoo 未公布该股票的这项数据。',
  },
  short_pct_of_float: {
    short: '空头占流通盘比',
    full: '在实际可交易的股份（流通盘）中，被借入卖空（押注下跌）的比例。',
    interp: '约 3% 以下正常；约 10%+ 是拥挤的空头交易；20%+ 进入轧空区——利好会迫使空头集体买回、推高股价。预期双向剧烈波动。',
    blank: 'Yahoo 既未公布该比例，也未公布计算所需的空头股数和流通盘。',
  },
  days_to_cover: {
    short: '空头股数/日均成交量',
    full: '空头股数除以日均成交量——空头按正常成交量全部买回需要多少个交易日。单位：天。',
    interp: '1–2 天 = 空头可以悄悄离场；5 天以上 = 离场时自己的买盘就会推高股价，轧空会走得更远。',
    blank: 'Yahoo 未公布该股票的这项数据。',
  },
  change_vs_prior_month_pct: {
    short: '空头股数变化（本期 vs 上期）',
    full: '相对上一期（半月一次）报告的空头股数变化百分比。',
    interp: '方向比水平重要：上升 = 空头加注；下降 = 空头已在认输回补，而回补本身就支撑股价。',
    blank: 'Yahoo 未公布本期或上期的空头股数。',
  },
  shares_short: {
    short: '空头股数',
    full: '仅旧运行（已退役字段）：被卖空的原始股数。只有对比流通盘才有意义——比例那一行才是可解读的。',
  },
  shares_outstanding: {
    short: '总股本',
    full: '仅旧运行（已退役字段）：公司已发行的股份总数。流通盘才是可交易的现实。',
  },
  insider_activity_6m: {
    short: '内部人交易（6个月）',
    full: '过去六个月公司内部人在公开市场的买卖，来自 SEC Form 4 申报。不含股权授予、期权行权和赠与——只有用自己的钱做的交易才体现信念。',
  },
  buy_count: {
    short: '6个月内部人买入笔数',
    full: '过去六个月内部人在公开市场买入自家股票的次数（不含授予、行权和赠与）。',
    interp: '本报告中最强的信号：内部人卖出的理由很多，买入的理由只有一个。哪怕一两笔真实买入也偏多。',
    blank: 'Yahoo 未返回任何内部人交易记录——空表可能是数据源故障，因此绝不显示为「0 笔」。',
  },
  sell_count: {
    short: '6个月内部人卖出笔数',
    full: '同一窗口内内部人在公开市场卖出的次数（不含授予、行权和赠与）。',
    interp: '零散卖出是常态（缴税、分散资产）；多名内部人短期内集中卖出才是警报形态。',
    blank: 'Yahoo 未返回任何内部人交易记录——空表可能是数据源故障，因此绝不显示为「0 笔」。',
  },
  net_shares: {
    short: '净买入股数',
    full: '仅旧运行（已退役字段）：买入股数减卖出股数。不同价位的股票之间不可比——金额差才可比。',
  },
  net_value_usd: {
    short: '6个月买卖金额差（买 − 卖）',
    full: '同一批公开市场交易中，内部人买入花的钱减去卖出拿走的钱。正数 = 净买入。',
    interp: '内部人信念的底线数字，跨股票可比：明显为正 = 看多信号；上涨途中大额为负 = 管理层趁强势套现。',
    blank: 'Yahoo 未返回任何内部人交易记录——空表可能是数据源故障，因此绝不显示为零。',
  },
  options: {
    short: '期权',
    full: '叠加在股票之上的方向押注：认沽（put）在股价下跌时获利（做空押注或保险），认购（call）在上涨时获利。本报告最新鲜的一组——每日更新，而基于股份的各组滞后数周到数月。',
  },
  put_call_oi_ratio: {
    short: '认沽/认购（持有）',
    full: '所有未平仓认沽合约除以未平仓认购合约——人们当前持有的仓位，是过去数周累积的，而非仅今天的交易。按最近几个到期日合计。',
    interp: '约 0.7–1.0 属正常。远高于 1 = 大量看跌押注或对冲；极低 = 一边倒看多——自满状态，此时利空杀伤最大。',
    blank: '数据源的未平仓量缺失或为零——零和缺失无法区分，因此不显示比率。',
  },
  put_call_volume_ratio: {
    short: '认沽/认购（当日成交）',
    full: '同一比率，但只用今天成交的合约——今天的新增资金流，而非存量仓位。',
    interp: '当日资金流与上面的持有比率背离时，说明情绪正在当下转向——持有比率是气候，这是天气。',
    blank: '数据源的成交量缺失或为零——零和缺失无法区分，因此不显示比率。',
  },
  total_open_interest: {
    short: '未平仓合约总数',
    full: '覆盖到期日内当前未平仓的期权合约总数（认沽加认购）——不是挂牌期权品种数，也不是成交量。',
    interp: '上面两个比率的可信度计量：大 = 期权市场活跃、比率有意义；很小 = 比率只是噪音——整组忽略。',
    blank: '数据源的未平仓量缺失或为零，因此不显示总数。',
  },
  expirations_covered: {
    short: '覆盖到期日数',
    full: '仅旧运行（已退役字段）：合计覆盖了多少个到期日。新运行改为发布「期权押注至」日期。',
  },
  implied_vol_pct: {
    short: '隐含波动率',
    full: '期权市场定价中隐含的年化波动幅度（%），取自行权价贴近现价（平值）的期权——CBOE 的 30 天数值。远离现价的期权不计入：其价格含有失真。',
    interp: '市场对这只股票的恐慌计：高 = 保险变贵、预期动荡——止损放宽、仓位缩小。原始水平单独看意义不大，每只股票有自己的常态。',
    blank: 'CBOE 未公布该股票的 30 天隐含波动率。',
  },
  implied_vol_rank_1y: {
    short: '隐含波动率位置（1年区间）',
    full: '仅旧的存档运行（已下线字段）：当前隐含波动率在其自身一年区间中的位置：0 = 期权市场对该股全年最平静，100 = 全年最紧绷。',
    interp: '接近顶部 = 已定价某个事件或风暴，容易跳空——缩小仓位或等待；接近底部 = 预期平静，走势有序。',
    blank: '已下线字段——需要一年的隐含波动率历史，没有免费数据源发布。新的运行不再包含此字段。',
  },
  implied_report_move_pct: {
    short: '财报日隐含波动幅度',
    full: '期权市场为下次季度财报定价的跳空幅度（%）——取财报日后第一个到期日的平值认购+认沽价格。无方向：期权价格只说明跳多大，不说明往哪跳（读作 ±）。\n仅在财报距今约 3 周以内才显示——更远时期权价格主要反映日常波动，而非财报跳空。',
    interp: '与止损距离对比：隐含 ±9% 的跳空对上 5% 的止损，意味着跳空会直接越过止损——要么财报前离场，要么把仓位缩到能承受全幅波动。',
    blank: '仅在下次季度财报距今约 3 周以内才显示（更远时期权价格主要反映日常波动，而非财报跳空），且需要财报日期和财报后第一个到期日的可用平值报价。',
  },
  report_move_ratio_implied_4q: {
    short: '财报日波动幅度比（隐含 vs 近4季均值）',
    full: '期权为下次财报日定价的隐含波动，除以最近4次财报日的实际平均波动（来自基本面报告）。1.0 = 期权定价的跳空幅度与往常一致。\n单位：倍数（×）。',
    interp: '明显大于 1 = 市场在为超出寻常的财报反应做准备；明显小于 1 = 预期异常平静。',
    blank: '仅旧的存档运行：需要同时具备“财报日隐含波动幅度”（仅季度财报距今约3周内显示）和基本面报告中的“近4季财报日平均波动幅度”——本次运行至少其一为空。较新的运行会在此直接指出缺失的一项。',
  },

  // ---- opinion（2026-08-18 数字化观点卡：分析师 + 散户情绪度量）----
  analyst: {
    short: '分析师观点',
    full: '华尔街专业研究机构当前的看法——买入/持有/卖出评级、12 个月目标价、以及最近一周的评级变动。数据来自 Yahoo Finance。',
    interp: '这是有依据的观点，不是事实：分析师整体偏乐观，目标价经常是跟着股价走而不是领先股价。',
  },
  crowd: {
    short: '散户热度',
    full: 'Reddit 上散户讨论这只股票的热度和语气，由两个公开统计源度量：ApeWisdom（提及次数与热度排名）和 Tradestie（WallStreetBets 评论情绪）。',
    interp: '本报告中最不可靠的一组：只能当作关注度和拥挤度来读，绝不能单独当作方向依据。',
  },
  firms_total: {
    short: '评级机构数',
    full: '当前有多少家研究机构对这只股票发布买入/持有/卖出评级。',
    interp: '机构越多，股票关注度越高、共识越稳；少于约 5 家时这些数字只是几个声音，不算共识。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  strong_buy_firms: {
    short: '强烈买入评级数',
    full: '本月给出强烈买入评级的机构数。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  buy_firms: {
    short: '买入评级数',
    full: '本月给出买入评级的机构数。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  hold_firms: {
    short: '持有评级数',
    full: '本月给出持有评级的机构数。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  sell_firms: {
    short: '卖出评级数',
    full: '本月给出卖出评级的机构数。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  strong_sell_firms: {
    short: '强烈卖出评级数',
    full: '本月给出强烈卖出评级的机构数。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  buy_rating_pct: {
    short: '买入评级占比',
    full: '本月给出买入或强烈买入评级的机构占比。\n单位：%。',
    interp: '这是专业观点，不是公司事实——分析师整体偏乐观，要结合下方的月度漂移一起读。',
    blank: '共识数据抓取失败，或覆盖该股票的机构太少。',
  },
  buy_rating_change_1m_pp: {
    short: '买入占比月度漂移',
    full: '买入评级占比相对一个月前变动了多少个百分点（正 = 分析师转暖）。\n单位：百分点。',
    interp: '漂移方向往往比水平更重要——股价上涨时买入占比却在下降，是一个安静的警告。',
    blank: '需要共识数据同时包含本月和上月两行。',
  },
  price_target_mean: {
    short: '平均目标价',
    full: '各机构 12 个月目标价的平均值。\n单位：美元。',
    interp: '一个变化缓慢的观点：目标价经常是跟着股价走而不是领先股价。',
    blank: 'Yahoo 未发布目标价，或分析师数据回退到了 Finnhub（免费档没有目标价）。',
  },
  price_target_high: {
    short: '最高目标价',
    full: '最乐观机构给出的 12 个月目标价。\n单位：美元。',
    blank: 'Yahoo 未发布目标价，或分析师数据回退到了 Finnhub（免费档没有目标价）。',
  },
  price_target_low: {
    short: '最低目标价',
    full: '最悲观机构给出的 12 个月目标价。\n单位：美元。',
    blank: 'Yahoo 未发布目标价，或分析师数据回退到了 Finnhub（免费档没有目标价）。',
  },
  target_vs_price_pct: {
    short: '平均目标价 vs 现价',
    full: '平均目标价距当前股价的百分比（正 = 目标价高于现价）。\n单位：%。',
    interp: '正向差距大只有在目标价是新鲜的时候才算利好——暴跌后差距大只是因为目标价还没来得及下调。',
    blank: '需要同一数据源同时给出平均目标价和当前价格。',
  },
  upgrades_count: {
    short: '评级上调数',
    full: '最近 7 个交易日内上调评级的机构数。',
    interp: '新鲜的上调偏利好；扎堆出现通常跟在财报之后。',
    blank: '评级变动数据抓取失败，或使用了 Finnhub 兜底（它没有评级变动历史）。',
  },
  downgrades_count: {
    short: '评级下调数',
    full: '最近 7 个交易日内下调评级的机构数。',
    interp: '新鲜的下调偏利空——而且往往伴随目标价下调。',
    blank: '评级变动数据抓取失败，或使用了 Finnhub 兜底（它没有评级变动历史）。',
  },
  initiations_count: {
    short: '新覆盖数',
    full: '最近 7 个交易日内首次覆盖这只股票的机构数（首次评级）。',
    interp: '新覆盖意味着新的专业关注——无论首评级别如何都略偏利好。',
    blank: '评级变动数据抓取失败，或使用了 Finnhub 兜底（它没有评级变动历史）。',
  },
  reddit_mentions: {
    short: 'Reddit 提及数（24h）',
    full: '过去 24 小时里 Reddit 主要投资板块的帖子和评论提到这只股票的次数（ApeWisdom 统计）。',
    interp: '这是关注度不是方向：激增说明散户突然在盯它——两个方向都拥挤，波动会更吵。',
    blank: '该股票不在 ApeWisdom 的热议榜上（讨论太少不足以上榜），或抓取失败。',
  },
  reddit_mentions_24h_ago: {
    short: 'Reddit 提及数（前 24h）',
    full: '再往前 24 小时的同一统计——当前提及数的对比基准。',
    blank: '该股票不在 ApeWisdom 的热议榜上（讨论太少不足以上榜），或抓取失败。',
  },
  reddit_upvotes: {
    short: 'Reddit 点赞数（24h）',
    full: '这些提及背后帖子获得的总点赞数——讨论引起了多大共鸣。',
    blank: '该股票不在 ApeWisdom 的热议榜上（讨论太少不足以上榜），或抓取失败。',
  },
  reddit_rank: {
    short: 'Reddit 热度排名',
    full: '这只股票当前在 ApeWisdom 最多提及榜上的名次（1 = 讨论最多）。',
    interp: '个位数 = 今天的话题主角；排名快速攀升是这一组里最清晰的散户关注信号。',
    blank: '该股票不在 ApeWisdom 的热议榜上（讨论太少不足以上榜），或抓取失败。',
  },
  reddit_rank_24h_ago: {
    short: 'Reddit 热度排名（前 24h）',
    full: '一天前的同一排名——对比可见攀升或退潮。',
    blank: '该股票不在 ApeWisdom 的热议榜上（讨论太少不足以上榜），或抓取失败。',
  },
  wsb_sentiment_score: {
    short: 'WallStreetBets 评论情绪',
    full: 'Tradestie 对今天 WallStreetBets 上关于这只股票的评论做的用词打分：大于 0 = 看多措辞占多，小于 0 = 看空（大致 -1 到 +1）。',
    interp: '本报告最不可靠的数字——一个论坛的情绪、按用词打分。最多算方向氛围，绝不能单独作为理由。',
    blank: '该股票不在今天 WallStreetBets 讨论最多的约 50 只股票之列，或抓取失败。',
  },
  wsb_comments: {
    short: 'WallStreetBets 评论数',
    full: '今天的扫描里提到该股票的 WallStreetBets 评论数（只有讨论最多的约 50 只股票上榜）。',
    blank: '该股票不在今天 WallStreetBets 讨论最多的约 50 只股票之列，或抓取失败。',
  },
};

export function metricEntry(key: string, language: UiLanguage): MetricEntry | null {
  const table = language === 'en' ? en : zh;
  return table[key] ?? null;
}
