import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TieredRunSummary } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltRunHistory, type AltRunHistoryProps } from '../AltRunHistory';

function makeRun(id: string, overrides: Partial<TieredRunSummary> = {}): TieredRunSummary {
  return {
    task_id: id,
    stock_code: 'AAPL',
    status: 'done',
    error: null,
    created_at: '2026-07-10T04:00:00',
    updated_at: null,
    direction: 'buy',
    shares: 41,
    tier: 1,
    capital: 100000,
    risk_fraction: 0.01,
    ...overrides,
  };
}

function renderHistory(overrides: Partial<AltRunHistoryProps> = {}) {
  const props: AltRunHistoryProps = {
    runs: [],
    expandedTaskId: null,
    expandedResult: null,
    expandedError: null,
    onToggle: vi.fn(),
    ...overrides,
  };
  render(
    <UiLanguageProvider>
      <AltRunHistory {...props} />
    </UiLanguageProvider>,
  );
  return props;
}

// Min boxes in filter order: capital, risk, reward, date (the shares
// filter was dropped 2026-08-16).
const minBoxes = () => screen.getAllByPlaceholderText(/^下限$|^Min$/);
const DATE_MIN = 3;

describe('AltRunHistory', () => {
  it('shows a queued row with its place in line and explains it when expanded', () => {
    renderHistory({
      runs: [makeRun('q1', { status: 'queued', queue_ahead: 2, direction: null, shares: null })],
      expandedTaskId: 'q1',
    });

    expect(screen.getByText(/排队中（前面 2 个）|Queued \(2 ahead\)/)).toBeInTheDocument();
    expect(screen.getByText(/轮到时会自动开始|starts by itself/)).toBeInTheDocument();
  });

  it('shows a queued row without a count when the backend sends none', () => {
    renderHistory({ runs: [makeRun('q1', { status: 'queued', direction: null })] });

    expect(screen.getByText(/^排队中$|^Queued$/)).toBeInTheDocument();
  });

  it('shows ticker, capital, risk, tier, outlook and date per row', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', tier: 3 }),
        makeRun('t2', {
          stock_code: 'NVDA',
          status: 'running',
          direction: null,
          shares: null,
          tier: null,
          capital: null,
          risk_fraction: null,
        }),
      ],
    });

    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText('100000')).toBeInTheDocument();
    expect(screen.getByText('1%')).toBeInTheDocument();
    expect(screen.getAllByText(/^\d{4}\/\d{2}\/\d{2}, \d{2}:\d{2}$/)).toHaveLength(2);
    expect(screen.getByText(/层级 3|Tier 3/)).toBeInTheDocument();
    // an old row without a stored outlook maps its buy verdict to bullish
    expect(screen.getByText(/看多|Bullish/)).toBeInTheDocument();
    // the shares column was dropped (owner request 2026-08-16)
    expect(screen.queryByText(/41/)).toBeNull();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText(/分析中|Running/)).toBeInTheDocument();
    // the running row has no capital/risk/reward/hold/tier yet — five
    // dashes, plus the done row's reward and hold dashes (stored
    // before those inputs were recorded).
    expect(screen.getAllByText('—')).toHaveLength(7);
    // the pager is always there, even when everything fits on one page
    expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument();
  });

  it('filters by capital and risk ranges', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', capital: 50000, risk_fraction: 0.005 }),
        makeRun('t2', { stock_code: 'NVDA', capital: 200000, risk_fraction: 0.02 }),
      ],
    });

    const capitalMin = minBoxes()[0];
    fireEvent.change(capitalMin, { target: { value: '100000' } });
    fireEvent.keyDown(capitalMin, { key: 'Enter' });
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /(Capital Min|本金下限): 100000/ }));

    const riskMax = screen.getAllByPlaceholderText(/^上限$|^Max$/)[1];
    fireEvent.change(riskMax, { target: { value: '1' } });
    fireEvent.keyDown(riskMax, { key: 'Enter' });
    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.queryByText('NVDA')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /(Risk Max|单笔风险上限): 1%/ })).toBeInTheDocument();
  });

  it('offers the tickers seen in history as a multi-pick dropdown filter', () => {
    renderHistory({
      runs: [makeRun('t1', { stock_code: 'MSFT' }), makeRun('t2', { stock_code: 'NVDA' })],
    });

    const tickerBox = screen.getByPlaceholderText(/筛选代码|Filter ticker/);
    fireEvent.focus(tickerBox);
    fireEvent.click(screen.getByRole('button', { name: 'NVDA' }));
    // close the still-open multi-pick dropdown so only rows remain
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();

    // multi-pick: adding the second ticker brings the other row back
    fireEvent.focus(tickerBox);
    fireEvent.click(screen.getByRole('button', { name: 'MSFT' }));
    fireEvent.mouseDown(document.body);
    expect(screen.getByText('MSFT')).toBeInTheDocument();

    // pills read Label: value and remove on click
    fireEvent.click(screen.getByRole('button', { name: /(Ticker|代码): NVDA/ }));
    fireEvent.click(screen.getByRole('button', { name: /(Ticker|代码): MSFT/ }));
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('clears an outlook filter by picking the same option again', () => {
    renderHistory({
      runs: [
        // a new run stores its outlook; an old run maps hold → neutral
        makeRun('t1', { stock_code: 'MSFT', direction: 'buy', outlook: 'bullish' }),
        makeRun('t2', { stock_code: 'NVDA', direction: 'hold' }),
      ],
    });

    fireEvent.focus(screen.getByPlaceholderText(/筛选展望|Filter outlook/));
    fireEvent.click(screen.getAllByText(/中性|Neutral/)[0]);
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();

    // the dropdown stays open for multi-pick filters — same option clears
    fireEvent.click(screen.getAllByText(/中性|Neutral/)[0]);
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('filters by tier from the dropdown', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', tier: 1 }),
        makeRun('t2', { stock_code: 'NVDA', tier: 3 }),
      ],
    });

    fireEvent.focus(screen.getByPlaceholderText(/筛选层级|Filter tier/));
    fireEvent.click(screen.getByRole('button', { name: '3' }));

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /(Tier|层级): 3/ })).toBeInTheDocument();
  });

  it('shows the max hold column and filters by it from the dropdown', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', hold_weeks: 2 }),
        // an old stored run without a recorded max hold shows a dash
        makeRun('t2', { stock_code: 'NVDA' }),
      ],
    });

    expect(screen.getByText(/^(2w|2 周)$/)).toBeInTheDocument();

    fireEvent.focus(screen.getByPlaceholderText(/筛选最长持有|Filter max hold/));
    fireEvent.click(screen.getByRole('button', { name: '2' }));

    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.queryByText('NVDA')).not.toBeInTheDocument();

    // the pill wears the same wording as the form's max-hold pill
    fireEvent.click(screen.getByRole('button', { name: /(Max hold|最长持有): 2/ }));
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('filters by a date range (wide bounds keep the row, a future start drops it)', () => {
    renderHistory({ runs: [makeRun('t1', { stock_code: 'MSFT' })] });
    const dateMin = minBoxes()[DATE_MIN];
    const dateMax = screen.getAllByPlaceholderText(/^上限$|^Max$/)[DATE_MIN];

    fireEvent.change(dateMin, { target: { value: '2026/07/01' } });
    fireEvent.keyDown(dateMin, { key: 'Enter' });
    fireEvent.change(dateMax, { target: { value: '2026/07/31' } });
    fireEvent.keyDown(dateMax, { key: 'Enter' });
    expect(screen.getByText('MSFT')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /2026\/07\/01/ }));
    fireEvent.change(dateMin, { target: { value: '2027/01/01' } });
    fireEvent.keyDown(dateMin, { key: 'Enter' });
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
  });

  it('rejects an invalid date instead of committing it', () => {
    renderHistory({ runs: [makeRun('t1', { stock_code: 'MSFT' })] });
    const dateMin = minBoxes()[DATE_MIN];

    fireEvent.change(dateMin, { target: { value: 'yesterday' } });
    fireEvent.keyDown(dateMin, { key: 'Enter' });

    expect(dateMin).toHaveValue('yesterday');
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('shows the column-name header row and filters by reward', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', reward_risk: 1.5 }),
        makeRun('t2', { stock_code: 'NVDA', reward_risk: 3 }),
      ],
    });
    expect(screen.getByTestId('alt-history-header')).toBeInTheDocument();
    expect(screen.getByText('1.5×')).toBeInTheDocument();
    expect(screen.getByText('3×')).toBeInTheDocument();

    const rewardMin = minBoxes()[2];
    fireEvent.change(rewardMin, { target: { value: '2' } });
    fireEvent.keyDown(rewardMin, { key: 'Enter' });

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /(Reward Min|盈亏比下限): 2×/ }),
    ).toBeInTheDocument();
  });

  it('pages the list 10 rows at a time with numbered page buttons', () => {
    renderHistory({
      runs: Array.from({ length: 12 }, (_, index) => makeRun(`t${index}`)),
    });

    expect(screen.getAllByText('AAPL')).toHaveLength(10);
    fireEvent.click(screen.getByRole('button', { name: '2' }));
    expect(screen.getAllByText('AAPL')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: /第一页|First page/ }));
    expect(screen.getAllByText('AAPL')).toHaveLength(10);
  });

  it('clicking a row asks to expand it; a failed expanded row shows its error', () => {
    const props = renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT' }),
        makeRun('t2', {
          stock_code: 'NVDA',
          status: 'failed',
          direction: null,
          shares: null,
          tier: null,
          error: 'LLM quota exhausted',
        }),
      ],
      expandedTaskId: 't2',
    });

    fireEvent.click(screen.getByRole('button', { name: /MSFT/ }));
    expect(props.onToggle).toHaveBeenCalledWith('t1');
    expect(screen.getByText('LLM quota exhausted')).toBeInTheDocument();
  });
});
