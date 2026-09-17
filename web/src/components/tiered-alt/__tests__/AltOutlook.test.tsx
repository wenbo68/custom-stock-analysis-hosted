import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type {
  TieredDebateDetail,
  TieredResult,
} from '../../../api/tiered';
import type { TieredPlanWarnings } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltResult } from '../AltResult';

// Outlook-redesign rendering: the conclusion block, the conditional plan
// display, the staleness note, the plan-review warnings row, and the
// v10/v11 vote trees.

const LEVELS = { entry: 96, stop_loss: 90, take_profit: 108 };

function makeDimension(name: string): TieredResult['dimensions'][number] {
  return {
    dimension: name,
    kind: 'numeric',
    is_actionable: true,
    payload: { close: 100 },
    narrative: null,
    warnings: [],
    citations: [],
  };
}

// A full 13-entry card: one flagged, one n/a, the rest ok.
function makeOutlookResult(overrides: Partial<TieredResult> = {}): TieredResult {
  return {
    symbol: 'AAPL',
    market: 'us',
    tier: 1,
    direction: 'buy',
    score: 72,
    confidence: null,
    levels: LEVELS,
    levels_detail: null,
    narrative: null,
    warnings: [],
    dimensions: ['technicals', 'fundamentals', 'macro_econ', 'positioning'].map(makeDimension),
    depth: 1,
    outlook: 'bullish',
    action: 'enter',
    earnings: null,
    ...overrides,
  };
}

// A v10 weighted vote tree: T1 rated 3 by both authors (weight 3), S1
// single-author weight 2.5 (author 3 + checker 2). Final pool: bullish
// weight 3 of 5.5 total → 10 × 3 / 5.5 = 5.45.
function makeWeightedDebate(): TieredDebateDetail {
  return {
    format: 10,
    items: [
      {
        id: 'T1',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The 14-day RSI (71.20) is above 70.',
        links: [{ ref: 'technicals.rsi_14', value: '71.20' }],
        struck: false,
        problems: [],
        authors: 2,
        author_weights: [3, 3],
        weight: 3,
        votes: [],
        response: null,
        judge: null,
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'S1',
        dimension: 'positioning',
        direction: 'bearish',
        claim: 'The deal is not closed yet.',
        links: [{ ref: 'citation:2', value: null }],
        struck: false,
        problems: [],
        authors: 1,
        author_weights: [3],
        weight: 2.5,
        votes: [
          {
            role: 'checker',
            verdict: 'valid',
            reason: 'Supported by the source.',
            links: [{ ref: 'citation:2', value: null }],
            weight: 2,
          },
        ],
        response: null,
        judge: null,
        final_status: 'counted',
        exclusion_reason: null,
      },
    ],
    verdict: {
      direction: 'hold',
      summary: 'Weighted to hold.',
      final_score: 5.45,
      initial_score: 5.45,
      pools: {
        initial: {
          dimensions: {
            technicals: {
              bullish: 1, bearish: 0, total: 1,
              bullish_weight: 3, bearish_weight: 0, total_weight: 3,
            },
            positioning: {
              bullish: 0, bearish: 1, total: 1,
              bullish_weight: 0, bearish_weight: 3, total_weight: 3,
            },
          },
          bullish: 1, bearish: 1, total: 2,
          bullish_weight: 3, bearish_weight: 3, total_weight: 6,
          score: 5.0,
        },
        final: {
          dimensions: {
            technicals: {
              bullish: 1, bearish: 0, total: 1,
              bullish_weight: 3, bearish_weight: 0, total_weight: 3,
            },
            positioning: {
              bullish: 0, bearish: 1, total: 1,
              bullish_weight: 0, bearish_weight: 2.5, total_weight: 2.5,
            },
          },
          bullish: 1, bearish: 1, total: 2,
          bullish_weight: 3, bearish_weight: 2.5, total_weight: 5.5,
          score: 5.45,
        },
      },
    },
    warnings: [],
  };
}

// A tier-2 section wrapping the given stored detail.
function makeTier2(detail: TieredDebateDetail): NonNullable<TieredResult['tier2']> {
  return {
    tier: 2,
    direction: 'hold',
    confidence: null,
    score: null,
    levels: LEVELS,
    narrative: 'Weighted to hold.',
    warnings: [],
    debate_detail: detail,
  };
}

