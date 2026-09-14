import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type {
  TieredDebateDetail,
  TieredLevelsDetail,
  TieredResult,
  TieredRiskDetail,
  TieredTierSection,
} from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltResult } from '../AltResult';

const LEVELS = { entry: 96, secondary_entry: 94, stop_loss: 90, take_profit: 108 };

// Consistent with LEVELS: entry and target were adjusted by the AI, the
// backup entry and the stop kept their computed bases.
const LEVELS_DETAIL: TieredLevelsDetail = {
  levels: {
    entry: {
      // The stored prose phrase — the UI must expand it into the actual
      // support values, never show the words.
      base: 95,
      formula: 'min(close, max(support candidates))',
      inputs: { close: 100, sma_20: 95, swing_low_20: 92 },
      adjusted: 96,
      reason: 'Momentum supports paying up a little.',
      evidence: ['technicals.sma_20'],
      rejection: null,
      final: 96,
    },
    stop_loss: {
      base: 90,
      formula: 'ideal_entry − 2 × atr_14',
      inputs: { ideal_entry: 95, atr_14: 2.5, multiplier: 2 },
      adjusted: null,
      reason: null,
      evidence: [],
      rejection: null,
      final: 90,
    },
    take_profit: {
      // Resistance-capped shape: the prose tail must expand into the
      // actual resistance values.
      base: 105,
      formula: 'min(ideal_entry + 2 × (ideal_entry − stop_loss), nearest overhead resistance)',
      inputs: {
        ideal_entry: 95, stop_loss: 90, geometric_target: 105,
        swing_high_20: 105, high_52w: 110,
      },
      adjusted: 108,
      reason: 'Growth supports a higher target.',
      evidence: [],
      rejection: null,
      final: 108,
    },
  },
  warnings: [],
};

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

function makeSection(tier: number, direction: TieredTierSection['direction']): TieredTierSection {
  return {
    tier,
    direction,
    confidence: null,
    score: null,
    levels: LEVELS,
    narrative: null,
    warnings: [],
  };
}

// Shaped like an old stored depth-1 run: none of the v2 optional blocks.
function makeV1Result(): TieredResult {
  return {
    symbol: 'AAPL',
    direction: 'buy',
    score: 72,
    confidence: null,
    levels: LEVELS,
    levels_detail: null,
    narrative: 'Tier-1 narrative.',
    warnings: [],
    dimensions: ['technicals', 'fundamentals', 'macro_econ', 'sentiment'].map(makeDimension),
  } as unknown as TieredResult;
}

function makeDeepResult(): TieredResult {
  return {
    ...makeV1Result(),
    levels_detail: LEVELS_DETAIL,
    depth: 3,
    final: { tier: 3, direction: 'hold', confidence: null, levels: LEVELS },
    tier2: { ...makeSection(2, 'hold'), debate_detail: { turns: [], verdict: null, warnings: [] } },
    tier3: {
      ...makeSection(3, 'hold'),
      risk_detail: {
        takes: [],
        verdict: {
          stance: 'hold',
          size_multiplier: 0.5,
          confidence: 0.7,
          stop_advice: 'keep',
          tightened_stop: null,
          summary: 'Risk summary.',
          key_risks: [],
        },
        warnings: [],
      },
    },
    sizing: {
      enabled: true,
      shares: 83,
      shares_before_multiplier: 166,
      risk_multiplier: 0.5,
      position_value: 7968,
      risk_amount: 498,
      loss_per_share: 6,
      lot_size: 1,
      reason_code: null,
      refusal_reason: null,
      notes: [],
      inputs: {
        capital: 100000,
        risk_fraction: 0.01,
        entry: 96,
        stop_loss: 90,
      },
    },
  };
}

// A v3 scored-debate audit trail: debater turns carry their own scores
// and citations; the verdict carries the judge grades and the computed
// final number.
function makeScoredDebate(): TieredDebateDetail {
  return {
    turns: [
      {
        role: 'bull',
        round: 1,
        argument: 'Bull argument.',
        bullishness: 8,
        citations: ['technicals.close'],
      },
      { role: 'bear', round: 1, argument: 'Bear argument.', bullishness: 3, citations: [] },
    ],
    verdict: {
      direction: 'hold',
      summary: 'Weighted to hold.',
      bull_summary: 'Corrected bull case.',
      bear_summary: 'Corrected bear case.',
      final_score: 6.095,
      final_score_rounded: 6,
      scoring: {
        bull: {
          bullishness: 8,
          citation_validity: 4,
          knowledge_validity: 5,
          logical_validity: 4,
          weight: 0.8667,
          notes: 'Solid case.',
        },
        bear: {
          bullishness: 3,
          citation_validity: 2,
          knowledge_validity: 3,
          logical_validity: 3,
          weight: 0.5333,
          notes: 'Weaker case.',
        },
      },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
    },
    warnings: [],
  };
}

// A v4 threaded audit trail: argue/attack/respond turns with kinds, the
// position score only on response turns, and axis grades that carry the
// judge's quote + why below 5 (null at 5/5 → N/A).
function makeThreadedDebate(): TieredDebateDetail {
  return {
    turns: [
      {
        role: 'bull',
        kind: 'argument',
        argument: 'Momentum is strong.',
        citations: ['technicals.close'],
      },
      { role: 'bear', kind: 'attack', argument: 'The bull overstates momentum.', citations: [] },
      {
        role: 'bull',
        kind: 'response',
        argument: 'I stand by the momentum case.',
        position_score: 8,
        citations: [],
      },
      { role: 'bear', kind: 'argument', argument: 'Valuation is stretched.', citations: [] },
      { role: 'bull', kind: 'attack', argument: 'The bear misreads valuation.', citations: [] },
      {
        role: 'bear',
        kind: 'response',
        argument: 'I concede part of it.',
        position_score: 3,
        citations: [],
      },
    ],
    verdict: {
      direction: 'hold',
      summary: 'Weighted to hold.',
      bull_summary: 'Corrected bull case.',
      bear_summary: 'Corrected bear case.',
      final_score: 6.095,
      final_score_rounded: 6,
      scoring: {
        bull: {
          position_score: 8,
          citation_validity: {
            score: 4,
            quote: 'Momentum is strong.',
            why: 'Overstated from one indicator.',
          },
          knowledge_validity: { score: 5, quote: null, why: null },
          logical_validity: { score: 4, quote: 'I stand by the momentum case.', why: 'No new support.' },
          weight: 0.8667,
        },
        bear: {
          position_score: 3,
          citation_validity: { score: 2, quote: 'Valuation is stretched.', why: 'The cited ratio does not show that.' },
          knowledge_validity: { score: 3, quote: 'I concede part of it.', why: 'Partial concession left gaps.' },
          logical_validity: { score: 3, quote: 'The bull overstates momentum.', why: 'Attack gave no specifics.' },
          weight: 0.5333,
        },
      },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
    },
    warnings: [],
  };
}


