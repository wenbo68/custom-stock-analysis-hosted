import { useState, type ComponentProps, type ReactNode } from 'react';
import type {
  TieredAction,
  TieredAnchoredReason,
  TieredCitation,
  TieredResult,
  TieredTierSection,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { formatPrice, sentimentCitations } from '../tiered/termHelpers';
import { isPlanNote } from './altWarningText';
import { HelpTerm as BaseHelpTerm } from '../tiered/terms';
import { directionOutlook } from './altFormat';
import { ALT_LINK, OUTLOOK_TEXT } from './altStyles';
import {
  AltCard,
  AltEvidenceRefs,
  AltFold,
  AltModal,
  AltNotesButton,
  AltSectionLabel,
} from './AltUi';
import { AltDebateScoring } from './AltDebateScoring';
import { AltSummaryOutline } from './AltSummaryOutline';
import { AltDebateTree, DebateScores } from './AltDebateTree';
import { AltRiskTree } from './AltRiskTree';
import { AltDimensions } from './AltDimensions';
import { AltLevels } from './AltLevels';

// ---------- small shared pieces ----------

// Alt skin rule: help popups everywhere, dotted underlines nowhere.
const HelpTerm = (props: ComponentProps<typeof BaseHelpTerm>) => (
  <BaseHelpTerm underline={false} {...props} />
);

// An UPPERCASE title sitting above its card, like the page's section titles.
const AltBlock = ({
  title,
  helpKey,
  children,
}: {
  title: string;
  helpKey?: UiTextKey;
  children: ReactNode;
}) => (
  <section className="flex flex-col gap-2">
    <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
      {helpKey ? <HelpTerm label={title} helpKey={helpKey} /> : title}
    </h3>
    {children}
  </section>
);

// ---------- tier cards ----------

// One header fact — quiet label, prominent value; the same styling for
// verdict, size, stop loss and score alike (children may recolor the
// value, e.g. the verdict's buy/hold/sell tint).
const AltFact = ({
  label,
  helpKey,
  children,
}: {
  label: string;
  helpKey?: UiTextKey;
  children: ReactNode;
}) => (
  <span className="text-xs text-gray-500">
    {helpKey ? <HelpTerm label={label} helpKey={helpKey} /> : label}
    {': '}
    <span className="text-sm font-semibold text-gray-200">{children}</span>
  </span>
);

// The unified per-tier "Score", shown out of 10. The tier-2/3 judges
// report 0-1 confidence; callers pass it as 0-100 and it rounds to /10.
const TierScore = ({ value, helpKey }: { value: number; helpKey: UiTextKey }) => {
  const { t } = useUiLanguage();
  return (
    <AltFact label={t('tiered.score')} helpKey={helpKey}>
      <span className="tabular-nums">{Math.round(value / 10)}/10</span>
    </AltFact>
  );
};

interface TierHeaderProps {
  section: Pick<TieredTierSection, 'direction'>;
  notes?: string[];
  score?: number | null;
  scoreHelpKey?: UiTextKey;
  side?: ReactNode;
}

// The card's title lives above the card (AltBlock); inside, the header is
// one row of `Label: value` facts — Outlook first, any side facts (tier 3
// puts Size and Stop loss there), Score last — and the data-notes mark
// pinned top-right: nothing when there is nothing to report, ⚠ when
// there is. The stored verdict is still buy/hold/sell; the outlook
// rename maps it to bullish/neutral/bearish for display.
const TierHeader = ({ section, notes, score, scoreHelpKey, side }: TierHeaderProps) => {
  const { t } = useUiLanguage();
  const outlook = directionOutlook(section.direction);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-1">
      <AltFact label={t('tiered.alt.outlook')}>
        {/* Same bullish/neutral/bearish tint as the run-history rows. */}
        <span className={OUTLOOK_TEXT[outlook]}>
          {t(`tiered.outlook.${outlook}` as UiTextKey)}
        </span>
      </AltFact>
      {side}
      {score != null && scoreHelpKey ? <TierScore value={score} helpKey={scoreHelpKey} /> : null}
      <span className="ml-auto">
        <AltNotesButton notes={notes ?? []} />
      </span>
    </div>
  );
};

// ---------- the conclusion (outlook redesign) ----------

