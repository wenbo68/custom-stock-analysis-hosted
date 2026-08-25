import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert } from 'lucide-react';
import type { TieredCitation } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
import { jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK } from './altStyles';
import { friendlyWarning } from './altWarningText';

interface AltCardProps {
  children: ReactNode;
  className?: string;
  testId?: string;
}

// The only surface on the alt page: flat gray-800, small radius, no border,
// no shadow — separation comes from the gray-900 canvas and whitespace.
export const AltCard = ({ children, className, testId }: AltCardProps) => (
  <section data-testid={testId} className={cn('rounded bg-gray-800 p-5', className)}>
    {children}
  </section>
);

interface AltModalProps {
  isOpen: boolean;
  /** Omit for a title-less popup (the data-notes modal). */
  title?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Overrides the panel's width classes (e.g. fit-to-content for formulas). */
  panelClassName?: string;
}

// A formula variable: italic, so words read as placeholders and numbers
// (plain or linked) read as values — no underscores, no parentheses.
export const FVar = ({ children }: { children: ReactNode }) => <i>{children}</i>;

// One typography contract for EVERY popup body on the alt page (owner
// decision 2026-07-21): same font size, spacing, colors and divider in
// every modal — body text gray-300, emphasized lines gray-200 semibold.
export const MODAL_BODY = 'flex flex-col gap-2 text-sm leading-relaxed text-gray-300';
export const MODAL_STRONG = 'font-semibold text-gray-200';
export const AltModalDivider = () => <hr className="border-gray-700/60" />;

export const AltSectionLabel = ({ children }: { children: ReactNode }) => (
  <div className="mb-1 text-xs font-semibold text-gray-500">{children}</div>
);

// Every popup title on the alt page names two things: WHAT the popup is
// about (a metric, a plan level, a check) and WHICH KIND of popup it is
// (formula / adjustment / warnings / why blank / a verdict). They used to
// run together as one "subject: kind" sentence, which read as a single
// long label. Owner request 2026-08-08: split them, and always onto TWO
// LINES — subject first, kind under it — so the shape of the header is
// identical in every popup no matter how long either part is. The subject
// keeps the panel's largest, brightest type; the kind sits below as a
// small tracked uppercase tag in the muted body gray. Hierarchy by scale
// and weight, no new accent color competing with the amber note mark.
export const AltModalTitle = ({ subject, kind }: { subject: ReactNode; kind: ReactNode }) => (
  <span className="flex flex-col gap-0.5">
    <span className="text-base font-semibold leading-tight text-gray-100">{subject}</span>
    <span className="text-[11px] font-semibold uppercase leading-tight tracking-[0.14em] text-gray-500">
      {kind}
    </span>
  </span>
);

// A quiet inline fold (debate transcript, scoring breakdown).
export const AltFold = ({ title, children }: { title: string; children: ReactNode }) => (
  <details className="mt-4 rounded bg-gray-900/60 px-4 py-3">
    <summary className="cursor-pointer text-xs font-semibold text-gray-300">{title}</summary>
    <div className="mt-3 flex flex-col gap-3">{children}</div>
  </details>
);

// showplayer-style popup: black/50 backdrop, flat gray-800 panel.
export const AltModal = ({ isOpen, title, onClose, children, panelClassName }: AltModalProps) => {
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'max-h-[80vh] w-full max-w-lg overflow-y-auto rounded bg-gray-800 p-5 text-sm text-gray-400',
          panelClassName,
        )}
        onClick={(event) => event.stopPropagation()}
      >
        {/* No ✕ button (owner decision 2026-07-24): clicking the backdrop
            or pressing Escape closes every popup. mb-2 matches MODAL_BODY's
            gap-2, so the title-to-body gap equals every other gap in the
            popup (owner report 2026-07-21). Every titled popup gets a
            divider between title and body (owner request 2026-08-09).
            Title-less popups (the data-notes modal) start straight at the
            body — no leftover header spacing. */}
        {title != null ? (
          <>
            <h3 className="mb-2 font-semibold text-gray-300">{title}</h3>
            <hr className="mb-2 border-gray-700/60" />
          </>
        ) : null}
        {children}
      </div>
    </div>,
    document.body,
  );
};

