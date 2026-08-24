import { useMemo, useState, type ReactNode } from 'react';
import type {
  TieredCitation,
  TieredLevelDetail,
  TieredLevelReason,
  TieredLevels,
  TieredLevelsDetail,
  TieredPlanWarnings,
  TieredReviewFailure,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { metricEntry } from '../../i18n/metricLabels';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, formatPrice, jumpToMetricFirst } from '../tiered/termHelpers';
import { HelpTerm as BaseHelpTerm } from '../tiered/terms';
import { LinkedTextV8 } from './AltDebateTree';
import { AltWarningsCell } from './AltPlanWarnings';
import { adjustedCellId, computedCellId, plainNumber, riskPctText } from './altFormat';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import {
  AltEvidenceRefs,
  AltModal,
  AltModalTitle,
  AltSectionLabel,
  FVar,
  MODAL_BODY,
  MODAL_STRONG,
} from './AltUi';

// Alt skin rule: help popups everywhere, dotted underlines nowhere.
const HelpTerm = (props: Parameters<typeof BaseHelpTerm>[0]) => (
  <BaseHelpTerm underline={false} {...props} />
);

// Backup entry retired (owner decision, 2026-07-21): the plan is one
// order at the entry, so the table shows three levels — old stored
// runs simply no longer render their backup column. The plan-review
// redesign (2026-07-22) adds the shares column at the end.
const LEVEL_ORDER = ['entry', 'stop_loss', 'take_profit'] as const;
type LevelKey = (typeof LEVEL_ORDER)[number];
const COLUMNS = ['entry', 'stop_loss', 'take_profit', 'shares'] as const;
type ColumnKey = (typeof COLUMNS)[number];

const LEVEL_LABEL_KEYS: Record<ColumnKey, UiTextKey> = {
  entry: 'tiered.levels.entry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
  shares: 'tiered.levels.shares',
};

const LEVEL_HELP_KEYS: Record<ColumnKey, UiTextKey> = {
  entry: 'tiered.help.entry',
  stop_loss: 'tiered.help.stopLoss',
  take_profit: 'tiered.help.takeProfit',
  shares: 'tiered.help.sizing',
};

// Every risk line — an AI adjustment reason or a plan warning — opens
// with a fixed keyword so the reader can categorize it at a glance
// (owner decision 2026-07-22). The keyword comes from the backend's
// deterministic check/warning id, never from LLM text; unknown ids
// render without one rather than get a made-up label.
const CHECK_KEYWORD_KEYS: Record<string, UiTextKey> = {
  downtrend: 'tiered.alt.checkKey.downtrend',
  liquidity: 'tiered.alt.checkKey.liquidity',
  volatility: 'tiered.alt.checkKey.volatility',
  stop_vs_swing_low: 'tiered.alt.checkKey.stop_vs_swing_low',
  // v2 (2026-07-27): the stop check compares against the nearest pivot
  // support now; stored runs keep the old id above.
  stop_vs_support: 'tiered.alt.checkKey.stop_vs_support',
};

// One bullet per reason, each opening with its check keyword; old stored
// runs (a single paragraph, no check) get one keyword-less bullet.
// `leading` renders as the first bullet regardless of reasons — the
// shares modal always opens with its arithmetic receipt (2026-07-22).
const AdjustReasonList = ({
  reasons,
  legacyReason,
  legacyLinks,
  leading,
}: {
  reasons: TieredLevelReason[];
  legacyReason?: string | null;
  legacyLinks?: TieredLevelDetail['links'];
  leading?: ReactNode;
}) => {
  const { t } = useUiLanguage();
  if (!leading && reasons.length === 0 && !legacyReason) {
    return null;
  }
  return (
    <ul className="flex list-disc flex-col gap-2 pl-4" data-testid="alt-adjust-reasons">
      {leading ? <li data-testid="alt-adjust-receipt">{leading}</li> : null}
      {reasons.map((reason, index) => {
        const keywordKey = CHECK_KEYWORD_KEYS[reason.check];
        return (
          <li key={index}>
            <span className={MODAL_STRONG}>{keywordKey ? t(keywordKey) : reason.check}: </span>
            <LinkedTextV8 text={reason.text} links={reason.links ?? []} />
          </li>
        );
      })}
      {reasons.length === 0 && legacyReason ? (
        <li>
          {legacyLinks && legacyLinks.length > 0 ? (
            <LinkedTextV8 text={legacyReason} links={legacyLinks} />
          ) : (
            legacyReason
          )}
        </li>
      ) : null}
    </ul>
  );
};