// True when the run's local calendar day is before today's — a plan from
// a previous trading day should be re-run, not traded (owner decision:
// no expiry mechanism, just this note).
const isFromPreviousDay = (runDate: Date): boolean => {
  const now = new Date();
  return (
    new Date(runDate.getFullYear(), runDate.getMonth(), runDate.getDate()).getTime() <
    new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  );
};

interface AltConclusionProps {
  result: TieredResult;
  runDate?: Date | null;
}

// The run's bottom line, above everything else: the impersonal outlook,
// the personal action code derived from outlook × your ownership, and
// the previous-day staleness note. (The old earnings warning is gone —
// the date now lives on the fundamentals card, and the deep analysis
// weighs the event risk itself.) The run-level analysis/data notes mark
// sits here too (owner decision 2026-08-09: the preliminary-analysis
// card is gone — its outlook duplicated this card); plan-flavored
// warnings stay on the plan card.
const AltConclusion = ({ result, runDate }: AltConclusionProps) => {
  const { t } = useUiLanguage();
  const outlook = result.outlook ?? 'unknown';
  const action = result.action ?? 'unknown';
  const stale = runDate ? isFromPreviousDay(runDate) : false;
  // A stopped run (staleness gate) has no analysis behind it: the
  // outlook word IS the whole story — no action, no note. (The max hold
  // time moved to the run-history row, 2026-08-09.)
  const stopped = outlook === 'stopped';
  return (
    <AltCard testId="alt-conclusion">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <AltFact label={t('tiered.alt.outlook')} helpKey="tiered.help.outlook">
          <span className={OUTLOOK_TEXT[outlook]}>
            {t(`tiered.outlook.${outlook}` as UiTextKey)}
          </span>
        </AltFact>
        {!stopped ? (
          <AltFact label={t('tiered.alt.action')} helpKey="tiered.help.action">
            {t(`tiered.action.${action}` as UiTextKey)}
          </AltFact>
        ) : null}
        <span className="ml-auto">
          <AltNotesButton
            notes={(result.warnings ?? []).filter((raw) => !isPlanNote(raw))}
          />
        </span>
      </div>
      {stale && !stopped ? (
        <p className="mt-2 text-xs text-amber-300" data-testid="alt-stale-note">
          {t('tiered.alt.staleNote')}
        </p>
      ) : null}
    </AltCard>
  );
};

interface AltTierOneProps {
  result: TieredResult;
  citations: TieredCitation[];
  /** Undefined on old stored runs → the full levels table (legacy). */
  action?: TieredAction;
  /** The run's task id — the shares receipt links the run-row inputs. */
  taskId?: string;
}

// A resistance-capped target that misses the user's chosen reward-to-risk
// ratio arrives as a backend warning; on old stored runs (no structured
// plan warnings) it is surfaced ON the plan, not only in the notes popup.
// Plan-review runs carry it in the warnings row instead.
const REWARD_BELOW_GOAL =
  /^reward below goal: .*reward-to-risk at ([\d.]+), below your ([\d.]+)/;

// The conditional plan display (owner decision): which levels show
// depends on the action. Old runs (no action) keep the full table.
const PlanBody = ({ result, citations, action, taskId }: AltTierOneProps) => {
  const { t } = useUiLanguage();
  const plan =
    action === undefined ||
    action === 'enter' ||
    action === 'enter_later' ||
    action === 'unknown'
      ? 'full'
      : action;
  if (plan === 'full') {
    const planWarnings = result.plan_warnings ?? null;
    const rewardMiss = planWarnings
      ? null
      : (result.warnings ?? [])
          .map((warning) => REWARD_BELOW_GOAL.exec(warning))
          .find((match) => match !== null);
    return (
      <div className="flex flex-col gap-2">
        {rewardMiss ? (
          <p className="text-xs text-amber-300" data-testid="alt-reward-warning">
            {t('tiered.alt.rewardBelowGoal', {
              ratio: rewardMiss[1],
              goal: rewardMiss[2],
            })}
          </p>
        ) : null}
        <AltLevels
          levels={result.levels}
          levelsDetail={result.levels_detail}
          citations={citations}
          planWarnings={planWarnings}
          taskId={taskId}
        />
      </div>
    );
  }
  if (plan === 'keep_holding') {
    // Holders get the one number that still matters: the structural
    // exit level. Entries and targets are entry-plan material and a
    // bullish-while-holding run deliberately does not say "buy more".
    return (
      <p className="text-sm" data-testid="alt-structural-stop">
        <span className="text-xs text-gray-500">
          <HelpTerm
            label={t('tiered.alt.structuralStop')}
            helpKey="tiered.help.structuralStop"
          />
          {': '}
        </span>
        <span className="font-semibold tabular-nums text-gray-200">
          {result.levels.stop_loss != null ? formatPrice(result.levels.stop_loss) : '—'}
        </span>
      </p>
    );
  }
  // Unreachable for current runs (only bullish outlooks render a plan
  // section, and their actions are enter/enter_later/keep_holding) —
  // kept as a crash-guard for unexpected stored actions.
  return (
    <p className="text-sm text-gray-500" data-testid="alt-no-plan">
      {t('tiered.alt.noPlan')}
    </p>
  );
};

