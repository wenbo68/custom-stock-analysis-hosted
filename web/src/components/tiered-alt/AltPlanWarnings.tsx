import { useState, type ReactNode } from 'react';
import type { TieredPlanWarning } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { metricEntry } from '../../i18n/metricLabels';
import type { UiLanguage, UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, formatPrice, jumpToMetric, jumpToMetricFirst } from '../tiered/termHelpers';
import { slashDate } from './altFormat';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { AltModal, AltModalTitle, FVar, MODAL_BODY, MODAL_STRONG } from './AltUi';

// The trade-plan warnings row (plan-review redesign, 2026-07-22): the
// backend ships ids and numbers only; every sentence here is worded by
// the frontend, and every value in it is live — report values jump to
// their technicals row, plan values flash their table cell, computed
// values open the arithmetic that produced them (same three-line shape
// as the computed-cell popups), and the reward goal flashes the run
// row's reward column.

type PlanColumn = 'entry' | 'stop_loss' | 'take_profit' | 'shares';

const WARN_KEYWORD_KEYS: Record<string, UiTextKey> = {
  downtrend: 'tiered.alt.warnKey.downtrend',
  gap_atr: 'tiered.alt.warnKey.gap_atr',
  gap_worst: 'tiered.alt.warnKey.gap_worst',
  reward_below_goal: 'tiered.alt.warnKey.reward_below_goal',
  earnings_soon: 'tiered.alt.warnKey.earnings_soon',
  macro_event_soon: 'tiered.alt.warnKey.macro_event_soon',
};

// The macro events group's payload row + display-name key per warning
// event tag.
const MACRO_EVENT_REFS: Record<string, string> = {
  rate_decision: 'macro_econ.events.next_rate_decision_date',
  inflation_data: 'macro_econ.events.next_cpi_release_date',
  employment_data: 'macro_econ.events.next_jobs_release_date',
};
const MACRO_EVENT_NAME_KEYS: Record<string, UiTextKey> = {
  rate_decision: 'tiered.alt.warnEvent.rate_decision',
  inflation_data: 'tiered.alt.warnEvent.inflation_data',
  employment_data: 'tiered.alt.warnEvent.employment_data',
};

// The technicals payload moved metrics into groups (v2, 2026-07-27);
// stored runs still anchor at the old flat paths, so report jumps try
// the new path first and fall back.
const ATR_REFS = ['technicals.volatility.atr_14', 'technicals.atr_14'];
// worst_day_pct_1y has lived in three homes: volatility (2026-07-28
// regrouping), risk (early v2), and the flat v1 payload.
const WORST_PCT_REFS = [
  'technicals.volatility.worst_day_pct_1y',
  'technicals.risk.worst_day_pct_1y',
  'technicals.worst_day_pct_1y',
];

// A number for warning sentences: at most 2 decimals, no float noise.
const wNum = (value: unknown): string =>
  typeof value === 'number' ? String(Number(value.toFixed(2))) : '—';

// Price-like values match the plan table's formatting (391.20, not 391.2).
const wPrice = (value: unknown): string =>
  typeof value === 'number' ? formatPrice(value) : '—';

// Formula variables that are report metrics carry the exact label their
// technicals row shows (metricLabels shorts) — never shorthand.
const metricName = (key: string, language: UiLanguage): string =>
  metricEntry(key, language)?.short ?? key;

interface WarnEnv {
  values: Record<string, unknown>;
  /** The run's task id — lets the goal value flash the run-row reward. */
  taskId?: string;
  /** The plan cell (adjusted when one exists, else computed) per column. */
  cellTarget: (key: PlanColumn) => string;
  /** Close the warnings modal before scrolling to something behind it. */
  closeAll: () => void;
  t: (key: UiTextKey, params?: Record<string, string | number>) => string;
  language: UiLanguage;
}

