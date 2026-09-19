import { useState, type ReactNode } from 'react';
import { tieredApi, type TieredTranscriptEntry } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Tooltip } from '../common/Tooltip';
import { AltCard, AltFold } from './AltUi';

export interface AltTranscriptProps {
  /** The run whose LLM exchanges to show. */
  taskId: string;
  /** The usage line ("This run used N LLM calls…") — it is the toggle. */
  label: ReactNode;
  /** Test seam; production reads the run's stored transcript. */
  loader?: (taskId: string) => Promise<TieredTranscriptEntry[]>;
}

type LoadState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; items: TieredTranscriptEntry[] };

// The run's AI exchanges — every prompt and raw reply — folded under the
// usage line itself (owner decision 2026-09-17: one line to click, not a
// second "view transcript" link below it). Loaded on first open only:
// the rows can be large, and most readers never need them. Exists so a
// "returned no usable JSON" warning is diagnosable from the page instead
// of a re-run.
export const AltTranscript = ({
  taskId,
  label,
  loader = tieredApi.getTranscript,
}: AltTranscriptProps) => {
  const { t } = useUiLanguage();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<LoadState>({ kind: 'idle' });

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || state.kind === 'ready' || state.kind === 'loading') {
      return;
    }
    setState({ kind: 'loading' });
    try {
      const items = await loader(taskId);
      setState({ kind: 'ready', items });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState({ kind: 'error', message });
    }
  };

  return (
    <div className="text-xs">
      {/* The help popup wraps the button rather than sitting inside it,
          so the line is a single tab stop: hover or focus shows the help,
          click/Enter opens the transcript. */}
      <Tooltip
        content={
          <span className="block max-w-[16rem] whitespace-pre-line">
            {t('tiered.help.llmUsage')}
          </span>
        }
      >
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="text-left text-gray-600 hover:text-gray-300"
        >
          {label}
        </button>
      </Tooltip>
      {open ? (
        // The same card surface as the report and analysis cards (owner
        // request 2026-09-18), not the history backdrop.
        <AltCard testId="alt-transcript" className="mt-2 flex flex-col gap-4">
          {state.kind === 'loading' ? (
            <p className="text-gray-500">{t('tiered.transcript.loading')}</p>
          ) : null}
          {state.kind === 'error' ? (
            <p className="text-amber-300">
              {t('tiered.transcript.error', { error: state.message })}
            </p>
          ) : null}
          {state.kind === 'ready' && state.items.length === 0 ? (
            <p className="text-gray-500">{t('tiered.transcript.empty')}</p>
          ) : null}
          {state.kind === 'ready'
            ? state.items.map((item) => <TranscriptEntry key={item.seq} item={item} />)
            : null}
        </AltCard>
      ) : null}
    </div>
  );
};

// The stage identifier reads as words: "company_news" → "company news".
const stageWords = (stage: string | null): string => (stage ?? '—').replace(/_/g, ' ');

// One exchange: the call number, then five fact lines (who owns it,
// what it was for, the model, time, tokens) in the same
// quiet-label / bright-value styling as the outlook and score facts,
// then the prompt and the reply on the same fold surface the
// deep-analysis card uses — both folded by default and shown whole when
// opened, no inner scroll box (owner requests 2026-09-18). "Owner"
// exists for reused runs (2026-09-19), whose list starts with the
// exchanges of the run the outlook was borrowed from.
const TranscriptEntry = ({ item }: { item: TieredTranscriptEntry }) => {
  const { t } = useUiLanguage();
  const tokens = (item.prompt_tokens ?? 0) + (item.completion_tokens ?? 0);
  const payer =
    item.paid_by === 'another_user'
      ? t('tiered.transcript.paidByOther')
      : t('tiered.transcript.paidByYou');
  const facts: [string, string][] = [
    [t('tiered.transcript.paidBy'), payer],
    [t('tiered.transcript.for'), stageWords(item.stage)],
    [t('tiered.transcript.llm'), item.model ?? '—'],
    [t('tiered.transcript.time'), item.duration_ms == null ? '—' : `${item.duration_ms}ms`],
    [t('tiered.transcript.tokens'), String(tokens)],
  ];
  return (
    <article className="flex flex-col gap-2 border-t border-gray-700 pt-4 first:border-t-0 first:pt-0">
      <div className="flex flex-col gap-1">
        <p className="font-semibold text-gray-300">{t('tiered.transcript.call', { n: item.seq })}</p>
        <p className="flex flex-col gap-0.5" data-testid="alt-transcript-facts">
          {facts.map(([label, value]) => (
            <span key={label} className="text-gray-500">
              {label}
              {': '}
              <span className="font-semibold text-gray-200">{value}</span>
            </span>
          ))}
        </p>
      </div>
      {item.error ? (
        <p className="text-amber-300">{t('tiered.transcript.failed', { error: item.error })}</p>
      ) : null}
      <AltFold title={t('tiered.transcript.prompt')} className="">
        <pre className="whitespace-pre-wrap break-words text-[11px] text-gray-400">
          {item.prompt ?? ''}
        </pre>
      </AltFold>
      <AltFold title={t('tiered.transcript.reply')} className="">
        <pre className="whitespace-pre-wrap break-words text-[11px] text-gray-300">
          {item.reply ?? t('tiered.transcript.noReply')}
        </pre>
      </AltFold>
    </article>
  );
};
