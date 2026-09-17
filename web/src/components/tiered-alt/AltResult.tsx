import { useState, type ComponentProps, type ReactNode } from 'react';
import type { TieredResult, TieredTierSection } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement } from '../tiered/termHelpers';
import { isPlanNote } from './altWarningText';
import { HelpTerm as BaseHelpTerm } from '../tiered/terms';
import { adjustedCellId, computedCellId, directionOutlook } from './altFormat';
import { RewardRatioValue, type PlanColumn, type RewardRatioValues } from './AltPlanWarnings';
import { fillTemplate } from './altTemplate';
import { ALT_LINK, OUTLOOK_TEXT } from './altStyles';
import { AltCard, AltModal, AltNotesButton } from './AltUi';
import { AltSummaryOutline } from './AltSummaryOutline';
import { AltDebateTree, DebateScores } from './AltDebateTree';
import { AltDimensions } from './AltDimensions';
import { AltLevels } from './AltLevels';
import { AltTranscript } from './AltTranscript';

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
// outlook, size, stop loss and score alike (children may recolor the
// value, e.g. the outlook's buy/hold/sell tint).
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

interface TierHeaderProps {
  section: Pick<TieredTierSection, 'direction'>;
  notes?: string[];
  side?: ReactNode;
}

// The card's title lives above the card (AltBlock); inside, the header is
// one row of `Label: value` facts — Outlook first, then any side facts
// (the deep-analysis score) — and the data-notes mark pinned top-right:
// nothing when there is nothing to report, ⚠ when there is. The stored
// outlook is still buy/hold/sell; the outlook rename maps it to
// bullish/neutral/bearish for display.
const TierHeader = ({ section, notes, side }: TierHeaderProps) => {
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

// The numbers behind a "Buy later": the plan review's reward-below-goal
// warning carries them; a run without that warning (none expected) falls
// back to the same arithmetic over the plan levels.
const rewardRatioValues = (result: TieredResult): RewardRatioValues | null => {
  const warning = (result.plan_warnings?.take_profit ?? []).find(
    (entry) => entry.id === 'reward_below_goal',
  );
  if (warning) {
    const v = warning.values;
    return { entry: v.entry, stop_loss: v.stop_loss, take_profit: v.take_profit, ratio: v.ratio };
  }
  const { entry, stop_loss, take_profit } = result.levels;
  if (entry == null || stop_loss == null || take_profit == null || entry === stop_loss) {
    return null;
  }
  return {
    entry,
    stop_loss,
    take_profit,
    ratio: (take_profit - entry) / (entry - stop_loss),
  };
};

// Flash the plan cell a price came from: the adjusted cell when the
// plan review moved that level, else the computed one.
const jumpToPlanCell = (key: PlanColumn) => {
  if (!flashElement(adjustedCellId(key))) {
    flashElement(computedCellId(key));
  }
};

// The run's bottom line, above everything else: the impersonal outlook,
// the personal action code derived from the outlook and the plan, and
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
  // (The max hold time moved to the run-history row, 2026-08-09.)
  // "Buy later" says why, inline: the plan's current reward-to-risk,
  // clickable for its arithmetic (owner request 2026-09-16).
  const rewardValues = action === 'enter_later' ? rewardRatioValues(result) : null;
  return (
    <AltCard testId="alt-conclusion">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <AltFact label={t('tiered.alt.outlook')} helpKey="tiered.help.outlook">
          <span className={OUTLOOK_TEXT[outlook]}>
            {t(`tiered.outlook.${outlook}` as UiTextKey)}
          </span>
        </AltFact>
        <AltFact label={t('tiered.alt.action')} helpKey="tiered.help.action">
          {t(`tiered.action.${action}` as UiTextKey)}
          {rewardValues ? (
            <span data-testid="alt-action-reason">
              {' ('}
              {fillTemplate(t('tiered.alt.actionRatio'), {
                ratio: <RewardRatioValue values={rewardValues} onJump={jumpToPlanCell} />,
              })}
              {')'}
            </span>
          ) : null}
        </AltFact>
        <span className="ml-auto">
          <AltNotesButton
            notes={(result.warnings ?? []).filter((raw) => !isPlanNote(raw))}
          />
        </span>
      </div>
      {stale ? (
        <p className="mt-2 text-xs text-amber-300" data-testid="alt-stale-note">
          {t('tiered.alt.staleNote')}
        </p>
      ) : null}
    </AltCard>
  );
};