// Legacy layout only (old stored runs without an outlook): the tier-1
// card still carries the plan inside it.
const AltTierOne = ({ result, citations, action }: AltTierOneProps) => (
  <AltCard testId="alt-tier1">
    {/* No score here: tier 1's stored score is the analyzer's bullishness
        composite, not a judge confidence — showing it under the same
        "Score" label would mean two different things. */}
    <TierHeader
      section={{ direction: result.direction }}
      notes={result.warnings}
    />
    <PlanBody result={result} citations={citations} action={action} />
  </AltCard>
);

// Backend note strings whose fact the plan table's structured warnings
// row already carries under these ids — the row recomputes its numbers
// from the FINAL (post-review) levels, so the note's stale copy must not
// show beside it (owner decision 2026-07-24).
const NOTE_RE_BY_PLAN_WARNING_ID: Record<string, RegExp> = {
  downtrend: /^trend warning: /,
  reward_below_goal: /^reward below goal: /,
};

// The plan card's data notes: the plan-flavored run warnings (the
// analysis/data notes stay on the preliminary card), minus anything the
// plan's own warnings row already states.
const planCardNotes = (result: TieredResult): string[] => {
  const shownIds = new Set(
    Object.values(result.plan_warnings ?? {})
      .flat()
      .map((warning) => warning.id),
  );
  return (result.warnings ?? [])
    .filter(isPlanNote)
    .filter(
      (raw) =>
        !Object.entries(NOTE_RE_BY_PLAN_WARNING_ID).some(
          ([id, pattern]) => shownIds.has(id) && pattern.test(raw),
        ),
    );
};

// The trade plan in its own card, under the analysis (owner order,
// 2026-07-22). The data-notes mark floats in the card's top-right corner
// so it never occupies a line of its own. Only bullish-outlook runs
// render this card at all (owner decision 2026-08-05), so the plan
// inside is never empty.
const AltPlanCard = ({ result, citations, action, taskId }: AltTierOneProps) => (
  <AltCard testId="alt-plan" className="relative">
    <span className="absolute right-5 top-5">
      <AltNotesButton notes={planCardNotes(result)} />
    </span>
    <PlanBody result={result} citations={citations} action={action} taskId={taskId} />
  </AltCard>
);

interface AltTierSectionProps {
  section: TieredTierSection;
  citations: TieredCitation[];
}

