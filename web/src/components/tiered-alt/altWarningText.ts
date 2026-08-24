import { metricEntry } from '../../i18n/metricLabels';
import type { UiLanguage, UiTextKey } from '../../i18n/uiText';

// The backend records its data notes as engineer-speak ("unparseable sniper
// level ideal_buy=…"). Each known shape is matched here and rewritten as a
// plain-English sentence via an i18n key, led by a fixed keyword — chosen
// per rule from the closed list below (owner decision 2026-07-24), never
// generated, mirroring the plan-warnings modal's id → keyword map. Unknown
// shapes keep their raw text (never invent a friendly sentence we can't
// back up) under the generic "Data note" keyword, so every note leads
// with a keyword (owner request 2026-08-09).

type Translate = (key: UiTextKey, params?: Record<string, string | number>) => string;

// The closed keyword list. Every note leads with one of these.
const KEY = {
  missingData: 'tiered.note.key.missingData',
  fetchFailed: 'tiered.note.key.fetchFailed',
  citations: 'tiered.note.key.citations',
  aiReply: 'tiered.note.key.aiReply',
  levels: 'tiered.note.key.levels',
  verdict: 'tiered.note.key.verdict',
  vote: 'tiered.note.key.vote',
  debate: 'tiered.note.key.debate',
  riskCheck: 'tiered.note.key.riskCheck',
  settings: 'tiered.note.key.settings',
  // The fallback for note shapes no rule recognizes.
  other: 'tiered.note.key.other',
  // The plan card's warnings row shows these same facts under these same
  // keywords — the notes list must not word them differently.
  rewardRatio: 'tiered.alt.warnKey.reward_below_goal',
  downtrend: 'tiered.alt.warnKey.downtrend',
} as const satisfies Record<string, UiTextKey>;

// Backend sniper-level source names → the level labels users already know.
const SNIPER_SOURCE_LABEL_KEYS: Record<string, UiTextKey> = {
  ideal_buy: 'tiered.levels.entry',
  secondary_buy: 'tiered.levels.secondaryEntry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
};

// Level keys as they appear in adjustment warnings ("adjustment for entry …").
const LEVEL_LABEL_KEYS: Record<string, UiTextKey> = {
  entry: 'tiered.levels.entry',
  shares: 'tiered.levels.shares',
  secondary_entry: 'tiered.levels.secondaryEntry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
};

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// Backend stage names → the role labels the debate tree already uses
// (owner request 2026-08-05: retry/invalid notes lead with the AI's
// role). Unknown stages (old stored formats) fall back to the raw stage
// text — never invent a label.
const STAGE_ROLES: Record<string, (t: Translate) => string> = {
  'first analyst grade sheet': (t) => t('tiered.tree.lister', { n: 1 }),
  'second analyst grade sheet': (t) => t('tiered.tree.lister', { n: 2 }),
  'first analyst list': (t) => t('tiered.tree.lister', { n: 1 }),
  'second analyst list': (t) => t('tiered.tree.lister', { n: 2 }),
  'check round': (t) => t('tiered.role.checkRound'),
  'deciding round': (t) => t('tiered.role.decidingRound'),
  'report outline': (t) => t('tiered.role.reportOutline'),
};

const levelLabel = (key: string, t: Translate): string =>
  LEVEL_LABEL_KEYS[key] ? t(LEVEL_LABEL_KEYS[key]) : key;

const stageRole = (stage: string, t: Translate): string =>
  STAGE_ROLES[stage] ? STAGE_ROLES[stage](t) : stage;

interface NoteRule {
  pattern: RegExp;
  keywordKey: UiTextKey;
  toText: (match: RegExpMatchArray, t: Translate) => string;
}