// A v11 tree: T1 both-listed (lister ratings 4 and 5 → median 4.5); S1
// single-author (lister 2 rated 3) checked invalid (2) and ruled valid
// by the decider (2) → median 2. Every rating carries its reason.
function makeRichDebate(): TieredDebateDetail {
  const detail = makeWeightedDebate();
  return {
    ...detail,
    format: 11,
    items: [
      {
        ...detail.items![0],
        author_weights: [4, 5],
        author_votes: [
          { lister: 1, weight: 4, weight_reason: 'Strong but not decisive.' },
          { lister: 2, weight: 5, weight_reason: 'Momentum drives the thesis.' },
        ],
        weight: 4.5,
      },
      {
        ...detail.items![1],
        author_weights: [3],
        author_votes: [
          { lister: 2, weight: 3, weight_reason: 'Sentiment is soft evidence.' },
        ],
        weight: 2,
        votes: [
          {
            role: 'checker',
            verdict: 'invalid',
            reason: 'The deal risk is already priced in.',
            links: [],
            weight: 2,
            weight_reason: 'A minor point either way.',
          },
          {
            role: 'decider',
            verdict: 'valid',
            reason: 'The objection is speculation.',
            links: [],
            weight: 2,
            weight_reason: 'Still a side note.',
          },
        ],
      },
    ],
  };
}

function renderResult(result: TieredResult, runDate?: Date | null) {
  render(
    <MemoryRouter>
      <UiLanguageProvider>
        <AltResult result={result} taskId="task-9" runDate={runDate} />
      </UiLanguageProvider>
    </MemoryRouter>,
  );
}

