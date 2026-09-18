import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

// Company-news card (news-only since 2026-08-13): one-sentence event
// summaries under a date-then-outlet header line (owner format
// 2026-08-16, revised 2026-08-17: no "|" divider — the outlet is a
// dimmer italic span beside the date), whose [n] marks jump to the
// numbered, hyperlinked sources at the card's foot. No group titles.
const LONG_ABSTRACT =
  'Apple introduced a set of AI features across its devices, expanding its ' +
  'assistant with real-time content deals and a staged rollout plan that ' +
  'analysts said could reshape services revenue over the coming years.';

function makeEvents(overrides: Partial<TieredDimension> = {}): TieredDimension {
  return {
    dimension: 'company_news',
    kind: 'textual',
    is_actionable: false,
    narrative: null,
    warnings: [],
    formulas: null,
    field_notes: null,
    payload: {
      news_coverage: {
        // New runs carry only the actual span (the window is a
        // business-day quota with a varying calendar length);
        // window_days survives in old stored runs only.
        oldest: '2026-08-05',
        newest: '2026-08-13',
        items: [
          {
            text: LONG_ABSTRACT,
            citation: 1,
            date: '2026-08-12',
            publisher: 'Reuters',
          },
          {
            text: 'Analysts weigh iPhone demand',
            citation: 2,
            date: '2026-08-05',
            publisher: 'Bloomberg',
          },
        ],
      },
    },
    citations: [
      {
        source_name: 'Reuters',
        url: 'https://example.com/apple-ai',
        title: 'Apple unveils new AI features',
        snippet: null,
      },
      {
        source_name: 'Bloomberg',
        url: 'https://example.com/iphone-demand',
        title: 'Analysts weigh iPhone demand',
        snippet: null,
      },
    ],
    ...overrides,
  };
}

