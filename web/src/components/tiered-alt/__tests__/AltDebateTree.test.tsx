import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredDebateLink } from '../../../api/tiered';
import { LinkedTextV8 } from '../AltDebateTree';
import { stripInlineRefs } from '../altFormat';

// Models sometimes leak the citation markup INLINE in a reason instead
// of plain prose + a links entry. The UI must show only the value.

const INLINE_REASON =
  'The close price of {{ref: "technicals.close", "value": "340.75"}} is above the ' +
  '20-day swing low of {{ref: "technicals.swing_low_20", "value": "336.53"}}.';

describe('stripInlineRefs', () => {
  it('replaces inline ref markup with the bare value and collects links', () => {
    const { text, links } = stripInlineRefs(INLINE_REASON, []);
    expect(text).toBe('The close price of 340.75 is above the 20-day swing low of 336.53.');
    expect(links).toEqual([
      { ref: 'technicals.close', value: '340.75' },
      { ref: 'technicals.swing_low_20', value: '336.53' },
    ]);
  });

  it('does not duplicate a link the array already carries', () => {
    const existing: TieredDebateLink[] = [{ ref: 'technicals.close', value: '340.75' }];
    const { links } = stripInlineRefs(
      'Close {{ref: "technicals.close", "value": "340.75"}} holds.',
      existing,
    );
    expect(links).toEqual(existing);
  });

  it('drops a bare sentiment ref marker without leaving double spaces', () => {
    const { text, links } = stripInlineRefs('Guided up {{ref: "citation:2"}} last week.', []);
    expect(text).toBe('Guided up last week.');
    expect(links).toEqual([{ ref: 'citation:2', value: null }]);
  });

  it('leaves markup-free text and its links untouched', () => {
    const links: TieredDebateLink[] = [{ ref: 'technicals.rsi_14', value: '56.28' }];
    expect(stripInlineRefs('RSI at 56.28 is neutral.', links)).toEqual({
      text: 'RSI at 56.28 is neutral.',
      links,
    });
  });
});

describe('LinkedTextV8', () => {
  it('renders leaked inline markup as clickable values, not raw braces', () => {
    const { container } = render(<LinkedTextV8 text={INLINE_REASON} links={[]} />);
    expect(container.textContent).toBe(
      'The close price of 340.75 is above the 20-day swing low of 336.53.',
    );
    expect(screen.getByRole('button', { name: '340.75' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '336.53' })).toBeInTheDocument();
  });
});
