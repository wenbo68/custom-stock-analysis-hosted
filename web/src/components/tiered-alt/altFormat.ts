// Number-to-text helpers shared across the alt page.
import type { TieredDebateLink } from '../../api/tiered';
import { formatValue } from '../tiered/termHelpers';

// Display units per payload key (owner request 2026-07-28): numbers
// render as "2.88 ATR", "-6.82 %". Dimensionless numbers (RSI, P/E, a
// ranking, ratios) and labels stay bare.
const METRIC_UNIT: Record<string, string> = {
  chg_5d_pct: '%',
  atr_pct: '%',
  worst_day_pct_1y: '%',
  rs_1m: '%',
  rs_3m: '%',
  stretch_10w_atr: 'ATR',
  stretch_50d_atr: 'ATR',
  typical_pullback_atr: 'ATR',
  avg_vol_60d: 'shares',
  avg_vol_5d: 'shares',
  vol_ratio_5_60: '×',
  // Stored-run keys that carry the same units.
  volatility_pct: '%',
  bias_20: '%',
  avg_volume_20: 'shares',
  // Fundamentals v2 (2026-07-29; regrouped 2026-07-31).
  days_until_earnings: 'days',
  avg_surprise_pct_4q: '%',
  reaction_avg_abs_pct: '%',
  reaction_worst_pct: '%',
  eps_rev_30d_pct: '%',
  revenue_yoy_q: '%',
  eps_yoy_q: '%',
  gross_margin_pct: '%',
  operating_margin_pct: '%',
  roe_pct: '%',
  fcf: 'USD',
  fcf_to_earnings_pct: '%',
  market_cap: 'USD',
  // Technicals market-vs-sector-vs-stock + distance diffs (2026-08-04).
  rs_sector_1m: '%',
  rs_sector_3m: '%',
  rs_stock_sector_1m: '%',
  rs_stock_sector_3m: '%',
  stretch_200d_atr: 'ATR',
  support_dist_atr: 'ATR',
  resistance_dist_atr: 'ATR',
  // Macro econ v2 (2026-08-04). The yield/rate fields share the % unit;
  // trends and event dates are words/dates so no entry.
  official_rate_pct: '%',
  diff_2y_vs_official_pp: '%',
  gov10y_yield_pct: '%',
  yield_diff_10y_2y_pp: '%',
  yield_diff_hy_gov_pp: '%',
  cpi_yoy_pct: '%',
  unemployment_rate_pct: '%',
  wti_oil_usd: 'USD',
  // Positioning v2 (2026-08-01).
  short_pct_of_float: '%',
  days_to_cover: 'days',
  change_vs_prior_month_pct: '%',
  institutional_pct: '%',
  institutional_diff_q_pp: '%',
  top10_institutions_pct: '%',
  insider_pct: '%',
  float_shares: 'shares',
  net_value_usd: 'USD',
  // Insider trade counts are numbers of filed trades, not shares.
  buy_count: 'trades',
  sell_count: 'trades',
  total_open_interest: 'contracts',
  implied_vol_pct: '%',
  report_move_ratio_implied_4q: '×',
  // Opinion (numeric card 2026-08-18). The buzz ranks and the WSB tone
  // score are dimensionless and stay bare.
  firms_total: 'firms',
  strong_buy_firms: 'firms',
  buy_firms: 'firms',
  hold_firms: 'firms',
  sell_firms: 'firms',
  strong_sell_firms: 'firms',
  buy_rating_pct: '%',
  buy_rating_change_1m_pp: 'pp',
  price_target_mean: 'USD',
  price_target_high: 'USD',
  price_target_low: 'USD',
  target_vs_price_pct: '%',
  upgrades_count: 'firms',
  downgrades_count: 'firms',
  initiations_count: 'firms',
  reddit_mentions: 'mentions',
  reddit_mentions_24h_ago: 'mentions',
  reddit_upvotes: 'upvotes',
  wsb_comments: 'comments',
};