// A value that closes the popup stack and scrolls/flashes its source.
const JumpValue = ({
  text,
  onJump,
  closeAll,
}: {
  text: string;
  onJump: () => void;
  closeAll: () => void;
}) => (
  <button
    type="button"
    className={cn('cursor-pointer tabular-nums', ALT_LINK)}
    onClick={() => {
      closeAll();
      // Let the modal unmount before scrolling to the row behind it.
      window.setTimeout(onJump, 50);
    }}
  >
    {text}
  </button>
);

// A computed value: clicking it opens its arithmetic, formatted exactly
// like the computed-cell popups (words / plugged-in numbers / result).
// The body builder receives a close-this-popup callback so inner links
// can collapse the whole stack before jumping.
const ComputedValue = ({
  text,
  title,
  body,
}: {
  text: string;
  title: ReactNode;
  body: (closeSelf: () => void) => ReactNode;
}) => {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
        onClick={() => setIsOpen(true)}
      >
        {text}
      </button>
      <AltModal
        isOpen={isOpen}
        title={title}
        onClose={() => setIsOpen(false)}
        panelClassName="w-fit min-w-72 max-w-[95vw]"
      >
        {body(() => setIsOpen(false))}
      </AltModal>
    </>
  );
};

const FormulaBody = ({
  words,
  plugged,
  result,
}: {
  words: ReactNode;
  plugged: ReactNode;
  result: string;
}) => (
  <div className="flex flex-col gap-2 overflow-x-auto text-sm">
    <p className={FORMULA_LINE}>{words}</p>
    <p className={FORMULA_LINE}>= {plugged}</p>
    <p className={FORMULA_RESULT}>= {result}</p>
  </div>
);

// Fill a uiText template's {name} slots with live nodes; unknown slots
// stay as text so a wording/values mismatch is visible, never silent.
const TEMPLATE_TOKEN_RE = /(\{\w+\})/g;
const fillTemplate = (template: string, nodes: Record<string, ReactNode>): ReactNode[] =>
  template.split(TEMPLATE_TOKEN_RE).map((part, index) => {
    const match = /^\{(\w+)\}$/.exec(part);
    const node = match ? nodes[match[1]] : undefined;
    return <span key={index}>{node !== undefined ? node : part}</span>;
  });

// ---------- per-warning wiring: which value is live in which way ----------

