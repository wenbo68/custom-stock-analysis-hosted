import apiClient from './index';

// Types mirror the backend JSON verbatim (snake_case). Dimension payloads
// hold metric names like revenue_yoy_pct — do not camelize them.
export type TieredCitation = {
  source_name: string;
  url: string | null;
  title: string | null;
  snippet: string | null;
};

// Technicals v2 UI receipt (2026-07-28): how a derived payload metric was
// computed, keyed by "group.key" (e.g. "daily.rsi_14"). One-outcome
// formulas carry a `formula` string; rules with several possible outcomes
// carry `branches` — one {label, condition} line per outcome, the
// catch-all with condition null. The plugged-line style is told apart by
// inspecting the words: every input token appears → substitution (numbers
// plug in place); tokens absent → listed ("ingredient = value" pairs —
// rules whose ingredients are words, like ma_stack = up); empty inputs →
// words-only (aggregates over a whole series).
export type TieredMetricBranch = {
  label: string;
  /** null = the catch-all ("else") branch. */
  condition: string | null;
};

export type TieredMetricFormula = {
  formula?: string | null;
  branches?: TieredMetricBranch[] | null;
  inputs: Record<string, number | string>;
};

export type TieredDimension = {
  dimension: string;
  kind: 'numeric' | 'textual';
  is_actionable: boolean;
  payload: Record<string, unknown> | null;
  /** Computation receipts keyed "group.key". Technicals ships them from
      2026-07-27, fundamentals from 2026-07-29; absent on the other
      dimensions and on old stored runs. */
  formulas?: Record<string, TieredMetricFormula> | null;
  narrative: string | null;
  warnings: string[];
  /** The same notes as `warnings`, keyed by the payload field
      ("group.key") each is about (2026-08-05). A warning absent from
      this map has no field to live on and stays a card-level note.
      Absent on old stored runs. */
  field_notes?: Record<string, string[]> | null;
  citations: TieredCitation[];
};

export type TieredLevels = {
  entry: number | null;
  secondary_entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
};

// v2 slice 3 audit trail: per-level formula base + validated AI adjustment.
// The plan-review redesign (2026-07-22) adds a "shares" entry in the same
// shape (base = count from the computed levels; adjusted_inputs = the
// final levels a mechanical recompute used) and `links` — inline
// citations for the adjustment reason, in the debate-link shape.
// One adjustment reason: the flagged check it fixes (a fixed keyword id
// the UI translates) plus one cited sentence.
export type TieredLevelReason = {
  check: string;
  text: string;
  links?: TieredDebateLink[];
};

export type TieredLevelDetail = {
  base: number | null;
  formula: string | null;
  inputs: Record<string, number> | null;
  adjusted: number | null;
  /** Old stored runs: one paragraph. New runs carry `reasons` instead. */
  reason?: string | null;
  reasons?: TieredLevelReason[] | null;
  evidence: string[];
  links?: TieredDebateLink[];
  adjusted_inputs?: Record<string, number> | null;
  /** Shares only: the mechanical recompute from the adjusted levels,
   *  before any AI trim — the receipt's result line. */
  mechanical?: number | null;
  rejection: string | null;
  final: number | null;
};

// One round of the check-adjust cycle that ended with a risk check still
// firing. Present (non-empty) only when the review never converged and
// the computed plan was kept — the UI words it in the blue-keep modal.
export type TieredReviewFailure = {
  round: number;
  checks: string[];
};

export type TieredLevelsDetail = {
  levels: Record<string, TieredLevelDetail>;
  warnings: string[];
  review_failures?: TieredReviewFailure[] | null;
};

// One structured trade-plan warning: numbers only, the frontend words it.
export type TieredPlanWarning = {
  id: string;
  values: Record<string, unknown>;
};

// Per-column warning lists for the plan table's Warnings row.
export type TieredPlanWarnings = Record<string, TieredPlanWarning[]>;

export type TieredAnchoredReason = {
  claim: string;
  evidence: string[];
};

// v4 judge grade for one validity axis: the 0-5 score plus, below 5, the
// exact offending sentence and why it is wrong (both null at 5/5 → N/A).
export type TieredAxisGrade = {
  score: number;
  quote?: string | null;
  why?: string | null;
};

// One debater's numbers — its own 0-10 position score plus the judge's
// three 0-5 validity grades; weight = (sum of grades) / 15. v3 runs store
// the position score as `bullishness` and the axes as bare numbers; v4
// runs store `position_score` and axis objects with quote/why comments.
export type TieredDebaterScore = {
  position_score?: number;
  bullishness?: number;
  citation_validity: number | TieredAxisGrade;
  knowledge_validity: number | TieredAxisGrade;
  logical_validity: number | TieredAxisGrade;
  weight: number;
  notes?: string | null;
};