describe('AltResult outlook conclusion', () => {
  it('leads with outlook and action; enter keeps the full levels table', () => {
    renderResult(makeOutlookResult());
    const conclusion = screen.getByTestId('alt-conclusion');
    expect(conclusion).toHaveTextContent(/(展望|Outlook): (看多|Bullish)/);
    expect(conclusion).toHaveTextContent(/(操作|Action): (现在买入|Buy now)/);
    expect(screen.getByTestId('alt-levels-table')).toBeInTheDocument();
  });

  it('enter_later says buy later and keeps the full levels table', () => {
    renderResult(makeOutlookResult({ action: 'enter_later' }));
    const conclusion = screen.getByTestId('alt-conclusion');
    expect(conclusion).toHaveTextContent(/(操作|Action): (稍后再买|Buy later)/);
    expect(screen.getByTestId('alt-levels-table')).toBeInTheDocument();
  });

  it('enter_later shows the current reward-to-risk, clickable for its arithmetic', () => {
    // The plan review's numbers win over the raw levels.
    const planWarnings: TieredPlanWarnings = {
      entry: [],
      stop_loss: [],
      take_profit: [
        {
          id: 'reward_below_goal',
          values: { entry: 330, stop_loss: 314.9, take_profit: 334.7, ratio: 0.3112, goal: 2 },
        },
      ],
      shares: [],
    };
    renderResult(makeOutlookResult({ action: 'enter_later', plan_warnings: planWarnings }));
    const reason = screen.getByTestId('alt-action-reason');
    expect(reason).toHaveTextContent(/\((当前盈亏比为|current reward-to-risk ratio is) 0\.31\)/);
    fireEvent.click(within(reason).getByRole('button', { name: '0.31' }));
    // The formula popup: words, this run's prices, the result.
    expect(screen.getByText('= 0.31')).toBeInTheDocument();
    expect(screen.getAllByText('334.70').length).toBeGreaterThan(0);
  });

  it('enter_later without a plan review computes the ratio from the levels', () => {
    // LEVELS: (108 − 96) ÷ (96 − 90) = 2
    renderResult(makeOutlookResult({ action: 'enter_later', plan_warnings: null }));
    expect(screen.getByTestId('alt-action-reason')).toHaveTextContent(/ 2\)/);
  });

  it('enter shows no reason suffix', () => {
    renderResult(makeOutlookResult({ action: 'enter' }));
    expect(screen.queryByTestId('alt-action-reason')).not.toBeInTheDocument();
  });

  it('no_trade shows no trade-plan section at all', () => {
    renderResult(
      makeOutlookResult({
        outlook: 'neutral',
        action: 'no_trade',
        warnings: [
          'trend warning: close 303.42 is at or below the 50-day average ' +
            '309.52 (downtrend) — a pullback buy against the trend carries ' +
            'extra downside risk',
        ],
      }),
    );
    // A non-bullish outlook removes the whole plan section (owner
    // decision 2026-08-05) — no card, no levels, no notes mark.
    expect(screen.queryByTestId('alt-plan')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-levels-table')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-structural-stop')).not.toBeInTheDocument();
  });

  it('plan warnings stay off the conclusion card and vanish with the plan', () => {
    // Owner report 2026-08-09: a bearish run showed plan-level and
    // reward warnings outside the (hidden) plan card. Plan-flavored
    // notes now live on the plan card only; the conclusion card carries
    // the analysis/data notes (the preliminary card is gone).
    renderResult(
      makeOutlookResult({
        outlook: 'bearish',
        action: 'no_trade',
        direction: 'sell',
        warnings: [
          'no usable ATR — no volatility stop, and no target without a stop',
          "reward below goal: overhead resistance at 316.94 caps the plan's " +
            'reward-to-risk at 0.28, below your 2× goal',
          'no collected evidence to vote on — no outlook (re-run)',
        ],
      }),
    );
    expect(screen.queryByTestId('alt-plan')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier1')).not.toBeInTheDocument();
    const conclusion = screen.getByTestId('alt-conclusion');
    fireEvent.click(within(conclusion).getByTestId('alt-notes-button'));
    const dialog = screen.getByRole('dialog');
    // The analysis note stays; both plan notes are gone with the plan.
    expect(dialog).toHaveTextContent(/Verdict|结论/);
    expect(dialog).not.toHaveTextContent(/0\.28/);
    expect(within(dialog).getAllByRole('listitem')).toHaveLength(1);
  });

  it('a bearish run with only plan warnings shows no notes mark at all', () => {
    renderResult(
      makeOutlookResult({
        outlook: 'bearish',
        action: 'no_trade',
        direction: 'sell',
        warnings: ['no usable ATR — no volatility stop, and no target without a stop'],
      }),
    );
    const conclusion = screen.getByTestId('alt-conclusion');
    expect(within(conclusion).queryByTestId('alt-notes-button')).not.toBeInTheDocument();
  });

  it('an unknown outlook (failed run) shows no trade-plan section either', () => {
    renderResult(makeOutlookResult({ outlook: 'unknown', action: 'unknown' }));
    expect(screen.queryByTestId('alt-plan')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-levels-table')).not.toBeInTheDocument();
  });

  it('a stopped run shows only the outlook and the data cards', () => {
    // Staleness gate (2026-08-08): the outlook word IS the whole story —
    // no action fact, no analysis card, no plan, no message text.
    renderResult(makeOutlookResult({ outlook: 'stopped', action: 'unknown' }));
    const conclusion = screen.getByTestId('alt-conclusion');
    expect(conclusion).toHaveTextContent(/(已停止|Stopped)/);
    expect(conclusion).not.toHaveTextContent(/(操作|Action)/);
    expect(screen.queryByTestId('alt-plan')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-levels-table')).not.toBeInTheDocument();
    // No preliminary/deep analysis card renders for a stopped run.
    expect(screen.queryByText(/(初步分析|Preliminary analysis)/)).not.toBeInTheDocument();
  });

  it('keeps the max hold time off the conclusion (it lives on the run row)', () => {
    // Owner request 2026-08-09: the conclusion is outlook + action only;
    // the max hold shows as its own run-history column instead.
    renderResult(makeOutlookResult({ hold_weeks: 3 }));
    const conclusion = screen.getByTestId('alt-conclusion');
    expect(conclusion).not.toHaveTextContent(/(最长持有|Max hold)/);
  });

  it('a bearish no_trade hides the plan and sizes nothing', () => {
    renderResult(
      makeOutlookResult({
        outlook: 'bearish',
        action: 'no_trade',
        sizing: {
          enabled: true,
          shares: null,
          position_value: null,
          risk_amount: null,
          loss_per_share: null,
          lot_size: 1,
          reason_code: 'not_a_buy',
          refusal_reason: null,
          notes: [],
          inputs: {
            capital: 100000,
            risk_fraction: 0.01,
            entry: null,
            stop_loss: null,
          },
        },
      }),
    );
    expect(screen.queryByTestId('alt-plan')).not.toBeInTheDocument();
    // The shares-computation card is retired (2026-07-22) — the action
    // line already says the whole holding goes.
    expect(screen.queryByTestId('alt-sell-formula')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-shares-computation')).not.toBeInTheDocument();
  });

  it('never shows an earnings warning in the conclusion (moved to fundamentals)', () => {
    renderResult(
      makeOutlookResult({
        earnings: {
          next_date: '2026-07-24',
          days_until: 4,
          warning_days: 7,
          is_near: true,
          note: null,
        },
      }),
    );
    expect(screen.queryByTestId('alt-earnings-warning')).not.toBeInTheDocument();
  });

  it('notes a report from a previous trading day; a same-day run has no note', () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    renderResult(makeOutlookResult(), yesterday);
    expect(screen.getByTestId('alt-stale-note')).toHaveTextContent(/重跑|re-run/);
  });

  it('a same-day run has no staleness note', () => {
    renderResult(makeOutlookResult(), new Date());
    expect(screen.queryByTestId('alt-stale-note')).not.toBeInTheDocument();
  });

});

describe('AltResult plan-card data notes vs the warnings row', () => {
  it('drops notes the structured warnings row already carries, keeps the rest', () => {
    const staleReward =
      "reward below goal: overhead resistance at 106 caps the plan's " +
      'reward-to-risk at 1.67, below your 2× goal';
    const trendNote =
      'trend warning: close 100 is at or below the 60-day average 102 ' +
      '(downtrend) — a pullback buy against the trend carries extra downside risk';
    renderResult(
      makeOutlookResult({
        warnings: [staleReward, trendNote, 'no usable entry price — cannot place a stop'],
        plan_warnings: {
          entry: [{ id: 'downtrend', values: { close: 100, sma_60: 102 } }],
          stop_loss: [],
          take_profit: [
            {
              id: 'reward_below_goal',
              values: { entry: 96, stop_loss: 90, take_profit: 98, ratio: 0.33, goal: 2 },
            },
          ],
          shares: [],
        },
      }),
    );
    fireEvent.click(within(screen.getByTestId('alt-plan')).getByTestId('alt-notes-button'));
    const dialog = screen.getByRole('dialog');
    // The row's facts (reward shortfall, downtrend) don't repeat as notes —
    // the row recomputes them from the final levels, so the note copy is stale.
    expect(dialog).not.toHaveTextContent(/1\.67/);
    expect(dialog).not.toHaveTextContent(/downtrend|逆势低吸/);
    // Unrelated notes stay.
    expect(dialog).toHaveTextContent(/price levels|价格参考位/i);
  });
});

describe('AltResult weighted vote formula', () => {
  function renderWeighted() {
    const result = makeOutlookResult({
      depth: 2,
      tier2: {
        tier: 2,
        direction: 'hold',
        confidence: null,
        score: null,
        levels: LEVELS,
        narrative: 'Weighted to hold.',
        warnings: [],
        debate_detail: makeWeightedDebate(),
      },
    });
    renderResult(result);
  }

  it('renders a structured summary as the fixed outline instead of the paragraph', () => {
    const result = makeOutlookResult({
      depth: 2,
      tier2: {
        tier: 2,
        direction: 'hold',
        confidence: null,
        score: null,
        levels: LEVELS,
        narrative: 'Summary: flat text fallback.',
        warnings: [],
        debate_detail: {
          ...makeWeightedDebate(),
          verdict: {
            ...makeWeightedDebate().verdict!,
            summary_structure: {
              summary: [{ text: 'The outlook is neutral.', links: [], children: [] }],
              technicals: [
                {
                  text: 'Momentum is mixed.',
                  links: [],
                  children: [{ text: 'RSI sits mid-range.', links: [] }],
                },
              ],
              fundamentals: [],
              positioning: [
                {
                  text: 'Short interest is low at 3.10% of float.',
                  links: [
                    {
                      ref: 'positioning.short_interest.short_pct_of_float',
                      value: '3.10',
                    },
                  ],
                  children: [],
                },
              ],
              macro_econ: [],
            },
          },
        },
      },
    });
    renderResult(result);
    const outline = screen.getByTestId('alt-summary-outline');
    // Groups render in the fixed order; empty groups are skipped.
    const groupLabels = within(outline)
      .getAllByRole('listitem')
      .map((item) => item.textContent ?? '');
    expect(outline).toHaveTextContent(/Summary|总结/);
    expect(groupLabels.join(' ')).toContain('The outlook is neutral.');
    expect(outline).toHaveTextContent('RSI sits mid-range.');
    expect(outline).not.toHaveTextContent('flat text fallback');
    // The flat paragraph does not render alongside the outline.
    expect(screen.queryByText('Summary: flat text fallback.')).not.toBeInTheDocument();
    // A cited value renders as a jump link — the same claim contract as
    // the evidence bullets in the details fold.
    const valueLink = within(outline).getByRole('button', { name: '3.10' });
    expect(valueLink.className).toContain('text-blue-300');
  });

  it('the header score opens the weighted formula in a modal', () => {
    renderWeighted();
    // The arithmetic no longer sits inside the transcript fold.
    expect(screen.queryByTestId('alt-tree-scores')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('alt-debate-score'));
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent(/看多权重和|bullish weight/);
    expect(screen.getByTestId('alt-tree-final-formula')).toHaveTextContent('= 10 × 3 / 5.5');
    expect(scores).toHaveTextContent('= 5.45');
  });
});

describe('AltResult deep-analysis layout', () => {
  it('hides the tier-1 card on a new deep run and shows the trade plan instead', () => {
    renderResult(
      makeOutlookResult({ depth: 2, tier2: makeTier2(makeWeightedDebate()) }),
    );
    expect(screen.queryByTestId('alt-tier1')).not.toBeInTheDocument();
    expect(
      screen.queryByText(/层级 1：初步分析|Tier 1: preliminary analysis/),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/交易计划|Trade plan/)).toBeInTheDocument();
    // action = enter → the plan block carries the full levels table.
    expect(
      within(screen.getByTestId('alt-plan')).getByTestId('alt-levels-table'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('alt-tier2')).toBeInTheDocument();
  });
});

describe('AltResult v11 detail tree', () => {
  function renderRich() {
    renderResult(makeOutlookResult({ depth: 2, tier2: makeTier2(makeRichDebate()) }));
  }

  it('shows the median as a bare number whose modal lists every score', () => {
    renderRich();
    const badge = screen.getByTestId('alt-tree-weight-T1');
    expect(badge).toHaveTextContent(/^4\.5$/);
    fireEvent.click(badge);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/显著性评分|Significance Score/);
    expect(dialog).toHaveTextContent(/各方评分：4 \| 5|Scores: 4 \| 5/);
    expect(dialog).toHaveTextContent(/中位数：4\.5|Median: 4\.5/);
  });

  it('shows one check per lister; its modal carries validity, score and reason', () => {
    renderRich();
    const marks = within(screen.getByTestId('alt-tree-item-T1')).getAllByRole('button', {
      name: '✓',
    });
    expect(marks).toHaveLength(2); // both listers, no longer hidden
    fireEvent.click(marks[0]);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/列出者 1|Lister 1/);
    expect(dialog).toHaveTextContent(/判定：有效|verdict: valid/);
    expect(dialog).toHaveTextContent('The 14-day RSI (71.20) is above 70.');
    expect(dialog).toHaveTextContent(/评分：4|score: 4/);
    expect(dialog).toHaveTextContent('Strong but not decisive.');
  });

  it('a checker ✗ modal shows the objection, then the score and its reason', () => {
    renderRich();
    fireEvent.click(
      within(screen.getByTestId('alt-tree-item-S1')).getByRole('button', { name: '✗' }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/核查员 1|Checker 1/);
    expect(dialog).toHaveTextContent(/判定：无效|verdict: invalid/);
    expect(dialog).toHaveTextContent('The deal risk is already priced in.');
    expect(dialog).toHaveTextContent(/评分：2|score: 2/);
    expect(dialog).toHaveTextContent('A minor point either way.');
  });

  it('the second vote is Checker 2 — never a decider word', () => {
    renderRich();
    const marks = within(screen.getByTestId('alt-tree-item-S1')).getAllByRole('button', {
      name: '✓',
    });
    // author mark first, then the deciding vote's ✓.
    fireEvent.click(marks[marks.length - 1]);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/核查员 2|Checker 2/);
    expect(dialog).not.toHaveTextContent(/裁决者|Decider/);
  });

  it('the how-it-works list explains the 1-5 scale', () => {
    renderRich();
    expect(screen.getByTestId('alt-tree-explain')).toHaveTextContent(/1-5/);
  });
});

