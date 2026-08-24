import { useState, type ReactNode } from 'react';
import type {
  TieredDebateAuthorVote,
  TieredDebateCheck,
  TieredDebateDetail,
  TieredDebateItem,
  TieredDebateJudgeAxis,
  TieredDebateLink,
  TieredDebateResponse,
  TieredDebateVote,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, jumpToMetric } from '../tiered/termHelpers';
import { stripInlineRefs } from './altFormat';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT, TAG_BASE } from './altStyles';
import {
  AltFold,
  AltModal,
  AltModalDivider,
  AltModalTitle,
  AltSectionLabel,
  FVar,
  MODAL_BODY,
} from './AltUi';

// The v5/v6/v7 debate tree: one tree, four steps. Step 1 shows the
// defender's evidence list; step 2 adds the attacker's checks and
// additions; step 3 adds the defender's responses; step 4 (the default)
// adds the judge's rulings and the scores block. v7 runs underline the
// cited display values themselves (code fixed or struck every citation
// before the debate, so the tree carries a single logic axis); v6 runs
// keep their word-underlines, value-check lines and two-axis threads;
// stored v5 runs keep their citation chips and the weight formula.
// Color rules: defender text in the normal ink, attacker material tinted
// sky, judge rulings tinted violet, with green valid / red invalid
// verdicts throughout.

const STEPS = [
  { n: 1, labelKey: 'tiered.tree.step.argument' },
  { n: 2, labelKey: 'tiered.tree.step.attack' },
  { n: 3, labelKey: 'tiered.tree.step.response' },
  { n: 4, labelKey: 'tiered.tree.step.judge' },
] as const;

// "company_events" and "world_events" joined the debate 2026-08-16
// (news events as graded rows); "opinion" (numeric analyst + crowd
// sentiment measures) joined 2026-08-18 and sits between macro and the
// news cards since 2026-08-19 (owner display order); "sentiment" stays
// for old stored runs that still carry the retired news-sentiment
// dimension.
const DIMENSION_ORDER = [
  'technicals',
  'fundamentals',
  'positioning',
  'macro_econ',
  'opinion',
  'company_events',
  'world_events',
  'sentiment',
];

const DIMENSION_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  positioning: 'tiered.dimension.positioning',
  company_events: 'tiered.dimension.company_events',
  world_events: 'tiered.dimension.world_events',
  opinion: 'tiered.dimension.opinion',
  sentiment: 'tiered.dimension.sentiment',
};

const AXES = ['citation', 'logic'] as const;
type Axis = (typeof AXES)[number];

const AXIS_LABEL_KEYS: Record<Axis, UiTextKey> = {
  citation: 'tiered.tree.citationCheck',
  logic: 'tiered.tree.logicCheck',
};

const ROLE_TINT = {
  attacker: 'text-sky-300',
  judge: 'text-violet-300',
  defender: 'text-gray-300',
  code: 'text-amber-300',
} as const;