// --- v5/v6/v7 debate tree (defender/attacker/judge) ---

// Inline citation. v6: text = the words underlined in the claim, value =
// the claimed number (mismatch marks a code-detected contradiction).
// v7: payload links carry value (the report's display string; the claim
// contains it verbatim) with text null; sentiment links carry text (the
// words resting on that news source) with value null.
export type TieredDebateLink = {
  text?: string | null;
  ref: string;
  value: number | string | null;
  mismatch?: boolean;
};

// One citation-or-logic check; 'invalid' carries the reason + citations.
export type TieredDebateCheck = {
  verdict: 'valid' | 'invalid';
  reason: string | null;
  citations: string[];
};

// The defender's response to one challenge: its own checks ON the
// attack/addition. v6 stores the citation/logic pair (both valid →
// accepted); v7 stores the single `check` (valid → accepted). All three
// fields optional so both generations type-check.
export type TieredDebateResponse = {
  accepted: boolean;
  citation_check?: TieredDebateCheck;
  logic_check?: TieredDebateCheck;
  check?: TieredDebateCheck;
};

// The judge's word on one axis of a defender item: its own check when the
// axis was unattacked, a ruling on the attack when it was.
export type TieredDebateJudgeAxis = {
  kind: 'reason_check' | 'attack_ruling';
  verdict: 'valid' | 'invalid' | 'attack_right' | 'attack_wrong';
  reason: string | null;
  citations: string[];
};

export type TieredDebateJudgeAddition = {
  kind: 'addition_ruling';
  verdict: 'real' | 'bogus';
  reason: string | null;
  citations: string[];
};

// One v8 vote on a bullet: the check round's second vote or the
// deciding round's tiebreaker. Reasons carry the same code-verified
// links the bullets use. v10 votes carry the voter's own importance
// rating of the bullet (1-3; 1-5 since v11); v11 adds one plain
// sentence saying why (weight_reason).
export type TieredDebateVote = {
  role: 'checker' | 'decider';
  verdict: 'valid' | 'invalid';
  reason: string | null;
  links: TieredDebateLink[];
  weight?: number;
  weight_reason?: string | null;
};

// v11: one lister's own rating of a bullet they authored — which lister
// (1 or 2), the 1-5 importance score, and why.
export type TieredDebateAuthorVote = {
  lister: number;
  weight: number;
  weight_reason?: string | null;
};

// One evidence item of the tree with everything that happened to it.
// v5 runs store citations + the count/outcome ledger; v6 runs store
// links + value_check + the per-axis checks; v7 runs store single-axis
// fields (attacker_check, one response, one judge line) plus struck +
// problems for bullets whose citations code could not fix; v8 runs
// store authors (how many analysts listed it independently) + votes —
// all optional so every generation renders.
export type TieredDebateItem = {
  id: string;
  dimension: string;
  direction: 'bullish' | 'bearish';
  claim: string;
  citations?: string[];
  links?: TieredDebateLink[];
  value_check?: { verdict: 'valid' | 'invalid'; problems: string[] } | null;
  struck?: boolean;
  problems?: string[];
  authors?: number;
  votes?: TieredDebateVote[];
  // v10 weighted votes: the authors' own ratings (one or two), and the
  // final median of every voter's rating (null on struck bullets).
  // v11 adds author_votes: the same ratings with the lister number and
  // the reason attached.
  author_weights?: number[];
  author_votes?: TieredDebateAuthorVote[];
  weight?: number | null;
  added_by_attacker?: boolean;
  attacker_checks?: { citation: TieredDebateCheck; logic: TieredDebateCheck } | null;
  attacker_check?: TieredDebateCheck | null;
  responses?: {
    citation: TieredDebateResponse | null;
    logic: TieredDebateResponse | null;
  };
  response: TieredDebateResponse | null;
  judge:
    | { citation: TieredDebateJudgeAxis; logic: TieredDebateJudgeAxis }
    | TieredDebateJudgeAddition
    | TieredDebateJudgeAxis
    | null;
  count?: { numerator: number; denominator: number } | null;
  outcome?: 'valid' | 'invalid' | 'neutral' | null;
  final_status?: 'counted' | 'excluded' | null;
  exclusion_reason?: string | null;
};

