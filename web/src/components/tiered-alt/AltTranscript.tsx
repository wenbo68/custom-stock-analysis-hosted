import { useState } from 'react';
import { tieredApi, type TieredTranscriptEntry } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

export interface AltTranscriptProps {
  /** The run whose LLM exchanges to show. */
  taskId: string;
  /** How many calls the run recorded (from llm_usage.transcript_entries). */
  entries: number;
  /** Test seam; production reads the run's stored transcript. */
  loader?: (taskId: string) => Promise<TieredTranscriptEntry[]>;
}

type LoadState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; items: TieredTranscriptEntry[] };

// The run's AI exchanges — every prompt and raw reply — behind a quiet
// toggle under the usage line. Loaded on first open only: the rows can
// be large, and most readers never need them. Exists so a "returned no
// usable JSON" warning is diagnosable from the page instead of a re-run.
export const AltTranscript = ({
  taskId,
  entries,
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
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="text-gray-500 underline decoration-dotted underline-offset-2 hover:text-gray-300"
      >
        {t('tiered.transcript.title', { count: entries })}
      </button>
      {open ? (
        <div className="mt-2 flex flex-col gap-3 rounded bg-gray-900/60 px-4 py-3">
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
        </div>
      ) : null}
    </div>
  );
};

const TranscriptEntry = ({ item }: { item: TieredTranscriptEntry }) => {
  const { t } = useUiLanguage();
  const tokens = (item.prompt_tokens ?? 0) + (item.completion_tokens ?? 0);
  return (
    <article className="flex flex-col gap-2 border-t border-gray-800 pt-3 first:border-t-0 first:pt-0">
      <p className="font-semibold text-gray-300">
        #{item.seq} · {item.stage ?? '—'} · {item.model ?? '—'} ·{' '}
        {item.duration_ms ?? '—'} ms · {tokens} tokens
      </p>
      {item.error ? (
        <p className="text-amber-300">{t('tiered.transcript.failed', { error: item.error })}</p>
      ) : null}
      <details>
        <summary className="cursor-pointer text-gray-500">{t('tiered.transcript.prompt')}</summary>
        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] text-gray-400">
          {item.prompt ?? ''}
        </pre>
      </details>
      <div>
        <p className="text-gray-500">{t('tiered.transcript.reply')}</p>
        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] text-gray-300">
          {item.reply ?? t('tiered.transcript.noReply')}
        </pre>
      </div>
    </article>
  );
};