function renderEvents(dimension: TieredDimension = makeEvents()) {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[dimension]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — company news', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders date | publisher header lines above full summary bullets', () => {
    renderEvents();
    const card = screen.getByTestId('alt-dimension-company_news');
    expect(within(card).getByText('Company news')).toBeInTheDocument();
    // The card's horizon sits beside the title as the actual date span
    // fetched (owner format 2026-08-17, same as the world card).
    expect(within(card).getByText('2026/08/05 – 2026/08/13')).toBeInTheDocument();
    // The header line: slashed date, then the outlet as its own
    // dimmer span — no "|" divider (owner format 2026-08-17); the
    // full line still copies as "date outlet".
    expect(within(card).getByText('2026/08/12').textContent).toBe(
      '2026/08/12 Reuters',
    );
    expect(within(card).getByText('2026/08/05').textContent).toBe(
      '2026/08/05 Bloomberg',
    );
    expect(within(card).queryByText(/\|/)).toBeNull();
    // The summary renders in full, untruncated.
    expect(
      within(card).getByText(new RegExp(LONG_ABSTRACT.slice(0, 60))),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(/reshape services revenue over the coming years/),
    ).toBeInTheDocument();
    // No group headings survive (owner format 2026-08-13).
    expect(within(card).queryByText('Company statements')).toBeNull();
    expect(within(card).queryByText('News coverage')).toBeNull();
  });

  it('lists numbered sources as links to the original articles', () => {
    renderEvents();
    const card = screen.getByTestId('alt-dimension-company_news');
    expect(within(card).getByText('Sources')).toBeInTheDocument();
    const sourceRow = document.getElementById('alt-src-company_news-2');
    expect(sourceRow).not.toBeNull();
    expect(within(sourceRow as HTMLElement).getByText('[2]')).toBeInTheDocument();
    const link = within(sourceRow as HTMLElement).getByRole('link');
    expect(link).toHaveAttribute('href', 'https://example.com/iphone-demand');
  });

  it('scrolls to the matching source when a bullet [n] mark is clicked', () => {
    renderEvents();
    const scrollSpy = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = scrollSpy;
    const card = screen.getByTestId('alt-dimension-company_news');
    fireEvent.click(within(card).getByRole('button', { name: '[2]' }));
    expect(scrollSpy).toHaveBeenCalled();
  });

  it('says so when the feed fetched fine but found nothing in the window', () => {
    renderEvents(
      makeEvents({
        payload: { news_coverage: { window_days: 14, items: [] } },
        citations: [],
      }),
    );
    const card = screen.getByTestId('alt-dimension-company_news');
    expect(within(card).getByText('None in the last 14 days')).toBeInTheDocument();
  });

  it('shows no underscore anywhere on the card (payload keys never leak)', () => {
    renderEvents();
    const card = screen.getByTestId('alt-dimension-company_news');
    expect(card.textContent).not.toContain('_');
  });

  it('still renders news bullets from old stored runs that carried a statements group', () => {
    renderEvents(
      makeEvents({
        payload: {
          company_statements: {
            window_days: 30,
            items: [{ text: 'Old statements bullet', citation: 9 }],
          },
          news_coverage: {
            window_days: 14,
            items: [{ text: 'Still-shown news bullet — Wire (2026-08-12)', citation: 1 }],
          },
        },
      }),
    );
    const card = screen.getByTestId('alt-dimension-company_news');
    expect(within(card).getByText(/Still-shown news bullet/)).toBeInTheDocument();
    // The deleted group no longer renders, even from old stored runs.
    expect(within(card).queryByText(/Old statements bullet/)).toBeNull();
  });

  it('renders the world-news card through the same events renderer', () => {
    renderEvents(
      makeEvents({
        dimension: 'world_news',
        payload: {
          news_coverage: {
            oldest: '2026-08-14',
            newest: '2026-08-16',
            items: [
              {
                text: 'The central bank held rates steady and signaled a cut.',
                citation: 1,
                date: '2026-08-16',
                publisher: 'Reuters',
              },
            ],
          },
        },
        citations: [
          {
            source_name: 'Reuters',
            url: 'https://example.com/fed-hold',
            title: 'Fed holds rates',
            snippet: null,
          },
        ],
      }),
    );
    const card = screen.getByTestId('alt-dimension-world_news');
    expect(within(card).getByText('World news')).toBeInTheDocument();
    // The honest horizon label beside the title: the feed has no date
    // range, so the card states the span it actually covered.
    expect(within(card).getByText('2026/08/14 – 2026/08/16')).toBeInTheDocument();
    expect(within(card).getByText('2026/08/16').textContent).toBe(
      '2026/08/16 Reuters',
    );
    expect(
      within(card).getByText(/held rates steady and signaled a cut/),
    ).toBeInTheDocument();
    // Bullet [n] marks target this card's own source rows, not the
    // company card's.
    const sourceRow = document.getElementById('alt-src-world_news-1');
    expect(sourceRow).not.toBeNull();
  });

  it('world card with an empty feed says so with the generic empty text', () => {
    renderEvents(
      makeEvents({
        dimension: 'world_news',
        payload: {
          news_coverage: { oldest: null, newest: null, items: [] },
        },
        citations: [],
      }),
    );
    const card = screen.getByTestId('alt-dimension-world_news');
    expect(within(card).getByText('None found')).toBeInTheDocument();
  });

  it('renders pre-2026-08-16 items (no date field) as the old inline line', () => {
    renderEvents(
      makeEvents({
        payload: {
          news_coverage: {
            window_days: 14,
            items: [
              { text: 'Old-format bullet — Wire (2026-08-12)', citation: 1 },
            ],
          },
        },
      }),
    );
    const card = screen.getByTestId('alt-dimension-company_news');
    expect(
      within(card).getByText('Old-format bullet — Wire (2026-08-12)'),
    ).toBeInTheDocument();
    // No header line is invented for items that never carried a date.
    expect(within(card).queryByText(/\|/)).toBeNull();
    // A stored run without the date span falls back to the days phrase.
    expect(within(card).getByText('last 14 days')).toBeInTheDocument();
  });
});
