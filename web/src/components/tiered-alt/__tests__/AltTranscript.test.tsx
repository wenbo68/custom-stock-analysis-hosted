import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TieredTranscriptEntry } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltTranscript } from '../AltTranscript';

const entry = (overrides: Partial<TieredTranscriptEntry> = {}): TieredTranscriptEntry => ({
  seq: 1,
  created_at: '2026-09-14T10:00:00',
  stage: 'tier1_analysis',
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
      <AltTranscript taskId="task-1" label="This run used 2 LLM calls (30 tokens)" loader={loader} />
    </UiLanguageProvider>,
  );
}

// A fact line is one span whose full text is "label: value"; the value
// sits in a nested span, so plain getByText cannot see the pair together.
const factLines = (pattern: RegExp) =>
  screen.getAllByTestId('alt-transcript-facts').flatMap((row) =>
    Array.from(row.children).filter((fact) => pattern.test(fact.textContent ?? '')),
  );

describe('AltTranscript', () => {
  it('loads nothing until opened, then shows every exchange', async () => {
    const loader = vi.fn().mockResolvedValue([
      entry(),
      entry({ seq: 2, stage: 'trade_plan', reply: null, error: "RuntimeError('boom')" }),
    ]);
    renderTranscript(loader);
    expect(loader).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /2 LLM calls/ }));

    await waitFor(() => expect(screen.getByText(/tier1 analysis/)).toBeInTheDocument());
    expect(loader).toHaveBeenCalledWith('task-1');
    expect(screen.getByText('{"outlook": "buy"}')).toBeInTheDocument();
    expect(screen.getAllByText('the prompt')).toHaveLength(2);
    expect(screen.getByText(/boom/)).toBeInTheDocument();
    // The call number, then one row of label/value facts: the label
    // stays muted, the value is bright and bold.
    expect(screen.getByText(/^(Call 1|第 1 次调用)$/)).toBeInTheDocument();
    expect(screen.getAllByTestId('alt-transcript-facts')).toHaveLength(2);
    expect(factLines(/^tokens: 15$/)).toHaveLength(2);
    expect(factLines(/^(for|用于): trade plan$/)).toHaveLength(1);
    // Rows without a payer are the caller's own.
    expect(factLines(/^(owner|所有者): (you|你)$/)).toHaveLength(2);
    expect(factLines(/^(time|耗时): 120ms$/)).toHaveLength(2);
    expect(screen.getByText('trade plan')).toHaveClass('font-semibold', 'text-gray-200');
    // Both prompt and reply folded by default, on the same fold surface
    // as the deep-analysis card's details.
    const folds = Array.from(document.querySelectorAll('details'));
    expect(folds).toHaveLength(4);
    expect(folds.every((fold) => !fold.open)).toBe(true);
    expect(folds.every((fold) => fold.classList.contains('bg-gray-900/60'))).toBe(true);
    // Shown whole when opened: no inner scroll box.
    expect(document.querySelector('pre.max-h-64')).toBeNull();
    // On the card surface, not the history backdrop.
    expect(screen.getByTestId('alt-transcript')).toHaveClass('bg-gray-800');
  });

  it('says who owns each exchange, shared rows first', async () => {
    const loader = vi.fn().mockResolvedValue([
      entry({ seq: 1, stage: 'tier2_analysis', paid_by: 'another_user' }),
      entry({ seq: 2, stage: 'trade_plan', paid_by: 'you' }),
    ]);
    renderTranscript(loader);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(screen.getByText(/tier2 analysis/)).toBeInTheDocument());
    const rows = screen.getAllByTestId('alt-transcript-facts');
    // "owner" is the first fact of every exchange, above "for".
    expect(rows[0].children[0].textContent).toMatch(/^(owner|所有者): (another user|其他用户)$/);
    expect(rows[0].children[1].textContent).toMatch(/^(for|用于): tier2 analysis$/);
    expect(rows[1].children[0].textContent).toMatch(/^(owner|所有者): (you|你)$/);
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
    await waitFor(() => expect(screen.getByText(/tier1 analysis/)).toBeInTheDocument());
    fireEvent.click(button);
    expect(screen.queryByText(/tier1 analysis/)).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByText(/tier1 analysis/)).toBeInTheDocument();
    expect(loader).toHaveBeenCalledTimes(1);
  });
});
