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

// ---------- outlook + action ----------

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

// The personal action code derived from the outlook and the plan.
// "Buy later" says why, inline: the plan's current reward-to-risk,
// clickable for its arithmetic (owner request 2026-09-16). Shown on
// whichever analysis card the run has (owner decision 2026-09-18: the
// separate conclusion card is gone).
const ActionFact = ({ result }: { result: TieredResult }) => {
  const { t } = useUiLanguage();
  const action = result.action ?? 'unknown';
  const rewardValues = action === 'enter_later' ? rewardRatioValues(result) : null;
  return (
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
  );
};

// The run-level analysis/data notes: everything but the plan-flavored
// warnings, which stay on the plan card.
const analysisNotes = (result: TieredResult): string[] =>
  (result.warnings ?? []).filter((raw) => !isPlanNote(raw));

// The preliminary-analysis card (depth 1): the impersonal outlook and
// the personal action, plus the run-level notes mark. (The old earnings
// warning is gone — the date lives on the fundamentals card; the
// previous-day note moved to the history row's date, 2026-09-18.)
const AltPreliminary = ({ result }: { result: TieredResult }) => {
  const { t } = useUiLanguage();
  const outlook = result.outlook ?? 'unknown';
  return (
    <AltCard testId="alt-tier1">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <AltFact label={t('tiered.alt.outlook')} helpKey="tiered.help.outlook">
          <span className={OUTLOOK_TEXT[outlook]}>
            {t(`tiered.outlook.${outlook}` as UiTextKey)}
          </span>
        </AltFact>
        <ActionFact result={result} />
        <span className="ml-auto">
          <AltNotesButton notes={analysisNotes(result)} />
        </span>
      </div>
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
  result: TieredResult;
  section: TieredTierSection;
}

// The deep-analysis card: the outlook, the clickable pool score, the
// action, the fixed-outline report, and the evidence vote tree. Its
// notes mark carries the card's own warnings plus the run-level ones
// (owner decision 2026-09-18: the conclusion card that held them is gone).
const AltDebate = ({ result, section }: AltDebateProps) => {
  const { t } = useUiLanguage();
  const [scoreOpen, setScoreOpen] = useState(false);
  const detail = section.debate_detail ?? null;
  const outlook = detail?.outlook ?? null;
  const notes = Array.from(new Set([...section.warnings, ...analysisNotes(result)]));
  return (
    <AltCard testId="alt-tier2">
      <TierHeader
        section={section}
        notes={notes}
        side={
          <>
            {outlook?.final_score != null ? (
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
            ) : null}
            <ActionFact result={result} />
          </>
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
}

// The fixed skeleton (owner order 2026-09-18): the dimension reports →
// one analysis card (preliminary at depth 1, deep at depth 2; both carry
// the outlook and the action) → the trade plan (levels + shares +
// warnings). The separate conclusion card is gone.
export const AltResult = ({ result, taskId }: AltResultProps) => {
  const { t } = useUiLanguage();
  const usage = result.llm_usage ?? null;
  // Token total is the exact sum of what the provider reported per call
  // — the same numbers the transcript shows for each exchange. On a run
  // that borrowed another run's analysis the line names this run's own
  // calls and the borrowed ones separately (owner wording 2026-09-19).
  const usageLine = (u: NonNullable<typeof usage>) =>
    u.own && u.borrowed
      ? t('tiered.llmUsageShared', {
          calls: u.own.calls,
          tokens: u.own.prompt_tokens + u.own.completion_tokens,
          sharedCalls: u.borrowed.calls,
          sharedTokens: u.borrowed.prompt_tokens + u.borrowed.completion_tokens,
        })
      : t('tiered.llmUsage', {
          calls: u.total.calls,
          tokens: u.total.prompt_tokens + u.total.completion_tokens,
        });

  return (
    <div className="flex flex-col gap-6">
      <AltBlock title={t('tiered.alt.dimensionsTitle')}>
        <AltDimensions dimensions={result.dimensions} />
      </AltBlock>
      {result.tier2 ? (
        <AltBlock title={t('tiered.alt.tier2Title')} helpKey="tiered.help.debate">
          <AltDebate result={result} section={result.tier2} />
        </AltBlock>
      ) : (
        <AltBlock title={t('tiered.alt.tier1Title')} helpKey="tiered.help.outlook">
          <AltPreliminary result={result} />
        </AltBlock>
      )}
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
        {usage && usage.total.calls > 0 ? (
          taskId && usage.transcript_entries ? (
            // The usage line is the transcript toggle when the run kept
            // one; runs without a transcript (expired, or recorded
            // before it existed) show the same line as plain text.
            <AltTranscript taskId={taskId} label={usageLine(usage)} />
          ) : (
            <p className="text-gray-600">
              <HelpTerm label={usageLine(usage)} helpKey="tiered.help.llmUsage" />
            </p>
          )
        ) : null}
      </div>
    </div>
  );
};
