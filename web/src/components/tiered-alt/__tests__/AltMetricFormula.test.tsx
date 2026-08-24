import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

// Technicals v2 dimension slice: nested envelope groups + the parallel
// formulas map (2026-07-28). rsi_14 has a substituted receipt, sma_50 a
// words-only receipt, the trend and regime labels rule receipts, and
// as_of (a raw fact) none.
function makeTechnicals(): TieredDimension {
  const env = (name: string, value: unknown) => ({
    name,
    explanation: `${name} explained`,
    value,
  });
  return {
    dimension: 'technicals',
    kind: 'numeric',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      meta: { as_of: env('as of', '2026-07-24') },
      market: { regime: env('benchmark: market', 'bullish') },
      price: {
        close: env('closing price', 157.79),
        range_pct_1y: env('current closing price ranking (1y range)', 30.4),
      },
      daily: {
        trend: env('daily trend (SMA + pivots)', 'neutral'),
        sma_50: env('50d SMA', 156.36),
        stretch_50d_atr: env('diff: closing price vs 50d SMA', 0.45),
        rsi_14: env('14d RSI', 38.89),
        momentum: env('momentum', 'weak'),
      },
      volatility: { atr_14: env('14d ATR', 3.17) },
    },
    formulas: {
      'market.regime': {
        branches: [
          { label: 'bullish', condition: 'index_close > index_sma_200 && index_range_pct > 50' },
          { label: 'bearish', condition: 'index_close < index_sma_200 && index_range_pct < 50' },
          { label: 'mixed', condition: null },
        ],
        inputs: { index_close: 6234.5, index_sma_200: 5890.2, index_range_pct: 78 },
      },
      'daily.trend': {
        branches: [
          {
            label: 'bullish',
            condition: 'ma_stack = up && pivot_structure = higher highs and lows',
          },
          {
            label: 'bearish',
            condition: 'ma_stack = down && pivot_structure = lower highs and lows',
          },
          { label: 'neutral', condition: null },
        ],
        inputs: { ma_stack: 'mixed', pivot_structure: 'sideways' },
      },
      'daily.momentum': {
        branches: [
          { label: 'strong', condition: 'rsi_14 > 55 && macd_hist = rising && macd_line > 0' },
          { label: 'weak', condition: 'rsi_14 < 45 && macd_hist = falling && macd_line < 0' },
          { label: 'fading', condition: 'rsi_14 > 55 && macd_hist = falling' },
          { label: 'basing', condition: 'rsi_14 < 45 && macd_hist = rising' },
          { label: 'neutral', condition: null },
        ],
        inputs: { rsi_14: 38.89, macd_hist: 'falling', macd_line: -1.02 },
      },
      'daily.rsi_14': {
        formula: '100 − 100 / (1 + avg_gain_14 / avg_loss_14)',
        inputs: { avg_gain_14: 0.1017, avg_loss_14: 0.1598 },
      },
      'daily.stretch_50d_atr': {
        formula: '(close − sma_50) / atr_14',
        inputs: { close: 157.79, sma_50: 156.36, atr_14: 3.17 },
      },
      'daily.sma_50': {
        formula: 'the sum of the last 50 daily closes / 50',
        inputs: {},
      },
    },
  };
}

function renderTechnicals() {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[makeTechnicals()]} />
    </UiLanguageProvider>,
  );
}