// Pool snapshot: per-dimension bullish/bearish counts plus the
// pool-wide totals and score. v6-v8 store a per-dimension score and an
// averaged overall score; v9 stores flat counting (10 × bullish/total)
// and no per-dimension score; v10 adds importance-weight sums and a
// weighted score (10 × bullish weight / total weight).
export type TieredDebatePool = {
  dimensions: Record<
    string,
    {
      bullish: number;
      bearish: number;
      total: number;
      score?: number | null;
      bullish_weight?: number;
      bearish_weight?: number;
      total_weight?: number;
    }
  >;
  bullish: number;
  bearish: number;
  total: number;
  bullish_weight?: number;
  bearish_weight?: number;
  total_weight?: number;
  score: number | null;
};

// Bull/bear debate audit trail (tier-2 section). Four generations coexist
// in stored runs: the v2 judged shape (confidence, reasons, would_change_
// One bullet of the structured deep-analysis report. Bullets carry the
// same code-verified {ref, value} links as the evidence list — cited
// values render as jumps to their report row. Children are sub-bullets
// one level deep with the same contract.
export type TieredSummaryChild = {
  text: string;
  links?: TieredDebateLink[] | null;
};
export type TieredSummaryBullet = {
  text: string;
  links?: TieredDebateLink[] | null;
  children?: TieredSummaryChild[] | null;
};

// The fixed report outline (owner decision 2026-07-24): the group set
// and order never change run to run — the AI only fills the bullets.
export type TieredSummaryStructure = {
  summary?: TieredSummaryBullet[] | null;
  technicals?: TieredSummaryBullet[] | null;
  fundamentals?: TieredSummaryBullet[] | null;
  positioning?: TieredSummaryBullet[] | null;
  macro_econ?: TieredSummaryBullet[] | null;
  // Opinion (analyst + crowd) joined 2026-08-18; absent on older runs.
  opinion?: TieredSummaryBullet[] | null;
  // Company news joined the debate 2026-08-16; absent on older runs.
  company_events?: TieredSummaryBullet[] | null;
  // World news (macro backdrop card) joined the same day; absent on
  // older runs.
  world_events?: TieredSummaryBullet[] | null;
};

// mind), the v3 scored shape (final_score, scoring, corrected bull/bear
// summaries), the v4 threaded shape (turn kinds, axis-grade comments),
// and the v5 tree (format: 5, items, weight ledger) — every
// generation-specific field is optional.
export type TieredDebateDetail = {
  // 5/6/7 on tree-format runs; absent on everything stored before.
  format?: number;
  items?: TieredDebateItem[];
  turns: {
    role: string;
    // v2/v3 runs number their rounds; v4 turns carry a kind instead.
    round?: number;
    kind?: string;
    argument: string;
    bullishness?: number | null;
    position_score?: number | null;
    citations?: string[];
  }[];
  verdict: {
    direction: string;
    summary: string;
    // v11+ structured report: the fixed five-group outline the summary
    // stage fills (summary + one group per dimension); `summary` above
    // is its flat-text rendering for older readers.
    summary_structure?: TieredSummaryStructure | null;
    // v2 judged shape
    confidence?: number | null;
    reasons_for?: TieredAnchoredReason[];
    reasons_against?: TieredAnchoredReason[];
    would_change_mind?: string | null;
    // v3 scored shape
    final_score?: number | null;
    final_score_rounded?: number | null;
    bull_summary?: string | null;
    bear_summary?: string | null;
    scoring?: { bull: TieredDebaterScore; bear: TieredDebaterScore } | null;
    // v5/v6 tree shape (v5 scores are whole numbers + weight; v6 scores
    // are 2-decimal pool counts + pools)
    initial_score?: number | null;
    adjusted_score?: number | null;
    adjusted_kept?: boolean | null;
    weight?: { numerator: number; denominator: number; value: number } | null;
    // v8 pools drop the adjusted snapshot (no concede/adopt step).
    pools?: {
      initial: TieredDebatePool;
      adjusted?: TieredDebatePool;
      final: TieredDebatePool;
    } | null;
  } | null;
  warnings: string[];
};

// One tier-3 risk bullet (risk_detail format 2): the tier-2 vote-item
// shape minus the direction tag — every bullet is a risk, and code maps
// the confirmed count to the size multiplier.
export type TieredRiskItem = {
  id: string;
  dimension: string;
  claim: string;
  links?: TieredDebateLink[];
  struck?: boolean;
  problems?: string[];
  authors?: number;
  votes?: TieredDebateVote[];
  final_status?: 'counted' | 'excluded' | null;
  exclusion_reason?: string | null;
};