const DIRECTION_TEXT: Record<string, string> = {
  bullish: 'text-emerald-300',
  bearish: 'text-red-300',
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

// v6 claims: the cited words themselves are underlined, tinted links —
// payload refs flash their metric row, sentiment refs jump to the
// sources list. Mismatched links (auto-failed by code) render red.
const LinkedClaim = ({ claim, links }: { claim: string; links: TieredDebateLink[] }) => {
  const markers = links
    .map((link) => {
      const text = link.text ?? '';
      const start = text ? claim.indexOf(text) : -1;
      return start >= 0 ? { start, end: start + text.length, link } : null;
    })
    .filter((m): m is { start: number; end: number; link: TieredDebateLink } => m !== null)
    .sort((a, b) => a.start - b.start);
  const segments: ReactNode[] = [];
  let cursor = 0;
  markers.forEach((marker, index) => {
    if (marker.start < cursor) {
      return; // overlapping link texts — keep the first
    }
    if (marker.start > cursor) {
      segments.push(<span key={`t${index}`}>{claim.slice(cursor, marker.start)}</span>);
    }
    segments.push(
      <button
        key={`l${index}`}
        type="button"
        className={cn(
          'cursor-pointer underline decoration-1 underline-offset-2',
          marker.link.mismatch
            ? 'text-red-300 decoration-red-400/60 hover:text-red-200'
            : 'text-blue-300 decoration-blue-400/60 hover:text-blue-200',
        )}
        onClick={() => jumpToRef(marker.link.ref)}
      >
        {claim.slice(marker.start, marker.end)}
      </button>,
    );
    cursor = marker.end;
  });
  if (cursor < claim.length) {
    segments.push(<span key="tail">{claim.slice(cursor)}</span>);
  }
  return <span className="text-gray-200">{segments}</span>;
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

// v5 claims keep their trailing citation chips.
const ChipRefs = ({ refs }: { refs: string[] }) => {
  if (refs.length === 0) {
    return null;
  }
  return (
    <span className="inline-flex flex-wrap gap-x-2 text-[11px]">
      {refs.map((refPath, index) => {
        const citationMatch = CITATION_REF_RE.exec(refPath);
        return (
          <button
            key={index}
            type="button"
            className={cn('cursor-pointer', ALT_LINK)}
            onClick={() => jumpToRef(refPath)}
          >
            {citationMatch ? `sentiment.${refPath}` : refPath}
          </button>
        );
      })}
    </span>
  );
};

const VerdictWord = ({ ok, label }: { ok: boolean; label: string }) => (
  <span className={ok ? 'text-emerald-300' : 'text-red-300'}>{label}</span>
);

// One "role · check · verdict — reason [refs]" line.
const CheckLine = ({
  role,
  label,
  ok,
  verdictLabel,
  reason,
  citations,
}: {
  role: keyof typeof ROLE_TINT;
  label: string;
  ok: boolean;
  verdictLabel: string;
  reason?: string | null;
  citations?: string[];
}) => {
  const { t } = useUiLanguage();
  return (
    <p className="text-xs text-gray-400">
      <span className={cn('font-semibold', ROLE_TINT[role])}>
        {t(`tiered.tree.${role}` as UiTextKey)}
      </span>
      {' · '}
      {label}
      {' · '}
      <VerdictWord ok={ok} label={verdictLabel} />
      {reason ? <span className="text-gray-500"> — {reason}</span> : null}
      {citations && citations.length > 0 ? (
        <>
          {' '}
          <ChipRefs refs={citations} />
        </>
      ) : null}
    </p>
  );
};

// The defender's response to one challenge: its two checks on the
// challenge itself, one line each — the valid/invalid words tell the
// accept/reject story on their own.
const ResponseChecks = ({ response }: { response: TieredDebateResponse }) => {
  const { t } = useUiLanguage();
  return (
    <div className="flex flex-col gap-0.5">
      {AXES.map((axis) => {
        const check = response[`${axis}_check`];
        if (!check) {
          return null; // v7 responses carry a single check instead
        }
        const ok = check.verdict === 'valid';
        return (
          <CheckLine
            key={axis}
            role="defender"
            label={t(AXIS_LABEL_KEYS[axis])}
            ok={ok}
            verdictLabel={t(ok ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
            reason={ok ? null : check.reason}
            citations={ok ? [] : check.citations}
          />
        );
      })}
    </div>
  );
};

const JudgeAxisLine = ({ axis, ruling }: { axis: Axis; ruling: TieredDebateJudgeAxis }) => {
  const { t } = useUiLanguage();
  if (ruling.kind === 'attack_ruling') {
    const ok = ruling.verdict === 'attack_wrong'; // wrong attack → item survives
    return (
      <CheckLine
        role="judge"
        label={t(AXIS_LABEL_KEYS[axis])}
        ok={ok}
        verdictLabel={t(ok ? 'tiered.tree.attackWrong' : 'tiered.tree.attackRight')}
        reason={ruling.reason}
        citations={ruling.citations}
      />
    );
  }
  const ok = ruling.verdict === 'valid';
  return (
    <CheckLine
      role="judge"
      label={t(AXIS_LABEL_KEYS[axis])}
      ok={ok}
      verdictLabel={t(ok ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
      reason={ruling.reason}
      citations={ruling.citations}
    />
  );
};

// The code's own mechanical verdict on an item's numbers (v6).
const ValueCheckLine = ({ item }: { item: TieredDebateItem }) => {
  const { t } = useUiLanguage();
  if (!item.value_check || item.value_check.verdict !== 'invalid') {
    return null;
  }
  return (
    <CheckLine
      role="code"
      label={t('tiered.tree.citationCheck')}
      ok={false}
      verdictLabel={t('tiered.tree.invalid')}
      reason={(item.value_check.problems ?? []).join('; ')}
    />
  );
};

// Everything under one defender item: per-axis attacker check → defender
// response → judge word, indentation mirroring the debate's structure.
const DefenderItemThread = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  const judge = item.judge && !('kind' in item.judge) ? item.judge : null;
  return (
    <div className="flex flex-col gap-1 border-l border-gray-700/60 pl-3">
      {step >= 2 ? <ValueCheckLine item={item} /> : null}
      {AXES.map((axis) => {
        const check = item.attacker_checks?.[axis];
        if (!check) {
          return null;
        }
        const attacked = check.verdict === 'invalid';
        const response = item.responses?.[axis] ?? null;
        return (
          <div key={axis} className="flex flex-col gap-0.5">
            {step >= 2 ? (
              <CheckLine
                role="attacker"
                label={t(AXIS_LABEL_KEYS[axis])}
                ok={!attacked}
                verdictLabel={t(attacked ? 'tiered.tree.invalid' : 'tiered.tree.valid')}
                reason={attacked ? check.reason : null}
                citations={attacked ? check.citations : []}
              />
            ) : null}
            {step >= 3 && response ? (
              <div className="pl-3">
                <ResponseChecks response={response} />
              </div>
            ) : null}
            {step >= 4 && judge ? (
              <div className={attacked ? 'pl-6' : 'pl-3'}>
                <JudgeAxisLine axis={axis} ruling={judge[axis]} />
              </div>
            ) : null}
          </div>
        );
      })}
      {/* Attacker review degraded (no checks): the judge still ruled. */}
      {!item.attacker_checks && step >= 4 && judge ? (
        <div className="flex flex-col gap-0.5">
          {AXES.map((axis) => (
            <JudgeAxisLine key={axis} axis={axis} ruling={judge[axis]} />
          ))}
        </div>
      ) : null}
    </div>
  );
};

const AdditionThread = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  const judge = item.judge ?? null;
  return (
    <div className="flex flex-col gap-1 border-l border-gray-700/60 pl-3">
      <p className="text-xs text-gray-400">
        <span className={cn('font-semibold', ROLE_TINT.attacker)}>
          {t('tiered.tree.attacker')}
        </span>
        {' · '}
        {t('tiered.tree.newlyAdded')}
      </p>
      {step >= 2 ? <ValueCheckLine item={item} /> : null}
      {step >= 3 && item.response ? (
        <div className="pl-3">
          <ResponseChecks response={item.response} />
        </div>
      ) : null}
      {step >= 4 && judge && !('kind' in judge) ? (
        // v6: the judge's own two checks, same shape as everywhere else.
        <div className="pl-6">
          {AXES.map((axis) => (
            <JudgeAxisLine key={axis} axis={axis} ruling={judge[axis]} />
          ))}
        </div>
      ) : null}
      {step >= 4 && judge && 'kind' in judge && judge.kind === 'addition_ruling' ? (
        // Stored v5 runs keep their real/bogus ruling.
        <div className="pl-6">
          <CheckLine
            role="judge"
            label={t('tiered.tree.addition')}
            ok={judge.verdict === 'real'}
            verdictLabel={t(judge.verdict === 'real' ? 'tiered.tree.real' : 'tiered.tree.bogus')}
            reason={judge.reason}
            citations={judge.citations}
          />
        </div>
      ) : null}
    </div>
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
  rich = false,
  onShow,
}: {
  item: TieredDebateItem;
  rich?: boolean;
  onShow: (modal: MarkModal) => void;
}) => {
  const { t } = useUiLanguage();
  const dead = item.final_status === 'excluded';
  const votes = item.votes ?? [];
  const authorVotes = item.author_votes ?? [];
  const showVote = (vote: TieredDebateVote, index: number) =>
    onShow({
      title: (
        <AltModalTitle
          subject={t(index === 0 ? 'tiered.tree.firstCheck' : 'tiered.tree.secondCheck')}
          kind={t(vote.verdict === 'valid' ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
        />
      ),
      body: (
        <div className={MODAL_BODY}>
          <p>
            {vote.reason ? (
              <LinkedTextV8 text={vote.reason} links={vote.links ?? []} />
            ) : (
              '—'
            )}
          </p>
          {vote.weight != null ? (
            // v10: the voter's own 1-3 importance rating of the bullet.
            <p>{t('tiered.tree.voteWeight', { value: vote.weight })}</p>
          ) : null}
        </div>
      ),
    });
  const showWeight = () =>
    onShow({
      title: t('tiered.tree.weightTitle'),
      body: (
        <div className={MODAL_BODY}>
          <p>{t('tiered.tree.weightExplain')}</p>
          <p>
            {t('tiered.tree.authorWeights', {
              value: (item.author_weights ?? []).join(', ') || '—',
            })}
          </p>
        </div>
      ),
    });
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
        {rich && item.weight != null ? (
          // v11 median badge — the bare number; the modal lists every score.
          <button
            type="button"
            data-testid={`alt-tree-weight-${item.id}`}
            className="cursor-pointer font-mono text-gray-400 hover:text-gray-200"
            onClick={showMedian}
          >
            {item.weight}
          </button>
        ) : null}
        {!rich && item.weight != null ? (
          // v10 weight badge — the median of every voter's 1-3 rating.
          <button
            type="button"
            data-testid={`alt-tree-weight-${item.id}`}
            className="cursor-pointer font-mono text-gray-500 hover:text-gray-300"
            onClick={showWeight}
          >
            {t('tiered.tree.weightBadge', { value: item.weight })}
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
        {rich
          ? authorVotes.map((vote, index) => (
              <MarkButton key={`a${index}`} label="✓" onClick={() => showAuthor(vote)} />
            ))
          : null}
        {votes.map((vote, index) => (
          <MarkButton
            key={index}
            label={vote.verdict === 'valid' ? '✓' : '✗'}
            onClick={() => (rich ? showRichVote(vote, index) : showVote(vote, index))}
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
  const weighted = detail.format != null && detail.format >= 10;
  const numerator = weighted ? (finalPool?.bullish_weight ?? null) : (finalPool?.bullish ?? null);
  const denominator = weighted ? (finalPool?.total_weight ?? null) : (finalPool?.total ?? null);
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
        <FVar>{t(weighted ? 'tiered.tree.bullishWeight' : 'tiered.tree.bullish')}</FVar>{' '}
        / <FVar>{t(weighted ? 'tiered.tree.totalWeight' : 'tiered.tree.total')}</FVar>
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
  // v10+ weights the score by the voters' significance ratings; v8/v9
  // counted every bullet the same. v11 (rich) also stores each voter's
  // score reason and the listers' own checks.
  const weighted = detail.format != null && detail.format >= 10;
  const rich = detail.format != null && detail.format >= 11;

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
              {weighted ? (
                <li>{t(rich ? 'tiered.tree.explainWeights5' : 'tiered.tree.explainWeights')}</li>
              ) : null}
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
                    <VoteItem key={item.id} item={item} rich={rich} onShow={setModal} />
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

// One "role · logic check · verdict" line (v7 has a single axis).
const SingleCheckLine = ({
  role,
  check,
}: {
  role: keyof typeof ROLE_TINT;
  check: TieredDebateCheck;
}) => {
  const { t } = useUiLanguage();
  const ok = check.verdict === 'valid';
  return (
    <CheckLine
      role={role}
      label={t('tiered.tree.logicCheck')}
      ok={ok}
      verdictLabel={t(ok ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
      reason={ok ? null : check.reason}
      citations={ok ? [] : check.citations}
    />
  );
};

// Everything under one v7 item: the attacker's single check (or the
// "newly added" opener), the defender's single response check, and the
// judge's one line — citation checking already happened in code, so the
// whole thread is the logic axis.
const ThreadV7 = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  const judge = item.judge && 'kind' in item.judge ? (item.judge as TieredDebateJudgeAxis) : null;
  const check = item.attacker_check ?? null;
  const responseCheck = item.response?.check ?? null;
  const showResponse = step >= 3 && responseCheck != null;
  return (
    <div className="flex flex-col gap-1 border-l border-gray-700/60 pl-3">
      {item.added_by_attacker ? (
        <p className="text-xs text-gray-400">
          <span className={cn('font-semibold', ROLE_TINT.attacker)}>
            {t('tiered.tree.attacker')}
          </span>
          {' · '}
          {t('tiered.tree.newlyAdded')}
        </p>
      ) : null}
      {!item.added_by_attacker && step >= 2 && check ? (
        <SingleCheckLine role="attacker" check={check} />
      ) : null}
      {showResponse && responseCheck ? (
        <div className="pl-3">
          <SingleCheckLine role="defender" check={responseCheck} />
        </div>
      ) : null}
      {step >= 4 && judge ? (
        <div className={showResponse ? 'pl-6' : 'pl-3'}>
          {judge.kind === 'attack_ruling' ? (
            <CheckLine
              role="judge"
              label={t('tiered.tree.logicCheck')}
              ok={judge.verdict === 'attack_wrong'}
              verdictLabel={t(
                judge.verdict === 'attack_wrong'
                  ? 'tiered.tree.attackWrong'
                  : 'tiered.tree.attackRight',
              )}
              reason={judge.reason}
              citations={judge.citations}
            />
          ) : (
            <CheckLine
              role="judge"
              label={t('tiered.tree.logicCheck')}
              ok={judge.verdict === 'valid'}
              verdictLabel={t(
                judge.verdict === 'valid' ? 'tiered.tree.valid' : 'tiered.tree.invalid',
              )}
              reason={judge.reason}
              citations={judge.citations}
            />
          )}
        </div>
      ) : null}
    </div>
  );
};

const TreeItem = ({
  item,
  step,
  v7 = false,
}: {
  item: TieredDebateItem;
  step: number;
  v7?: boolean;
}) => {
  const { t } = useUiLanguage();
  const counted =
    item.final_status != null ? item.final_status === 'counted' : null;
  return (
    <li data-testid={`alt-tree-item-${item.id}`} className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-gray-500">{item.id}</span>
        <span className={cn('font-semibold', DIRECTION_TEXT[item.direction])}>
          {t(item.direction === 'bullish' ? 'tiered.tree.bullish' : 'tiered.tree.bearish')}
        </span>
        {v7 && item.links ? (
          <LinkedClaimV7 claim={item.claim} links={item.links} struck={!!item.struck} />
        ) : item.links ? (
          <LinkedClaim claim={item.claim} links={item.links} />
        ) : (
          <span className="text-gray-200">{item.claim}</span>
        )}
        {!item.links && item.citations ? <ChipRefs refs={item.citations} /> : null}
        {step >= 4 && counted != null && !(v7 && item.struck) ? (
          <span
            className={cn(
              TAG_BASE,
              counted
                ? 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30'
                : 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
            )}
          >
            {t(counted ? 'tiered.tree.countedWord' : 'tiered.tree.excludedWord')}
          </span>
        ) : null}
        {step >= 4 && item.count ? (
          // Stored v5 runs keep their ledger badge.
          <span
            className={cn(
              TAG_BASE,
              item.outcome === 'valid'
                ? 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30'
                : item.outcome === 'invalid'
                  ? 'bg-red-500/20 text-red-300 ring-red-500/30'
                  : 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
            )}
          >
            {t('tiered.tree.counted', {
              num: item.count.numerator,
              den: item.count.denominator,
            })}
          </span>
        ) : null}
      </div>
      {v7 ? (
        step >= 2 && !item.struck ? (
          <ThreadV7 item={item} step={step} />
        ) : null
      ) : item.added_by_attacker ? (
        step >= 2 ? (
          <AdditionThread item={item} step={step} />
        ) : null
      ) : step >= 2 ? (
        <DefenderItemThread item={item} step={step} />
      ) : null}
    </li>
  );
};

// One dimension row of the final-pool breakdown (v6 scores block).
const PoolDimensionLine = ({
  dimension,
  stats,
}: {
  dimension: string;
  stats: { bullish: number; bearish: number; score?: number | null };
}) => {
  const { t } = useUiLanguage();
  return (
    <p className={FORMULA_LINE}>
      {DIMENSION_LABEL_KEYS[dimension] ? t(DIMENSION_LABEL_KEYS[dimension]) : dimension}
      {' · '}
      {stats.bullish} {t('tiered.tree.bullish')} / {stats.bearish} {t('tiered.tree.bearish')}
      {' → '}
      <span className="tabular-nums">{stats.score?.toFixed(2) ?? '—'}</span>
    </p>
  );
};

interface AltDebateTreeProps {
  detail: TieredDebateDetail;
}

export const AltDebateTree = ({ detail }: AltDebateTreeProps) => {
  if (detail.format != null && detail.format >= 8 && detail.format <= 11) {
    return <VoteTree detail={detail} />;
  }
  return <RoleDebateTree detail={detail} />;
};

// The v5/v6/v7 defender/attacker/judge renderer for stored runs.
const RoleDebateTree = ({ detail }: AltDebateTreeProps) => {
  const { t } = useUiLanguage();
  const v7 = detail.format === 7;
  const [step, setStep] = useState(4);
  const items = detail.items ?? [];
  const verdict = detail.verdict;
  const pools = verdict?.pools ?? null;
  const weight = verdict?.weight ?? null;
  const adjusted = verdict?.adjusted_score ?? null;
  // The pool scores average the per-dimension scores — the label says so
  // instead of printing overall counts the formula does not use.
  const initialDims = Object.keys(pools?.initial?.dimensions ?? {}).length;
  const adjustedDims = Object.keys(pools?.adjusted?.dimensions ?? {}).length;

  const visibleItems = step >= 2 ? items : items.filter((item) => !item.added_by_attacker);
  const groups = DIMENSION_ORDER.map((dimension) => ({
    dimension,
    items: visibleItems.filter((item) => item.dimension === dimension),
  })).filter((group) => group.items.length > 0);

  const finalDimensions = pools?.final?.dimensions ?? {};
  const finalScores = DIMENSION_ORDER.filter((d) => finalDimensions[d]).map(
    (d) => finalDimensions[d],
  );

  return (
    <div data-testid="alt-debate-tree" className="mt-4 flex flex-col gap-3">
      {/* The step selector; the complete tree is the default view. */}
      <div className="flex flex-wrap gap-1 text-xs">
        {STEPS.map(({ n, labelKey }) => (
          <button
            key={n}
            type="button"
            data-testid={`alt-tree-step-${n}`}
            onClick={() => setStep(n)}
            className={cn(
              'cursor-pointer rounded px-2 py-1',
              step === n
                ? 'bg-gray-700 font-semibold text-gray-200'
                : 'text-gray-500 hover:text-gray-300',
            )}
          >
            {n} · {t(labelKey)}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {groups.map((group) => (
          <div key={group.dimension}>
            <AltSectionLabel>
              {DIMENSION_LABEL_KEYS[group.dimension]
                ? t(DIMENSION_LABEL_KEYS[group.dimension])
                : group.dimension}
            </AltSectionLabel>
            <ul className="flex flex-col gap-2">
              {group.items.map((item) => (
                <TreeItem key={item.id} item={item} step={step} v7={v7} />
              ))}
            </ul>
          </div>
        ))}
      </div>

      {verdict && pools ? (
        // v6: the deterministic pool scores.
        <div
          data-testid="alt-tree-scores"
          className="flex flex-col gap-1 border-t border-gray-700/60 pt-3"
        >
          <AltSectionLabel>{t('tiered.tree.scores')}</AltSectionLabel>
          <p className="text-xs text-gray-400">
            {t('tiered.tree.initialScore')}
            {' · '}
            <span className="tabular-nums text-gray-300">
              {verdict.initial_score?.toFixed(2)}
            </span>
            <span className="text-gray-600">
              {' · '}
              {t('tiered.tree.dimensionAverage', { n: initialDims })}
            </span>
          </p>
          {step >= 3 && pools.adjusted ? (
            <p className="text-xs text-gray-400">
              {t('tiered.tree.adjustedScore')}
              {' · '}
              <span className="tabular-nums text-gray-300">{adjusted?.toFixed(2)}</span>
              <span className="text-gray-600">
                {' · '}
                {t('tiered.tree.dimensionAverage', { n: adjustedDims })}
              </span>
            </p>
          ) : null}
          {step >= 4 ? (
            <>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>
                  {t('tiered.tree.finalScore')} · 10 × <FVar>{t('tiered.tree.bullish')}</FVar>{' '}
                  / <FVar>{t('tiered.tree.total')}</FVar>
                </p>
                {DIMENSION_ORDER.filter((d) => finalDimensions[d]).map((dimension) => (
                  <PoolDimensionLine
                    key={dimension}
                    dimension={dimension}
                    stats={finalDimensions[dimension]}
                  />
                ))}
                {finalScores.length > 0 ? (
                  <p className={FORMULA_LINE} data-testid="alt-tree-final-formula">
                    = ({finalScores.map((s) => s.score?.toFixed(2)).join(' + ')}) /{' '}
                    {finalScores.length}
                  </p>
                ) : null}
                <p className={FORMULA_RESULT}>= {verdict.final_score?.toFixed(2)}</p>
              </div>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>{t('tiered.tree.ranges')}</p>
                <p className={FORMULA_RESULT} data-testid="alt-tree-verdict">
                  = {t(`tiered.direction.${verdict.direction}` as UiTextKey)}
                </p>
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {verdict && !pools ? (
        // Stored v5 runs: the weight-formula scores block.
        <div
          data-testid="alt-tree-scores"
          className="flex flex-col gap-1 border-t border-gray-700/60 pt-3"
        >
          <AltSectionLabel>{t('tiered.tree.scores')}</AltSectionLabel>
          <p className="text-xs text-gray-400">
            {t('tiered.tree.initialScore')}
            {' · '}
            <span className="tabular-nums text-gray-300">{verdict.initial_score}/10</span>
          </p>
          {step >= 3 && adjusted != null ? (
            <p className="text-xs text-gray-400">
              {t('tiered.tree.adjustedScore')}
              {' · '}
              <span className="tabular-nums text-gray-300">{adjusted}/10</span>
              {verdict.adjusted_kept ? ` ${t('tiered.tree.kept')}` : ''}
            </p>
          ) : null}
          {step >= 4 && weight ? (
            <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
              <p className={FORMULA_LINE}>{t('tiered.tree.weightWords')}</p>
              <p className={FORMULA_LINE}>
                = {weight.numerator}/{weight.denominator}
              </p>
              <p className={FORMULA_RESULT}>
                = {weight.value} ({t('tiered.debate.weight')})
              </p>
            </div>
          ) : null}
          {step >= 4 && weight && adjusted != null && verdict.final_score != null ? (
            <>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>
                  5 + <FVar>{t('tiered.debate.weight')}</FVar> × (
                  <FVar>{t('tiered.tree.adjustedScore')}</FVar> − 5)
                </p>
                <p className={FORMULA_LINE} data-testid="alt-tree-final-formula">
                  = 5 + {weight.value} × ({adjusted} − 5)
                </p>
                <p className={FORMULA_RESULT}>= {verdict.final_score.toFixed(2)}</p>
              </div>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>{t('tiered.tree.ranges')}</p>
                <p className={FORMULA_RESULT} data-testid="alt-tree-verdict">
                  = {t(`tiered.direction.${verdict.direction}` as UiTextKey)}
                </p>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
