import { useState, type ReactNode } from 'react';
import type {
  TieredDebateAuthorVote,
  TieredDebateDetail,
  TieredDebateItem,
  TieredDebateLink,
  TieredDebateVote,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, jumpToMetric } from '../tiered/termHelpers';
import { stripInlineRefs } from './altFormat';
import { FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import {
  AltFold,
  AltModal,
  AltModalDivider,
  AltModalTitle,
  AltSectionLabel,
  FVar,
  MODAL_BODY,
} from './AltUi';

// The evidence vote tree (debate format 11): every bullet the two
// analysts listed, grouped by dimension, with each voter's check mark,
// the 1-5 significance median, and the final weighted score. Bullets
// struck by the code's citation check or outvoted are crossed out.
// Display order of the dimensions is the owner's (2026-08-19).
const DIRECTION_TEXT: Record<string, string> = {
  bullish: 'text-emerald-300',
  bearish: 'text-red-300',
};

const DIMENSION_ORDER = [
  'technicals',
  'fundamentals',
  'positioning',
  'macro_econ',
  'company_events',
  'world_events',
];

const DIMENSION_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  positioning: 'tiered.dimension.positioning',
  company_events: 'tiered.dimension.company_events',
  world_events: 'tiered.dimension.world_events',
};

const CITATION_REF_RE = /^citation:(\d+)$/;

const jumpToRef = (ref: string) => {
  const citationMatch = CITATION_REF_RE.exec(ref);
  if (citationMatch) {
    flashElement(`alt-src-sentiment-${citationMatch[1]}`);
  } else {
    jumpToMetric(ref);
  }
};

// Where a display value may appear in a claim sentence — the exact
// string, tolerating thousands separators and (for text values)
// case/underscore looseness, with digit boundaries so "205" never
// matches inside "1205" or "205.4". Mirrors the backend's value_pattern.
const valuePattern = (valueText: string): RegExp => {
  const parts: string[] = [];
  const escape = (char: string) => char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (let index = 0; index < valueText.length; index += 1) {
    const char = valueText[index];
    parts.push(char === '_' ? '[_ ]' : escape(char));
    if (/\d/.test(char) && index + 1 < valueText.length && /\d/.test(valueText[index + 1])) {
      parts.push(',?');
    }
  }
  let pattern = parts.join('');
  if (/^\d/.test(valueText) || /^-\d/.test(valueText)) {
    pattern = `(?<![\\d.])${pattern}`;
  }
  if (/\d$/.test(valueText)) {
    pattern = `${pattern}(?!\\.?\\d)`;
  }
  return new RegExp(pattern, /\d/.test(valueText) ? '' : 'i');
};

// v7 claims: each payload link underlines exactly its cited display
// value inside the sentence; sentiment links underline their words.
// Links are located left to right, consuming the claim as they go.
// Exported: the structured summary outline renders its bullets under
// the same contract.
export const LinkedClaimV7 = ({
  claim,
  links,
  struck,
}: {
  claim: string;
  links: TieredDebateLink[];
  struck: boolean;
}) => {
  const markers: { start: number; end: number; link: TieredDebateLink }[] = [];
  // Links whose value never appears in the sentence (a news-event
  // citation carries the whole summary as its value) still need a jump
  // affordance — they render as trailing ↗ chips instead of underlines.
  const unmatched: TieredDebateLink[] = [];
  let cursor = 0;
  links.forEach((link) => {
    let start = -1;
    let end = -1;
    if (link.text) {
      start = claim.indexOf(link.text, cursor);
      end = start >= 0 ? start + link.text.length : -1;
    } else if (link.value != null) {
      const match = valuePattern(String(link.value)).exec(claim.slice(cursor));
      if (match) {
        start = cursor + match.index;
        end = start + match[0].length;
      }
    }
    if (start >= 0) {
      markers.push({ start, end, link });
      cursor = end;
    } else {
      unmatched.push(link);
    }
  });
  const segments: ReactNode[] = [];
  let from = 0;
  markers.forEach((marker, index) => {
    if (marker.start > from) {
      segments.push(<span key={`t${index}`}>{claim.slice(from, marker.start)}</span>);
    }
    segments.push(
      <button
        key={`l${index}`}
        type="button"
        className="cursor-pointer text-blue-300 underline decoration-1 decoration-blue-400/60 underline-offset-2 hover:text-blue-200"
        onClick={() => jumpToRef(marker.link.ref)}
      >
        {claim.slice(marker.start, marker.end)}
      </button>,
    );
    from = marker.end;
  });
  if (from < claim.length) {
    segments.push(<span key="tail">{claim.slice(from)}</span>);
  }
  unmatched.forEach((link, index) => {
    segments.push(
      <button
        key={`u${index}`}
        type="button"
        className="ml-1 cursor-pointer text-blue-300 hover:text-blue-200"
        onClick={() => jumpToRef(link.ref)}
      >
        ↗
      </button>,
    );
  });
  return (
    <span
      className={cn(
        'text-gray-200',
        // The strikethrough IS the verdict: code could not verify this
        // bullet's citations even after the fix rounds.
        struck && 'line-through decoration-gray-500 opacity-60',
      )}
    >
      {segments}
    </span>
  );
};