// A v5 tree audit trail: defender/attacker/judge over one evidence pool.
// Ledger: T1 kept 1/1, T2 attacked+rejected but the judge upholds the
// attack → 0/1, S1 kept 1/1, addition S2 accepted+real → 1/1 → weight
// 3/4 = 0.75; initial 8, adjusted 7 → final 5 + 0.75 × 2 = 6.50 → buy.
function makeTreeDebate(): TieredDebateDetail {
  const valid = { verdict: 'valid' as const, reason: null, citations: [] };
  return {
    format: 5,
    turns: [],
    items: [
      {
        id: 'T1',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'RSI shows strong momentum.',
        citations: ['technicals.rsi_14'],
        added_by_attacker: false,
        attacker_checks: { citation: valid, logic: valid },
        responses: { citation: null, logic: null },
        response: null,
        judge: {
          citation: { kind: 'reason_check', verdict: 'valid', reason: null, citations: [] },
          logic: { kind: 'reason_check', verdict: 'valid', reason: null, citations: [] },
        },
        count: { numerator: 1, denominator: 1 },
        outcome: 'valid',
      },
      {
        id: 'T2',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The price trend is up.',
        citations: ['technicals.close'],
        added_by_attacker: false,
        attacker_checks: {
          citation: valid,
          logic: {
            verdict: 'invalid',
            reason: 'One price point is not a trend.',
            citations: ['technicals.close'],
          },
        },
        responses: {
          citation: null,
          logic: {
            accepted: false,
            citation_check: valid,
            logic_check: {
              verdict: 'invalid',
              reason: 'The attack ignores the moving averages.',
              citations: ['technicals.sma_20'],
            },
          },
        },
        response: null,
        judge: {
          citation: { kind: 'reason_check', verdict: 'valid', reason: null, citations: [] },
          logic: {
            kind: 'attack_ruling',
            verdict: 'attack_right',
            reason: 'The averages do not rescue a single print.',
            citations: [],
          },
        },
        count: { numerator: 0, denominator: 1 },
        outcome: 'invalid',
      },
      {
        id: 'S1',
        dimension: 'sentiment',
        direction: 'bullish',
        claim: 'A big deal was announced.',
        citations: ['citation:1'],
        added_by_attacker: false,
        attacker_checks: { citation: valid, logic: valid },
        responses: { citation: null, logic: null },
        response: null,
        judge: {
          citation: { kind: 'reason_check', verdict: 'valid', reason: null, citations: [] },
          logic: { kind: 'reason_check', verdict: 'valid', reason: null, citations: [] },
        },
        count: { numerator: 1, denominator: 1 },
        outcome: 'valid',
      },
      {
        id: 'S2',
        dimension: 'sentiment',
        direction: 'bearish',
        claim: 'The deal is not closed yet.',
        citations: ['citation:1'],
        added_by_attacker: true,
        attacker_checks: null,
        responses: { citation: null, logic: null },
        response: { accepted: true, citation_check: valid, logic_check: valid },
        judge: { kind: 'addition_ruling', verdict: 'real', reason: 'Genuinely missed.', citations: [] },
        count: { numerator: 1, denominator: 1 },
        outcome: 'valid',
      },
    ],
    verdict: {
      direction: 'buy',
      summary: 'The surviving evidence leans bullish.',
      final_score: 6.5,
      final_score_rounded: 7,
      initial_score: 8,
      adjusted_score: 7,
      adjusted_kept: false,
      weight: { numerator: 3, denominator: 4, value: 0.75 },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
      bull_summary: null,
      bear_summary: null,
      scoring: null,
    },
    warnings: [],
  };
}


// A v6 tree audit trail: inline value-checked links, unified judge check
// pairs, deterministic pool scores. T1 counted; T2 excluded by the code's
// value check (claimed 999 vs the report's 100); addition S1 (bearish)
// counted. Pools: initial tech-only 10.00; adjusted/final (10 + 0)/2 = 5.00.
function makeTreeDebateV6(): TieredDebateDetail {
  const valid = { verdict: 'valid' as const, reason: null, citations: [] };
  const judgeValidPair = {
    citation: { kind: 'reason_check' as const, verdict: 'valid' as const, reason: null, citations: [] },
    logic: { kind: 'reason_check' as const, verdict: 'valid' as const, reason: null, citations: [] },
  };
  return {
    format: 6,
    turns: [],
    items: [
      {
        id: 'T1',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The 14-day RSI (71.2) is above 70.',
        links: [{ text: '14-day RSI', ref: 'technicals.rsi_14', value: 71.2 }],
        value_check: { verdict: 'valid', problems: [] },
        added_by_attacker: false,
        attacker_checks: { citation: valid, logic: valid },
        responses: { citation: null, logic: null },
        response: null,
        judge: judgeValidPair,
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'T2',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The closing price (999.0) holds above support.',
        links: [{ text: 'closing price', ref: 'technicals.close', value: 999.0, mismatch: true }],
        value_check: {
          verdict: 'invalid',
          problems: ["claimed 999.0 for technicals.close, the report says 100.0"],
        },
        added_by_attacker: false,
        attacker_checks: { citation: valid, logic: valid },
        responses: { citation: null, logic: null },
        response: null,
        judge: judgeValidPair,
        final_status: 'excluded',
        exclusion_reason: 'value_mismatch',
      },
      {
        id: 'S1',
        dimension: 'sentiment',
        direction: 'bearish',
        claim: 'The deal is not closed yet.',
        links: [{ text: 'deal', ref: 'citation:1', value: null }],
        value_check: { verdict: 'valid', problems: [] },
        added_by_attacker: true,
        attacker_checks: null,
        responses: { citation: null, logic: null },
        response: { accepted: true, citation_check: valid, logic_check: valid },
        judge: judgeValidPair,
        final_status: 'counted',
        exclusion_reason: null,
      },
    ],
    verdict: {
      direction: 'hold',
      summary: 'Only balanced evidence survived.',
      final_score: 5.0,
      final_score_rounded: 5,
      initial_score: 10.0,
      adjusted_score: 5.0,
      pools: {
        initial: {
          dimensions: { technicals: { bullish: 2, bearish: 0, total: 2, score: 10.0 } },
          bullish: 2,
          bearish: 0,
          total: 2,
          score: 10.0,
        },
        adjusted: {
          dimensions: {
            technicals: { bullish: 2, bearish: 0, total: 2, score: 10.0 },
            sentiment: { bullish: 0, bearish: 1, total: 1, score: 0.0 },
          },
          bullish: 2,
          bearish: 1,
          total: 3,
          score: 5.0,
        },
        final: {
          dimensions: {
            technicals: { bullish: 1, bearish: 0, total: 1, score: 10.0 },
            sentiment: { bullish: 0, bearish: 1, total: 1, score: 0.0 },
          },
          bullish: 1,
          bearish: 1,
          total: 2,
          score: 5.0,
        },
      },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
      bull_summary: null,
      bear_summary: null,
      scoring: null,
    },
    warnings: [],
  };
}

