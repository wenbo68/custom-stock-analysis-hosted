import { describe, expect, it } from 'vitest';
import { UI_TEXT, formatUiText, type UiTextKey } from '../../../i18n/uiText';
import { friendlyWarning } from '../altWarningText';

const t = (key: UiTextKey, params?: Record<string, string | number>) =>
  formatUiText(UI_TEXT.en[key], params);

describe('friendlyWarning — debate stage notes lead with the AI role', () => {
  it('a retried grade sheet names its lister', () => {
    const note = friendlyWarning(
      'first analyst grade sheet needed a retry — first reply was invalid',
      t,
    );
    expect(note?.keyword).toBe('AI reply');
    expect(note?.text).toBe('Lister 1 — the first reply was invalid; the retry succeeded.');
  });

  it('the two analysts produce two distinguishable notes', () => {
    const second = friendlyWarning(
      'second analyst grade sheet needed a retry — first reply was invalid',
      t,
    );
    expect(second?.text).toContain('Lister 2');
  });

  it('an invalid-after-retry sheet names its lister too', () => {
    const note = friendlyWarning(
      'first analyst grade sheet invalid after retry: unknown grade keys: technicals.levels.resistance_1',
      t,
    );
    expect(note?.text).toBe('Lister 1 — the reply was still invalid after a retry.');
  });

  it('check and deciding rounds use their vote labels', () => {
    expect(
      friendlyWarning('check round needed a retry — first reply was invalid', t)?.text,
    ).toContain('Check vote');
    expect(
      friendlyWarning('deciding round was not JSON even after a retry', t)?.text,
    ).toContain('Deciding vote');
  });

  it('an unmapped stage keeps its raw name rather than inventing a label', () => {
    const note = friendlyWarning(
      'defender opening needed a retry — first reply was invalid',
      t,
    );
    expect(note?.text).toContain('defender opening');
  });
});

describe('friendlyWarning — v12 voided-run notes are translated', () => {
  it('both grade sheets failing translates (v12 wording)', () => {
    const note = friendlyWarning(
      'both analyst grade sheets invalid after retry — tier-2 verdict voided',
      t,
    );
    expect(note?.text).toBe(
      'Both analysts kept returning invalid grade sheets — the deep analysis was voided.',
    );
  });

  it('the old v8 "lists" wording still translates', () => {
    const note = friendlyWarning(
      'both analyst lists invalid after retry — tier-2 verdict voided',
      t,
    );
    expect(note?.text).toContain('deep analysis was voided');
  });

  it('the no-outlook note translates with the re-run advice', () => {
    const note = friendlyWarning(
      'debate produced no verdict — no outlook (re-run)',
      t,
    );
    expect(note?.text).toContain('re-run');
  });

  it('one failed sheet names the failed lister', () => {
    const note = friendlyWarning(
      'second analyst grade sheet invalid after retry — proceeding with the other sheet only',
      t,
    );
    expect(note?.text).toContain('Lister 2');
  });
});