// v8 text with links: payload links underline exactly their cited
// display value inside the sentence; sentiment links render as trailing
// [N] hyperlinks that jump to source N. Used for claims AND vote reasons
// — here and in the tier-3 risk tree (AltRiskTree).
export const LinkedTextV8 = ({
  text: rawText,
  links: rawLinks,
  struck = false,
}: {
  text: string;
  links: TieredDebateLink[];
  struck?: boolean;
}) => {
  const { text, links } = stripInlineRefs(rawText, rawLinks);
  const payloadLinks = links.filter((link) => !CITATION_REF_RE.test(link.ref));
  const citationLinks = links.filter((link) => CITATION_REF_RE.test(link.ref));
  const markers: { start: number; end: number; link: TieredDebateLink }[] = [];
  let cursor = 0;
  payloadLinks.forEach((link) => {
    if (link.value == null) {
      return;
    }
    const match = valuePattern(String(link.value)).exec(text.slice(cursor));
    if (match) {
      const start = cursor + match.index;
      markers.push({ start, end: start + match[0].length, link });
      cursor = start + match[0].length;
    }
  });
  const segments: ReactNode[] = [];
  let from = 0;
  markers.forEach((marker, index) => {
    if (marker.start > from) {
      segments.push(<span key={`t${index}`}>{text.slice(from, marker.start)}</span>);
    }
    segments.push(
      <button
        key={`v${index}`}
        type="button"
        className="cursor-pointer text-blue-300 underline decoration-1 decoration-blue-400/60 underline-offset-2 hover:text-blue-200"
        onClick={() => jumpToRef(marker.link.ref)}
      >
        {text.slice(marker.start, marker.end)}
      </button>,
    );
    from = marker.end;
  });
  if (from < text.length) {
    segments.push(<span key="tail">{text.slice(from)}</span>);
  }
  return (
    <span
      className={cn(
        // The strikethrough IS the verdict: struck by the code citation
        // check, or voted out of the final pool.
        struck && 'line-through decoration-gray-500 opacity-60',
      )}
    >
      {segments}
      {citationLinks.map((link, index) => {
        const number = CITATION_REF_RE.exec(link.ref)?.[1];
        return (
          <button
            key={`c${index}`}
            type="button"
            className="ml-1 cursor-pointer text-blue-300 underline decoration-1 decoration-blue-400/60 underline-offset-2 hover:text-blue-200"
            onClick={() => jumpToRef(link.ref)}
          >
            [{number}]
          </button>
        );
      })}
    </span>
  );
};

// A clickable vote/check mark — the mark IS the record, the modal
// carries the reasoning. Shared with the tier-3 risk tree.
export const MarkButton = ({ label, onClick }: { label: string; onClick: () => void }) => (
  <button
    type="button"
    className="cursor-pointer font-semibold text-gray-400 hover:text-gray-200"
    onClick={onClick}
  >
    {label}
  </button>
);

export type MarkModal = { title: ReactNode; body: ReactNode };