// Formula inputs with a source row on the technicals card, and the
// payload path(s) that row anchors at. The technicals payload moved
// metrics into groups (v2, 2026-07-27); stored runs still anchor at the
// old flat paths, so jumps try the new path first and fall back.
const TECHNICALS_INPUT_REFS: Record<string, string[]> = {
  close: ['technicals.price.close', 'technicals.close'],
  atr_14: ['technicals.volatility.atr_14', 'technicals.atr_14'],
  // v2 level anchors (2026-07-27)
  sma_50: ['technicals.daily.sma_50'],
  sma_200: ['technicals.daily.sma_200'],
  support_1: ['technicals.levels.support_1'],
  resistance_1: ['technicals.levels.resistance_1'],
  high_1y: ['technicals.price.high_1y'],
  // v1 anchors old stored runs still carry
  sma_20: ['technicals.sma_20'],
  sma_60: ['technicals.sma_60'],
  swing_low_20: ['technicals.swing_low_20'],
  swing_low_60: ['technicals.swing_low_60'],
  swing_high_20: ['technicals.swing_high_20'],
  swing_high_60: ['technicals.swing_high_60'],
  high_52w: ['technicals.high_52w'],
};

// Formula inputs that ARE another computed level of this same table (the
// stop uses the computed entry, the target uses the computed stop) — their
// numbers link to that computed cell, so every number in a formula points
// at a place it already appeared.
const COMPUTED_CELL_INPUTS: Record<string, LevelKey> = {
  ideal_entry: 'entry',
  stop_loss: 'stop_loss',
};

// On-screen names for formula variables: report inputs carry the exact
// label their technicals row shows (metricLabels shorts, owner decision
// 2026-07-28) — never raw underscore tokens. Variables that are the
// plan's own numbers reuse the card's uiText names (the backend key
// stays ideal_entry for old stored runs; it displays as the entry).
const useVarLabel = (): ((key: string) => string) => {
  const { language, t } = useUiLanguage();
  return (key: string): string => {
    if (key === 'ideal_entry') return t('tiered.alt.f.entry');
    if (key === 'stop_loss') return t('tiered.alt.f.stop');
    if (key === 'round_level') return t('tiered.alt.roundLevelTitle');
    return metricEntry(key, language)?.short ?? key;
  };
};

// The stored formulas name two input GROUPS in prose. Expanding the
// phrases into the run's actual input keys lets the split-and-link
// machinery below turn every one of them into a real, clickable number.
// Each list carries both generations: v2 keys (2026-07-27) and the v1
// keys old stored runs still hold — a run only ever has one set.
const SUPPORT_KEYS = [
  'sma_50', 'sma_200', 'support_1',
  'sma_20', 'sma_60', 'swing_low_20', 'swing_low_60',
  'round_level',
];
const RESISTANCE_KEYS = [
  'resistance_1', 'high_1y',
  'swing_high_20', 'swing_high_60', 'high_52w',
];

const expandProse = (formula: string, inputs: Record<string, number>): string => {
  let expanded = formula;
  const supports = SUPPORT_KEYS.filter((key) => inputs[key] !== undefined);
  if (supports.length > 0) {
    expanded = expanded.replace('support candidates', supports.join(', '));
  }
  const resistances = RESISTANCE_KEYS.filter((key) => inputs[key] !== undefined);
  if (resistances.length > 0) {
    expanded = expanded.replace(
      'nearest overhead resistance',
      `nearest of (${resistances.join(', ')})`,
    );
  }
  return expanded;
};

const splitOnInputs = (formula: string, inputs: Record<string, number>): string[] => {
  const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
  if (keys.length === 0) {
    return [formula];
  }
  return expandProse(formula, inputs).split(new RegExp(`(${keys.join('|')})`, 'g'));
};

// The round level is computed on the spot (the largest round price below
// the close), so it has no source row to link to — clicking it opens a
// small how-computed note instead.
const RoundLevelNumber = ({ value }: { value: number }) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-label={t('tiered.alt.roundLevelTitle')}
        data-testid="alt-round-level"
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
        onClick={() => setIsOpen(true)}
      >
        {formatPrice(value)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.alt.roundLevelTitle')}
        onClose={() => setIsOpen(false)}
      >
        <p className={MODAL_BODY}>
          {t('tiered.alt.roundLevelBody', { value: formatPrice(value) })}
        </p>
      </AltModal>
    </>
  );
};

