import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { cn } from '../../utils/cn';
import { TAG_BASE } from './altStyles';

// Write-only form controls in the showplayer style: what the user picks or
// types never stays in the field — it becomes a removable pill below the
// form (AltPill), and the field clears for the next entry.

export interface AltSelectOption {
  value: string;
  label: string;
  node?: ReactNode;
}

interface AltFieldShellProps {
  label: ReactNode;
  children: ReactNode;
}

// A labeled form column, showplayer-style: bold label above the control.
const AltFieldShell = ({ label, children }: AltFieldShellProps) => (
  <div className="flex w-full flex-col gap-2">
    <span className="font-semibold text-gray-300">{label}</span>
    {children}
  </div>
);

interface AltSelectProps {
  label: ReactNode;
  options: AltSelectOption[];
  /** Committed value(s) — highlighted in the dropdown; clicking a
   *  highlighted option again is how the parent gets asked to clear it
   *  (onCommit fires with the same value; the parent toggles). */
  selected?: string[];
  placeholder?: string;
  inputMode?: 'decimal' | 'numeric';
  /**
   * false (default): only listed options commit; typing filters them.
   * true: Enter commits whatever was typed; options are suggestions.
   */
  freeText?: boolean;
  /** Keep the dropdown open after a pick, for multi-value filters. */
  multi?: boolean;
  validate?: (raw: string) => boolean;
  onCommit: (value: string) => void;
}