// A v7 tree audit trail: code-verified display-value links (the value
// itself is the underlined link), a single logic axis, and struck
// bullets. T1 counted (attack overruled); T2 struck by the citation-fix
// loop; addition S1 (bearish) counted. Pools: initial tech-only 10.00;
// adjusted/final (10 + 0)/2 = 5.00 → hold.
function makeTreeDebateV7(): TieredDebateDetail {
  const invalidCheck = {
    verdict: 'invalid' as const,
    reason: 'One price point is not resistance.',
    citations: ['technicals.rsi_14'],
  };
  return {
    format: 7,
    turns: [],
    items: [
      {
        id: 'T1',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The 14-day RSI (71.20) is above 70.',
        links: [{ ref: 'technicals.rsi_14', value: '71.20', text: null }],
        struck: false,
        problems: [],
        added_by_attacker: false,
        attacker_check: invalidCheck,
        response: {
          accepted: false,
          check: {
            verdict: 'invalid',
            reason: 'The claim was about momentum, not resistance.',
            citations: ['technicals.rsi_14'],
          },
        },
        judge: {
          kind: 'attack_ruling',
          verdict: 'attack_wrong',
          reason: 'The item read the number correctly.',
          citations: [],
        },
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'T2',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The closing price (999) holds above support.',
        links: [{ ref: 'technicals.close', value: '999', text: null }],
        struck: true,
        problems: ["item T2 link 'technicals.close': claimed value '999' must be copied exactly as the report displays it: '100'"],
        added_by_attacker: false,
        attacker_check: null,
        response: null,
        judge: null,
        final_status: 'excluded',
        exclusion_reason: 'citation_failed',
      },
      {
        id: 'S1',
        dimension: 'sentiment',
        direction: 'bearish',
        claim: 'The deal is not closed yet.',
        links: [{ ref: 'citation:1', value: null, text: 'deal' }],
        struck: false,
        problems: [],
        added_by_attacker: true,
        attacker_check: null,
        response: {
          accepted: true,
          check: { verdict: 'valid', reason: null, citations: [] },
        },
        judge: { kind: 'reason_check', verdict: 'valid', reason: null, citations: [] },
        final_status: 'counted',
        exclusion_reason: null,
      },
    ],
    verdict: {
      direction: 'hold',
      summary: 'Only balanced evidence survived.',
      final_score: 5.0,
      final_score_rounded: 5,
      initial_score: 10.0,
      adjusted_score: 5.0,
      pools: {
        initial: {
          dimensions: { technicals: { bullish: 1, bearish: 0, total: 1, score: 10.0 } },
          bullish: 1,
          bearish: 0,
          total: 1,
          score: 10.0,
        },
        adjusted: {
          dimensions: {
            technicals: { bullish: 1, bearish: 0, total: 1, score: 10.0 },
            sentiment: { bullish: 0, bearish: 1, total: 1, score: 0.0 },
          },
          bullish: 1,
          bearish: 1,
          total: 2,
          score: 5.0,
        },
        final: {
          dimensions: {
            technicals: { bullish: 1, bearish: 0, total: 1, score: 10.0 },
            sentiment: { bullish: 0, bearish: 1, total: 1, score: 0.0 },
          },
          bullish: 1,
          bearish: 1,
          total: 2,
          score: 5.0,
        },
      },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
      bull_summary: null,
      bear_summary: null,
      scoring: null,
    },
    warnings: [],
  };
}