// Per-group and total risk counts for one pool snapshot.
export type TieredRiskCounts = {
  groups: Record<string, number>;
  total: number;
};

// Risk stress audit trail (tier-3 section). Two generations coexist in
// stored runs: the persona/judge shape (takes + stance/stop advice) and
// the format-2 risk vote (items + count-derived multiplier) — every
// generation-specific field is optional.
export type TieredRiskDetail = {
  // 2 on risk-vote runs; absent on the stored persona/judge runs.
  format?: number;
  takes: { persona: string; assessment: string }[];
  items?: TieredRiskItem[];
  verdict: {
    stance: string;
    size_multiplier: number;
    // Absent on runs stored before the risk judge reported its own 0-1
    // sureness; the UI hides the score for those.
    confidence?: number | null;
    stop_advice: string;
    tightened_stop: number | null;
    summary: string;
    key_risks: TieredAnchoredReason[];
    // format 2: the code-owned count → multiplier arithmetic.
    confirmed_risks?: number;
    total_risks?: number;
    counts?: { initial: TieredRiskCounts; final: TieredRiskCounts } | null;
  } | null;
  warnings: string[];
};

// Outlook redesign (2026-07): the impersonal judgment on the stock.
// 'stopped' (2026-08-08): the staleness gate halted the run before any
// LLM stage — the data cards exist, but no analysis or plan does.
export type TieredOutlook = 'bullish' | 'neutral' | 'bearish' | 'unknown' | 'stopped';
// …and the personal instruction code derives from outlook × ownership.
export type TieredAction =
  | 'enter'
  | 'enter_later'
  | 'keep_holding'
  | 'no_trade'
  | 'sell_all'
  | 'unknown';

// Warning-only earnings info: never gates anything, never moves numbers.
export type TieredEarnings = {
  next_date: string | null;
  days_until: number | null;
  warning_days: number;
  is_near: boolean;
  note: string | null;
};

// One display-only risk-card entry. The 13 ids and their value keys are
// fixed by the backend (risk_card.py); wording lives in the i18n layer.
export type TieredRiskCardEntry = {
  id: string;
  status: 'ok' | 'flag' | 'na';
  values: Record<string, unknown>;
};

// The deepest tier's verdict in summary form — what the run ends on.
export type TieredFinal = {
  tier: number;
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  outlook?: TieredOutlook;
  action?: TieredAction;
  confidence: string | null;
  levels: TieredLevels;
};

export type TieredTierSection = {
  tier: number;
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  confidence: string | null;
  score: number | null;
  levels: TieredLevels;
  narrative: string | null;
  warnings: string[];
  debate_detail?: TieredDebateDetail;
  risk_detail?: TieredRiskDetail;
};

// v2 slice 6: deterministic sizing block (share count or explicit refusal).
export type TieredSizing = {
  enabled: boolean;
  shares: number | null;
  // Multiplier keys died with tier 3 — absent on outlook-redesign runs.
  shares_before_multiplier?: number | null;
  risk_multiplier?: number | null;
  // Ownership block (absent on runs stored before the ownership input):
  // held shares, and the exit size a sell verdict prints from them.
  ownership?: number | null;
  sell_shares?: number | null;
  sell_shares_before_multiplier?: number | null;
  position_value: number | null;
  risk_amount: number | null;
  loss_per_share: number | null;
  lot_size: number;
  reason_code: string | null;
  refusal_reason: string | null;
  notes: string[];
  // Fee rate and the position cap were removed 2026-07-22 (they return
  // later as user inputs); old stored runs may still carry those keys.
  inputs: {
    capital: number | null;
    risk_fraction: number | null;
    // Absent on runs stored before the reward filter existed.
    reward_risk?: number | null;
    entry: number | null;
    stop_loss: number | null;
  };
};

export type TieredLlmUsage = {
  stages: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number }>;
  total: { calls: number; prompt_tokens: number; completion_tokens: number };
  scope: string;
};

export type TieredResult = {
  symbol: string;
  market: string;
  tier: number;
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  score: number | null;
  confidence: string | null;
  levels: TieredLevels;
  levels_detail?: TieredLevelsDetail | null;
  narrative: string | null;
  warnings: string[];
  dimensions: TieredDimension[];
  // v2 slice 6 additions — absent on old stored runs, so all optional.
  depth?: number;
  final?: TieredFinal | null;
  tier2?: TieredTierSection | null;
  tier3?: TieredTierSection | null;
  sizing?: TieredSizing | null;
  llm_usage?: TieredLlmUsage | null;
  // Outlook redesign additions — absent on old stored runs.
  outlook?: TieredOutlook;
  action?: TieredAction;
  earnings?: TieredEarnings | null;
  // Retired 2026-07-22 (kept so old stored runs still type-check).
  risk_card?: TieredRiskCardEntry[] | null;
  // Plan review (2026-07-22): per-column trade-plan warnings.
  plan_warnings?: TieredPlanWarnings | null;
  // Max hold time in weeks the run was judged against (2026-08-08);
  // absent on old stored runs.
  hold_weeks?: number | null;
};