// One plugged-in number, linking to where it already appears — a
// technicals metric row, or another computed cell of the levels table.
const InputNumberLink = ({
  inputKey,
  value,
  onNavigate,
}: {
  inputKey: string;
  value: number;
  onNavigate: () => void;
}) => {
  const varLabel = useVarLabel();
  if (inputKey === 'round_level') {
    return <RoundLevelNumber value={value} />;
  }
  const computedTarget = COMPUTED_CELL_INPUTS[inputKey];
  const technicalsRefs = TECHNICALS_INPUT_REFS[inputKey];
  const jump = technicalsRefs
    ? () => jumpToMetricFirst(technicalsRefs)
    : computedTarget
      ? () => flashElement(computedCellId(computedTarget))
      : null;
  if (!jump) {
    return <span className="tabular-nums">{formatPrice(value)}</span>;
  }
  return (
    <button
      type="button"
      aria-label={varLabel(inputKey)}
      className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      onClick={() => {
        onNavigate();
        // Let the modal unmount before scrolling to the row behind it.
        window.setTimeout(jump, 50);
      }}
    >
      {formatPrice(value)}
    </button>
  );
};

interface AltFormulaProps {
  formula: string;
  inputs: Record<string, number>;
  onNavigate: () => void;
}

// The formula in words: variables italic, everything else as written.
const AltFormulaWords = ({ formula, inputs }: Omit<AltFormulaProps, 'onNavigate'>) => {
  const varLabel = useVarLabel();
  return (
    <>
      {splitOnInputs(formula, inputs).map((part, index) =>
        inputs[part] === undefined ? (
          <span key={index}>{part}</span>
        ) : (
          <FVar key={index}>{varLabel(part)}</FVar>
        ),
      )}
    </>
  );
};

// The formula with each input replaced by this run's number.
const AltFormula = ({ formula, inputs, onNavigate }: AltFormulaProps) => {
  const parts = useMemo(() => splitOnInputs(formula, inputs), [formula, inputs]);

  return (
    <>
      {parts.map((part, index) =>
        inputs[part] === undefined ? (
          <span key={index}>{part}</span>
        ) : (
          <InputNumberLink key={index} inputKey={part} value={inputs[part]} onNavigate={onNavigate} />
        ),
      )}
    </>
  );
};

interface AltLevelCellProps {
  levelKey: LevelKey;
  detail: TieredLevelDetail | null;
  label: string;
  citations: TieredCitation[];
}

