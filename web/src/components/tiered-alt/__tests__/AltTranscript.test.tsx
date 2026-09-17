import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TieredTranscriptEntry } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltTranscript } from '../AltTranscript';

const entry = (overrides: Partial<TieredTranscriptEntry> = {}): TieredTranscriptEntry => ({
  seq: 1,
  created_at: '2026-09-14T10:00:00',
  stage: 'tier1_quick',
  model: 'gemini/flash',
  temperature: 0,
  duration_ms: 120,
  prompt_tokens: 10,
  completion_tokens: 5,
  structured: 'schema',
  error: null,
  prompt: 'the prompt',
  reply: '{"outlook": "buy"}',
  ...overrides,
});

function renderTranscript(loader: (taskId: string) => Promise<TieredTranscriptEntry[]>) {
  render(
    <UiLanguageProvider>
      <AltTranscript taskId="task-1" entries={2} loader={loader} />
    </UiLanguageProvider>,
  );
}

describe('AltTranscript', () => {
  it('loads nothing until opened, then shows every exchange', async () => {
    const loader = vi.fn().mockResolvedValue([
      entry(),
      entry({ seq: 2, stage: 'plan_adjust', reply: null, error: "RuntimeError('boom')" }),
    ]);
    renderTranscript(loader);
    expect(loader).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /2/ }));

    await waitFor(() => expect(screen.getByText(/tier1_quick/)).toBeInTheDocument());
    expect(loader).toHaveBeenCalledWith('task-1');
    expect(screen.getByText('{"outlook": "buy"}')).toBeInTheDocument();
    expect(screen.getAllByText('the prompt')).toHaveLength(2);
    expect(screen.getByText(/boom/)).toBeInTheDocument();
    expect(screen.getAllByText(/15 tokens/)).toHaveLength(2);
  });

  it('reports a load failure instead of hiding it', async () => {
    const loader = vi.fn().mockRejectedValue(new Error('network down'));
    renderTranscript(loader);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(screen.getByText(/network down/)).toBeInTheDocument());
  });

  it('says so when the stored rows have expired', async () => {
    const loader = vi.fn().mockResolvedValue([]);
    renderTranscript(loader);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() =>
      expect(screen.getByText(/已过期|expired/)).toBeInTheDocument(),
    );
  });

  it('fetches once and only toggles afterwards', async () => {
    const loader = vi.fn().mockResolvedValue([entry()]);
    renderTranscript(loader);
    const button = screen.getByRole('button');
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByText(/tier1_quick/)).toBeInTheDocument());
    fireEvent.click(button);
    expect(screen.queryByText(/tier1_quick/)).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByText(/tier1_quick/)).toBeInTheDocument();
    expect(loader).toHaveBeenCalledTimes(1);
  });
});