// One v8-v11 bullet, a single line telling its whole history: id, a
// colored bullish/bearish word, then the marks. v11 (rich): the median
// importance score first, then one ✓ per lister who authored the bullet
// and one ✓/✗ per check/deciding vote — clicking a mark opens the
// voter's validity reason, their 1-5 score and why; clicking the median
// lists every score. v8-v10 keep their layout: ✓/✗ marks for the vote
// rounds only (no mark at all = both analysts listed it independently),
// v10 with its `w N` weight badge. The code's ✗ marks a struck bullet
// in every generation. A bullet out of the final pool is crossed out;
// the claim wraps with a hanging indent (its own grid column).
const VoteItem = ({
  item,
  onShow,
}: {
  item: TieredDebateItem;
  onShow: (modal: MarkModal) => void;
}) => {
  const { t } = useUiLanguage();
  const dead = item.final_status === 'excluded';
  const votes = item.votes ?? [];
  const authorVotes = item.author_votes ?? [];
  // v11 modal body — the owner-spec'd shape (2026-07-22): a verdict
  // line, the validity reason, a divider, then the voter's 1-5
  // significance score and why they rated it that. No bold anywhere.
  const scoreBody = (
    verdictOk: boolean,
    reasonNode: ReactNode,
    weight: number | null | undefined,
    weightReason?: string | null,
  ) => (
    <div className={MODAL_BODY}>
      <p>
        {t('tiered.tree.verdictLine', {
          value: t(verdictOk ? 'tiered.tree.valid' : 'tiered.tree.invalid'),
        })}
      </p>
      <p>
        {t('tiered.tree.reasonPrefix')} {reasonNode}
      </p>
      <AltModalDivider />
      <p>{t('tiered.tree.scoreLine', { value: weight ?? '—' })}</p>
      {weightReason ? (
        <p>
          {t('tiered.tree.reasonPrefix')} {weightReason}
        </p>
      ) : null}
    </div>
  );
  // A lister's own check: listing the bullet IS their valid vote, so the
  // validity reason is the claim itself (with its verified links).
  const showAuthor = (vote: TieredDebateAuthorVote) =>
    onShow({
      title: t('tiered.tree.lister', { n: vote.lister }),
      body: scoreBody(
        true,
        <LinkedTextV8 text={item.claim} links={item.links ?? []} />,
        vote.weight,
        vote.weight_reason,
      ),
    });
  // Checkers are numbered by vote order — always "Checker 1/2", never a
  // separate decider word (owner decision 2026-07-22).
  const showRichVote = (vote: TieredDebateVote, index: number) =>
    onShow({
      title: t('tiered.tree.checker', { n: index + 1 }),
      body: scoreBody(
        vote.verdict === 'valid',
        vote.reason ? <LinkedTextV8 text={vote.reason} links={vote.links ?? []} /> : '—',
        vote.weight,
        vote.weight_reason,
      ),
    });
  const showMedian = () => {
    const scores = [
      ...authorVotes.map((vote) => vote.weight),
      ...votes.map((vote) => vote.weight),
    ].filter((value): value is number => value != null);
    onShow({
      title: t('tiered.tree.medianTitle'),
      body: (
        <div className={MODAL_BODY}>
          <p>{t('tiered.tree.scoresList', { value: scores.join(' | ') || '—' })}</p>
          <p>{t('tiered.tree.medianLine', { value: item.weight ?? '—' })}</p>
        </div>
      ),
    });
  };
  return (
    <li
      data-testid={`alt-tree-item-${item.id}`}
      className="grid grid-cols-[auto_1fr] gap-x-2 text-xs"
    >
      <span className="flex items-baseline gap-1.5 whitespace-nowrap">
        <span className="font-mono text-gray-500">{item.id}</span>
        <span className={cn('font-semibold', DIRECTION_TEXT[item.direction])}>
          {t(item.direction === 'bullish' ? 'tiered.tree.bullish' : 'tiered.tree.bearish')}
        </span>
        {item.weight != null ? (
          // The median badge — the bare number; the modal lists every score.
          <button
            type="button"
            data-testid={`alt-tree-weight-${item.id}`}
            className="cursor-pointer font-mono text-gray-400 hover:text-gray-200"
            onClick={showMedian}
          >
            {item.weight}
          </button>
        ) : null}
        {item.struck ? (
          <MarkButton
            label="✗"
            onClick={() =>
              onShow({
                title: (
                  <AltModalTitle
                    subject={t('tiered.tree.codeCheck')}
                    kind={t('tiered.tree.invalid')}
                  />
                ),
                body: (
                  <ul className={cn(MODAL_BODY, 'list-disc pl-4')}>
                    {(item.problems ?? []).map((problem, index) => (
                      <li key={index}>{problem}</li>
                    ))}
                  </ul>
                ),
              })
            }
          />
        ) : null}
        {authorVotes.map((vote, index) => (
          <MarkButton key={`a${index}`} label="✓" onClick={() => showAuthor(vote)} />
        ))}
        {votes.map((vote, index) => (
          <MarkButton
            key={index}
            label={vote.verdict === 'valid' ? '✓' : '✗'}
            onClick={() => showRichVote(vote, index)}
          />
        ))}
      </span>
      <span className="text-gray-200">
        <LinkedTextV8 text={item.claim} links={item.links ?? []} struck={dead} />
      </span>
    </li>
  );
};