const warningNodes = (
  warning: TieredPlanWarning,
  env: WarnEnv,
): { templateKey: UiTextKey; nodes: Record<string, ReactNode> } | null => {
  const { values: v, t, language, closeAll } = env;
  const title = (nameKey: UiTextKey) => (
    <AltModalTitle subject={t(nameKey)} kind={t('tiered.alt.kind.formula')} />
  );

  const planJump = (key: PlanColumn, text: string, innerClose: () => void = closeAll) => (
    <JumpValue text={text} closeAll={innerClose} onJump={() => flashElement(env.cellTarget(key))} />
  );
  const reportJump = (refPath: string, text: string, innerClose: () => void = closeAll) => (
    <JumpValue text={text} closeAll={innerClose} onJump={() => jumpToMetric(refPath)} />
  );
  const reportJumpFirst = (refPaths: string[], text: string, innerClose: () => void = closeAll) => (
    <JumpValue text={text} closeAll={innerClose} onJump={() => jumpToMetricFirst(refPaths)} />
  );
  // Inner formula links must collapse the formula popup AND the warnings
  // modal before scrolling.
  const stack = (closeSelf: () => void) => () => {
    closeSelf();
    closeAll();
  };

  // shares × (entry − stop) — the loss the plan accepted; both gap
  // scenarios compare themselves against it.
  const plannedLoss = (
    <ComputedValue
      text={wNum(v.loss_at_stop)}
      title={title('tiered.alt.warnF.plannedLoss')}
      body={(closeSelf) => (
        <FormulaBody
          words={
            <>
              <FVar>{t('tiered.alt.f.shares')}</FVar> × (<FVar>{t('tiered.alt.f.entry')}</FVar> −{' '}
              <FVar>{t('tiered.alt.f.stop')}</FVar>)
            </>
          }
          plugged={
            <>
              {planJump('shares', wNum(v.shares), stack(closeSelf))} × (
              {planJump('entry', wPrice(v.entry), stack(closeSelf))} −{' '}
              {planJump('stop_loss', wPrice(v.stop_loss), stack(closeSelf))})
            </>
          }
          result={wNum(v.loss_at_stop)}
        />
      )}
    />
  );
  const extraLoss = (lossValue: unknown, lossNameKey: UiTextKey, extra: unknown) => (
    <ComputedValue
      text={wNum(extra)}
      title={title(lossNameKey)}
      body={() => (
        <FormulaBody
          words={
            <>
              <FVar>{t(lossNameKey)}</FVar> − <FVar>{t('tiered.alt.warnF.plannedLoss')}</FVar>
            </>
          }
          plugged={
            <>
              {wNum(lossValue)} − {wNum(v.loss_at_stop)}
            </>
          }
          result={wNum(extra)}
        />
      )}
    />
  );

  switch (warning.id) {
    case 'downtrend':
      // v2 runs compare against the 50-day average (values.sma_50);
      // stored runs carry the retired 60-day comparison (values.sma_60).
      if (typeof v.sma_50 === 'number') {
        return {
          templateKey: 'tiered.alt.warn.downtrend_50',
          nodes: {
            close: reportJumpFirst(['technicals.price.close', 'technicals.close'], wPrice(v.close)),
            sma50: reportJump('technicals.daily.sma_50', wPrice(v.sma_50)),
          },
        };
      }
      return {
        templateKey: 'tiered.alt.warn.downtrend',
        nodes: {
          close: reportJump('technicals.close', wPrice(v.close)),
          sma60: reportJump('technicals.sma_60', wPrice(v.sma_60)),
        },
      };
    case 'earnings_soon':
      return {
        templateKey: 'tiered.alt.warn.earnings_soon',
        nodes: {
          // v3 runs publish no days row (days are computed from the
          // date), so the days chip falls back to the date row; the
          // legacy paths keep old stored runs jumping to their own rows.
          days: reportJumpFirst(
            [
              'fundamentals.quarterly_report.next_earnings_date',
              'fundamentals.earnings.days_until_earnings',
              'fundamentals.days_until_earnings',
            ],
            wNum(v.days_until),
          ),
          date: reportJumpFirst(
            [
              'fundamentals.quarterly_report.next_earnings_date',
              'fundamentals.earnings.next_earnings_date',
              'fundamentals.next_earnings_date',
            ],
            typeof v.next_date === 'string' ? slashDate(v.next_date) : '—',
          ),
        },
      };
    case 'macro_event_soon': {
      // Market-wide mirror of earnings_soon: the chip jumps to the
      // macro events row the warning came from.
      const eventTag = typeof v.event === 'string' ? v.event : '';
      const eventRef = MACRO_EVENT_REFS[eventTag];
      const eventNameKey = MACRO_EVENT_NAME_KEYS[eventTag];
      const eventName = eventNameKey ? t(eventNameKey) : eventTag;
      return {
        templateKey: 'tiered.alt.warn.macro_event_soon',
        nodes: {
          event: eventName,
          days: reportJumpFirst(
            eventRef ? [eventRef] : [], wNum(v.days_until),
          ),
          date: reportJumpFirst(
            eventRef ? [eventRef] : [],
            typeof v.next_date === 'string' ? slashDate(v.next_date) : '—',
          ),
        },
      };
    }
    case 'gap_atr':
      return {
        templateKey: 'tiered.alt.warn.gap_atr',
        nodes: {
          atr: reportJumpFirst(ATR_REFS, wNum(v.atr_14)),
          stop: planJump('stop_loss', wPrice(v.stop_loss)),
          atrOpen: (
            <ComputedValue
              text={wPrice(v.atr_open)}
              title={title('tiered.alt.warnF.gapOpen')}
              body={(closeSelf) => (
                <FormulaBody
                  words={
                    <>
                      <FVar>{t('tiered.alt.f.stop')}</FVar> − {wNum(v.gap_atr_multiple)} ×{' '}
                      <FVar>{metricName('atr_14', language)}</FVar>
                    </>
                  }
                  plugged={
                    <>
                      {planJump('stop_loss', wPrice(v.stop_loss), stack(closeSelf))} −{' '}
                      {wNum(v.gap_atr_multiple)} ×{' '}
                      {reportJumpFirst(ATR_REFS, wNum(v.atr_14), stack(closeSelf))}
                    </>
                  }
                  result={wPrice(v.atr_open)}
                />
              )}
            />
          ),
          atrLoss: (
            <ComputedValue
              text={wNum(v.atr_loss)}
              title={title('tiered.alt.warnF.gapLoss')}
              body={(closeSelf) => (
                <FormulaBody
                  words={
                    <>
                      <FVar>{t('tiered.alt.f.shares')}</FVar> × (
                      <FVar>{t('tiered.alt.f.entry')}</FVar> −{' '}
                      <FVar>{t('tiered.alt.warnF.gapOpen')}</FVar>)
                    </>
                  }
                  plugged={
                    <>
                      {planJump('shares', wNum(v.shares), stack(closeSelf))} × (
                      {planJump('entry', wPrice(v.entry), stack(closeSelf))} − {wPrice(v.atr_open)})
                    </>
                  }
                  result={wNum(v.atr_loss)}
                />
              )}
            />
          ),
          planned: plannedLoss,
          atrExtra: extraLoss(v.atr_loss, 'tiered.alt.warnF.gapLoss', v.atr_extra),
        },
      };
    case 'gap_worst': {
      // New runs publish a percent (-16.97); runs stored before that fix
      // carry a raw fraction (-0.1697). Normalise to percent so one
      // formula reads correctly for both.
      const worstPct =
        typeof v.worst_day_pct === 'number'
          ? v.worst_day_pct
          : typeof v.worst_day_1y === 'number'
            ? v.worst_day_1y * 100
            : null;
      const worstDayPct =
        worstPct === null ? '—' : String(Number(worstPct.toFixed(1)));
      const worstRefs =
        typeof v.worst_day_pct === 'number'
          ? WORST_PCT_REFS
          : ['technicals.worst_day_1y'];
      // Name the variable after the report row the value links to.
      const worstName = metricName(
        typeof v.worst_day_pct === 'number' ? 'worst_day_pct_1y' : 'worst_day_1y',
        language,
      );
      return {
        templateKey: 'tiered.alt.warn.gap_worst',
        nodes: {
          worstDayPct: reportJumpFirst(worstRefs, worstDayPct),
          stop: planJump('stop_loss', wPrice(v.stop_loss)),
          worstOpen: (
            <ComputedValue
              text={wPrice(v.worst_open)}
              title={title('tiered.alt.warnF.worstOpen')}
              body={(closeSelf) => (
                <FormulaBody
                  words={
                    <>
                      <FVar>{t('tiered.alt.f.entry')}</FVar> × (1 +{' '}
                      <FVar>{worstName}</FVar> ÷ 100)
                    </>
                  }
                  plugged={
                    <>
                      {planJump('entry', wPrice(v.entry), stack(closeSelf))} × (1 +{' '}
                      {reportJumpFirst(worstRefs, worstDayPct, stack(closeSelf))} ÷ 100)
                    </>
                  }
                  result={wPrice(v.worst_open)}
                />
              )}
            />
          ),
          worstLoss: (
            <ComputedValue
              text={wNum(v.worst_loss)}
              title={title('tiered.alt.warnF.worstLoss')}
              body={(closeSelf) => (
                <FormulaBody
                  words={
                    <>
                      <FVar>{t('tiered.alt.f.shares')}</FVar> × (
                      <FVar>{t('tiered.alt.f.entry')}</FVar> −{' '}
                      <FVar>{t('tiered.alt.warnF.worstOpen')}</FVar>)
                    </>
                  }
                  plugged={
                    <>
                      {planJump('shares', wNum(v.shares), stack(closeSelf))} × (
                      {planJump('entry', wPrice(v.entry), stack(closeSelf))} −{' '}
                      {wPrice(v.worst_open)})
                    </>
                  }
                  result={wNum(v.worst_loss)}
                />
              )}
            />
          ),
          planned: plannedLoss,
          worstExtra: extraLoss(v.worst_loss, 'tiered.alt.warnF.worstLoss', v.worst_extra),
        },
      };
    }
    case 'reward_below_goal':
      return {
        templateKey: 'tiered.alt.rewardBelowGoal',
        nodes: {
          ratio: (
            <ComputedValue
              text={wNum(v.ratio)}
              title={title('tiered.alt.warnF.ratio')}
              body={(closeSelf) => (
                <FormulaBody
                  words={
                    <>
                      (<FVar>{t('tiered.alt.f.target')}</FVar> −{' '}
                      <FVar>{t('tiered.alt.f.entry')}</FVar>) ÷ (
                      <FVar>{t('tiered.alt.f.entry')}</FVar> −{' '}
                      <FVar>{t('tiered.alt.f.stop')}</FVar>)
                    </>
                  }
                  plugged={
                    <>
                      ({planJump('take_profit', wPrice(v.take_profit), stack(closeSelf))} −{' '}
                      {planJump('entry', wPrice(v.entry), stack(closeSelf))}) ÷ (
                      {planJump('entry', wPrice(v.entry), stack(closeSelf))} −{' '}
                      {planJump('stop_loss', wPrice(v.stop_loss), stack(closeSelf))})
                    </>
                  }
                  result={wNum(v.ratio)}
                />
              )}
            />
          ),
          goal: env.taskId ? (
            <JumpValue
              text={wNum(v.goal)}
              closeAll={closeAll}
              onJump={() => flashElement(`alt-run-${env.taskId}-reward`)}
            />
          ) : (
            <span className="tabular-nums">{wNum(v.goal)}</span>
          ),
        },
      };
    default:
      return null;
  }
};