export type TieredRunStatus = 'running' | 'done' | 'failed';

export type TieredRunSummary = {
  task_id: string;
  stock_code: string;
  status: TieredRunStatus;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
  // Digest of the stored report for the history rows. Null while running,
  // after a failure, or on rows stored before the backend sent these.
  // shares mirrors the report card: 0 = sizing ran but bought nothing,
  // null = the run has no sizing block (shown as a dash).
  direction?: 'buy' | 'hold' | 'sell' | 'unknown' | null;
  // Outlook digest: stored on new runs; the backend maps old runs'
  // buy/hold/sell to bullish/neutral/bearish so the filter is uniform.
  outlook?: TieredOutlook | null;
  shares?: number | null;
  // The tier the run went to (1-3); null while running/failed.
  tier?: number | null;
  // The sizing inputs the run used (capital in the ticker's own currency,
  // risk as a 0-1 fraction); null when the run had no sizing block.
  capital?: number | null;
  risk_fraction?: number | null;
  // The reward-to-risk goal the run planned toward (target = entry +
  // reward × risk); null on runs stored before it was recorded.
  reward_risk?: number | null;
  // Max hold time in weeks the run was judged against; null on runs
  // stored before it existed.
  hold_weeks?: number | null;
};

export type TieredRun = TieredRunSummary & {
  result: TieredResult | null;
};

// Tier 3 retired (outlook redesign): the backend rejects depth 3 with a
// validation error and the alt form offers 1-2 only. The type keeps 3 so
// the legacy /tiered page (deliberately untouched) still compiles.
export type TieredDepth = 1 | 2 | 3;

export type TieredSizingRequest = {
  capital?: number;
  risk_fraction?: number;
  // Kept for API compatibility; the alt form no longer collects it.
  ownership?: number;
  // Reward-to-risk ratio the plan aims for (target = entry + R × risk).
  reward_risk?: number;
};

// Extra run inputs (2026-08-08): the max hold time and the clock-gate
// override ("run anyway" after a 409 market-open rejection).
export type TieredStartOptions = {
  holdWeeks?: number;
  runAnyway?: boolean;
};

// The 409 market-open rejection body (2026-08-11): which market blocked
// the run, plus today's session bounds as ISO datetimes carrying the
// market's own UTC offset (null on backends from before they were sent).
export type TieredMarketOpenGate = {
  market: string | null;
  sessionOpen: string | null;
  sessionClose: string | null;
};

export const tieredApi = {
  start: async (
    stockCode: string,
    depth: TieredDepth = 1,
    sizing?: TieredSizingRequest,
    options?: TieredStartOptions,
  ): Promise<{ task_id: string }> => {
    const response = await apiClient.post<{ task_id: string }>('/api/v1/tiered/analyze', {
      stock_code: stockCode,
      depth,
      ...(sizing && Object.keys(sizing).length > 0 ? { sizing } : {}),
      ...(options?.holdWeeks != null ? { hold_weeks: options.holdWeeks } : {}),
      ...(options?.runAnyway ? { run_anyway: true } : {}),
    });
    return response.data;
  },

  // 200 is the backend's cap; the page paginates client-side over this.
  listRuns: async (limit = 200): Promise<TieredRunSummary[]> => {
    const response = await apiClient.get<{ items: TieredRunSummary[] }>('/api/v1/tiered/runs', {
      params: { limit },
    });
    return response.data.items;
  },

  getRun: async (taskId: string): Promise<TieredRun> => {
    const response = await apiClient.get<TieredRun>(`/api/v1/tiered/runs/${taskId}`);
    return response.data;
  },

  // Saved sizing settings (.env-backed) — what a run uses when the form
  // sends nothing. Both null when no defaults are configured.
  sizingDefaults: async (): Promise<{
    capital: number | null;
    risk_fraction: number | null;
    reward_risk?: number | null;
  }> => {
    const response = await apiClient.get<{
      capital: number | null;
      risk_fraction: number | null;
      reward_risk?: number | null;
    }>('/api/v1/tiered/sizing-defaults');
    return response.data;
  },
};
