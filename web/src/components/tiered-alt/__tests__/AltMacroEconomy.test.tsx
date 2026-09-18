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

// Macro econ v2 dimension slice (TODO.md truth 2026-08-04): meta /
// inflation / employment / interest rates / bonds / markets / events,
// every field an envelope, diffs and trends carrying receipts.
function makeMacro(): TieredDimension {
  return {
    dimension: 'macro_economy',
    kind: 'numeric',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      meta: {
        region: env('region', 'us'),
        inflation_data_up_to: env('inflation data up to', '2026-06-01'),
        employment_data_up_to: env('employment data up to', '2026-06-01'),
      },
      inflation: {
        cpi_yoy_pct: env('consumer price index (YoY)', 3.23),
        cpi_yoy_trend: env('consumer price index (YoY) trend', 'down'),
      },
      employment: {
        unemployment_rate_pct: env('unemployment rate', 4.1),
        unemployment_trend: env('unemployment rate trend', 'flat'),
      },
      interest_rates: {
        official_rate_pct: env('official interest rate', 4.33),
        diff_2y_vs_official_pp: env(
          'diff (2y gov bond yield vs official interest rate)', -0.33,
        ),
      },
      bonds: {
        gov10y_yield_pct: env('10y gov bond yield', 4.4),
        gov10y_trend: env('10y gov bond yield trend', 'up'),
        yield_diff_10y_2y_pp: env(
          'yield diff (10y gov bond vs 2y gov bond)', 0.4,
        ),
        yield_diff_hy_gov_pp: env(
          'yield diff (high-yield company bond vs gov bond)', 3.1,
        ),
      },
      markets: {
        vix: env('implied market volatility', 17.5),
        wti_oil_usd: env('crude oil price', 68.2),
        oil_trend: env('crude oil price trend', 'up'),
        dollar_trend: env('dollar strength trend', 'flat'),
      },
      events: {
        next_cpi_release_date: env('next inflation data date', '2026-07-15'),
        next_jobs_release_date: env('next employment data date', '2026-08-07'),
        next_rate_decision_date: env(
          'next official interest rate date', '2026-07-29',
        ),
      },
    },
    formulas: {
      'interest_rates.diff_2y_vs_official_pp': {
        formula: 'gov_bond_yield_2y − official_interest_rate',
        inputs: { gov_bond_yield_2y: 4.0, official_interest_rate: 4.33 },
      },
      'bonds.gov10y_trend': {
        branches: [
          { label: 'up', condition: 'value_now > value_3m_ago + 0.25' },
          { label: 'down', condition: 'value_now < value_3m_ago − 0.25' },
          { label: 'flat', condition: null },
        ],
        inputs: { value_now: 4.4, value_3m_ago: 4.0 },
      },
    },
  };
}

function renderMacro(dimension: TieredDimension = makeMacro()) {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[dimension]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — macro econ v2', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders the truth groups as titled sections without an Other bucket', () => {
    renderMacro();
    const card = screen.getByTestId('alt-dimension-macro_economy');
    expect(within(card).getByText('Inflation')).toBeInTheDocument();
    expect(within(card).getByText('Employment')).toBeInTheDocument();
    expect(within(card).getByText('Interest rates')).toBeInTheDocument();
    expect(within(card).getByText('Bonds')).toBeInTheDocument();
    expect(within(card).getByText('Events')).toBeInTheDocument();
    expect(within(card).queryByText('Other')).toBeNull();
  });

  it('labels the fields from metricLabels and shows units and trend words', () => {
    renderMacro();
    const card = screen.getByTestId('alt-dimension-macro_economy');
    expect(within(card).getByText('Official interest rate')).toBeInTheDocument();
    expect(within(card).getByText('10y gov bond yield')).toBeInTheDocument();
    expect(
      within(card).getByText('Yield diff (high-yield company bond vs gov bond)'),
    ).toBeInTheDocument();
    expect(within(card).getByText('Dollar strength trend')).toBeInTheDocument();
    expect(
      within(card).getByText('Next official interest rate date'),
    ).toBeInTheDocument();
    // Units from METRIC_UNIT; trend values render as bare words.
    expect(within(card).getByText('3.10 %')).toBeInTheDocument();
    expect(within(card).getByText('68.20 USD')).toBeInTheDocument();
    expect(within(card).getAllByText('flat').length).toBeGreaterThan(0);
    // The envelope prose never renders — the UI keeps its own labels.
    expect(within(card).queryByText(/explained/)).toBeNull();
  });

  it('opens the diff receipt with the 2y yield minus the official rate', () => {
    renderMacro();
    fireEvent.click(
      screen.getByTestId('alt-metric-formula-diff_2y_vs_official_pp'),
    );
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getByText(/2y gov bond yield/)).toBeInTheDocument();
    expect(within(modal).getByText(/4\.33/)).toBeInTheDocument();
  });

  it('opens the 10y trend receipt as branch rules with the two endpoints', () => {
    renderMacro();
    fireEvent.click(screen.getByTestId('alt-metric-formula-gov10y_trend'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Branch conditions repeat the variable names — assert presence,
    // not uniqueness.
    expect(within(modal).getAllByText(/value now/).length).toBeGreaterThan(0);
    expect(
      within(modal).getAllByText(/value 3 months ago/).length,
    ).toBeGreaterThan(0);
  });
});

// The technicals market group grew the sector comparison (cross-provider
// enrichment 2026-08-04); the same rendering machinery must label the
// six new fields and unit their diffs.
function makeTechnicalsMarket(): TieredDimension {
  return {
    dimension: 'technicals',
    kind: 'numeric',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      market: {
        regime: env('market trend', 'bullish'),
        rs_sector_1m: env('1m return diff (sector vs market)', 5.0),
        rs_sector_3m: env('3m return diff (sector vs market)', 4.0),
        sector_vs_market_label: env(
          'sector performance relative to market', 'leader',
        ),
        rs_1m: env('1m return diff (stock vs market)', 3.0),
        rs_3m: env('3m return diff (stock vs market)', 6.0),
        rs_label: env('stock performance relative to market', 'leader'),
        rs_stock_sector_1m: env('1m return diff (stock vs sector)', -2.0),
        rs_stock_sector_3m: env('3m return diff (stock vs sector)', 2.0),
        stock_vs_sector_label: env(
          'stock performance relative to sector', 'neutral',
        ),
      },
    },
    formulas: {
      'market.rs_sector_1m': {
        formula: 'sector_return_1m − index_return_1m',
        inputs: { sector_return_1m: 10.0, index_return_1m: 5.0 },
      },
    },
  };
}

describe('AltDimensions — technicals market vs sector vs stock', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('labels the sector comparison rows and the renamed readings', () => {
    render(
      <UiLanguageProvider>
        <AltDimensions dimensions={[makeTechnicalsMarket()]} />
      </UiLanguageProvider>,
    );
    const card = screen.getByTestId('alt-dimension-technicals');
    expect(
      within(card).getByText('Market vs sector vs stock'),
    ).toBeInTheDocument();
    expect(within(card).getByText('Market trend')).toBeInTheDocument();
    expect(
      within(card).getByText('1m return diff (sector vs market)'),
    ).toBeInTheDocument();
    expect(
      within(card).getByText('Sector performance relative to market'),
    ).toBeInTheDocument();
    expect(
      within(card).getByText('Stock performance relative to sector'),
    ).toBeInTheDocument();
    // Percentage-point diffs carry the % unit; the sector receipt opens.
    fireEvent.click(screen.getByTestId('alt-metric-formula-rs_sector_1m'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getByText(/sector return \(1m\)/)).toBeInTheDocument();
  });
});