// Audit 2026-08-08. Every string here was copied from the Python that
// emits it; each used to fall through friendlyWarning and render as raw
// engineer text. The point of the test is DRIFT: if a backend message is
// reworded and its rule is not, the note silently reverts to raw text
// under the generic keyword and nothing else fails. That is exactly how the trend
// rules rotted (they still said "60-day" long after the backend moved to
// the 50-day average), so the samples below are verbatim on purpose.
describe('friendlyWarning — rich notes carry live slots (2026-08-23)', () => {
  it('the far-report note exposes the real countdown with its receipt data', () => {
    const note = friendlyWarning(
      'next quarterly report is 68 days away (report 2026-10-30, today 2026-08-23) — ' +
        'more than 21 days out, option prices mostly reflect ordinary drift, not the ' +
        'report jump; implied report-day move omitted',
      t,
    );
    expect(note.keyword).toBe('Missing data');
    expect(note.text).toContain('68 days away');
    expect(note.text).toContain('more than 21');
    expect(note.template).toContain('{days}');
    expect(note.slots?.days).toEqual({
      kind: 'daysReceipt',
      days: 68,
      reportDate: '2026-10-30',
      today: '2026-08-23',
    });
  });

  it('a ratio blanked by the missing implied move links that exact field', () => {
    const note = friendlyWarning(
      'implied report-day move missing — report-move ratio (implied vs 4q avg) omitted',
      t,
    );
    expect(note.keyword).toBe('Missing data');
    // The plain text names the field by its exact report label.
    expect(note.text).toContain('"Implied quarterly report day price change magnitude"');
    expect(note.slots?.field).toEqual({
      kind: 'metricLink',
      term: 'implied_report_move_pct',
      paths: ['positioning.options.implied_report_move_pct'],
    });
  });

  it('a ratio blanked by the missing realized average links that exact field', () => {
    const note = friendlyWarning(
      'realized 4q average report-day move missing or zero — report-move ratio ' +
        '(implied vs 4q avg) omitted',
      t,
    );
    expect(note.text).toContain('"4q avg report day price change magnitude"');
    expect(note.slots?.field).toEqual({
      kind: 'metricLink',
      term: 'reaction_avg_abs_pct',
      paths: ['fundamentals.quarterly_report.reaction_avg_abs_pct'],
    });
  });
});