// One side of the debate card: the judged (v2) shape shows anchored
// reasons; the scored (v3) shape shows the judge's corrected case summary.
const AltDebateColumn = ({
  labelKey,
  color,
  reasons,
  summary,
  citations,
}: {
  labelKey: UiTextKey;
  color: string;
  reasons: TieredAnchoredReason[];
  summary: string | null;
  citations: TieredCitation[];
}) => {
  const { t } = useUiLanguage();
  return (
    <div>
      <div className={cn('mb-1 text-xs font-semibold', color)}>{t(labelKey)}</div>
      {summary !== null ? (
        <p className="text-xs leading-relaxed">{summary}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {reasons.map((reason, index) => (
            <li key={index} className="text-xs">
              {reason.claim}
              {reason.evidence.length > 0 ? (
                <span className="mt-0.5 block">
                  <AltEvidenceRefs refs={reason.evidence} citations={citations} />
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

// v4 transcript turn kinds → their display labels.
const TURN_KIND_KEYS: Record<string, UiTextKey> = {
  argument: 'tiered.debate.kind.argument',
  attack: 'tiered.debate.kind.attack',
  response: 'tiered.debate.kind.response',
};

const AltDebate = ({ section, citations }: AltTierSectionProps) => {
  const { t } = useUiLanguage();
  const [scoreOpen, setScoreOpen] = useState(false);
  const detail = section.debate_detail;
  const verdict = detail?.verdict ?? null;
  // v5/v6 runs carry the defender/attacker/judge tree and render it
  // whole — no scoring foldable, no bull/bear columns; the score's
  // arithmetic opens from the header score itself.
  if (
    detail?.format != null &&
    detail.format >= 5 &&
    detail.format <= 11 &&
    Array.isArray(detail.items)
  ) {
    return (
      <AltCard testId="alt-tier2">
        <TierHeader
          section={section}
          notes={section.warnings}
          side={
            verdict?.final_score != null ? (
              <AltFact label={t('tiered.score')} helpKey="tiered.help.debateScore">
                {/* Clicking the score opens its arithmetic (owner
                    decision 2026-07-22 — moved out of the fold). */}
                <button
                  type="button"
                  data-testid="alt-debate-score"
                  className={cn('cursor-pointer tabular-nums', ALT_LINK)}
                  onClick={() => setScoreOpen(true)}
                >
                  {verdict.final_score.toFixed(2)}/10
                </button>
              </AltFact>
            ) : null
          }
        />
        {verdict?.summary_structure ? (
          // v11+ runs carry the fixed-outline report; older runs keep
          // their flat paragraph.
          <div className="mb-2">
            <AltSummaryOutline structure={verdict.summary_structure} />
          </div>
        ) : section.narrative ? (
          <p className="mb-2 text-sm leading-relaxed">{section.narrative}</p>
        ) : null}
        {!verdict ? (
          <p className="text-sm text-amber-300">{t('tiered.debate.noVerdict')}</p>
        ) : null}
        <AltDebateTree detail={detail} />
        <AltModal
          isOpen={scoreOpen}
          title={t('tiered.tree.scores')}
          onClose={() => setScoreOpen(false)}
          panelClassName="w-fit min-w-72 max-w-[95vw]"
        >
          <DebateScores detail={detail} />
        </AltModal>
      </AltCard>
    );
  }
  // Scored (v3) runs carry the formula's audit trail; older stored runs
  // carry the judged shape and keep their original layout. TierScore
  // expects 0-100, so both generations scale up to it.
  const isScored = verdict?.scoring != null;
  const score = isScored
    ? verdict?.final_score_rounded != null
      ? verdict.final_score_rounded * 10
      : null
    : verdict?.confidence != null
      ? verdict.confidence * 100
      : null;

  return (
    <AltCard testId="alt-tier2">
      <TierHeader
        section={section}
        notes={section.warnings}
        score={score}
        scoreHelpKey={isScored ? 'tiered.help.debateScore' : 'tiered.help.judgeScore'}
      />

      {section.narrative ? (
        <p className="mb-4 text-sm leading-relaxed">{section.narrative}</p>
      ) : null}

      {verdict ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <AltDebateColumn
            labelKey={isScored ? 'tiered.debate.bullCase' : 'tiered.debate.reasonsFor'}
            color="text-emerald-300"
            reasons={verdict.reasons_for ?? []}
            summary={isScored ? (verdict.bull_summary ?? null) : null}
            citations={citations}
          />
          <AltDebateColumn
            labelKey={isScored ? 'tiered.debate.bearCase' : 'tiered.debate.reasonsAgainst'}
            color="text-red-300"
            reasons={verdict.reasons_against ?? []}
            summary={isScored ? (verdict.bear_summary ?? null) : null}
            citations={citations}
          />
        </div>
      ) : (
        <p className="text-sm text-amber-300">{t('tiered.debate.noVerdict')}</p>
      )}

      {verdict?.would_change_mind ? (
        <div className="mt-4">
          <AltSectionLabel>
            <HelpTerm
              label={t('tiered.debate.wouldChangeMind')}
              helpKey="tiered.help.wouldChangeMind"
            />
          </AltSectionLabel>
          <p className="text-xs">{verdict.would_change_mind}</p>
        </div>
      ) : null}

      {detail && detail.turns.length > 0 ? (
        <AltFold title={t('tiered.debate.transcript')}>
          {detail.turns.map((turn, index) => {
            // v4 turns carry a kind (argument/attack/response); older runs
            // numbered their rounds instead.
            const kindKey = turn.kind ? TURN_KIND_KEYS[turn.kind] : undefined;
            const positionScore = turn.position_score ?? turn.bullishness;
            return (
            <div key={index}>
              <div className="mb-0.5 text-xs font-semibold text-gray-300">
                {t((turn.role === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear') as UiTextKey)}{' '}
                <span className="font-normal text-gray-500">
                  {kindKey
                    ? t(kindKey)
                    : (turn.kind ?? t('tiered.debate.round', { round: turn.round ?? 1 }))}
                  {positionScore != null ? (
                    <>
                      {' · '}
                      {t('tiered.debate.positionScore')}{' '}
                      <span className="tabular-nums">{positionScore}/10</span>
                    </>
                  ) : null}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed">{turn.argument}</p>
              {turn.citations && turn.citations.length > 0 ? (
                <span className="mt-0.5 block">
                  <AltEvidenceRefs refs={turn.citations} citations={citations} />
                </span>
              ) : null}
            </div>
            );
          })}
        </AltFold>
      ) : null}

      {verdict && isScored ? <AltDebateScoring verdict={verdict} /> : null}
    </AltCard>
  );
};

const PERSONA_LABEL_KEYS: Record<string, UiTextKey> = {
  conservative: 'tiered.risk.persona.conservative',
  aggressive: 'tiered.risk.persona.aggressive',
  neutral: 'tiered.risk.persona.neutral',
};

const AltRisk = ({ section, citations }: AltTierSectionProps) => {
  const { t } = useUiLanguage();
  const detail = section.risk_detail;
  const verdict = detail?.verdict ?? null;

  // Format-2 runs carry the risk vote: same transcript treatment as the
  // tier-2 evidence vote. The stance is tier 2's own (already in the
  // header) and the levels stand, so the header facts are just the
  // verdict and the code-derived size multiplier — no score, no stop.
  if (detail?.format === 2 && Array.isArray(detail.items)) {
    return (
      <AltCard testId="alt-tier3">
        <TierHeader
          section={section}
          notes={section.warnings}
          side={
            verdict ? (
              <AltFact label={t('tiered.alt.size')} helpKey="tiered.help.multiplier">
                {/* id: the shares-computation formula links its multiplier here */}
                <span id="alt-risk-multiplier" className="tabular-nums">
                  {verdict.size_multiplier}x
                </span>
              </AltFact>
            ) : null
          }
        />
        {!verdict ? (
          <p className="mb-4 text-sm text-amber-300">{t('tiered.risk.noVerdict')}</p>
        ) : null}
        {section.narrative ? (
          <p className="mb-2 text-sm leading-relaxed">{section.narrative}</p>
        ) : null}
        <AltRiskTree detail={detail} />
      </AltCard>
    );
  }

  return (
    <AltCard testId="alt-tier3">
      <TierHeader
        section={section}
        notes={section.warnings}
        score={verdict?.confidence != null ? verdict.confidence * 100 : null}
        scoreHelpKey="tiered.help.riskScore"
        side={
          verdict ? (
            <>
              <AltFact label={t('tiered.alt.size')} helpKey="tiered.help.multiplier">
                {/* id: the shares-computation formula links its multiplier here */}
                <span id="alt-risk-multiplier" className="tabular-nums">
                  {verdict.size_multiplier}x
                </span>
              </AltFact>
              <AltFact label={t('tiered.levels.stopLoss')} helpKey="tiered.help.stopAdvice">
                {verdict.tightened_stop !== null ? (
                  // id: when the stop was tightened, this is the number the
                  // shares-computation formula actually used — it links here.
                  <span id="alt-tightened-stop" className="tabular-nums">
                    {formatPrice(verdict.tightened_stop)}
                  </span>
                ) : (
                  t('tiered.risk.stopAdvice.keep')
                )}
              </AltFact>
            </>
          ) : null
        }
      />

      {!verdict ? <p className="mb-4 text-sm text-amber-300">{t('tiered.risk.noVerdict')}</p> : null}

      {section.narrative ? (
        <p className="mb-4 text-sm leading-relaxed">{section.narrative}</p>
      ) : null}

      {verdict && verdict.key_risks.length > 0 ? (
        <div>
          <AltSectionLabel>{t('tiered.risk.keyRisks')}</AltSectionLabel>
          <ul className="flex flex-col gap-2">
            {verdict.key_risks.map((risk, index) => (
              <li key={index} className="text-xs">
                {risk.claim}
                {risk.evidence.length > 0 ? (
                  <span className="mt-0.5 block">
                    <AltEvidenceRefs refs={risk.evidence} citations={citations} />
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {detail && detail.takes.length > 0 ? (
        <AltFold title={t('tiered.debate.transcript')}>
          {detail.takes.map((take, index) => (
            <div key={index}>
              <div className="mb-0.5 text-xs font-semibold text-gray-300">
                {PERSONA_LABEL_KEYS[take.persona] ? t(PERSONA_LABEL_KEYS[take.persona]) : take.persona}
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed">{take.assessment}</p>
            </div>
          ))}
        </AltFold>
      ) : null}
    </AltCard>
  );
};

// ---------- the whole result ----------

interface AltResultProps {
  result: TieredResult;
  /** The run's task id — lets formula numbers link back to the run row. */
  taskId?: string;
  /** When the run happened — drives the previous-day staleness note. */
  runDate?: Date | null;
}

// The fixed skeleton (owner order, 2026-07-22): conclusion → the four
// dimension reports → the deep-analysis card (depth 2 only) → the trade
// plan (levels + shares + warnings). Depth-1 runs show no analysis card
// (owner decision 2026-08-09: the preliminary card only duplicated the
// conclusion's outlook — its notes mark moved onto the conclusion). Old
// stored runs without an outlook keep their legacy layout.
export const AltResult = ({ result, taskId, runDate }: AltResultProps) => {
  const { t } = useUiLanguage();
  const citations = sentimentCitations(result.dimensions);
  const usage = result.llm_usage ?? null;

  return (
    <div className="flex flex-col gap-6">
      {result.outlook ? (
        // Outlook-redesign runs lead with the bottom line; old stored
        // runs never carried it and keep their legacy layout.
        <AltBlock title={t('tiered.alt.conclusionTitle')} helpKey="tiered.help.outlook">
          <AltConclusion result={result} runDate={runDate} />
        </AltBlock>
      ) : null}
      <AltBlock title={t('tiered.alt.dimensionsTitle')}>
        <AltDimensions dimensions={result.dimensions} />
      </AltBlock>
      {!result.outlook ? (
        // Legacy runs (any depth) keep the combined verdict + plan card.
        <AltBlock title={t('tiered.alt.tier1Title')} helpKey="tiered.help.tier1">
          <AltTierOne result={result} citations={citations} action={result.action} />
        </AltBlock>
      ) : null}
      {result.tier2 ? (
        <AltBlock title={t('tiered.alt.tier2Title')} helpKey="tiered.help.debate">
          <AltDebate section={result.tier2} citations={citations} />
        </AltBlock>
      ) : null}
      {result.outlook === 'bullish' ? (
        // The trade plan sits under the analysis that judged it — and
        // only under a bullish one (owner decision 2026-08-05): a
        // neutral/bearish/unknown outlook shows no plan section at all;
        // the action line already says what to do. Legacy runs (no
        // outlook) keep their combined card above.
        <AltBlock title={t('tiered.alt.planTitle')} helpKey="tiered.help.plan">
          <AltPlanCard
            result={result}
            citations={citations}
            action={result.action}
            taskId={taskId}
          />
        </AltBlock>
      ) : null}
      {result.tier3 ? (
        <AltBlock title={t('tiered.alt.tier3Title')} helpKey="tiered.help.risk">
          <AltRisk section={result.tier3} citations={citations} />
        </AltBlock>
      ) : null}
      <div className="flex flex-col gap-1 text-xs">
        {result.signal?.logged && result.signal.signal_id != null ? (
          // Standalone app: the decision-signals page stayed in the parent
          // project, so the saved-signal note is plain text (the scoreboard
          // lives in scripts/run_forward_test.py).
          <p className="text-emerald-300">
            {t('tiered.alt.signalSaved', { id: result.signal.signal_id })}
          </p>
        ) : result.signal?.logged ? (
          <p className="text-emerald-300">{t('tiered.alt.signalSaved', { id: '—' })}</p>
        ) : result.signal ? (
          <p className="text-amber-300">
            {t('tiered.signalSkipped', { reason: result.signal.reason ?? '' })}
          </p>
        ) : null}
        {usage && usage.total.calls > 0 ? (
          <p className="text-gray-600">
            <HelpTerm
              underline={false}
              label={t('tiered.llmUsage', {
                calls: usage.total.calls,
                tokens: usage.total.prompt_tokens + usage.total.completion_tokens,
              })}
              helpKey="tiered.help.llmUsage"
            />
          </p>
        ) : null}
      </div>
    </div>
  );
};
