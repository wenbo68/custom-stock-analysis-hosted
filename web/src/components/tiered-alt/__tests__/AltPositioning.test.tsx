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

// Positioning v2 dimension slice (TODO.md truth 2026-08-01): the five
// groups — meta / ownership structure / short interest / insider
// trades / options. institutional_diff_q_pp and implied_vol_rank_1y
// were dropped from NEW runs (owner decision 2026-08-05, no reliable
// free source) — this fixture keeps them to stand in for an old stored
// run, whose "n/a" reason modals must keep working.
function makePositioning(): TieredDimension {
  return {
    dimension: 'positioning',
    kind: 'numeric',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      meta: {
        ownership_as_of: env('ownership structure up to', '2026-03-31'),
        short_interest_as_of: env('short interest up to', '2026-07-01'),
        options_bets_through: env('options betting up to', '2026-09-18'),
      },
      ownership: {
        institutional_pct: env('institutional ownership', 61.55),
        institutional_diff_q_pp: env(
          'institutional ownership diff (current vs prev quarter)',
          null,
        ),
        top10_institutions_pct: env('top-10 institutional ownership', 12),
        insider_pct: env('insider ownership', 2.1),
        float_shares: env('float', 1.6e9),
      },
      short_interest: {
        short_pct_of_float: env('shorted shares to float', 3.13),
        days_to_cover: env('shorted shares to avg daily volume', 1.8),
        change_vs_prior_month_pct: env(
          'shorted shares diff (current vs prev report)',
          25,
        ),
      },
      insider_activity_6m: {
        buy_count: env('6m total insider buys', 1),
        sell_count: env('6m total insider sells', 1),
        net_value_usd: env('6m money diff (insider buys vs sells)', 56000),
      },
      options: {
        put_call_oi_ratio: env('puts to calls (held)', 0.92),
        put_call_volume_ratio: env('puts to calls (traded today)', 1.2),
        total_open_interest: env('total held options', 2880),
        implied_vol_pct: env('implied stock volatility', 26.08),
        implied_vol_rank_1y: env(
          'implied stock volatility ranking (1y range)',
          null,
        ),
        implied_report_move_pct: env(
          'implied quarterly report day price change magnitude',
          8.4,
        ),
        report_move_ratio_implied_4q: env(
          'quarterly report day price change magnitude ratio '
            + '(implied vs 4q avg)',
          1.55,
        ),
      },
    },
    formulas: {
      'short_interest.short_pct_of_float': {
        formula: 'shorted_shares / float_shares × 100',
        inputs: { shorted_shares: 50e6, float_shares: 1.6e9 },
      },
      'insider_activity_6m.net_value_usd': {
        formula: 'insider_buy_money − insider_sell_money',
        inputs: { insider_buy_money: 100000, insider_sell_money: 44000 },
      },
      'options.put_call_oi_ratio': {
        formula: 'held_puts / held_calls',
        inputs: { held_puts: 1380, held_calls: 1500 },
      },
      'options.total_open_interest': {
        formula: 'held_puts + held_calls',
        inputs: { held_puts: 1380, held_calls: 1500 },
      },
      'options.implied_report_move_pct': {
        formula: '(atm_call_price + atm_put_price) / stock_price × 100',
        inputs: { atm_call_price: 4.3, atm_put_price: 4.1, stock_price: 100 },
      },
      'options.report_move_ratio_implied_4q': {
        formula: 'implied_report_move_pct / reaction_avg_abs_pct',
        inputs: { implied_report_move_pct: 8.4, reaction_avg_abs_pct: 5.4 },
      },
    },
  };
}