// The showplayer.net filter control: a flat gray-800 text row with a
// chevron, opening a flat dropdown panel underneath.
export const AltSelect = ({
  label,
  options,
  selected,
  placeholder,
  inputMode,
  freeText = false,
  multi = false,
  validate,
  onCommit,
}: AltSelectProps) => {
  const [written, setWritten] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setWritten('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const shown = freeText
    ? options
    : options.filter((option) => option.label.toLowerCase().includes(written.toLowerCase()));
  const cleaned = written.trim();
  const isInvalid = freeText && cleaned !== '' && validate ? !validate(cleaned) : false;

  const commit = (raw: string) => {
    onCommit(raw);
    setWritten('');
    if (!multi) {
      window.setTimeout(() => setIsOpen(false), 50);
    }
  };

  const handleEnter = () => {
    if (freeText) {
      if (cleaned && !isInvalid) {
        commit(cleaned);
      }
    } else if (shown.length === 1) {
      commit(shown[0].value);
    }
  };

  return (
    <AltFieldShell label={label}>
      <div ref={containerRef} className="relative">
        <div className="flex w-full items-center rounded bg-gray-800">
          <input
            type="text"
            value={written}
            inputMode={inputMode}
            onFocus={() => setIsOpen(true)}
            onChange={(event) => {
              setWritten(event.target.value);
              setIsOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                handleEnter();
              }
            }}
            placeholder={placeholder}
            aria-label={typeof label === 'string' ? label : undefined}
            className={cn(
              'w-full bg-transparent pl-3 placeholder-gray-500 outline-none',
              isInvalid ? 'text-red-300' : 'text-gray-300',
            )}
          />
          <button
            type="button"
            aria-label="Toggle options"
            onClick={() => setIsOpen(!isOpen)}
            className="cursor-pointer p-2 text-gray-500 hover:text-gray-300"
          >
            <ChevronDown className="h-5 w-5" />
          </button>
        </div>
        {isOpen && shown.length > 0 ? (
          <div className="absolute top-full z-10 mt-2 flex max-h-96 w-full flex-col overflow-y-auto rounded bg-gray-800 p-2 text-xs font-semibold">
            {shown.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => commit(option.value)}
                className={cn(
                  'w-full cursor-pointer rounded p-2 text-start hover:bg-gray-900 hover:text-blue-400',
                  selected?.includes(option.value) ? 'text-blue-400' : '',
                )}
              >
                {option.node ?? option.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </AltFieldShell>
  );
};

interface AltCommitInputProps {
  placeholder: string;
  inputMode?: 'decimal' | 'numeric';
  validate?: (raw: string) => boolean;
  onCommit: (value: string) => void;
}

// A bare write-only text box: Enter commits the trimmed text and clears.
// Invalid text (per validate) turns red and refuses to commit.
export const AltCommitInput = ({
  placeholder,
  inputMode,
  validate,
  onCommit,
}: AltCommitInputProps) => {
  const [written, setWritten] = useState('');
  const cleaned = written.trim();
  const isInvalid = cleaned !== '' && validate ? !validate(cleaned) : false;

  return (
    <input
      type="text"
      value={written}
      inputMode={inputMode}
      placeholder={placeholder}
      aria-label={placeholder}
      onChange={(event) => setWritten(event.target.value)}
      onKeyDown={(event) => {
        if (event.key !== 'Enter') {
          return;
        }
        event.preventDefault();
        if (!cleaned || isInvalid) {
          return;
        }
        onCommit(cleaned);
        setWritten('');
      }}
      className={cn(
        'w-full min-w-0 rounded bg-gray-800 px-3 py-2 placeholder-gray-500 outline-none',
        isInvalid ? 'text-red-300' : 'text-gray-300',
      )}
    />
  );
};

interface AltPairFieldProps {
  label: ReactNode;
  start: AltCommitInputProps;
  end: AltCommitInputProps;
}

// A labeled min/max (or start/end) pair — two commit boxes on one row.
export const AltPairField = ({ label, start, end }: AltPairFieldProps) => (
  <AltFieldShell label={label}>
    <div className="flex w-full items-center gap-2">
      <AltCommitInput {...start} />
      <AltCommitInput {...end} />
    </div>
  </AltFieldShell>
);

interface AltTextFieldProps extends AltCommitInputProps {
  label: ReactNode;
}

// A single labeled commit box (no dropdown).
export const AltTextField = ({ label, ...input }: AltTextFieldProps) => (
  <AltFieldShell label={label}>
    <AltCommitInput {...input} />
  </AltFieldShell>
);

interface AltPillProps {
  tone: string;
  onRemove: () => void;
  children: ReactNode;
}

// A committed selection, shown below the form; clicking it removes it.
export const AltPill = ({ tone, onRemove, children }: AltPillProps) => (
  <button
    type="button"
    onClick={onRemove}
    className={cn(TAG_BASE, tone, 'cursor-pointer transition hover:opacity-80')}
  >
    {children}
  </button>
);

interface AltPillRowProps {
  children: ReactNode;
}

// The pill strip under a form — wraps, keeps pill heights aligned. min-h
// reserves one pill row of space, so the first pill causes no layout shift.
export const AltPillRow = ({ children }: AltPillRowProps) => (
  <div className="flex min-h-5 flex-wrap items-center gap-2 text-xs font-semibold">{children}</div>
);

interface AltNavButtonProps {
  isActive?: boolean;
  isDisabled?: boolean;
  ariaLabel?: string;
  onClick: () => void;
  children: ReactNode;
}

// One square pagination button (showplayer's PlayerNavButton, button-only).
const AltNavButton = ({ isActive, isDisabled, ariaLabel, onClick, children }: AltNavButtonProps) => (
  <button
    type="button"
    disabled={isDisabled}
    aria-label={ariaLabel}
    onClick={onClick}
    className={cn(
      'flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded text-xs font-semibold transition-colors',
      isActive ? 'bg-gray-800 text-blue-400' : '',
      !isActive && !isDisabled ? 'text-gray-400 hover:bg-gray-800' : '',
      isDisabled ? 'pointer-events-none cursor-not-allowed text-gray-600' : '',
    )}
  >
    {children}
  </button>
);

export interface AltPageSelectorProps {
  page: number;
  pageCount: number;
  onPage: (page: number) => void;
  labels: { first: string; prev: string; next: string; last: string };
}

// The showplayer pager: first / previous / up to five page numbers around
// the current one / next / last. Always rendered — a single page shows an
// active "1" with the arrows disabled.
export const AltPageSelector = ({ page, pageCount, onPage, labels }: AltPageSelectorProps) => {
  const pagesToShow = 5;
  let startPage = Math.max(1, page - Math.floor(pagesToShow / 2));
  const endPage = Math.min(pageCount, startPage + pagesToShow - 1);
  if (endPage === pageCount) {
    startPage = Math.max(1, pageCount - pagesToShow + 1);
  }
  const numbers = Array.from({ length: endPage - startPage + 1 }, (_, i) => startPage + i);

  const go = (target: number) => {
    if (target >= 1 && target <= pageCount) {
      onPage(target);
    }
  };

  return (
    <div className="flex items-center justify-center gap-1">
      <AltNavButton onClick={() => go(1)} isDisabled={page <= 1} ariaLabel={labels.first}>
        <ChevronsLeft size={16} />
      </AltNavButton>
      <AltNavButton onClick={() => go(page - 1)} isDisabled={page <= 1} ariaLabel={labels.prev}>
        <ChevronLeft size={16} />
      </AltNavButton>
      {numbers.map((number) => (
        <AltNavButton key={number} onClick={() => go(number)} isActive={number === page}>
          {number}
        </AltNavButton>
      ))}
      <AltNavButton onClick={() => go(page + 1)} isDisabled={page >= pageCount} ariaLabel={labels.next}>
        <ChevronRight size={16} />
      </AltNavButton>
      <AltNavButton onClick={() => go(pageCount)} isDisabled={page >= pageCount} ariaLabel={labels.last}>
        <ChevronsRight size={16} />
      </AltNavButton>
    </div>
  );
};