interface AltPlanProps {
  result: TieredResult;
  /** The run's task id — the shares receipt links the run-row inputs. */
  taskId?: string;
}

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
const AltPlanCard = ({ result, taskId }: AltPlanProps) => (
  <AltCard testId="alt-plan" className="relative">
    <span className="absolute right-5 top-5">
      <AltNotesButton notes={planCardNotes(result)} />
    </span>
    <AltLevels
      levels={result.levels}
      levelsDetail={result.levels_detail}
      planWarnings={result.plan_warnings ?? null}
      taskId={taskId}
    />
  </AltCard>
);

interface AltDebateProps {
  section: TieredTierSection;
}

// The deep-analysis card: the outlook, the clickable pool score, the
// fixed-outline report, and the evidence vote tree.
const AltDebate = ({ section }: AltDebateProps) => {
  const { t } = useUiLanguage();
  const [scoreOpen, setScoreOpen] = useState(false);
  const detail = section.debate_detail ?? null;
  const outlook = detail?.outlook ?? null;
  return (
    <AltCard testId="alt-tier2">
      <TierHeader
        section={section}
        notes={section.warnings}
        side={
          outlook?.final_score != null ? (
            <AltFact label={t('tiered.score')} helpKey="tiered.help.debateScore">
              {/* Clicking the score opens its arithmetic (owner
                  decision 2026-07-22 — moved out of the fold). */}
              <button
                type="button"
                data-testid="alt-debate-score"
                className={cn('cursor-pointer tabular-nums', ALT_LINK)}
                onClick={() => setScoreOpen(true)}
              >
                {outlook.final_score.toFixed(2)}/10
              </button>
            </AltFact>
          ) : null
        }
      />
      {outlook?.summary_structure ? (
        <div className="mb-2">
          <AltSummaryOutline structure={outlook.summary_structure} />
        </div>
      ) : section.narrative ? (
        <p className="mb-2 text-sm leading-relaxed">{section.narrative}</p>
      ) : null}
      {!outlook ? (
        <p className="text-sm text-amber-300">{t('tiered.debate.noOutlook')}</p>
      ) : null}
      {detail ? <AltDebateTree detail={detail} /> : null}
      {detail ? (
        <AltModal
          isOpen={scoreOpen}
          title={t('tiered.tree.scores')}
          onClose={() => setScoreOpen(false)}
          panelClassName="w-fit min-w-72 max-w-[95vw]"
        >
          <DebateScores detail={detail} />
        </AltModal>
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

// The fixed skeleton (owner order, 2026-07-22): conclusion → the
// dimension reports → the deep-analysis card (depth 2 only) → the trade
// plan (levels + shares + warnings). Depth-1 runs show no analysis card
// (owner decision 2026-08-09: the preliminary card only duplicated the
// conclusion's outlook — its notes mark moved onto the conclusion).
export const AltResult = ({ result, taskId, runDate }: AltResultProps) => {
  const { t } = useUiLanguage();
  const usage = result.llm_usage ?? null;

  return (
    <div className="flex flex-col gap-6">
      <AltBlock title={t('tiered.alt.conclusionTitle')} helpKey="tiered.help.outlook">
        <AltConclusion result={result} runDate={runDate} />
      </AltBlock>
      <AltBlock title={t('tiered.alt.dimensionsTitle')}>
        <AltDimensions dimensions={result.dimensions} />
      </AltBlock>
      {result.tier2 ? (
        <AltBlock title={t('tiered.alt.tier2Title')} helpKey="tiered.help.debate">
          <AltDebate section={result.tier2} />
        </AltBlock>
      ) : null}
      {result.outlook === 'bullish' ? (
        // The trade plan sits under the analysis that judged it — and
        // only under a bullish one (owner decision 2026-08-05): a
        // neutral/bearish/unknown outlook shows no plan section at all;
        // the action line already says what to do.
        <AltBlock title={t('tiered.alt.planTitle')} helpKey="tiered.help.plan">
          <AltPlanCard result={result} taskId={taskId} />
        </AltBlock>
      ) : null}
      <div className="flex flex-col gap-1 text-xs">
        {result.reused ? (
          // Run reuse (2026-09-17): the outlook was borrowed from a
          // matching run; say at which tier and by which model, and
          // that only the trade plan is this user's own computation.
          <p className="text-gray-500" data-testid="alt-reused-note">
            {t('tiered.reused', {
              tier: result.reused.tier,
              model: result.reused.model_label ?? result.reused.model ?? '?',
            })}
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
        {taskId && usage?.transcript_entries ? (
          <AltTranscript taskId={taskId} entries={usage.transcript_entries} />
        ) : null}
      </div>
    </div>
  );
};