describe('AltMetricFormula', () => {
  it('opens the three-line receipt from the metric value', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-rsi_14'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Words line: variable tokens shown as their display labels.
    expect(within(modal).getByText('avg gain (14d)')).toBeInTheDocument();
    expect(within(modal).getByText('avg loss (14d)')).toBeInTheDocument();
    // Plugged line: this run's numbers, small values not flattened.
    expect(within(modal).getByText('0.1017')).toBeInTheDocument();
    expect(within(modal).getByText('0.1598')).toBeInTheDocument();
    // Result line.
    expect(within(modal).getByText('= 38.89')).toBeInTheDocument();
  });

  it('links plugged numbers that are payload rows back to their row', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-stretch_50d_atr'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // close / sma 50 / atr 14 all exist as rows on the card → buttons.
    expect(within(modal).getByRole('button', { name: 'Closing price' })).toBeInTheDocument();
    expect(within(modal).getByRole('button', { name: '50d SMA' })).toBeInTheDocument();
    expect(within(modal).getByRole('button', { name: '14d ATR' })).toBeInTheDocument();
  });

  it('renders words-only receipts without a plugged line', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-sma_50'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(
      within(modal).getByText('the sum of the last 50 daily closes / 50'),
    ).toBeInTheDocument();
    // One "=" line only: the result.
    expect(within(modal).getAllByText(/^=/)).toHaveLength(1);
    expect(within(modal).getByText('= 156.36')).toBeInTheDocument();
  });

  it('leaves metrics without a receipt as plain text', () => {
    renderTechnicals();
    // Dates render in the page's slashed style (owner request 2026-08-16).
    expect(screen.getByText('2026/07/24')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-metric-formula-as_of')).toBeNull();
  });

  it('appends units to displayed values', () => {
    renderTechnicals();
    // ATR-denominated stretch: "0.45 ATR" on the row's value button …
    const stretch = screen.getByTestId('alt-metric-formula-stretch_50d_atr');
    expect(stretch.textContent).toBe('0.45 ATR');
    // … and on the receipt's result line.
    fireEvent.click(stretch);
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getByText('= 0.45 ATR')).toBeInTheDocument();
    // Unitless values stay bare.
    expect(screen.getByTestId('alt-metric-formula-rsi_14').textContent).toBe('38.89');
  });

  it('renders the 1y price ranking as a position out of 100', () => {
    renderTechnicals();
    expect(screen.getByText('30/100')).toBeInTheDocument();
  });

  it('renders a numeric rule as one line per outcome, twice (regime)', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-regime'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Branch labels appear in the words section AND the plugged section.
    expect(within(modal).getAllByText('bullish')).toHaveLength(2);
    expect(within(modal).getAllByText('bearish')).toHaveLength(2);
    expect(within(modal).getAllByText('mixed')).toHaveLength(2);
    expect(
      within(modal).getAllByText(
        (_, element) =>
          element?.tagName === 'P' &&
          (element.textContent === 'mixed: else' || element.textContent === '= mixed: else'),
      ),
    ).toHaveLength(2);
    // Plugged lines: the index numbers in place (bullish + bearish rows),
    // the first line led by the same plain "= " the result line uses.
    expect(within(modal).getAllByText('6234.5')).toHaveLength(2);
    expect(within(modal).getAllByText('5890.2')).toHaveLength(2);
    expect(
      within(modal).getByText(
        (_, element) =>
          element?.tagName === 'P' && element.textContent === '= bullish: 6234.5 > 5890.2 && 78 > 50',
      ),
    ).toBeInTheDocument();
    expect(within(modal).getByText('= bullish')).toBeInTheDocument();
  });

  it('folds word ingredients into the result line (trend)', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-trend'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Words: one line per outcome, tokens swapped for on-screen names
    // with an explicit sign.
    expect(
      within(modal).getByText(
        (_, element) =>
          element?.tagName === 'P' &&
          element.textContent ===
            'bullish: moving-average check = up && pivot structure = higher highs and lows',
      ),
    ).toBeInTheDocument();
    expect(
      within(modal).getByText(
        (_, element) => element?.tagName === 'P' && element.textContent === 'neutral: else',
      ),
    ).toBeInTheDocument();
    // No separate plugged section: the ingredients ride the result line.
    expect(
      within(modal).getByText(
        (_, element) =>
          element?.tagName === 'P' &&
          element.textContent ===
            '= neutral: moving-average check = mixed && pivot structure = sideways',
      ),
    ).toBeInTheDocument();
    expect(
      within(modal).queryByText(
        (_, element) => element?.tagName === 'P' && element.textContent === '= neutral',
      ),
    ).toBeNull();
  });

  it('folds mixed word/number ingredients into the result line (momentum)', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-momentum'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Words use the report's exact names and a sign for every ingredient.
    expect(
      within(modal).getByText(
        (_, element) =>
          element?.tagName === 'P' &&
          element.textContent === 'strong: 14d RSI > 55 && MACD histogram = rising && MACD line > 0',
      ),
    ).toBeInTheDocument();
    // Result: "= weak: 14d RSI = 38.89 && MACD histogram = falling && …".
    expect(
      within(modal).getByText(
        (_, element) =>
          element?.tagName === 'P' &&
          element.textContent ===
            '= weak: 14d RSI = 38.89 && MACD histogram = falling && MACD line = -1.02',
      ),
    ).toBeInTheDocument();
  });
});

// The exclamation mark's TITLE follows the value, its BODY follows the
// notes (owner request 2026-08-08). The two vary independently, so all
// four combinations are pinned here — the case that used to be wrong is
// "blank field that also carries a run note", which read "data notes".
describe('AltFieldNotes — title says why blank vs warnings', () => {
  const env = (value: unknown) => ({ name: 'closing price', explanation: 'e', value });

  const renderField = (value: unknown, notes: string[] | null) =>
    render(
      <UiLanguageProvider>
        <AltDimensions
          dimensions={[
            {
              dimension: 'technicals',
              kind: 'numeric',
              is_actionable: true,
              narrative: null,
              warnings: [],
              citations: [],
              payload: { price: { close: env(value) } },
              field_notes: notes ? { 'price.close': notes } : null,
            } as unknown as TieredDimension,
          ]}
        />
      </UiLanguageProvider>,
    );

  const openMark = () => {
    fireEvent.click(screen.getByTestId('alt-field-notes-close'));
    return within(screen.getByRole('dialog')).getByRole('heading');
  };

  it('a blank field with no note reads "why blank"', () => {
    renderField(null, null);
    expect(openMark()).toHaveTextContent(/why blank/);
  });

  it('a blank field that DOES carry a run note still reads "why blank"', () => {
    renderField(null, ['vendor returned nothing']);
    const heading = openMark();
    expect(heading).toHaveTextContent(/why blank/);
    expect(heading).not.toHaveTextContent(/warnings/);
    // The note is still what the body shows — only the title changed.
    expect(screen.getByTestId('alt-field-notes-modal').textContent).toMatch(
      /vendor returned nothing/,
    );
  });

  it('a field that KEPT its value reads "warnings"', () => {
    renderField(157.79, ['only 120 daily bars (<253)']);
    expect(openMark()).toHaveTextContent(/warnings/);
  });

  it('a published value with no note gets no mark at all', () => {
    renderField(157.79, null);
    expect(screen.queryByTestId('alt-field-notes-close')).toBeNull();
  });

  it('stacks the subject over the kind — always two lines', () => {
    // Owner request 2026-08-08: the header keeps the same shape in every
    // popup, so the kind never wraps up beside a short subject.
    renderField(null, null);
    const heading = openMark();
    const stack = heading.firstElementChild as HTMLElement;
    expect(stack.className).toContain('flex-col');
    const lines = Array.from(stack.children).map((el) => el.textContent);
    expect(lines).toEqual(['Closing price', 'why blank']);
  });
});