interface AltNotesButtonProps {
  notes: string[];
}

// The card's only data-quality signal. Nothing to report → no mark at
// all (an exclamation mark opening an empty list reads as a bug, owner
// report 2026-08-09). Something to report → a small amber exclamation
// mark that opens a title-less modal listing each note as "keyword:
// plain-English sentence" (altWarningText.ts) — raw backend text no
// longer shown; unknown shapes keep their raw wording under the generic
// "Warning" keyword. No bullet dots — every entry is its own
// keyword-led line (owner request 2026-08-09). The old coverage grades
// (full/partial/unavailable badges, the red X) are retired 2026-08-19:
// blank fields with their own notes ARE the degradation signal.
export const AltNotesButton = ({ notes }: AltNotesButtonProps) => {
  const { t, language } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);

  if (notes.length === 0) {
    return null;
  }
  return (
    <>
      <button
        type="button"
        data-testid="alt-notes-button"
        aria-label={t('tiered.warnings')}
        onClick={() => setIsOpen(true)}
        className="inline-flex cursor-pointer items-center rounded text-amber-300 hover:text-amber-200"
      >
        <CircleAlert className="h-4 w-4" />
      </button>
      <AltModal isOpen={isOpen} onClose={() => setIsOpen(false)}>
        {/* No title, no explainer line (owner decision 2026-07-24) — the
            amber lives on the trigger icon only. Entries are keyword-led
            lines in the "keyword: sentence" shape. */}
        <ul className={MODAL_BODY}>
          {notes.map((raw, index) => {
            const friendly = friendlyWarning(raw, t, language);
            return (
              <li key={index}>
                <span className={MODAL_STRONG}>{friendly.keyword}: </span>
                {friendly.text}
              </li>
            );
          })}
        </ul>
      </AltModal>
    </>
  );
};

const CITATION_MARKER_SPLIT_RE = /(\[\d+\])/g;
const CITATION_MARKER_RE = /^\[(\d+)\]$/;

interface AltNarrativeProps {
  text: string;
  citations: TieredCitation[];
}

// Narrative text with [n] markers linked to their numbered sources —
// same behavior as the main page, alt colors.
export const AltNarrative = ({ text, citations }: AltNarrativeProps) => (
  <p className="text-sm leading-relaxed">
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
            className={ALT_LINK}
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

interface AltEvidenceRefsProps {
  refs: string[];
  citations: TieredCitation[];
  onNavigate?: () => void;
}

// Evidence references as links: "citation:N" opens the news source (shown
// as "sentiment.citation:N" — the same dimension.path grammar as every
// other reference), a payload path scrolls to that metric row.
// Unresolvable refs stay text.
export const AltEvidenceRefs = ({ refs, citations, onNavigate }: AltEvidenceRefsProps) => (
  <span className="inline-flex flex-wrap gap-x-2 text-[11px]">
    {refs.map((refPath, index) => {
      const citationMatch = CITATION_REF_RE.exec(refPath);
      if (citationMatch) {
        const citation = citations[Number(citationMatch[1]) - 1];
        const shown = `sentiment.${refPath}`;
        if (citation?.url) {
          return (
            <a
              key={index}
              href={citation.url}
              target="_blank"
              rel="noreferrer"
              aria-label={citation.title ?? citation.url}
              className={ALT_LINK}
            >
              {shown}
            </a>
          );
        }
        return <span key={index}>{shown}</span>;
      }
      return (
        <button
          key={index}
          type="button"
          className={cn('cursor-pointer', ALT_LINK)}
          onClick={() => {
            onNavigate?.();
            // Let any open modal unmount before scrolling to the row behind it.
            window.setTimeout(() => jumpToMetric(refPath), 50);
          }}
        >
          {refPath}
        </button>
      );
    })}
  </span>
);