//: The numbered how-it-works list shown at the top of the transcript.
const EXPLAIN_KEYS = [
  'tiered.tree.explain1',
  'tiered.tree.explain2',
  'tiered.tree.explain3',
  'tiered.tree.explain4',
  'tiered.tree.explain5',
  'tiered.tree.explain6',
  'tiered.tree.explain7',
] as const;

// The final-score arithmetic (10 × bullish weight ÷ total weight) —
// shown in the modal behind the score at the top of the deep-analysis
// card (owner decision 2026-07-22), no longer inside the transcript fold.
export const DebateScores = ({ detail }: { detail: TieredDebateDetail }) => {
  const { t } = useUiLanguage();
  const verdict = detail.verdict;
  const finalPool = verdict?.pools?.final ?? null;
  const numerator = finalPool?.bullish_weight ?? null;
  const denominator = finalPool?.total_weight ?? null;
  // Show the plugged-in formula only when it reproduces the stored
  // score (stored format-8 runs used a per-dimension mean).
  const flat =
    numerator != null && denominator != null && denominator > 0
      ? Math.round((10 * numerator * 100) / denominator) / 100
      : null;
  const showFormula =
    flat != null &&
    verdict?.final_score != null &&
    Math.abs(flat - verdict.final_score) < 0.005;
  if (!verdict || !finalPool) {
    return null;
  }
  return (
    <div
      data-testid="alt-tree-scores"
      className="flex flex-col gap-1 overflow-x-auto text-sm"
    >
      <p className={FORMULA_LINE}>
        {t('tiered.tree.finalScore')}: 10 ×{' '}
        <FVar>{t('tiered.tree.bullishWeight')}</FVar>{' '}
        / <FVar>{t('tiered.tree.totalWeight')}</FVar>
      </p>
      {showFormula ? (
        <p className={FORMULA_LINE} data-testid="alt-tree-final-formula">
          = 10 × {numerator} / {denominator}
        </p>
      ) : null}
      <p className={FORMULA_RESULT}>= {verdict.final_score?.toFixed(2)}</p>
    </div>
  );
};

// The v8/v9 evidence vote, one page: per-dimension groups headed by the
// surviving ↑/↓ counts and every bullet's history as marks. No steps, no
// pills — crossed out = not counted. The score arithmetic lives in the
// header score's modal (DebateScores), not here.
const VoteTree = ({ detail }: { detail: TieredDebateDetail }) => {
  const { t } = useUiLanguage();
  const [modal, setModal] = useState<MarkModal | null>(null);
  const items = detail.items ?? [];
  const groups = DIMENSION_ORDER.map((dimension) => ({
    dimension,
    items: items.filter((item) => item.dimension === dimension),
  })).filter((group) => group.items.length > 0);

  return (
    <>
      <AltFold title={t('tiered.tree.transcript')}>
        <div data-testid="alt-debate-tree" className="flex flex-col gap-3">
          <div data-testid="alt-tree-explain">
            <AltSectionLabel>{t('tiered.tree.howItWorks')}</AltSectionLabel>
            <ol className="flex list-decimal flex-col gap-1 pl-4 text-xs text-gray-400">
              {EXPLAIN_KEYS.map((key) => (
                <li key={key}>{t(key)}</li>
              ))}
              <li>{t('tiered.tree.explainWeights5')}</li>
            </ol>
          </div>

          {groups.map((group) => {
            const counted = group.items.filter((item) => item.final_status === 'counted');
            const up = counted.filter((item) => item.direction === 'bullish').length;
            const down = counted.length - up;
            return (
              <div key={group.dimension}>
                <AltSectionLabel>
                  {DIMENSION_LABEL_KEYS[group.dimension]
                    ? t(DIMENSION_LABEL_KEYS[group.dimension])
                    : group.dimension}
                  {': '}
                  {/* Only the counts wear color — the words stay plain. */}
                  <span className="text-emerald-300">{up}</span>
                  {` ${t('tiered.tree.bullish')}, `}
                  <span className="text-red-300">{down}</span>
                  {` ${t('tiered.tree.bearish')}`}
                </AltSectionLabel>
                <ul className="flex flex-col gap-1.5">
                  {group.items.map((item) => (
                    <VoteItem key={item.id} item={item} onShow={setModal} />
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </AltFold>

      <AltModal
        isOpen={modal !== null}
        title={modal?.title ?? ''}
        onClose={() => setModal(null)}
      >
        {modal?.body}
      </AltModal>
    </>
  );
};

interface AltDebateTreeProps {
  detail: TieredDebateDetail;
}

export const AltDebateTree = ({ detail }: AltDebateTreeProps) => <VoteTree detail={detail} />;