// The page's one date style (owner request 2026-08-16): an ISO date
// value (2026-08-12) renders as 2026/08/12 everywhere on the alt page.
// Anything that is not exactly a yyyy-mm-dd string passes through
// untouched — prose sentences and citation-checked claim text are
// never rewritten.
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
export const slashDate = (value: string): string =>
  ISO_DATE_RE.test(value) ? value.split('-').join('/') : value;

// A metric value with its unit appended when it has one.
export const formatMetricValue = (key: string, value: unknown): string => {
  // The 1y rankings read as a position on a 0-100 scale: "30/100"
  // (owner format 2026-07-28).
  if (
    (key === 'range_pct_1y' || key === 'implied_vol_rank_1y') &&
    typeof value === 'number'
  ) {
    return `${Math.round(value)}/100`;
  }
  // Report-day move magnitudes carry no direction — the "±" tells the
  // reader the jump can go either way.
  if (
    (key === 'implied_report_move_pct' || key === 'reaction_avg_abs_pct') &&
    typeof value === 'number'
  ) {
    return `±${formatValue(value)} %`;
  }
  // Date-valued fields (next earnings, macro event dates) take the
  // page's slashed date style.
  if (typeof value === 'string') {
    return slashDate(value.trim());
  }
  const text = formatValue(value);
  const unit = typeof value === 'number' ? METRIC_UNIT[key] : undefined;
  return unit ? `${text} ${unit}` : text;
};

// 0.01 -> '1', 0.005 -> '0.5' — a stored risk fraction as the percent the
// user typed, without float noise (0.01 * 100 === 1.0000000000000002).
export const riskPctText = (fraction: number): string =>
  String(Number((fraction * 100).toPrecision(12)));

// 100000.0 -> '100000' — a capital amount as the plain number it was entered as.
export const plainNumber = (value: number): string => String(Number(value));

// Anchor ids of the levels table's cells ('entry', 'stop_loss',
// 'take_profit', 'shares'), so formulas elsewhere in the report can
// scroll-flash the cell a number came from.
export const computedCellId = (key: string): string => `alt-level-computed-${key}`;
export const adjustedCellId = (key: string): string => `alt-level-adjusted-${key}`;

// The outlook word for a tier outlook — the outlook redesign renamed
// buy/hold/sell to bullish/neutral/bearish everywhere the UI speaks.
export const directionOutlook = (direction: string | null | undefined): string => {
  switch (direction) {
    case 'buy':
      return 'bullish';
    case 'hold':
      return 'neutral';
    case 'sell':
      return 'bearish';
    default:
      return 'unknown';
  }
};

// The citation markup the backend prompts describe — the model is told
// to put links in a separate array, but sometimes writes the markup
// inline in the sentence instead: {{ref: "technicals.close", "value":
// "340.75"}}. Quoting varies, so keys and values are matched loosely.
const INLINE_REF_RE =
  /\{\{\s*"?ref"?\s*:\s*"?([^",}]+?)"?\s*(?:,\s*"?value"?\s*:\s*(?:"([^"]*)"|([^,}]+?))\s*)?\}\}/g;

// Renders inline markup as just its cited value, merging the ref into
// the links list (deduped) so the value still underlines and jumps.
export const stripInlineRefs = (
  text: string,
  links: TieredDebateLink[],
): { text: string; links: TieredDebateLink[] } => {
  if (!text.includes('{{')) {
    return { text, links };
  }
  const merged = [...links];
  const known = new Set(links.map((link) => `${link.ref}|${link.value ?? ''}`));
  const clean = text
    .replace(INLINE_REF_RE, (_all, ref: string, quoted?: string, bare?: string) => {
      const value = quoted ?? bare ?? null;
      const key = `${ref}|${value ?? ''}`;
      if (!known.has(key)) {
        known.add(key);
        merged.push({ ref, value });
      }
      return value ?? '';
    })
    .replace(/ {2,}/g, ' ');
  return { text: clean, links: merged };
};
