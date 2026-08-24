import type { ReactNode } from 'react';
import { Tooltip } from '../common/Tooltip';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { metricEntry } from '../../i18n/metricLabels';
import type { UiTextKey } from '../../i18n/uiText';
import type { TieredCitation } from '../../api/tiered';
import { cn } from '../../utils/cn';
import { jumpToMetric } from './termHelpers';

interface HelpTermProps {
  label: ReactNode;
  helpKey: UiTextKey;
  underline?: boolean;
}

// A term with its explanation in a popup. Hover shows it; click/tap keeps
// it open (focus), so it also works on touch screens; clicking elsewhere
// or Escape closes it.
export const HelpTerm = ({ label, helpKey, underline = true }: HelpTermProps) => {
  const { t } = useUiLanguage();

  return (
    <Tooltip
      focusable
      // pre-line: help texts put each sentence on its own line via \n
      content={<span className="block max-w-[16rem] whitespace-pre-line">{t(helpKey)}</span>}
    >
      <span
        className={cn(
          'cursor-help',
          underline ? 'border-b border-dotted border-secondary-text/60' : '',
        )}
      >
        {label}
      </span>
    </Tooltip>
  );
};

interface MetricTermProps {
  term: string;
  underline?: boolean;
  /** Keep the label on one line, ellipsizing when space runs out (the
      tooltip's bold header always carries the full name). Truncation
      must sit on the text INSIDE the tooltip's inline-flex wrapper —
      an ellipsis on a block clipping an atomic inline box renders
      inconsistently across browsers. */
  truncate?: boolean;
}

// Compact vocab (e.g. "SMA 20") with the full plain-language definition in
// a popup: hover shows it, click/tap keeps it open (focus), clicking
// elsewhere or Escape closes it. Unknown keys render as-is, no popup.
export const MetricTerm = ({ term, underline = true, truncate = false }: MetricTermProps) => {
  const { language } = useUiLanguage();
  const entry = metricEntry(term, language);

  if (!entry) {
    return <>{term}</>;
  }
  // Entries with an `interp` render the owner's two-block popup format
  // (2026-07-29): "Meaning: …" then a divider then "Interpretation: …".
  const meaningLabel = language === 'en' ? 'Meaning:' : '含义：';
  const interpLabel = language === 'en' ? 'Interpretation:' : '解读：';
  return (
    <Tooltip
      focusable
      className={truncate ? 'max-w-full' : undefined}
      content={
        <span className="block max-w-[16rem] whitespace-pre-line">
          <span className="block font-semibold text-foreground">{entry.short}</span>
          {entry.interp ? (
            <>
              <span className="mt-0.5 block text-secondary-text">
                <span className="font-medium text-foreground/80">{meaningLabel}</span>{' '}
                {entry.full}
              </span>
              <span className="my-1 block border-t border-secondary-text/30" aria-hidden />
              <span className="block text-secondary-text">
                <span className="font-medium text-foreground/80">{interpLabel}</span>{' '}
                {entry.interp}
              </span>
            </>
          ) : (
            <span className="mt-0.5 block text-secondary-text">{entry.full}</span>
          )}
        </span>
      }
    >
      <span
        className={cn(
          'cursor-help',
          underline ? 'border-b border-dotted border-secondary-text/60' : '',
          truncate ? 'min-w-0 truncate' : '',
        )}
      >
        {entry.short}
      </span>
    </Tooltip>
  );
};

const CITATION_MARKER_SPLIT_RE = /(\[\d+\])/g;
const CITATION_MARKER_RE = /^\[(\d+)\]$/;

interface NarrativeWithCitationsProps {
  text: string;
  citations: TieredCitation[];
}

// Renders inline [n] markers as links to the numbered source, so a claim
// can be checked in one click. Markers without a matching source (old
// stored runs, missing URL) stay plain text.
export const NarrativeWithCitations = ({ text, citations }: NarrativeWithCitationsProps) => (
  <p className="mb-3 text-sm leading-relaxed text-secondary-text">
    {text.split(CITATION_MARKER_SPLIT_RE).map((part, index) => {
      const match = CITATION_MARKER_RE.exec(part);
      const citation = match ? citations[Number(match[1]) - 1] : undefined;
      if (citation?.url) {
        return (
          <a
            key={index}
            href={citation.url}
            target="_blank"
            rel="noreferrer"
            aria-label={citation.title ?? citation.url}
            className="text-cyan hover:underline"
          >
            {part}
          </a>
        );
      }
      return <span key={index}>{part}</span>;
    })}
  </p>
);

const CITATION_REF_RE = /^citation:(\d+)$/;

interface EvidenceRefProps {
  refPath: string;
  citations: TieredCitation[];
  onNavigate?: () => void;
}

// One evidence reference as a link: "citation:N" opens the numbered news
// source; a payload path scrolls to that metric's row on its dimension
// card (closing any open modal first via onNavigate). Unresolvable refs
// render as plain text — never a dead link.
export const EvidenceRef = ({ refPath, citations, onNavigate }: EvidenceRefProps) => {
  const citationMatch = CITATION_REF_RE.exec(refPath);
  if (citationMatch) {
    const citation = citations[Number(citationMatch[1]) - 1];
    if (citation?.url) {
      return (
        <a
          href={citation.url}
          target="_blank"
          rel="noreferrer"
          aria-label={citation.title ?? citation.url}
          className="text-cyan hover:underline"
        >
          {refPath}
        </a>
      );
    }
    return <span>{refPath}</span>;
  }

  return (
    <button
      type="button"
      className="text-cyan hover:underline"
      onClick={() => {
        onNavigate?.();
        // Let the modal unmount before scrolling to the row behind it.
        window.setTimeout(() => jumpToMetric(refPath), 50);
      }}
    >
      {refPath}
    </button>
  );
};

interface EvidenceRefListProps {
  refs: string[];
  citations: TieredCitation[];
  onNavigate?: () => void;
}

export const EvidenceRefList = ({ refs, citations, onNavigate }: EvidenceRefListProps) => (
  <span className="inline-flex flex-wrap gap-x-2 font-mono text-[11px]">
    {refs.map((refPath, index) => (
      <EvidenceRef key={index} refPath={refPath} citations={citations} onNavigate={onNavigate} />
    ))}
  </span>
);
