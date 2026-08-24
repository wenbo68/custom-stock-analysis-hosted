// Shared (non-component) pieces of the news cards, split out of
// AltEvents.tsx so that file exports only its component
// (react-refresh/only-export-components).
//
// The news cards (qualitative reports): company_events and
// world_events both ship the same news_coverage payload, so one parser
// and one horizon reader serve both.

export const EVENTS_DIMENSIONS = ['company_events', 'world_events'];

export const NEWS_GROUP_KEY = 'news_coverage';

export interface EventItem {
  text: string;
  citation: number | null;
  date: string | null;
  publisher: string | null;
}

export interface EventGroup {
  windowDays: number | null;
  oldest: string | null;
  newest: string | null;
  items: EventItem[];
}

// Defensive read of the payload group — the payload crosses a JSON
// boundary, so unknown shapes must degrade to "nothing", never crash.
export function parseEventGroup(raw: unknown): EventGroup | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return null;
  }
  const group = raw as Record<string, unknown>;
  const rawItems = group.items;
  if (!Array.isArray(rawItems)) {
    return null;
  }
  const items: EventItem[] = [];
  for (const entry of rawItems) {
    if (entry === null || typeof entry !== 'object') {
      continue;
    }
    const item = entry as Record<string, unknown>;
    if (typeof item.text !== 'string') {
      continue;
    }
    items.push({
      text: item.text,
      citation: typeof item.citation === 'number' ? item.citation : null,
      date: typeof item.date === 'string' && item.date ? item.date : null,
      publisher:
        typeof item.publisher === 'string' && item.publisher
          ? item.publisher
          : null,
    });
  }
  return {
    windowDays: typeof group.window_days === 'number' ? group.window_days : null,
    oldest: typeof group.oldest === 'string' && group.oldest ? group.oldest : null,
    newest: typeof group.newest === 'string' && group.newest ? group.newest : null,
    items,
  };
}

// The card's horizon, rendered next to the card title (owner request
// 2026-08-17): the actual date span covered — both cards publish
// oldest/newest since 2026-08-17 (owner format: real dates, never a
// "last N days" phrase). The days form survives only for runs stored
// before the span existed (their payloads carry window_days alone).
// Null when the payload carries neither (unavailable card, or a run
// stored before the news_coverage group existed).
export type EventsWindow =
  | { kind: 'days'; count: number }
  | { kind: 'span'; oldest: string; newest: string };

export function eventsWindowLabel(
  payload: Record<string, unknown>,
): EventsWindow | null {
  const group = parseEventGroup(payload[NEWS_GROUP_KEY]);
  if (!group) {
    return null;
  }
  if (group.oldest != null && group.newest != null) {
    return { kind: 'span', oldest: group.oldest, newest: group.newest };
  }
  if (group.windowDays != null) {
    return { kind: 'days', count: group.windowDays };
  }
  return null;
}