export interface AltWarningsCellProps {
  column: PlanColumn;
  warnings: TieredPlanWarning[];
  label: string;
  taskId?: string;
  cellTarget: (key: PlanColumn) => string;
}

// One warnings cell: an unclickable "none", or the count as a button
// opening a modal that lists each warning — fixed keyword first, then
// the worded sentence with every value clickable.
export const AltWarningsCell = ({
  column,
  warnings,
  label,
  taskId,
  cellTarget,
}: AltWarningsCellProps) => {
  const { language, t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);

  if (warnings.length === 0) {
    // Same quiet gray as the adjusted row's "keep".
    return (
      <span data-testid={`alt-plan-warnings-${column}`} className="text-gray-500">
        {t('tiered.alt.warn.none')}
      </span>
    );
  }
  const env: WarnEnv = {
    values: {},
    taskId,
    cellTarget,
    closeAll: () => setIsOpen(false),
    t,
    language,
  };
  return (
    <>
      <button
        type="button"
        data-testid={`alt-plan-warnings-${column}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {warnings.length}
      </button>
      <AltModal
        isOpen={isOpen}
        title={<AltModalTitle subject={label} kind={t('tiered.alt.kind.warnings')} />}
        onClose={() => setIsOpen(false)}
      >
        <ul className={cn(MODAL_BODY, 'list-disc pl-4')}>
          {warnings.map((warning, index) => {
            const keywordKey = WARN_KEYWORD_KEYS[warning.id];
            const built = warningNodes(warning, { ...env, values: warning.values });
            return (
              <li key={index}>
                {keywordKey ? (
                  <span className={MODAL_STRONG}>{t(keywordKey)}: </span>
                ) : null}
                {built ? fillTemplate(t(built.templateKey), built.nodes) : warning.id}
              </li>
            );
          })}
        </ul>
      </AltModal>
    </>
  );
};