const NOTE_RULES: NoteRule[] = [
  {
    pattern: /^reward below goal: .*reward-to-risk at ([\d.]+), below your ([\d.]+)/,
    keywordKey: KEY.rewardRatio,
    toText: (m, t) =>
      t('tiered.alt.rewardBelowGoal', { ratio: m[1], goal: m[2] }),
  },
  {
    pattern: /^trend warning: close .* is at or below the (?:50|60)-day average/,
    keywordKey: KEY.downtrend,
    toText: (_m, t) => t('tiered.note.downtrend'),
  },
  {
    pattern: /^sma_(?:50|60) unavailable — trend check skipped$/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.trendCheckSkipped'),
  },
  {
    pattern: /^unparseable sniper level (\w+)='?(.*?)'?$/,
    keywordKey: KEY.levels,
    toText: (m, t) =>
      t('tiered.note.textLevel', {
        level: SNIPER_SOURCE_LABEL_KEYS[m[1]] ? t(SNIPER_SOURCE_LABEL_KEYS[m[1]]) : m[1],
        text: m[2],
      }),
  },
  {
    pattern: /^sniper points missing from tier-1 result$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.levelsMissing'),
  },
  {
    pattern: /^page fetch blocked for (\S+); using shorter search extract instead$/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.pageBlocked', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^fetch (?:failed for|returned no content for) (\S+?):?(?:\s|$)/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.fetchFailed', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^EDGAR (?:fundamentals failed|returned no usable (?:annual|statement) facts)/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.fundamentalsUnavailable'),
  },
  {
    pattern: /^Yahoo (?:valuation failed|returned no valuation ratios)/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.valuationUnavailable'),
  },
  {
    pattern: /^FRED series (\S+) (?:failed|returned no data)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.macroUnavailable', { series: m[1] }),
  },
  {
    pattern: /^indicators lacking history/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.indicatorNoHistory'),
  },
  {
    pattern: /^macro fields lacking data/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.macroFieldMissing'),
  },
  {
    // Both the retired "from Yahoo" wording and the source-neutral one.
    pattern: /^options open interest (?:from Yahoo is )?missing or zero/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.optionsOiMissing'),
  },
  {
    pattern: /^options volume (?:from Yahoo is )?missing or zero/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.optionsVolumeMissing'),
  },
  {
    pattern: /^Yahoo returned no insider transaction rows/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.insiderRowsMissing'),
  },
  {
    pattern: /^LLM sentiment output unparseable or empty$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.sentimentUnreadable'),
  },
  {
    pattern: /^no verifiable citations survive — discarding narrative$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.citationsDiscarded'),
  },
  {
    pattern: /^citation dropped: quote not found in (\S+?):?\s/,
    keywordKey: KEY.citations,
    toText: (m, t) => t('tiered.note.citationQuoteMissing', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^citation dropped: invalid source index/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.citationBadIndex'),
  },
  {
    pattern: /^malformed adjustment entry ignored$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.adjustmentMalformed'),
  },
  {
    pattern: /^adjustment for unknown level\b/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.adjustUnknownLevel'),
  },
  {
    pattern: /^adjustment for '?(\w+)'?\b/,
    keywordKey: KEY.levels,
    toText: (m, t) =>
      t('tiered.note.adjustmentRejected', {
        level: levelLabel(m[1], t),
      }),
  },
  {
    pattern: / — falling back to the ATR stop$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.stopFallback'),
  },
  {
    pattern: /^no ATR available to derive a volatility stop$/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noAtrStop'),
  },
  {
    pattern: /^no usable ATR — no volatility stop, and no target without a stop$/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noAtrStopTarget'),
  },
  {
    pattern: /^no deeper support strictly below the ideal entry — no backup entry$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noBackupEntry'),
  },
  {
    pattern: /^no usable entry price — cannot place a stop$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noEntryNoStop'),
  },
  // --- v8 evidence-vote notes (tier 2) + format-2 risk-vote notes
  // (tier 3): the two engines share their phrasing, differing only in
  // bullet/risk wording ---
  {
    // v8 wording ("list") and v12 wording ("grade sheet").
    pattern: /^(first|second) analyst (?:list|grade sheet) invalid after retry — proceeding with/,
    keywordKey: KEY.vote,
    toText: (m, t) =>
      t('tiered.note.listerDegradedRole', {
        role: stageRole(`${m[1]} analyst grade sheet`, t),
      }),
  },
  {
    pattern: /^both analyst (?:lists|grade sheets) invalid after retry — tier-2 verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.sheetsVoided'),
  },
  {
    pattern: /^debate produced no verdict — no outlook \(re-run\)$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.noOutlook'),
  },
  {
    pattern: /^both analyst lists invalid after retry — tier-3 risk verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.riskVoided'),
  },
  {
    pattern: /^risk stress produced no verdict — direction falls back to tier 2$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.riskFellBack'),
  },
  {
    pattern: /^merge invalid after retry — second list dropped$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.mergeDegraded'),
  },
  {
    pattern: /^check round invalid after retry — (?:bullets|risks) counted on/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.checkDegraded'),
  },
  {
    pattern: /^deciding round invalid after retry — tied (?:bullets|risks) excluded/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.tiebreakDegraded'),
  },
  {
    pattern: /^analyst \S+: citations unfixable .* — struck from the list$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.struckBullet'),
  },
  {
    pattern: /^vote on \S+ discarded — citations unfixable/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.voteDiscarded'),
  },
  {
    pattern: /^no deciding vote for \S+ — excluded as unresolved$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.unresolved'),
  },
  {
    pattern: /^every (?:bullet|risk) was listed by both analysts — check round skipped$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.allConfirmed'),
  },
  {
    pattern: / — the final score rests on a thin base$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.thinBase'),
  },
  // --- v7 tree-debate notes ---
  {
    pattern: /^defender \S+: citations unfixable .* — struck from the debate$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.struckBullet'),
  },
  {
    pattern: /^attacker \S+: citations unfixable .* — bullet dropped$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.attackerBulletDropped'),
  },
  {
    pattern: /citation-fix reply invalid — fix round lost$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.fixRoundLost'),
  },
  {
    pattern: /^summary citations unfixable — those values are shown without links$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.summaryLinksDropped'),
  },
  // --- v6 tree-debate notes ---
  {
    pattern: /citation check failed mechanically$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.valueMismatch'),
  },
  {
    pattern: / — link dropped$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.linkDropped'),
  },
  {
    pattern: /evidence restored to the final pool$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.restoredEvidence'),
  },
  {
    pattern: /included in the final pool$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.includedAddition'),
  },
  // --- v5 tree-debate notes ---
  {
    pattern: /^(?:defender opening|defender reply|judge rulings) invalid after retry — tier-2 verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.stageInvalid'),
  },
  {
    pattern: /^attacker (?:opening|review) invalid after retry — proceeding without/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.attackerDegraded'),
  },
  {
    pattern: /^(.+) needed a retry — first reply was invalid$/,
    keywordKey: KEY.aiReply,
    toText: (m, t) =>
      t('tiered.note.stageRetriedRole', { role: stageRole(m[1], t) }),
  },
  {
    pattern: /^(.+?)(?: was not JSON even after a retry$| invalid after retry: )/,
    keywordKey: KEY.aiReply,
    toText: (m, t) =>
      t('tiered.note.stageInvalidRole', { role: stageRole(m[1], t) }),
  },
  {
    pattern: /^defender accepted an attack the judge ruled wrong/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.concededFlawedAttack'),
  },
  {
    pattern: /^attacker raised no challenges — defender response skipped/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.noChallenges'),
  },
  {
    pattern: /^no surviving evidence to weigh/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.emptyLedger'),
  },
  {
    pattern: / — the weight rests on a thin base$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.thinBase'),
  },
  {
    pattern: /^(defender|attacker|judge) cited evidence that does not resolve to a single value/,
    keywordKey: KEY.citations,
    toText: (m, t) =>
      t('tiered.note.treeBadRefs', { side: t(`tiered.tree.${m[1]}` as UiTextKey) }),
  },
  // --- pre-v5 debate notes (old stored runs) ---
  {
    // v3: "bull reply was not JSON — argument kept as plain text, no score"
    // v4: "bull argument|attack|response was not JSON — kept as plain text[, no score]"
    pattern: /^(bull|bear) (?:reply|argument|attack|response) was not JSON — .*kept as plain text/,
    keywordKey: KEY.aiReply,
    toText: (m, t) =>
      t('tiered.note.debaterNotJson', {
        side: t(m[1] === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear'),
      }),
  },
  {
    pattern: /^(bull|bear) (?:bullishness|position score) .* is not a whole number 0-10 — dropped$/,
    keywordKey: KEY.aiReply,
    toText: (m, t) =>
      t('tiered.note.debaterScoreDropped', {
        side: t(m[1] === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear'),
      }),
  },
  {
    pattern: /^no usable (?:bullishness|position) score from .* — tier-2 verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.debateVoided'),
  },
  {
    pattern: /^(bull|bear) cited evidence that does not resolve — invalid refs dropped$/,
    keywordKey: KEY.citations,
    toText: (m, t) =>
      t('tiered.note.debaterBadRefs', {
        side: t(m[1] === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear'),
      }),
  },
  {
    pattern: /^grading judge gave no quote for .* — kept, flagged$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.gradingNoQuote'),
  },
  {
    pattern: /^grading judge quote for .* not found verbatim in the transcript — kept, flagged$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.gradingQuoteMismatch'),
  },
  {
    pattern: /^grading judge .* voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.gradingVoided'),
  },
  {
    pattern: /^both debaters graded zero validity/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.zeroValidity'),
  },
  {
    pattern: /^(?:judge summary unparseable|summary LLM call failed: .*) — computed verdict stands$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.summaryFailed'),
  },
  {
    pattern: /^(?:risk )?judge confidence .* unusable — dropped$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.judgeConfidenceDropped'),
  },
  {
    pattern: /^judge gave no summary$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.judgeNoSummary'),
  },
  {
    pattern: /^risk judge gave no summary$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.riskNoSummary'),
  },
  {
    pattern: /^(?:judge|risk) claim not anchored to evidence \(kept, flagged\)/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.claimNoEvidence'),
  },
  {
    pattern: /^risk judge stop advice .* unusable/,
    keywordKey: KEY.riskCheck,
    toText: (_m, t) => t('tiered.note.stopAdviceUnusable'),
  },
  {
    pattern: /^tightened stop .* — dropped$/,
    keywordKey: KEY.riskCheck,
    toText: (_m, t) => t('tiered.note.tightenedStopDropped'),
  },
  {
    pattern: / is not a number — ignored$/,
    keywordKey: KEY.settings,
    toText: (_m, t) => t('tiered.note.badSetting'),
  },

  // ---- Audit 2026-08-08 -------------------------------------------------
  // Everything below used to fall through and render as the backend's own
  // engineer text — Python exception reprs ("HTTPError(...)"), variable
  // names ("bars_loader", "sma_50 / sma_200 / support_1") and even a note
  // addressed to a developer ("extend FOMC_DECISION_DATES"). Appended in a
  // block so the older, more specific rules above always win first.

  // Fetch failures: each names the source in words and says what went blank.
  {
    pattern: /^bars_loader failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.barsLoadFailed'),
  },
  {
    pattern: /^Yahoo summary failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.yahooSummaryFailed'),
  },
  {
    pattern: /^institutional holders failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.holdersFailed'),
  },
  {
    pattern: /^insider transactions failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.insiderFetchFailed'),
  },
  {
    pattern: /^options chain failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.optionsFetchFailed'),
  },
  {
    pattern: /^earnings date lookup failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.earningsDateFailed'),
  },
  {
    pattern: /^earnings history failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.earningsHistoryFailed'),
  },
  {
    pattern: /^bars for earnings reaction failed/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.reactionBarsFailed'),
  },
  {
    pattern: /^EPS estimate trend failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.epsTrendFailed'),
  },
  {
    pattern: /^EPS revision counts failed for/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.epsRevisionsFailed'),
  },
  {
    pattern: /^FRED release calendar for (.+) failed:/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.releaseCalendarFailed', { label: m[1] }),
  },
  {
    pattern: /^benchmark index bars unavailable/,
    keywordKey: KEY.fetchFailed,
    toText: (_m, t) => t('tiered.note.benchmarkBarsFailed'),
  },
  {
    pattern: /^sector ETF (\S+) bars unavailable/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.sectorBarsFailed', { ticker: m[1] }),
  },
  {
    pattern: /^(\w+) provider crashed/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.providerCrashed', { dimension: m[1] }),
  },
  {
    pattern: /^tier-1 analysis failed for/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.tier1Failed'),
  },
  {
    pattern: /^debate LLM call failed/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.debateCallFailed'),
  },
  {
    pattern: /^plan review LLM call failed/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.planReviewCallFailed'),
  },
  {
    pattern: /^plan review skipped:/,
    keywordKey: KEY.settings,
    toText: (_m, t) => t('tiered.note.planReviewSkipped'),
  },

  // Thin or absent history.
  {
    pattern: /^insufficient history for \S+: (\d+) bars < (\d+) required/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.insufficientHistory', { bars: m[1], min: m[2] }),
  },
  {
    pattern: /^only (\d+) daily bars \(<(\d+)\)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.shortDailyHistory', { bars: m[1], year: m[2] }),
  },
  {
    pattern: /^only (\d+) weekly bars \(<(\d+)\)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.shortWeeklyHistory', { bars: m[1], target: m[2] }),
  },
  {
    pattern: /^benchmark index not configured/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.benchmarkNotConfigured'),
  },
  {
    pattern: /^benchmark index history too short \((\d+) bars\)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.benchmarkShort', { bars: m[1] }),
  },
  {
    pattern: /^benchmark index history too short for the regime read/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.benchmarkShortRegime'),
  },

  // Options board shortfalls.
  {
    pattern: /^CBOE published no 30-day implied volatility/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noImpliedVol'),
  },
  {
    pattern: /^CBOE published no stock price/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noOptionsStockPrice'),
  },
  {
    pattern: /^next report date unknown/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.reportDateUnknown'),
  },
  {
    pattern: /^next report date unparseable/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.reportDateUnreadable'),
  },
  {
    pattern: /^next report is more than (\d+) days away/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.reportTooFar', { days: m[1] }),
  },
  {
    pattern: /^no usable at-the-money quotes/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noAtmQuotes'),
  },
  {
    pattern: /^no fetched option expiration falls after/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noPostReportExpiry'),
  },
  {
    pattern: /^no listed options found for/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noListedOptions'),
  },

  // Disclosure and fundamentals shortfalls.
  {
    pattern: /^Yahoo returned no short-interest fields/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noShortInterest'),
  },
  {
    pattern: /^Yahoo returned no ownership fields/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noOwnership'),
  },
  {
    pattern: /^no earnings history rows for/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noEarningsHistory'),
  },
  {
    pattern: /^too few earnings reports inside the bar history \((\d+)\)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.tooFewReports', { count: m[1] }),
  },

  // Economy data.
  {
    pattern: /^FRED_API_KEY is not set/,
    keywordKey: KEY.settings,
    toText: (_m, t) => t('tiered.note.fredKeyMissing'),
  },
  {
    pattern: /^no upcoming (.+) release date found/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.noReleaseDate', { label: m[1] }),
  },
  {
    pattern: /^FOMC decision-date table exhausted/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.fomcTableExhausted'),
  },

  // Sector comparison.
  {
    pattern: /^sector unknown \(/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.sectorUnknown'),
  },
  {
    pattern: /^sector '(.+)' has no sector-ETF mapping/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.sectorNoEtf'),
  },
  {
    pattern: /^sector comparison needs the market benchmark returns/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.sectorNeedsBenchmark'),
  },
  {
    pattern: /^sector ETF (\S+) history too short \((\d+) bars\)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.sectorShort', { ticker: m[1], bars: m[2] }),
  },

  // Trade plan.
  {
    pattern: /^no close price —/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noClosePrice'),
  },
  {
    pattern: /^no structural support anchors/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noEntryAnchor'),
  },
  {
    pattern: /^technicals unavailable — deterministic levels/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noTechnicalsForLevels'),
  },
  {
    pattern: /^duplicate adjustment for '?(\w+)'?/,
    keywordKey: KEY.levels,
    toText: (m, t) =>
      t('tiered.note.duplicateAdjust', { level: levelLabel(m[1], t) }),
  },
  {
    pattern: /^plan-review adjustment for '?(\w+)'? dropped/,
    keywordKey: KEY.citations,
    toText: (m, t) =>
      t('tiered.note.planAdjustDropped', { level: levelLabel(m[1], t) }),
  },
  {
    pattern: /^plan-review reply problem/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.planReplyProblem'),
  },
  {
    pattern: /^plan review did not converge/,
    keywordKey: KEY.riskCheck,
    toText: (_m, t) => t('tiered.note.planNoConverge'),
  },

  // Verdict.
  {
    pattern: /^no gradable report fields collected/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.noGradableFields'),
  },
  {
    pattern: /^no collected evidence to vote on/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.noEvidenceToVote'),
  },

  // Settings.
  {
    pattern: /must be above 1 — using the default/,
    keywordKey: KEY.settings,
    toText: (_m, t) => t('tiered.note.rewardRiskDefaulted'),
  },
];

// ---- plan-note routing (owner request 2026-08-09) ----------------------
// Warnings the trade-plan machinery emits — the AI's sniper levels
// (tiers.py), the deterministic levels engine (levels.py, stops.py) and
// the plan review (plan_review.py). They describe the PLAN, not the
// analysis, so the plan card is their only home; on runs whose outlook
// renders no plan card they disappear with it instead of leaking onto
// the preliminary-analysis card.
const PLAN_NOTE_RES: RegExp[] = [
  /^unparseable sniper level /,
  /^sniper points missing from tier-1 result$/,
  /^reward below goal: /,
  /^trend warning: /,
  /^sma_(?:50|60) unavailable — trend check skipped$/,
  /^no close price —/,
  /^no structural support anchors/,
  /^no usable ATR — /,
  /^no ATR available to derive a volatility stop$/,
  / — falling back to the ATR stop$/,
  /^no usable entry price — cannot place a stop$/,
  /^technicals unavailable — deterministic levels/,
  /^adjustment for /,
  /^duplicate adjustment for /,
  /^malformed adjustment entry ignored$/,
  // Retired backup-entry note old stored runs still carry.
  /^no deeper support strictly below/,
  /^plan-review /,
  /^plan review /,
];

// True when a backend run warning is about the trade plan (see the list
// above). Plan-review retries prefix their notes with "round N: ".
export function isPlanNote(raw: string): boolean {
  const text = raw.replace(/^round \d+: /, '');
  return PLAN_NOTE_RES.some((pattern) => pattern.test(text));
}

// ---- rich note slots (owner request 2026-08-23) -------------------------
// Some notes carry values that the field-notes modal renders live: a
// report-field name as a jump link to that field's row, or a day count
// with its own date-minus-date receipt. The slot data stays plain here
// (this module renders no JSX); AltFieldNotes builds the elements.

/** Another report field, shown under its exact display name (its
    metricLabels `short`) as a link that jumps to its row. */
export interface NoteMetricLinkSlot {
  kind: 'metricLink';
  /** The metricLabels key whose `short` names the link. */
  term: string;
  /** Payload row paths to try in order (new format first). */
  paths: string[];
}

/** A "days until the next quarterly report" count, clickable to open
    its calculation receipt (report date − today). */
export interface NoteDaysReceiptSlot {
  kind: 'daysReceipt';
  days: number;
  /** ISO dates the receipt plugs in. */
  reportDate: string;
  today: string;
}

export type NoteSlot = NoteMetricLinkSlot | NoteDaysReceiptSlot;

export interface FriendlyNote {
  /** The fixed keyword the note leads with (already translated). */
  keyword: string;
  /** The plain-English sentence (already translated, slots resolved
      to their plain names/numbers). */
  text: string;
  /** Rich notes only: `text` with its {name} tokens still in place… */
  template?: string;
  /** …and how each token renders live. */
  slots?: Record<string, NoteSlot>;
}

interface RichRule {
  pattern: RegExp;
  keywordKey: UiTextKey;
  build: (
    match: RegExpMatchArray,
    t: Translate,
  ) => {
    templateKey: UiTextKey;
    params?: Record<string, string | number>;
    slots: Record<string, NoteSlot>;
  };
}

// Note shapes whose modal rendering carries live elements. Matched
// before NOTE_RULES; the older plain shapes stay there for stored runs.
const RICH_RULES: RichRule[] = [
  {
    // 2026-08-23 note format: the actual countdown plus both dates, so
    // the modal shows the real number of days with its receipt.
    pattern:
      /^next quarterly report is (\d+) days away \(report (\d{4}-\d{2}-\d{2}), today (\d{4}-\d{2}-\d{2})\) — more than (\d+) days out/,
    keywordKey: KEY.missingData,
    build: (m) => ({
      templateKey: 'tiered.note.reportTooFarExact',
      params: { max: m[4] },
      slots: {
        days: {
          kind: 'daysReceipt',
          days: Number(m[1]),
          reportDate: m[2],
          today: m[3],
        },
      },
    }),
  },
  {
    pattern: /^implied report-day move missing — report-move ratio/,
    keywordKey: KEY.missingData,
    build: () => ({
      templateKey: 'tiered.note.ratioMissingIngredient',
      slots: {
        field: {
          kind: 'metricLink',
          term: 'implied_report_move_pct',
          paths: ['positioning.options.implied_report_move_pct'],
        },
      },
    }),
  },
  {
    pattern: /^realized 4q average report-day move missing or zero — report-move ratio/,
    keywordKey: KEY.missingData,
    build: () => ({
      templateKey: 'tiered.note.ratioMissingIngredient',
      slots: {
        field: {
          kind: 'metricLink',
          term: 'reaction_avg_abs_pct',
          paths: ['fundamentals.quarterly_report.reaction_avg_abs_pct'],
        },
      },
    }),
  },
];

// A slot's plain-text stand-in — what non-rich renderings (and copied
// text) show in place of the live element.
function slotText(slot: NoteSlot, language: UiLanguage): string {
  if (slot.kind === 'metricLink') {
    return `"${metricEntry(slot.term, language)?.short ?? slot.term}"`;
  }
  return String(slot.days);
}

function resolveSlots(
  template: string,
  slots: Record<string, NoteSlot>,
  language: UiLanguage,
): string {
  return template.replace(/\{(\w+)\}/g, (token, name: string) => {
    const slot = slots[name];
    return slot === undefined ? token : slotText(slot, language);
  });
}

// Keyword + plain-English rewrite of one backend data note. Unknown
// shapes keep their raw text under the generic "Data note" keyword.
export function friendlyWarning(
  raw: string,
  t: Translate,
  language: UiLanguage = 'en',
): FriendlyNote {
  const text = raw.replace(/^round \d+: /, '');
  for (const rule of RICH_RULES) {
    const match = text.match(rule.pattern);
    if (match) {
      const { templateKey, params, slots } = rule.build(match, t);
      const template = t(templateKey, params);
      return {
        keyword: t(rule.keywordKey),
        text: resolveSlots(template, slots, language),
        template,
        slots,
      };
    }
  }
  for (const rule of NOTE_RULES) {
    const match = text.match(rule.pattern);
    if (match) {
      return { keyword: t(rule.keywordKey), text: rule.toText(match, t) };
    }
  }
  return { keyword: t(KEY.other), text: raw };
}