describe('friendlyWarning — every backend note reaches plain English', () => {
  const SAMPLES: Array<[string, string]> = [
    // src/tiered_analysis/levels.py — the rotted pair.
    [
      'trend warning: close 303.42 is at or below the 50-day average 310.1 (downtrend) — a pullback buy against the trend carries extra downside risk',
      'Downtrend',
    ],
    ['sma_50 unavailable — trend check skipped', 'Missing data'],
    ['no close price — deterministic levels cannot be computed', 'Price levels'],
    [
      'no structural support anchors (sma_50 / sma_200 / support_1) — no entry base, so no deterministic levels',
      'Price levels',
    ],
    ['technicals unavailable — deterministic levels cannot be computed', 'Price levels'],
    ['duplicate adjustment for entry ignored (first proposal kept)', 'Price levels'],
    ["adjustment for unknown level 'foo' ignored", 'Price levels'],
    // src/tiered_analysis/providers/technicals.py
    ['bars_loader failed for AAPL: HTTPError()', 'Fetch failed'],
    ['insufficient history for AAPL: 9 bars < 15 required', 'Missing data'],
    [
      'only 120 daily bars (<253): the one-year fields cover the history that exists',
      'Missing data',
    ],
    [
      'only 24 weekly bars (<60): the weekly structure read is unreliable',
      'Missing data',
    ],
    ['benchmark index not configured for this market', 'Missing data'],
    ['benchmark index bars unavailable: HTTPError()', 'Fetch failed'],
    ['benchmark index history too short (30 bars)', 'Missing data'],
    ['benchmark index history too short for the regime read', 'Missing data'],
    // src/tiered_analysis/providers/positioning.py
    [
      'CBOE published no 30-day implied volatility — implied stock volatility omitted',
      'Missing data',
    ],
    ['next report date unknown — implied report-day move omitted', 'Missing data'],
    ['next report date unparseable — implied report-day move omitted', 'Missing data'],
    [
      'next report is more than 21 days away — option prices there mostly reflect ordinary drift, not the report jump; implied report-day move omitted',
      'Missing data',
    ],
    ['CBOE published no stock price — implied report-day move omitted', 'Missing data'],
    [
      'no usable at-the-money quotes on the post-report expiration — implied report-day move omitted',
      'Missing data',
    ],
    [
      'no fetched option expiration falls after the next report date — implied report-day move omitted',
      'Missing data',
    ],
    ['Yahoo summary failed for AAPL: HTTPError()', 'Fetch failed'],
    ['institutional holders failed for AAPL: HTTPError()', 'Fetch failed'],
    ['insider transactions failed for AAPL: HTTPError()', 'Fetch failed'],
    ['options chain failed for AAPL: HTTPError()', 'Fetch failed'],
    ['no listed options found for AAPL', 'Missing data'],
    ['earnings date lookup failed for AAPL: HTTPError()', 'Fetch failed'],
    ['Yahoo returned no short-interest fields for AAPL', 'Missing data'],
    ['Yahoo returned no ownership fields for AAPL', 'Missing data'],
    // src/tiered_analysis/providers/fundamentals_us.py
    ['earnings history failed for AAPL: HTTPError()', 'Fetch failed'],
    [
      'no earnings history rows for AAPL — the beat and report-day-move fields are blank',
      'Missing data',
    ],
    ['bars for earnings reaction failed: HTTPError()', 'Fetch failed'],
    [
      'too few earnings reports inside the bar history (2) for the earnings-day move',
      'Missing data',
    ],
    ['EPS estimate trend failed for AAPL: HTTPError()', 'Fetch failed'],
    // src/tiered_analysis/providers/macro_econ.py
    ['FRED_API_KEY is not set; get a free key at fred.stlouisfed.org', 'Settings'],
    ['FRED release calendar for inflation data (CPI) failed: HTTPError()', 'Fetch failed'],
    ['no upcoming inflation data (CPI) release date found', 'Missing data'],
    [
      "FOMC decision-date table exhausted; extend FOMC_DECISION_DATES from the Fed's published calendar",
      'Missing data',
    ],
    // src/tiered_analysis/cross_fields.py
    [
      'sector unknown (fundamentals carries no sector label); sector comparison fields absent',
      'Missing data',
    ],
    [
      "sector 'Technology' has no sector-ETF mapping (US sectors only for now); sector comparison fields absent",
      'Missing data',
    ],
    [
      'sector comparison needs the market benchmark returns, which are absent; sector comparison fields absent',
      'Missing data',
    ],
    ['sector ETF XLK bars unavailable: HTTPError(); sector comparison fields absent', 'Fetch failed'],
    ['sector ETF XLK history too short (30 bars); sector comparison fields absent', 'Missing data'],
    // src/tiered_analysis/tiers.py + debate.py + plan_review.py
    ['tier-1 analysis failed for AAPL: RuntimeError()', 'Verdict'],
    ['no collected evidence to vote on — no outlook (re-run)', 'Verdict'],
    ['debate LLM call failed: RuntimeError()', 'AI reply'],
    ['no gradable report fields collected — tier-2 verdict voided', 'Verdict'],
    [
      'plan-review adjustment for stop_loss dropped — citations unfixable: bad ref',
      'Citation check',
    ],
    ['plan-review reply problem: missing field', 'AI reply'],
    ['plan review skipped: LlmConfigError()', 'Settings'],
    ['plan review LLM call failed: RuntimeError()', 'AI reply'],
    [
      'plan review did not converge: the adjusted plan still tripped risk checks after every round, so all adjustments were discarded and the computed plan stands',
      'Risk check',
    ],
    // src/tiered_analysis/integration.py + settings.py
    ['positioning provider crashed: RuntimeError()', 'Fetch failed'],
    ['TIERED_REWARD_RISK=0.5 must be above 1 — using the default 2.0', 'Settings'],
  ];

  it.each(SAMPLES)('rewrites %s', (raw, keyword) => {
    const note = friendlyWarning(raw, t);
    expect(note, `no rule matched: ${raw}`).not.toBeNull();
    expect(note?.keyword).toBe(keyword);
    // No rewrite may leak a Python repr or a source identifier.
    expect(note?.text).not.toMatch(/Error\(|_[a-z]+_|\bsma_\d|HTTPError/);
  });

  it('a "round N:" prefix does not defeat the rules', () => {
    // plan_review.py prefixes retried rounds; ^-anchored patterns would
    // otherwise all miss.
    const note = friendlyWarning('round 2: plan-review reply problem: missing field', t);
    expect(note?.keyword).toBe('AI reply');
  });

  it('an unknown shape keeps its raw text under the generic keyword', () => {
    const note = friendlyWarning('something nobody has ever written', t);
    expect(note.keyword).toBe('Data note');
    expect(note.text).toBe('something nobody has ever written');
  });
});