describe('AltResult trade-plan warnings row and shares column', () => {
  const sharesDetail = {
    base: 166,
    formula: 'capital × risk_fraction ÷ (entry − stop_loss)',
    inputs: { capital: 100000, risk_fraction: 0.01, entry: 96, stop_loss: 90 },
    adjusted: 50,
    reasons: [{ check: 'liquidity', text: 'The planned order is far above the 5% liquidity limit.' }],
    evidence: [],
    rejection: null,
    final: 50,
  };
  const levelDetail = (base: number) => ({
    base,
    formula: 'f',
    inputs: {},
    adjusted: null,
    reason: null,
    evidence: [],
    rejection: null,
    final: base,
  });
  const planWarnings: TieredPlanWarnings = {
    entry: [],
    stop_loss: [
      {
        id: 'gap_atr',
        values: { atr_open: 87, atr_loss: 450, atr_extra: 150, loss_at_stop: 300 },
      },
      {
        id: 'gap_worst',
        values: {
          worst_day_1y: -0.1, worst_open: 86.4, worst_loss: 480,
          worst_extra: 180, loss_at_stop: 300,
        },
      },
    ],
    take_profit: [{ id: 'reward_below_goal', values: { ratio: 1.67, goal: 2 } }],
    shares: [],
  };

  function renderPlan() {
    renderResult(
      makeOutlookResult({
        plan_warnings: planWarnings,
        levels_detail: {
          levels: {
            entry: levelDetail(96),
            stop_loss: levelDetail(90),
            take_profit: levelDetail(108),
            shares: sharesDetail,
          },
          warnings: [],
        },
      }),
    );
  }

  it('renders none / counts per column; the count lists the warnings', () => {
    renderPlan();
    expect(screen.getByTestId('alt-plan-warnings-entry')).toHaveTextContent(/无|none/);
    const stop = screen.getByTestId('alt-plan-warnings-stop_loss');
    expect(stop).toHaveTextContent('2');
    fireEvent.click(stop);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('87'); // forced-sell price
    expect(dialog).toHaveTextContent('450'); // total loss
    expect(dialog).toHaveTextContent('150'); // extra vs planned
    expect(dialog).toHaveTextContent('86.4'); // worst-day open
  });

  it('the target column carries the reward-below-goal warning', () => {
    renderPlan();
    const target = screen.getByTestId('alt-plan-warnings-take_profit');
    expect(target).toHaveTextContent('1');
    fireEvent.click(target);
    expect(screen.getByRole('dialog')).toHaveTextContent('1.67');
  });

  it('the shares column shows computed and AI-adjusted counts', () => {
    renderPlan();
    expect(screen.getByTestId('alt-level-computed-shares')).toHaveTextContent('166');
    const adjusted = screen.getByTestId('alt-level-adjusted-shares');
    expect(adjusted).toHaveTextContent('50');
    fireEvent.click(adjusted);
    expect(screen.getByRole('dialog')).toHaveTextContent(/liquidity limit/);
  });

  it('the computed shares modal shows the arithmetic receipt', () => {
    renderPlan();
    fireEvent.click(screen.getByTestId('alt-level-computed-shares'));
    const receipt = screen.getByTestId('alt-shares-receipt');
    expect(receipt).toHaveTextContent('100000');
    expect(receipt).toHaveTextContent('1%');
    expect(receipt).toHaveTextContent('166');
  });
});