// A v9 evidence-vote audit trail: arrows and marks, majority votes.
// T1 listed by both analysts (confirmed 2-0); T2 outvoted 1-2 (checker
// + deciding vote against, crossed out); T3 struck by the code citation
// check (crossed out); S1 counted 2-0 with a trailing [2] source link.
// Final pool: 1 bullish of 2 → flat score 10 × 1/2 = 5.00 → hold.
function makeTreeDebateV9(): TieredDebateDetail {
  return {
    format: 9,
    turns: [],
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
        votes: [],
        response: null,
        judge: null,
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'T2',
        dimension: 'technicals',
        direction: 'bearish',
        claim: 'The closing price (100) is below the 105 resistance.',
        links: [{ ref: 'technicals.close', value: '100' }],
        struck: false,
        problems: [],
        authors: 1,
        votes: [
          {
            role: 'checker',
            verdict: 'invalid',
            reason: 'A single close below one level is not a trend.',
            links: [],
          },
          {
            role: 'decider',
            verdict: 'invalid',
            reason: 'The objection holds.',
            links: [],
          },
        ],
        response: null,
        judge: null,
        final_status: 'excluded',
        exclusion_reason: 'outvoted',
      },
      {
        id: 'T3',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The technical score (999) is strong.',
        links: [{ ref: 'technicals.score', value: '999' }],
        struck: true,
        problems: ["item T3 link 'technicals.score': claimed value '999' must be copied exactly as the report displays it: '68'"],
        authors: 1,
        votes: [],
        response: null,
        judge: null,
        final_status: 'excluded',
        exclusion_reason: 'citation_failed',
      },
      {
        id: 'S1',
        dimension: 'sentiment',
        direction: 'bearish',
        claim: 'The deal is not closed yet.',
        links: [{ ref: 'citation:2', value: null }],
        struck: false,
        problems: [],
        authors: 1,
        votes: [
          {
            role: 'checker',
            verdict: 'valid',
            reason: 'Supported by the source.',
            links: [{ ref: 'citation:2', value: null }],
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
      summary: 'Only balanced evidence survived.',
      final_score: 5.0,
      final_score_rounded: 5,
      initial_score: 3.33,
      adjusted_score: null,
      pools: {
        initial: {
          dimensions: {
            technicals: { bullish: 1, bearish: 1, total: 2 },
            sentiment: { bullish: 0, bearish: 1, total: 1 },
          },
          bullish: 1,
          bearish: 2,
          total: 3,
          score: 3.33,
        },
        final: {
          dimensions: {
            technicals: { bullish: 1, bearish: 0, total: 1 },
            sentiment: { bullish: 0, bearish: 1, total: 1 },
          },
          bullish: 1,
          bearish: 1,
          total: 2,
          score: 5.0,
        },
      },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
      bull_summary: null,
      bear_summary: null,
      scoring: null,
    },
    warnings: [],
  };
}

function renderResult(result: TieredResult) {
  render(
    <MemoryRouter>
      <UiLanguageProvider>
        <AltResult result={result} taskId="task-9" />
      </UiLanguageProvider>
    </MemoryRouter>,
  );
}

describe('AltResult', () => {
  it('renders a depth-1 (old) run: dimensions and tier 1 only, no shares block', () => {
    renderResult(makeV1Result());
    expect(screen.getAllByTestId(/alt-dimension-/)).toHaveLength(4);
    expect(screen.getByTestId('alt-tier1')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier3')).not.toBeInTheDocument();
    // no sizing block recorded → no shares-computation block at all
    expect(screen.queryByTestId('alt-shares-computation')).not.toBeInTheDocument();
    // the obsolete symbol/verdict hero is gone — the row already says both
    expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
    // no audit trail on old runs → the table falls back to the stored values
    expect(screen.getByTestId('alt-levels-table')).toHaveTextContent('96');
  });

  it('keeps the blocks in the fixed order with their titles above the cards', () => {
    renderResult(makeDeepResult());
    const ids = Array.from(document.querySelectorAll('[data-testid]'))
      .map((el) => el.getAttribute('data-testid') ?? '')
      .filter(
        (id) =>
          ['alt-tier1', 'alt-tier2', 'alt-tier3'].includes(id) ||
          id === 'alt-dimension-technicals',
      );
    expect(ids).toEqual([
      'alt-dimension-technicals',
      'alt-tier1',
      'alt-tier2',
      'alt-tier3',
    ]);
    expect(screen.getByText(/数据报告|Data reports/)).toBeInTheDocument();
    // Card titles carry no tier prefix (owner decision 2026-07-21).
    expect(screen.getByText(/^(初步分析|Preliminary analysis)$/)).toBeInTheDocument();
    expect(screen.getByText(/^(深度分析|Deep analysis)$/)).toBeInTheDocument();
    expect(screen.getByText(/层级 3：风险辩论|Tier 3: risk debate/)).toBeInTheDocument();
    // The shares-computation card is retired (2026-07-22).
    expect(screen.queryByText(/股数计算|Shares computation/)).not.toBeInTheDocument();
  });

  it('shows the tier-1 levels as a computed/adjusted table', () => {
    renderResult(makeDeepResult());
    // computed row on top, one clickable base per level — no backup
    // entry column anywhere (retired)
    expect(screen.getByTestId('alt-level-computed-entry')).toHaveTextContent('95');
    expect(screen.queryByTestId('alt-level-computed-secondary_entry')).not.toBeInTheDocument();
    expect(screen.getByTestId('alt-level-computed-stop_loss')).toHaveTextContent('90');
    expect(screen.getByTestId('alt-level-computed-take_profit')).toHaveTextContent('105');
    // adjusted row: moved levels show the new number, untouched ones "keep"
    expect(screen.getByTestId('alt-level-adjusted-entry')).toHaveTextContent('96');
    expect(screen.getByTestId('alt-level-adjusted-take_profit')).toHaveTextContent('108');
    expect(screen.getAllByTestId(/alt-level-keep-/)).toHaveLength(1);
    // the old explainer texts around the levels are gone
    expect(screen.queryByText(/价格参考位|Price levels/)).not.toBeInTheDocument();
    expect(screen.queryByText(/资金管理|money-management/)).not.toBeInTheDocument();
  });

  it('clicking a computed level opens its formula with every number linked to a source', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-computed-stop_loss'));
    const dialog = screen.getByRole('dialog');
    // Title is two styled parts now: the subject, then the kind tag.
    expect(within(dialog).getByRole('heading')).toHaveTextContent(
      /(止损\s*公式|Stop loss\s*formula)/,
    );
    // the formula in words — report-exact variable names, never raw tokens
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'entry − 2 × 14d ATR',
    );
    // the entry came from the computed entry cell, the ATR from technicals
    expect(within(dialog).getByRole('button', { name: 'entry' })).toHaveTextContent('95');
    expect(within(dialog).getByRole('button', { name: '14d ATR' })).toHaveTextContent('2.50');
    expect(within(dialog).getByText('= 90')).toBeInTheDocument();
  });

  it('expands "support candidates" in the entry formula into the actual values', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-computed-entry'));
    const dialog = screen.getByRole('dialog');
    // the prose phrase is expanded into the run's support inputs, each
    // named exactly as its technicals row is in the report
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'min(Closing price, max(SMA 20, Swing low 20))',
    );
    expect(within(dialog).queryByText(/support candidates/)).not.toBeInTheDocument();
    // every plugged number is a link to its source row
    expect(within(dialog).getByRole('button', { name: 'Closing price' })).toHaveTextContent('100');
    expect(within(dialog).getByRole('button', { name: 'SMA 20' })).toHaveTextContent('95');
    expect(within(dialog).getByRole('button', { name: 'Swing low 20' })).toHaveTextContent('92');
    expect(within(dialog).getByText('= 95')).toBeInTheDocument();
  });

  it('expands "nearest overhead resistance" in the target formula into the actual values', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-computed-take_profit'));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'min(entry + 2 × (entry − stop loss), nearest of (Swing high 20, 52w high))',
    );
    expect(within(dialog).queryByText(/overhead resistance/)).not.toBeInTheDocument();
    // resistance values link to their technicals rows
    expect(within(dialog).getByRole('button', { name: 'Swing high 20' })).toHaveTextContent('105');
    expect(within(dialog).getByRole('button', { name: '52w high' })).toHaveTextContent('110');
    expect(within(dialog).getByText('= 105')).toBeInTheDocument();
  });

  it('expands the v2 (grouped-payload) formulas: pivot supports, nearest resistance', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    const deep = makeDeepResult();
    deep.levels_detail = {
      levels: {
        entry: {
          base: 170,
          formula: 'min(close, max(support candidates))',
          inputs: { close: 171, sma_50: 168, sma_200: 150, support_1: 169.5, round_level: 170 },
          adjusted: null, reason: null, evidence: [], rejection: null, final: 170,
        },
        stop_loss: {
          base: 165.96,
          formula: 'ideal_entry − 2 × atr_14',
          inputs: { ideal_entry: 170, atr_14: 2.02, multiplier: 2 },
          adjusted: null, reason: null, evidence: [], rejection: null, final: 165.96,
        },
        take_profit: {
          base: 173.35,
          formula: 'min(ideal_entry + 2 × (ideal_entry − stop_loss), nearest overhead resistance)',
          inputs: {
            ideal_entry: 170, stop_loss: 165.96, geometric_target: 178.08,
            resistance_1: 173.35, high_1y: 180,
          },
          adjusted: null, reason: null, evidence: [], rejection: null, final: 173.35,
        },
      },
      warnings: [],
    };
    renderResult(deep);

    fireEvent.click(screen.getByTestId('alt-level-computed-entry'));
    let dialog = screen.getByRole('dialog');
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'min(Closing price, max(50d SMA, 200d SMA, Nearest support, Round level))',
    );
    expect(within(dialog).getByRole('button', { name: '50d SMA' })).toHaveTextContent('168');
    expect(within(dialog).getByRole('button', { name: 'Nearest support' })).toHaveTextContent(
      '169.50',
    );
    fireEvent.keyDown(window, { key: 'Escape' });

    fireEvent.click(screen.getByTestId('alt-level-computed-take_profit'));
    dialog = screen.getByRole('dialog');
    // the prose tail expands into the run's actual resistance inputs…
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'min(entry + 2 × (entry − stop loss), nearest of (Nearest resistance, 1y highest price))',
    );
    expect(within(dialog).queryByText(/overhead resistance/)).not.toBeInTheDocument();
    // …and each plugged number links to its technicals row
    expect(within(dialog).getByRole('button', { name: 'Nearest resistance' })).toHaveTextContent(
      '173.35',
    );
    expect(within(dialog).getByRole('button', { name: '1y highest price' })).toHaveTextContent(
      '180',
    );
    expect(within(dialog).getByText('= 173.35')).toBeInTheDocument();
  });

  it('clicking an adjusted level opens the AI reason with its references, nothing else', () => {
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-adjusted-entry'));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Momentum supports paying up a little.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'technicals.sma_20' })).toBeInTheDocument();
    // the inputs table and the reference explainer were removed
    expect(within(dialog).queryByText(/^(输入项|Inputs)$/)).not.toBeInTheDocument();
  });

  it('renders no shares-computation card (retired 2026-07-22)', () => {
    renderResult(makeDeepResult());
    expect(screen.queryByTestId('alt-shares-computation')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-shares-formula')).not.toBeInTheDocument();
  });

  it('renders a scored (v3) debate: corrected cases, scored turns, header 6/10', () => {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeScoredDebate();
    renderResult(deep);
    const tier2 = screen.getByTestId('alt-tier2');
    // header score is the rounded final number out of 10
    expect(tier2).toHaveTextContent(/(评分|Score): 6\/10/);
    // corrected side summaries instead of the old reasons columns
    expect(within(tier2).getByText(/多方总结|Bull case/)).toBeInTheDocument();
    expect(within(tier2).getByText('Corrected bull case.')).toBeInTheDocument();
    expect(within(tier2).getByText('Corrected bear case.')).toBeInTheDocument();
    // transcript turns carry the debater's own score and citations
    // (the label is "outlook score" for every generation since v4)
    expect(tier2).toHaveTextContent(/(展望分|outlook score) 8\/10/);
    expect(within(tier2).getByRole('button', { name: 'technicals.close' })).toBeInTheDocument();
  });

  it('shows the scoring foldable with the weight and final-score formulas', () => {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeScoredDebate();
    renderResult(deep);
    expect(screen.getByText(/评分与计算|Scoring and calculation/)).toBeInTheDocument();
    // per-debater grades and weight formula, in the three-line shape
    const bull = screen.getByTestId('alt-scoring-bull');
    expect(bull).toHaveTextContent('8/10');
    expect(bull).toHaveTextContent('= (4 + 5 + 4) / 15');
    expect(bull).toHaveTextContent('= 0.87');
    expect(bull).toHaveTextContent('Solid case.');
    // the final score plugs in the weights and scores shown above it
    expect(screen.getByTestId('alt-scoring-final-formula').textContent).toBe(
      '= (0.87 × 8 + 0.53 × 3) / (0.87 + 0.53)',
    );
    expect(screen.getByText('= 6.1')).toBeInTheDocument();
    // rounding + the fixed ranges + the mapped verdict
    expect(screen.getByText(/6\.1 (四舍五入为|rounds to) 6/)).toBeInTheDocument();
    expect(screen.getByText(/0–3 (卖出|sell)/)).toBeInTheDocument();
    expect(screen.getByTestId('alt-scoring-verdict')).toHaveTextContent(/持有|Hold/);
  });

  it('renders a threaded (v4) transcript: kinds shown, score only on responses', () => {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeThreadedDebate();
    renderResult(deep);
    const tier2 = screen.getByTestId('alt-tier2');
    // six turns labeled by kind, no round numbering
    expect(within(tier2).getAllByText(/立论|argument/).length).toBeGreaterThanOrEqual(2);
    expect(within(tier2).getAllByText(/质疑|attack/).length).toBeGreaterThanOrEqual(2);
    expect(tier2).not.toHaveTextContent(/第 1 轮|round 1/);
    // the outlook score sits on the response turn
    expect(tier2).toHaveTextContent(/(展望分|outlook score) 8\/10/);
    expect(within(tier2).getByText('I stand by the momentum case.')).toBeInTheDocument();
  });

  it('shows a judge comment per axis grade: quote + why below 5, N/A at 5/5', () => {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeThreadedDebate();
    renderResult(deep);
    const bull = screen.getByTestId('alt-scoring-bull');
    expect(bull).toHaveTextContent(/(展望分|outlook score): 8\/10/);
    // sub-5 grade → the offending sentence, quoted, plus the reason
    expect(bull).toHaveTextContent('“Momentum is strong.” — Overstated from one indicator.');
    // 5/5 grade → N/A
    expect(bull).toHaveTextContent(/(知识有效性|knowledge validity): 5\/5 · (评语|comment): N\/A/);
    // weight formula still plugs the numeric scores
    expect(bull).toHaveTextContent('= (4 + 5 + 4) / 15');
    expect(bull).toHaveTextContent('= 0.87');
    // final formula uses the v4 position_score field
    expect(screen.getByTestId('alt-scoring-final-formula').textContent).toBe(
      '= (0.87 × 8 + 0.53 × 3) / (0.87 + 0.53)',
    );
  });

  it('renders citation evidence as sentiment.citation:N in link colors', () => {
    const deep = makeDeepResult();
    const sentiment = deep.dimensions.find((d) => d.dimension === 'sentiment')!;
    sentiment.citations = [
      { source_name: 'news', title: 'Some article', url: 'https://example.com/a', snippet: null },
    ];
    deep.tier2!.debate_detail!.verdict = {
      direction: 'hold',
      confidence: 0.6,
      summary: 'Summary.',
      reasons_for: [{ claim: 'Bull claim', evidence: ['citation:1'] }],
      reasons_against: [],
      would_change_mind: null,
    };
    renderResult(deep);
    const ref = screen.getByText('sentiment.citation:1');
    expect(ref.tagName).toBe('A');
    expect(ref).toHaveAttribute('href', 'https://example.com/a');
    expect(ref.className).toContain('text-blue-400');
  });

  it('lists non-link sources above link sources under one Sources title', () => {
    const result = makeV1Result();
    result.dimensions[1].citations = [
      { source_name: 'SEC EDGAR', title: 'SEC EDGAR companyfacts', url: 'https://sec.gov/x', snippet: null },
      { source_name: 'Yahoo Finance summary (yfinance)', title: null, url: null, snippet: null },
    ];
    renderResult(result);
    const card = screen.getByTestId('alt-dimension-fundamentals');
    expect(within(card).getByText(/^(来源|Sources)$/)).toBeInTheDocument();
    const items = within(card).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Yahoo Finance summary (yfinance)');
    // link sources are listed as their URL, not their headline
    expect(items[1]).toHaveTextContent('https://sec.gov/x');
    expect(items[1]).not.toHaveTextContent('SEC EDGAR companyfacts');
  });

  it('inlines each macro observation date beside its value, keeping the date anchor', () => {
    const result = makeV1Result();
    result.dimensions[2].payload = {
      region: 'us',
      as_of: '2026-07-24',
      markets: { vix: 16.64 },
      observation_dates: { vix: '2026-07-22' },
    };
    renderResult(result);
    // The value row carries its date, and the date keeps the citable
    // anchor id (macro_econ.observation_dates.vix) evidence links jump to
    // — the dates group no longer renders as a section of its own.
    const row = document.getElementById('tiered-metric-macro_econ-markets-vix');
    // Dates render in the page's slashed style (owner request 2026-08-16).
    expect(row).toHaveTextContent('16.64 2026/07/22');
    const date = document.getElementById('tiered-metric-macro_econ-observation_dates-vix');
    expect(date).toHaveTextContent('2026/07/22');
    expect(row?.contains(date)).toBe(true);
  });

  it('renders a v2 envelope payload as one row per metric with group titles', () => {
    const result = makeV1Result();
    // technicals v2 (2026-07-27): nested groups of {name, explanation,
    // value} envelopes.
    result.dimensions[0].payload = {
      price: {
        close: { name: 'closing price', explanation: 'anchor', value: 157.79 },
      },
      daily: {
        trend: { name: 'daily trend', explanation: 'combined', value: 'bullish' },
        rsi_14: { name: 'RSI (14d)', explanation: 'momentum', value: 61.42 },
      },
    };
    renderResult(result);
    const card = screen.getByTestId('alt-dimension-technicals');
    // One row per envelope, unwrapped to its value — the prose keys
    // (name/explanation) must not render as rows of their own.
    const close = document.getElementById('tiered-metric-technicals-price-close');
    expect(close).toHaveTextContent('157.79');
    const trend = document.getElementById('tiered-metric-technicals-daily-trend');
    expect(trend).toHaveTextContent('bullish');
    expect(within(card).queryByText('anchor')).not.toBeInTheDocument();
    expect(within(card).queryByText('combined')).not.toBeInTheDocument();
    // Group keys become section titles via the metric vocabulary.
    expect(within(card).getByText(/股票价格|Stock price/)).toBeInTheDocument();
    expect(within(card).getByText(/日线时间框架|Daily timeframe/)).toBeInTheDocument();
    // No Other bucket: every v2 group renders under its own name.
    expect(within(card).queryByText(/^(其他|Other)$/)).not.toBeInTheDocument();
  });

  it('shows verdict, size, stop loss and score as plain Label: value facts', () => {
    renderResult(makeDeepResult());
    const tier3 = screen.getByTestId('alt-tier3');
    // no pill anymore — the verdict is text like every other fact
    expect(tier3).toHaveTextContent(/(展望|Outlook): (中性|Neutral)/);
    expect(tier3).toHaveTextContent(/(仓位|Size): 0.5x/);
    expect(tier3).toHaveTextContent(/(止损|Stop loss): (维持|keep)/);
    // judge confidence 0.7 → a whole number out of 10
    expect(tier3).toHaveTextContent(/(评分|Score): 7\/10/);
    const tier1 = screen.getByTestId('alt-tier1');
    expect(tier1).toHaveTextContent(/(展望|Outlook): (看多|Bullish)/);
    // tier 1's stored score is a bullishness composite, not a judge
    // confidence — it is not shown as "Score"
    expect(tier1).not.toHaveTextContent(/评分|Score/);
  });

  it('tucks data notes behind an exclamation mark that opens a plain-English modal', () => {
    const result = {
      ...makeV1Result(),
      warnings: [
        "unparseable sniper level ideal_buy='Ideal buy point: N/A (waiting for clarity)'",
        'some brand-new warning shape the frontend has never seen',
      ],
    };
    renderResult(result);
    // Nothing inline — the notes only exist behind the mark.
    expect(screen.queryByText(/left blank|留空/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('alt-notes-button'));
    // Known shape → fixed keyword + friendly sentence; the raw backend
    // text is no longer shown (owner decision 2026-07-24).
    expect(screen.getByText(/Price levels|价格参考位/)).toBeInTheDocument();
    expect(screen.getByText(/left blank|留空/)).toBeInTheDocument();
    expect(screen.queryByText(/unparseable sniper level/)).not.toBeInTheDocument();
    // Unknown shape → raw text unchanged, no keyword (never an invented gloss).
    expect(
      screen.getByText('some brand-new warning shape the frontend has never seen'),
    ).toBeInTheDocument();
  });
});

