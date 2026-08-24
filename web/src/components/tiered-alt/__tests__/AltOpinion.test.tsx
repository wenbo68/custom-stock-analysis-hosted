import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

const env = (name: string, value: unknown) => ({
  name,
  explanation: `${name} explained`,
  interpretation: `${name} interpreted`,
  value,
});

// The opinion card (numeric, 2026-08-18): two groups — analyst (Yahoo
// consensus/targets/rating actions) and crowd (ApeWisdom Reddit buzz +
// Tradestie WallStreetBets tone). This fixture mirrors a live AAPL run.
function makeOpinion(): TieredDimension {
  return {
    dimension: 'opinion',
    kind: 'numeric',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      analyst: {
        firms_total: env('firms rating the stock', 46),
        strong_buy_firms: env('strong-buy ratings', 6),
        buy_firms: env('buy ratings', 21),
        hold_firms: env('hold ratings', 14),
        sell_firms: env('sell ratings', 3),
        strong_sell_firms: env('strong-sell ratings', 2),
        buy_rating_pct: env('buy share of ratings', 58.7),
        buy_rating_change_1m_pp: env('buy share drift, 1 month', -2.2),
        price_target_mean: env('average price target', 321.0),
        price_target_high: env('highest price target', 400.0),
        price_target_low: env('lowest price target', 215.0),
        target_vs_price_pct: env('average target vs price', 7.0),
        upgrades_count: env('rating upgrades', 0),
        downgrades_count: env('rating downgrades', 1),
        initiations_count: env('new coverage started', 1),
      },
      crowd: {
        reddit_mentions: env('Reddit mentions, 24h', 146),
        reddit_mentions_24h_ago: env('Reddit mentions, prior 24h', 9),
        reddit_upvotes: env('Reddit upvotes, 24h', 832),
        reddit_rank: env('Reddit buzz rank', 4),
        reddit_rank_24h_ago: env('Reddit buzz rank, prior 24h', 29),
        wsb_sentiment_score: env('WallStreetBets comment tone', 0.168),
        wsb_comments: env('WallStreetBets comments', 43),
      },
    },
    formulas: {
      'analyst.buy_rating_pct': {
        formula: '(strong_buy_firms + buy_firms) / firms_total × 100',
        inputs: { strong_buy_firms: 6, buy_firms: 21, firms_total: 46 },
      },
      'analyst.buy_rating_change_1m_pp': {
        formula: "this month's buy share − last month's buy share",
        inputs: { this_month_pct: 58.7, last_month_pct: 60.9 },
      },
      'analyst.target_vs_price_pct': {
        formula: '(price_target_mean / current_price − 1) × 100',
        inputs: { price_target_mean: 321.0, current_price: 300.0 },
      },
    },
  };
}

function renderOpinion(dimension: TieredDimension = makeOpinion()) {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[dimension]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — opinion (analyst + crowd)', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders the two groups titled from metricLabels with truth field names', () => {
    renderOpinion();
    const card = screen.getByTestId('alt-dimension-opinion');
    // Group titles come from the metricLabels entries for the group
    // keys — never the raw payload keys.
    expect(within(card).getByText('Analyst opinion')).toBeInTheDocument();
    expect(within(card).getByText('Crowd chatter')).toBeInTheDocument();
    expect(within(card).getByText('Buy share of ratings')).toBeInTheDocument();
    expect(within(card).getByText('Reddit buzz rank')).toBeInTheDocument();
    expect(
      within(card).getByText('WallStreetBets comment tone'),
    ).toBeInTheDocument();
    // No raw underscore keys anywhere on the card.
    expect(card.textContent).not.toMatch(/_/);
    // The envelope prose never renders — the UI keeps its own labels.
    expect(within(card).queryByText(/explained/)).toBeNull();
  });

  it('appends the units: firms, %, pp, USD, mentions', () => {
    renderOpinion();
    expect(screen.getByText('46 firms')).toBeInTheDocument();
    expect(screen.getByText('321 USD')).toBeInTheDocument();
    expect(screen.getByText('-2.20 pp')).toBeInTheDocument();
    expect(screen.getByText('146 mentions')).toBeInTheDocument();
    // The sentiment score and ranks stay bare numbers.
    expect(screen.getByText('0.17')).toBeInTheDocument();
  });

  it('opens the buy-share drift receipt with named month ingredients', () => {
    renderOpinion();
    fireEvent.click(
      screen.getByTestId('alt-metric-formula-buy_rating_change_1m_pp'),
    );
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // this month's value IS the published buy-share row, so it carries
    // that row's exact name and links to it (modal naming rule
    // 2026-08-23); last month's stays a receipt-only helper name.
    expect(
      within(modal).getByRole('button', { name: 'Buy share of ratings' }),
    ).toBeInTheDocument();
    expect(
      within(modal).getAllByText("last month's buy share (%)").length,
    ).toBeGreaterThan(0);
  });

  it('shows blank crowd fields as n/a with the not-trending note behind the mark', () => {
    const dimension = makeOpinion();
    const note =
      "crowd opinions: AAPL is not on Tradestie's ranking — too little"
      + ' Reddit chatter to register';
    dimension.warnings = [note];
    dimension.field_notes = {
      'crowd.wsb_sentiment_score': [note],
      'crowd.wsb_comments': [note],
    };
    const crowd = dimension.payload!.crowd as Record<string, unknown>;
    crowd.wsb_sentiment_score = env('WallStreetBets comment tone', null);
    crowd.wsb_comments = env('WallStreetBets comments', null);
    renderOpinion(dimension);

    expect(
      screen.getByTestId('alt-metric-blank-wsb_sentiment_score').textContent,
    ).toBe('n/a');
    // Every note sits beside a field → no card-level notes button.
    expect(screen.queryByTestId('alt-notes-button')).toBeNull();
    fireEvent.click(screen.getByTestId('alt-field-notes-wsb_comments'));
    expect(
      screen.getByTestId('alt-field-notes-modal').textContent,
    ).toContain('too little Reddit chatter');
  });
});