function renderPositioning(dimension: TieredDimension = makePositioning()) {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[dimension]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — positioning v2', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders the TODO.md groups as titled sections with the truth names', () => {
    renderPositioning();
    const card = screen.getByTestId('alt-dimension-positioning');
    expect(within(card).getByText('Meta info')).toBeInTheDocument();
    expect(within(card).getByText('Ownership structure')).toBeInTheDocument();
    expect(within(card).getByText('Short interest')).toBeInTheDocument();
    expect(within(card).getByText('Insider trades (6m)')).toBeInTheDocument();
    expect(within(card).getByText('Options')).toBeInTheDocument();
    // Field labels come from metricLabels (truth names), not raw keys.
    expect(within(card).getByText('Shorted shares to float')).toBeInTheDocument();
    expect(within(card).getByText('Puts to calls (held)')).toBeInTheDocument();
    expect(within(card).getByText('Options betting up to')).toBeInTheDocument();
    // The envelope prose never renders — the UI keeps its own labels.
    expect(within(card).queryByText(/explained/)).toBeNull();
    expect(within(card).queryByText(/interpreted/)).toBeNull();
  });

  it('appends units, renders the report-day move as a ± magnitude', () => {
    renderPositioning();
    expect(screen.getByText('1.80 days')).toBeInTheDocument();
    expect(screen.getByText('61.55 %')).toBeInTheDocument();
    expect(screen.getByText('1.60 billion shares')).toBeInTheDocument();
    expect(
      screen.getByTestId('alt-metric-formula-implied_report_move_pct').textContent,
    ).toMatch(/^±8\.40 %$/);
    expect(
      screen.getByTestId('alt-metric-formula-total_open_interest').textContent,
    ).toMatch(/contracts$/);
    // Ratios stay bare.
    expect(
      screen.getByTestId('alt-metric-formula-put_call_oi_ratio').textContent,
    ).toBe('0.92');
    // The cross-report ratio carries the × unit and its receipt divides
    // the implied move by the realized 4q average.
    const ratio = screen.getByTestId(
      'alt-metric-formula-report_move_ratio_implied_4q',
    );
    expect(ratio.textContent).toBe('1.55 ×');
    fireEvent.click(ratio);
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(
      within(modal).getAllByText(/4q avg report day price change magnitude/i)
        .length,
    ).toBeGreaterThan(0);
  });

  it('shows run notes beside their own field and drops the card button', () => {
    const dimension = makePositioning();
    const farReport =
      'next report is more than 21 days away — option prices there mostly '
      + 'reflect ordinary drift, not the report jump; implied report-day '
      + 'move omitted';
    dimension.warnings = [farReport];
    dimension.field_notes = {
      'options.implied_report_move_pct': [farReport],
    };
    const options = dimension.payload!.options as Record<string, unknown>;
    options.implied_report_move_pct = env(
      'implied quarterly report day price change magnitude',
      null,
    );
    renderPositioning(dimension);

    // Every note sits beside a field → no card-level notes button.
    expect(screen.queryByTestId('alt-notes-button')).toBeNull();

    // The field's own mark opens a modal with exactly this run's reason.
    fireEvent.click(
      screen.getByTestId('alt-field-notes-implied_report_move_pct'),
    );
    const modal = screen.getByTestId('alt-field-notes-modal');
    expect(modal.textContent).toContain('more than 21 days away');

    // Fields without notes get no mark.
    expect(screen.queryByTestId('alt-field-notes-put_call_oi_ratio')).toBeNull();
  });

  it('shows the real countdown in the far-report note, with its receipt (new runs)', () => {
    const dimension = makePositioning();
    const farReport =
      'next quarterly report is 68 days away (report 2026-10-30, today '
      + '2026-08-23) — more than 21 days out, option prices mostly reflect '
      + 'ordinary drift, not the report jump; implied report-day move omitted';
    dimension.warnings = [farReport];
    dimension.field_notes = {
      'options.implied_report_move_pct': [farReport],
    };
    const options = dimension.payload!.options as Record<string, unknown>;
    options.implied_report_move_pct = env(
      'implied quarterly report day price change magnitude',
      null,
    );
    renderPositioning(dimension);

    fireEvent.click(
      screen.getByTestId('alt-field-notes-implied_report_move_pct'),
    );
    const modal = screen.getByTestId('alt-field-notes-modal');
    // The actual number of days, not just the threshold.
    expect(modal.textContent).toContain('68 days away');
    expect(modal.textContent).toContain('more than 21');

    // The number opens its date-minus-date receipt in the standard
    // three-line format, naming the report-date row exactly.
    fireEvent.click(screen.getByTestId('alt-note-days-receipt'));
    const receipt = screen.getByText('Days until next quarterly report')
      .closest('[role="dialog"]') as HTMLElement;
    expect(receipt.textContent).toContain('Next quarterly report date');
    expect(receipt.textContent).toContain('today');
    expect(
      within(receipt).getByRole('button', { name: '2026/10/30' }),
    ).toBeInTheDocument();
    expect(receipt.textContent).toContain('2026/08/23');
    expect(receipt.textContent).toContain('= 68');
  });

  it('names and links the missing ingredient behind a blank report-move ratio', () => {
    const dimension = makePositioning();
    const missing =
      'implied report-day move missing — report-move ratio '
      + '(implied vs 4q avg) omitted';
    dimension.warnings = [missing];
    dimension.field_notes = {
      'options.report_move_ratio_implied_4q': [missing],
    };
    const options = dimension.payload!.options as Record<string, unknown>;
    options.report_move_ratio_implied_4q = env(
      'quarterly report day price change magnitude ratio (implied vs 4q avg)',
      null,
    );
    renderPositioning(dimension);

    fireEvent.click(
      screen.getByTestId('alt-field-notes-report_move_ratio_implied_4q'),
    );
    const modal = screen.getByTestId('alt-field-notes-modal');
    // The missing ingredient under its exact report name, as a jump link.
    expect(
      within(modal).getByRole('button', {
        name: 'Implied quarterly report day price change magnitude',
      }),
    ).toBeInTheDocument();
  });

  it('keeps the card-level button for old stored runs without field notes', () => {
    const dimension = makePositioning();
    dimension.warnings = ['no listed options found for AAPL'];
    renderPositioning(dimension);
    expect(screen.getByTestId('alt-notes-button')).toBeInTheDocument();
  });

  it('opens the money-diff receipt with named ingredients and a unit result', () => {
    renderPositioning();
    fireEvent.click(screen.getByTestId('alt-metric-formula-net_value_usd'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getAllByText('insider buying ($)').length).toBeGreaterThan(0);
    expect(within(modal).getAllByText('insider selling ($)').length).toBeGreaterThan(0);
    expect(within(modal).getByText('= 56000 USD')).toBeInTheDocument();
  });

  it('links the computed short-percentage receipt back to the float row', () => {
    renderPositioning();
    fireEvent.click(screen.getByTestId('alt-metric-formula-short_pct_of_float'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // float_shares is a published row → its plugged number jump-links.
    expect(within(modal).getByRole('button', { name: 'Float' })).toBeInTheDocument();
    // shorted_shares is receipt-only, named by the helper table.
    expect(within(modal).getAllByText('shorted shares').length).toBeGreaterThan(0);
  });

  it('shows Meaning + Interpretation blocks in a positioning tooltip', () => {
    renderPositioning();
    const label = screen.getAllByText('6m total insider buys')[0];
    fireEvent.mouseEnter(label.closest('span[class*="inline-flex"]') ?? label);
    const tooltip = screen.getByRole('tooltip');
    expect(within(tooltip).getByText('Meaning:')).toBeInTheDocument();
    expect(within(tooltip).getByText('Interpretation:')).toBeInTheDocument();
    expect(
      within(tooltip).getByText(/insiders sell for many reasons but buy for exactly one/i),
    ).toBeInTheDocument();
  });
});