describe('AltResult v5 debate tree', () => {
  function renderTree() {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeTreeDebate();
    deep.tier2!.narrative = 'The surviving evidence leans bullish.';
    renderResult(deep);
  }

  it('renders the tree with the full step-4 view by default — no scoring foldable, no bull/bear columns', () => {
    renderTree();
    expect(screen.getByTestId('alt-debate-tree')).toBeInTheDocument();
    // The old v3/v4 surfaces are gone on v5 runs.
    expect(screen.queryByText(/Scoring and calculation|评分与计算/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Bull case|多方总结/)).not.toBeInTheDocument();
    // Header score is the 2-decimal final.
    expect(within(screen.getByTestId('alt-tier2')).getByText('6.50/10')).toBeInTheDocument();
    // Judge rulings and counted badges are visible at step 4.
    const t2 = screen.getByTestId('alt-tree-item-T2');
    expect(t2).toHaveTextContent(/attack upheld|质疑成立/);
    expect(t2).toHaveTextContent(/counted 0\/1|计 0\/1/);
    // The addition is tagged and ruled real.
    const s2 = screen.getByTestId('alt-tree-item-S2');
    expect(s2).toHaveTextContent(/newly added|新增证据/);
    expect(s2).toHaveTextContent(/real|成立/);
  });

  it('shows the weight ledger and the final-score formula with this run’s numbers', () => {
    renderTree();
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent(/initial outlook score|初始展望分/);
    expect(scores).toHaveTextContent('8/10');
    expect(scores).toHaveTextContent('7/10');
    expect(scores).toHaveTextContent('= 3/4');
    expect(scores).toHaveTextContent('0.75');
    expect(screen.getByTestId('alt-tree-final-formula')).toHaveTextContent(
      '= 5 + 0.75 × (7 − 5)',
    );
    expect(scores).toHaveTextContent('= 6.50');
    expect(screen.getByTestId('alt-tree-verdict')).toHaveTextContent(/buy|买入/i);
  });

  it('step 1 shows only the defender’s list and the initial score', () => {
    renderTree();
    fireEvent.click(screen.getByTestId('alt-tree-step-1'));
    // Attacker material and judge rulings disappear…
    expect(screen.queryByText(/newly added|新增证据/)).not.toBeInTheDocument();
    expect(screen.queryByText(/attack upheld|质疑成立/)).not.toBeInTheDocument();
    expect(screen.queryByText(/counted|计 /)).not.toBeInTheDocument();
    // …the defender items and initial score stay.
    expect(screen.getByTestId('alt-tree-item-T2')).toHaveTextContent('The price trend is up.');
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent('8/10');
    expect(scores).not.toHaveTextContent(/adjusted outlook score|调整后展望分/);
  });

  it('step 2 adds the attacker’s checks and additions but no responses yet', () => {
    renderTree();
    fireEvent.click(screen.getByTestId('alt-tree-step-2'));
    const t2 = screen.getByTestId('alt-tree-item-T2');
    expect(t2).toHaveTextContent('One price point is not a trend.');
    expect(t2).not.toHaveTextContent('The attack ignores the moving averages.');
    expect(screen.getByTestId('alt-tree-item-S2')).toHaveTextContent(
      /newly added|新增证据/,
    );
    expect(t2).not.toHaveTextContent(/attack upheld|质疑成立/);
  });

  it('a voided v5 run still renders its partial tree with the no-verdict note', () => {
    const deep = makeDeepResult();
    const detail = makeTreeDebate();
    detail.verdict = null;
    detail.items = detail.items!.map((item) => ({
      ...item,
      judge: null,
      count: null,
      outcome: null,
    }));
    deep.tier2!.debate_detail = detail;
    deep.tier2!.narrative = null;
    renderResult(deep);
    expect(screen.getByText(/no usable verdict|未产生可用结论/)).toBeInTheDocument();
    expect(screen.getByTestId('alt-debate-tree')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-tree-scores')).not.toBeInTheDocument();
  });
});

describe('AltResult v6 debate tree', () => {
  function renderTreeV6() {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeTreeDebateV6();
    deep.tier2!.narrative = 'Only balanced evidence survived.';
    renderResult(deep);
  }

  it('renders claims with the cited words as inline links, no trailing chips', () => {
    renderTreeV6();
    const link = within(screen.getByTestId('alt-tree-item-T1')).getByRole('button', {
      name: '14-day RSI',
    });
    expect(link).toBeInTheDocument();
    // No chip with the raw ref path next to the claim.
    expect(
      within(screen.getByTestId('alt-tree-item-T1')).queryByText('technicals.rsi_14'),
    ).not.toBeInTheDocument();
  });

  it('shows the code’s mechanical citation failure and the counted/excluded badges', () => {
    renderTreeV6();
    const t2 = screen.getByTestId('alt-tree-item-T2');
    expect(t2).toHaveTextContent(/code|代码/);
    expect(t2).toHaveTextContent('the report says 100.0');
    expect(t2).toHaveTextContent(/excluded|不计入/);
    expect(screen.getByTestId('alt-tree-item-T1')).toHaveTextContent(/counted|计入/);
  });

  it('renders the addition with the newly-added line and the judge’s two checks, no real/bogus words', () => {
    renderTreeV6();
    const s1 = screen.getByTestId('alt-tree-item-S1');
    expect(s1).toHaveTextContent(/newly added|新增证据/);
    expect(s1).not.toHaveTextContent(/real evidence|bogus/);
    // defender's two checks + judge's two checks all render as check lines
    expect(s1).toHaveTextContent(/citation check|引用检查/);
    expect(s1).toHaveTextContent(/judge|裁判/);
  });

  it('shows the three pool scores and the per-dimension counting formula', () => {
    renderTreeV6();
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent('10.00');
    expect(scores).toHaveTextContent(/adjusted outlook score|调整后展望分/);
    expect(scores).toHaveTextContent('5.00');
    // per-dimension breakdown of the final pool
    expect(scores).toHaveTextContent(/technicals|技术面/i);
    expect(screen.getByTestId('alt-tree-final-formula')).toHaveTextContent(
      '= (10.00 + 0.00) / 2',
    );
    expect(screen.getByTestId('alt-tree-verdict')).toHaveTextContent(/hold|持有/i);
    // No weight block on v6 runs.
    expect(scores).not.toHaveTextContent(/correct keeps|正确保留数/);
  });

  it('step 1 hides the addition and the checking machinery', () => {
    renderTreeV6();
    fireEvent.click(screen.getByTestId('alt-tree-step-1'));
    expect(screen.queryByTestId('alt-tree-item-S1')).not.toBeInTheDocument();
    expect(screen.queryByText(/newly added|新增证据/)).not.toBeInTheDocument();
    expect(screen.getByTestId('alt-tree-item-T2')).not.toHaveTextContent(/code|代码/);
    expect(screen.queryByText(/excluded|不计入/)).not.toBeInTheDocument();
  });
});

describe('AltResult v7 debate tree', () => {
  function renderTreeV7() {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeTreeDebateV7();
    deep.tier2!.narrative = 'Only balanced evidence survived.';
    renderResult(deep);
  }

  it('underlines exactly the cited display value, nothing else', () => {
    renderTreeV7();
    const t1 = screen.getByTestId('alt-tree-item-T1');
    expect(within(t1).getByRole('button', { name: '71.20' })).toBeInTheDocument();
    // The metric words are plain text now — only the value is a link.
    expect(within(t1).queryByRole('button', { name: /14-day RSI/ })).not.toBeInTheDocument();
  });

  it('sentiment links still underline their words', () => {
    renderTreeV7();
    const s1 = screen.getByTestId('alt-tree-item-S1');
    expect(within(s1).getByRole('button', { name: 'deal' })).toBeInTheDocument();
  });

  it('draws a line through a struck bullet and gives it no thread or badge', () => {
    renderTreeV7();
    const t2 = screen.getByTestId('alt-tree-item-T2');
    expect(t2.querySelector('.line-through')).not.toBeNull();
    // No code line, no checks, no counted/excluded badge — the strike
    // is the whole story.
    expect(t2).not.toHaveTextContent(/code|代码/);
    expect(t2).not.toHaveTextContent(/check|检查/);
    expect(t2).not.toHaveTextContent(/excluded|不计入/);
  });

  it('shows the single-axis thread: attacker check, defender response, judge ruling', () => {
    renderTreeV7();
    const t1 = screen.getByTestId('alt-tree-item-T1');
    expect(t1).toHaveTextContent(/attacker|攻方/);
    expect(t1).toHaveTextContent(/logic check|逻辑检查/);
    expect(t1).toHaveTextContent(/attack overruled|质疑不成立/);
    // The citation axis is code's job now — no AI citation-check lines.
    expect(t1).not.toHaveTextContent(/citation check|引用检查/);
  });

  it('renders the addition with the newly-added line and one judge check', () => {
    renderTreeV7();
    const s1 = screen.getByTestId('alt-tree-item-S1');
    expect(s1).toHaveTextContent(/newly added|新增证据/);
    expect(s1).toHaveTextContent(/judge|裁判/);
    expect(s1).not.toHaveTextContent(/real evidence|bogus/);
  });

  it('labels the pool scores as per-dimension averages instead of raw counts', () => {
    renderTreeV7();
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent(/average of 1 dimensions|1 个维度的平均分/);
    expect(scores).toHaveTextContent(/average of 2 dimensions|2 个维度的平均分/);
    expect(scores).not.toHaveTextContent(/\(\d+ bullish|（\d+ 看多/);
    expect(screen.getByTestId('alt-tree-final-formula')).toHaveTextContent(
      '= (10.00 + 0.00) / 2',
    );
    expect(screen.getByTestId('alt-tree-verdict')).toHaveTextContent(/hold|持有/i);
  });

  it('step 1 hides the addition but keeps the strikethrough', () => {
    renderTreeV7();
    fireEvent.click(screen.getByTestId('alt-tree-step-1'));
    expect(screen.queryByTestId('alt-tree-item-S1')).not.toBeInTheDocument();
    const t2 = screen.getByTestId('alt-tree-item-T2');
    expect(t2.querySelector('.line-through')).not.toBeNull();
  });
});

describe('AltResult v9 evidence vote', () => {
  function renderTreeV9() {
    const deep = makeDeepResult();
    deep.tier2!.debate_detail = makeTreeDebateV9();
    deep.tier2!.narrative = 'Only balanced evidence survived.';
    renderResult(deep);
  }

  it('tucks the whole vote record into a Transcript foldable with the how-it-works list on top', () => {
    renderTreeV9();
    expect(screen.getByText(/Details|详情/)).toBeInTheDocument();
    const explain = screen.getByTestId('alt-tree-explain');
    expect(explain).toHaveTextContent(/How this works|规则说明/);
    // The list explains that mark-less bullets came from both AIs.
    expect(explain).toHaveTextContent(/carries no check marks|没有任何检查标记/);
    expect(explain).toHaveTextContent(/deciding vote|决胜票/);
  });

  it('shows colored direction words and counts them in the section headers', () => {
    renderTreeV9();
    const t1 = screen.getByTestId('alt-tree-item-T1');
    expect(within(t1).getByText(/bullish|看多/)).toHaveClass('text-emerald-300');
    const t2 = screen.getByTestId('alt-tree-item-T2');
    expect(within(t2).getByText(/bearish|看空/)).toHaveClass('text-red-300');
    // Headers count only the surviving bullets: technicals 1 bullish, 0 bearish.
    expect(screen.getByTestId('alt-debate-tree')).toHaveTextContent(/1 bullish, 0 bearish|1 看多, 0 看空/);
  });

  it('a bullet from both AIs carries no marks; single-author bullets carry ✓/✗ marks', () => {
    renderTreeV9();
    expect(
      within(screen.getByTestId('alt-tree-item-T1')).queryAllByRole('button', { name: /✓|✗/ }),
    ).toHaveLength(0);
    expect(
      within(screen.getByTestId('alt-tree-item-T2')).getAllByRole('button', { name: '✗' }),
    ).toHaveLength(2);
    expect(
      within(screen.getByTestId('alt-tree-item-S1')).getByRole('button', { name: '✓' }),
    ).toBeInTheDocument();
  });

  it('clicking a mark opens the numbered check result with the reasoning', () => {
    renderTreeV9();
    fireEvent.click(
      within(screen.getByTestId('alt-tree-item-T2')).getAllByRole('button', { name: '✗' })[0],
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/1st check result\s*invalid|第一次检查结果\s*/);
    expect(dialog).toHaveTextContent('A single close below one level is not a trend.');
  });

  it('the second mark opens as the 2nd check result', () => {
    renderTreeV9();
    fireEvent.click(
      within(screen.getByTestId('alt-tree-item-T2')).getAllByRole('button', { name: '✗' })[1],
    );
    expect(screen.getByRole('dialog')).toHaveTextContent(/2nd check result|第二次检查结果/);
  });

  it('clicking the code ✗ on a struck bullet shows the citation errors', () => {
    renderTreeV9();
    fireEvent.click(
      within(screen.getByTestId('alt-tree-item-T3')).getByRole('button', { name: '✗' }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/code check result|代码检查结果/);
    expect(dialog).toHaveTextContent('must be copied exactly');
  });

  it('crosses out every bullet that is not in the final score, with no pills or steps', () => {
    renderTreeV9();
    expect(
      screen.getByTestId('alt-tree-item-T2').querySelector('.line-through'),
    ).not.toBeNull();
    expect(
      screen.getByTestId('alt-tree-item-T3').querySelector('.line-through'),
    ).not.toBeNull();
    expect(
      screen.getByTestId('alt-tree-item-T1').querySelector('.line-through'),
    ).toBeNull();
    expect(screen.queryByTestId('alt-tree-step-1')).not.toBeInTheDocument();
    expect(screen.queryByText(/^counted$|^excluded$/)).not.toBeInTheDocument();
  });

  it('opens the flat formula from the header score; no verdict-bands block', () => {
    renderTreeV9();
    // The arithmetic no longer sits inside the transcript fold.
    expect(screen.queryByTestId('alt-tree-scores')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('alt-debate-score'));
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent(/final outlook score: |最终展望分: /);
    expect(screen.getByTestId('alt-tree-final-formula')).toHaveTextContent('= 10 × 1 / 2');
    expect(scores).toHaveTextContent('= 5.00');
    expect(scores).not.toHaveTextContent(/below 4 sell|低于 4 卖出/);
    expect(screen.queryByTestId('alt-tree-verdict')).not.toBeInTheDocument();
  });

  it('wraps long claims with a hanging indent (two-column grid rows)', () => {
    renderTreeV9();
    expect(screen.getByTestId('alt-tree-item-T1').className).toContain('grid');
  });
});

// The format-2 risk vote: T1 confirmed by both AIs, T2 outvoted 1-2,
// P1 (plan group) confirmed by a ✓ check vote, S1 struck by code.
// Confirmed: T1, P1 = 2 of 3 listed → multiplier 0.5.
function makeRiskDetailV2(): TieredRiskDetail {
  return {
    format: 2,
    takes: [],
    items: [
      {
        id: 'T1',
        dimension: 'technicals',
        claim: 'The 14-day RSI (71.20) is overbought.',
        links: [{ ref: 'technicals.rsi_14', value: '71.20' }],
        struck: false,
        problems: [],
        authors: 2,
        votes: [],
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'T2',
        dimension: 'technicals',
        claim: 'The technical score (68) leaves little cushion.',
        links: [{ ref: 'technicals.score', value: '68' }],
        struck: false,
        problems: [],
        authors: 1,
        votes: [
          {
            role: 'checker',
            verdict: 'invalid',
            reason: 'A decent score is not a concrete risk.',
            links: [],
          },
          {
            role: 'decider',
            verdict: 'invalid',
            reason: 'The objection holds.',
            links: [],
          },
        ],
        final_status: 'excluded',
        exclusion_reason: 'outvoted',
      },
      {
        id: 'P1',
        dimension: 'plan',
        claim: 'The stop-loss (90) sits close under the entry (96).',
        links: [
          { ref: 'plan.stop_loss', value: '90' },
          { ref: 'plan.entry', value: '96' },
        ],
        struck: false,
        problems: [],
        authors: 1,
        votes: [
          {
            role: 'checker',
            verdict: 'valid',
            reason: 'The gap really is tight.',
            links: [],
          },
        ],
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'S1',
        dimension: 'sentiment',
        claim: 'Doubts remain (999).',
        links: [{ ref: 'citation:2', value: null }],
        struck: true,
        problems: ["item S1 link 'citation:2': citation number out of range"],
        authors: 1,
        votes: [],
        final_status: 'excluded',
        exclusion_reason: 'citation_failed',
      },
    ],
    verdict: {
      stance: 'hold',
      size_multiplier: 0.5,
      summary: 'Two risks survived; size is halved.',
      confirmed_risks: 2,
      total_risks: 3,
      counts: {
        initial: { groups: { technicals: 2, plan: 1 }, total: 3 },
        final: { groups: { technicals: 1, plan: 1 }, total: 2 },
      },
      confidence: null,
      stop_advice: 'keep',
      tightened_stop: null,
      key_risks: [],
    },
    warnings: [],
  };
}

describe('AltResult format-2 risk vote', () => {
  function renderRiskV2() {
    const deep = makeDeepResult();
    deep.tier3!.risk_detail = makeRiskDetailV2();
    deep.tier3!.narrative = 'Two risks survived; size is halved.';
    renderResult(deep);
  }

  it('shows only Verdict and Size in the header — no score, no stop advice', () => {
    renderRiskV2();
    const tier3 = screen.getByTestId('alt-tier3');
    expect(tier3).toHaveTextContent(/(展望|Outlook): (中性|Neutral)/);
    expect(tier3).toHaveTextContent(/(仓位|Size): 0.5x/);
    expect(tier3).not.toHaveTextContent(/(止损|Stop loss): (维持|keep)/);
    expect(tier3).not.toHaveTextContent(/(评分|Score): /);
  });

  it('tucks the risk record into a Transcript foldable with its own how-it-works list', () => {
    renderRiskV2();
    const explain = screen.getByTestId('alt-risk-explain');
    expect(explain).toHaveTextContent(/How this works|规则说明/);
    expect(explain).toHaveTextContent(/stress-test|压力测试/);
    // The list states the fixed count → multiplier mapping.
    expect(explain).toHaveTextContent(/0 = full size \(×1\)|0 项 = 全仓（×1）/);
  });

  it('groups risks with confirmed counts in the headers, including the plan group', () => {
    renderRiskV2();
    const tree = screen.getByTestId('alt-risk-tree');
    // technicals: 1 counted of 2; plan: 1 counted.
    expect(tree).toHaveTextContent(/(Technicals|技术面): 1 (risk|项风险)/);
    expect(tree).toHaveTextContent(/(Trade plan|交易计划): 1 (risk|项风险)/);
  });

  it('risk bullets carry no bullish/bearish words; marks follow the tier-2 rules', () => {
    renderRiskV2();
    const t1 = screen.getByTestId('alt-risk-item-T1');
    expect(t1).not.toHaveTextContent(/bullish|bearish|看多|看空/);
    expect(within(t1).queryAllByRole('button', { name: /✓|✗/ })).toHaveLength(0);
    expect(
      within(screen.getByTestId('alt-risk-item-T2')).getAllByRole('button', { name: '✗' }),
    ).toHaveLength(2);
    expect(
      within(screen.getByTestId('alt-risk-item-P1')).getByRole('button', { name: '✓' }),
    ).toBeInTheDocument();
  });

  it('clicking a mark opens the numbered check result with the reasoning', () => {
    renderRiskV2();
    fireEvent.click(
      within(screen.getByTestId('alt-risk-item-P1')).getByRole('button', { name: '✓' }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/1st check result\s*valid|第一次检查结果\s*有效/);
    expect(dialog).toHaveTextContent('The gap really is tight.');
  });

  it('clicking the code ✗ on a struck risk shows the citation errors', () => {
    renderRiskV2();
    fireEvent.click(
      within(screen.getByTestId('alt-risk-item-S1')).getByRole('button', { name: '✗' }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/code check result|代码检查结果/);
    expect(dialog).toHaveTextContent('citation number out of range');
  });

  it('crosses out outvoted and struck risks', () => {
    renderRiskV2();
    expect(
      screen.getByTestId('alt-risk-item-T2').querySelector('.line-through'),
    ).not.toBeNull();
    expect(
      screen.getByTestId('alt-risk-item-S1').querySelector('.line-through'),
    ).not.toBeNull();
    expect(
      screen.getByTestId('alt-risk-item-T1').querySelector('.line-through'),
    ).toBeNull();
  });

  it('shows the Size block with the fixed mapping and the plugged-in count', () => {
    renderRiskV2();
    const size = screen.getByTestId('alt-risk-size');
    expect(size).toHaveTextContent(
      /size multiplier: 0 confirmed risks = ×1|仓位倍数：确认风险 0 项 = ×1/,
    );
    expect(screen.getByTestId('alt-risk-size-formula')).toHaveTextContent(/= (2 confirmed|确认风险 2 项)/);
    expect(size).toHaveTextContent('= ×0.5');
  });
});

describe('AltResult sell sizing from ownership', () => {
  it('renders no shares card on sell runs either (retired 2026-07-22)', () => {
    const deep = makeDeepResult();
    renderResult({
      ...deep,
      direction: 'sell',
      sizing: {
        ...deep.sizing!,
        shares: null,
        reason_code: 'not_a_buy',
        refusal_reason: 'not a buy',
        ownership: 300,
        sell_shares: 300,
      },
    });
    expect(screen.queryByTestId('alt-shares-computation')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-sell-formula')).not.toBeInTheDocument();
  });
});