// The computed (formula-base) number. Clicking it opens the receipts, in
// the shares-computation shape: the formula, the formula with this run's
// numbers plugged in (each number a link to its source), and the result.
const AltComputedCell = ({ levelKey, detail, label }: Omit<AltLevelCellProps, 'citations'>) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }

  return (
    <>
      <button
        type="button"
        id={computedCellId(levelKey)}
        data-testid={`alt-level-computed-${levelKey}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {formatPrice(detail.base)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={<AltModalTitle subject={label} kind={t('tiered.alt.kind.formula')} />}
        onClose={close}
        // Fit the widest formula line; each line stays a single line.
        panelClassName="w-fit min-w-72 max-w-[95vw]"
      >
        {!detail.formula ? (
          <p>{t('tiered.levelModal.noBase')}</p>
        ) : (
          <div className="flex flex-col gap-2 overflow-x-auto text-sm" data-testid="alt-formula-modal">
            <p className={FORMULA_LINE} data-testid="alt-formula-words">
              <AltFormulaWords formula={detail.formula} inputs={detail.inputs ?? {}} />
            </p>
            <p className={FORMULA_LINE} data-testid="alt-formula-plugged">
              {'= '}
              <AltFormula formula={detail.formula} inputs={detail.inputs ?? {}} onNavigate={close} />
            </p>
            <p className={FORMULA_RESULT}>= {formatPrice(detail.base)}</p>
          </div>
        )}
      </AltModal>
    </>
  );
};

// The AI's adjusted number — or "keep" when the computed value stands.
// Clicking the number opens why the AI moved it, with its references.
const AltAdjustedCell = ({ levelKey, detail, label, citations }: AltLevelCellProps) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }
  if (detail.adjusted === null) {
    return (
      <span data-testid={`alt-level-keep-${levelKey}`} className="text-gray-500">
        {t('tiered.alt.levels.keep')}
      </span>
    );
  }

  return (
    <>
      <button
        type="button"
        id={adjustedCellId(levelKey)}
        data-testid={`alt-level-adjusted-${levelKey}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {formatPrice(detail.adjusted)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={<AltModalTitle subject={label} kind={t('tiered.alt.kind.adjustment')} />}
        onClose={close}
      >
        <div className={MODAL_BODY}>
          {/* No header lines (owner decision 2026-07-22): straight to the
              bulleted reasons, keyword first, cited values linked. */}
          <AdjustReasonList
            reasons={detail.reasons ?? []}
            legacyReason={detail.reason}
            legacyLinks={detail.links}
          />
          {detail.evidence.length > 0 ? (
            <div>
              <AltSectionLabel>{t('tiered.levelModal.references')}</AltSectionLabel>
              <ul className="flex flex-col gap-1">
                {detail.evidence.map((refPath, index) => (
                  <li key={index} className="flex gap-2 text-xs">
                    <span className="shrink-0 text-gray-500">[{index + 1}]</span>
                    <AltEvidenceRefs refs={[refPath]} citations={citations} onNavigate={close} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </AltModal>
    </>
  );
};

// When the check-adjust cycle never converged, the backend threw every
// adjustment away — the whole adjusted row shows "keep" in link-blue and
// clicking any of them opens what still failed in each round.
const AltKeepFailedCell = ({
  columnKey,
  detail,
  failures,
}: {
  columnKey: ColumnKey;
  detail: TieredLevelDetail | null;
  failures: TieredReviewFailure[];
}) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }
  const checkNames = (checks: string[]) =>
    checks
      .map((check) => {
        const keywordKey = CHECK_KEYWORD_KEYS[check];
        return keywordKey ? t(keywordKey) : check;
      })
      .join(', ');
  return (
    <>
      <button
        type="button"
        data-testid={`alt-level-keepfail-${columnKey}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer', ALT_LINK)}
      >
        {t('tiered.alt.levels.keep')}
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.alt.reviewFail.title')}
        onClose={() => setIsOpen(false)}
      >
        <div className={MODAL_BODY}>
          <p>{t('tiered.alt.reviewFail.intro')}</p>
          <ul className="flex list-disc flex-col gap-2 pl-4" data-testid="alt-review-failures">
            {failures.map((failure, index) => (
              <li key={index}>
                {t('tiered.alt.reviewFail.round', {
                  round: String(failure.round),
                  checks: checkNames(failure.checks),
                })}
              </li>
            ))}
          </ul>
        </div>
      </AltModal>
    </>
  );
};

// ---------- the shares column (plan-review redesign, 2026-07-22) ----------

// A number that scroll-flashes the element it came from (run-row inputs,
// plan-table cells); plain text when there is nothing to point at.
const FlashNum = ({ targetId, text }: { targetId: string | null; text: string }) =>
  targetId ? (
    <button
      type="button"
      className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      onClick={() => flashElement(targetId)}
    >
      {text}
    </button>
  ) : (
    <span className="tabular-nums text-gray-300">{text}</span>
  );

// The share-count arithmetic, in the same three-line receipt shape as the
// level formulas: words, this run's numbers (each linking to where it
// already appears), result.
const SharesReceipt = ({
  inputs,
  shares,
  taskId,
  entryTargetId,
  stopTargetId,
}: {
  inputs: Record<string, number>;
  shares: number;
  taskId?: string;
  entryTargetId: string | null;
  stopTargetId: string | null;
}) => {
  const { t } = useUiLanguage();
  const capital = inputs.capital;
  const risk = inputs.risk_fraction;
  const entry = inputs.entry;
  const stop = inputs.stop_loss;
  return (
    <div className="flex flex-col gap-2 overflow-x-auto text-sm" data-testid="alt-shares-receipt">
      <p className={FORMULA_LINE}>
        <FVar>{t('tiered.alt.f.capital')}</FVar> × <FVar>{t('tiered.alt.f.risk')}</FVar>
        {' / ('}
        <FVar>{t('tiered.alt.f.entry')}</FVar> − <FVar>{t('tiered.alt.f.stop')}</FVar>
        {')'}
      </p>
      <p className={FORMULA_LINE}>
        {'= '}
        <FlashNum
          targetId={taskId ? `alt-run-${taskId}-capital` : null}
          text={capital != null ? plainNumber(capital) : '—'}
        />
        {' × '}
        <FlashNum
          targetId={taskId ? `alt-run-${taskId}-risk` : null}
          text={risk != null ? `${riskPctText(risk)}%` : '—'}
        />
        {' / ('}
        <FlashNum targetId={entryTargetId} text={formatPrice(entry ?? null)} />
        {' − '}
        <FlashNum targetId={stopTargetId} text={formatPrice(stop ?? null)} />
        {')'}
      </p>
      <p className={FORMULA_RESULT}>= {t('tiered.altHistory.shares', { value: shares })}</p>
    </div>
  );
};

interface SharesCellProps {
  detail: TieredLevelDetail | null;
  taskId?: string;
  /** Whether entry / stop carry an accepted adjustment (links target). */
  levelAdjusted: (key: LevelKey) => boolean;
}

// The computed share count — clicking it opens the arithmetic receipt.
const AltSharesComputedCell = ({ detail, taskId }: Omit<SharesCellProps, 'levelAdjusted'>) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }
  return (
    <>
      <button
        type="button"
        id={computedCellId('shares')}
        data-testid="alt-level-computed-shares"
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {detail.base}
      </button>
      <AltModal
        isOpen={isOpen}
        title={
          <AltModalTitle
            subject={t('tiered.levels.shares')}
            kind={t('tiered.alt.kind.formula')}
          />
        }
        onClose={() => setIsOpen(false)}
        panelClassName="w-fit min-w-72 max-w-[95vw]"
      >
        <SharesReceipt
          inputs={detail.inputs ?? {}}
          shares={detail.base}
          taskId={taskId}
          entryTargetId={computedCellId('entry')}
          stopTargetId={computedCellId('stop_loss')}
        />
      </AltModal>
    </>
  );
};

// The adjusted share count: an AI trim opens its cited reason; a purely
// mechanical recompute (a level moved, so the count followed) opens the
// same receipt with the final levels plugged in.
const AltSharesAdjustedCell = ({ detail, taskId, levelAdjusted }: SharesCellProps) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }
  if (detail.adjusted === null) {
    return (
      <span data-testid="alt-level-keep-shares" className="text-gray-500">
        {t('tiered.alt.levels.keep')}
      </span>
    );
  }
  const levelTarget = (key: LevelKey): string =>
    levelAdjusted(key) ? adjustedCellId(key) : computedCellId(key);
  return (
    <>
      <button
        type="button"
        id={adjustedCellId('shares')}
        data-testid="alt-level-adjusted-shares"
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {detail.adjusted}
      </button>
      <AltModal
        isOpen={isOpen}
        title={
          <AltModalTitle
            subject={t('tiered.levels.shares')}
            kind={t('tiered.alt.kind.adjustment')}
          />
        }
        onClose={() => setIsOpen(false)}
        panelClassName="w-fit min-w-72 max-w-[95vw]"
      >
        <div className={MODAL_BODY}>
          {/* Bullet 1 is always the mechanical recompute from the adjusted
              levels — the AI trim's reasons follow (owner, 2026-07-22). */}
          <AdjustReasonList
            reasons={detail.reasons ?? []}
            legacyReason={detail.reason}
            legacyLinks={detail.links}
            leading={
              detail.adjusted_inputs ? (
                <SharesReceipt
                  inputs={detail.adjusted_inputs}
                  shares={detail.mechanical ?? detail.adjusted}
                  taskId={taskId}
                  entryTargetId={levelTarget('entry')}
                  stopTargetId={levelTarget('stop_loss')}
                />
              ) : undefined
            }
          />
        </div>
      </AltModal>
    </>
  );
};

// ---------- the warnings row ----------
// Rendering lives in AltPlanWarnings.tsx: keyword-first sentences whose
// every value is clickable (report rows, plan cells, formula popups).

interface AltLevelsProps {
  levels: TieredLevels;
  levelsDetail: TieredLevelsDetail | null | undefined;
  citations: TieredCitation[];
  /** Plan-review warnings per column; absent on old stored runs. */
  planWarnings?: TieredPlanWarnings | null;
  /** The run's task id — lets the shares receipt link the run-row inputs. */
  taskId?: string;
}

const CELL = 'py-1.5 pr-4 text-sm';
const ROW_LABEL = 'py-1.5 pr-4 text-xs text-gray-500';

// The trade plan as a computed/adjusted table — the three price levels
// plus the share count, with the AI's validated adjustments beneath the
// formula bases and (on plan-review runs) a warnings row underneath.
// Old runs without the audit trail fall back to a single row of values.
export const AltLevels = ({
  levels,
  levelsDetail,
  citations,
  planWarnings,
  taskId,
}: AltLevelsProps) => {
  const { t } = useUiLanguage();
  const details = levelsDetail?.levels ?? null;
  const sharesDetail = details?.shares ?? null;
  const reviewFailures = levelsDetail?.review_failures ?? [];
  const levelAdjusted = (key: LevelKey): boolean =>
    (details?.[key]?.adjusted ?? null) !== null;
  // Where a warning value pointing at a plan column should flash: the
  // adjusted cell when an adjustment exists, else the computed cell.
  const cellTarget = (key: ColumnKey): string => {
    const isAdjusted =
      key === 'shares' ? (sharesDetail?.adjusted ?? null) !== null : levelAdjusted(key);
    return isAdjusted ? adjustedCellId(key) : computedCellId(key);
  };

  const headerCells: ReactNode = (
    <tr>
      <th className="pb-1.5 pr-4" />
      {COLUMNS.map((key) => (
        <th key={key} className="pb-1.5 pr-4 text-left text-xs font-semibold text-gray-500">
          <HelpTerm label={t(LEVEL_LABEL_KEYS[key])} helpKey={LEVEL_HELP_KEYS[key]} />
        </th>
      ))}
    </tr>
  );

  return (
    <div className="overflow-x-auto" data-testid="alt-levels-table">
      <table className="w-full">
        <thead>{headerCells}</thead>
        <tbody>
          {details ? (
            <>
              <tr>
                <td className={ROW_LABEL}>{t('tiered.alt.levels.computed')}</td>
                {LEVEL_ORDER.map((key) => (
                  <td key={key} className={CELL}>
                    <AltComputedCell
                      levelKey={key}
                      detail={details[key] ?? null}
                      label={t(LEVEL_LABEL_KEYS[key])}
                    />
                  </td>
                ))}
                <td className={CELL}>
                  <AltSharesComputedCell detail={sharesDetail} taskId={taskId} />
                </td>
              </tr>
              <tr>
                <td className={ROW_LABEL}>{t('tiered.alt.levels.adjusted')}</td>
                {reviewFailures.length > 0 ? (
                  COLUMNS.map((key) => (
                    <td key={key} className={CELL}>
                      <AltKeepFailedCell
                        columnKey={key}
                        detail={(key === 'shares' ? sharesDetail : details[key]) ?? null}
                        failures={reviewFailures}
                      />
                    </td>
                  ))
                ) : (
                  <>
                    {LEVEL_ORDER.map((key) => (
                      <td key={key} className={CELL}>
                        <AltAdjustedCell
                          levelKey={key}
                          detail={details[key] ?? null}
                          label={t(LEVEL_LABEL_KEYS[key])}
                          citations={citations}
                        />
                      </td>
                    ))}
                    <td className={CELL}>
                      <AltSharesAdjustedCell
                        detail={sharesDetail}
                        taskId={taskId}
                        levelAdjusted={levelAdjusted}
                      />
                    </td>
                  </>
                )}
              </tr>
              {planWarnings ? (
                <tr>
                  <td className={ROW_LABEL}>{t('tiered.alt.levels.warnings')}</td>
                  {COLUMNS.map((key) => (
                    <td key={key} className={CELL}>
                      <AltWarningsCell
                        column={key}
                        warnings={planWarnings[key] ?? []}
                        label={t(LEVEL_LABEL_KEYS[key])}
                        taskId={taskId}
                        cellTarget={cellTarget}
                      />
                    </td>
                  ))}
                </tr>
              ) : null}
            </>
          ) : (
            <tr>
              <td className={ROW_LABEL} />
              {LEVEL_ORDER.map((key) => (
                <td key={key} className={cn(CELL, 'tabular-nums text-gray-300')}>
                  {formatPrice(levels[key])}
                </td>
              ))}
              <td className={cn(CELL, 'text-gray-600')}>—</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
