import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { flashElement, metricAnchorId } from '../tiered/termHelpers';
import { slashDate } from './altFormat';
import { ALT_LINK } from './altStyles';
import { NEWS_GROUP_KEY, parseEventGroup } from './altEventsData';

// The news cards (qualitative reports): company_events (news-only
// since 2026-08-13 — the statements group was deleted; its red-flag
// signal moves into fundamentals as fields) and world_events (the
// macro/world backdrop card, 2026-08-16). Both ship the same
// news_coverage payload, so one renderer serves them instead of
// AltPayloadTable: one-sentence event summaries whose [n] marks jump
// to the numbered source at the card's foot. Owner format 2026-08-16,
// revised 2026-08-17: each bullet is a header line — the date, then
// the outlet in a dimmer italic (no "|" divider) — with the summary
// beneath it, newest first. Items from runs stored before that
// format carry no date field and render as the old single inline line.
// No group title (owner format 2026-08-13) — the card title alone
// carries the meaning. The card's horizon (fixed window / the world
// card's fetched date span) renders beside the card TITLE, not here.
// Shared payload parsing, the EVENTS_DIMENSIONS list, and the
// title-side horizon reader live in altEventsData.ts (this file
// exports only its component — react-refresh rule).
interface AltEventsListProps {
  /** The card's dimension name — anchors ids and source-jump targets
      (company_events / world_events share this renderer). */
  dimension: string;
  payload: Record<string, unknown>;
}

// Card body: bullet lines with [n] source marks (the sources section
// below adds its own divider). An empty fetched window says so
// explicitly instead of rendering a blank card.
export const AltEventsList = ({ dimension, payload }: AltEventsListProps) => {
  const { t } = useUiLanguage();
  const group = parseEventGroup(payload[NEWS_GROUP_KEY]);
  if (!group) {
    return null;
  }
  if (group.items.length === 0) {
    return (
      <p className="text-xs italic text-gray-500">
        {group.windowDays != null
          ? t('tiered.alt.eventsNone', { count: group.windowDays })
          : t('tiered.alt.eventsNoneGeneric')}
      </p>
    );
  }
  // The horizon (fixed window / fetched span) renders next to the card
  // TITLE, not here (owner request 2026-08-17 — eventsWindowLabel).
  return (
    <ul className="flex list-disc flex-col gap-2 pl-4">
      {group.items.map((item, index) => (
        <li
          key={index}
          // The debate cites items by their payload path
          // (<dimension>.<group>.items.3.text); the anchor id lets
          // those citations scroll-flash this bullet.
          id={metricAnchorId(`${dimension}.${NEWS_GROUP_KEY}.items.${index}.text`)}
          className="scroll-mt-24 text-xs leading-relaxed text-gray-300"
        >
          {item.date != null ? (
            // Date and outlet are told apart by treatment, not a "|"
            // divider (owner request 2026-08-17: the pipe made them
            // run together): the date keeps its weight, the outlet
            // sits beside it dimmer and italic. The literal space
            // keeps copied text readable; the margin is the visual
            // gap.
            <span className="font-medium text-gray-400">
              {slashDate(item.date)}
              {item.publisher ? (
                <>
                  {' '}
                  <span className="ml-1 font-normal italic text-gray-500">
                    {item.publisher}
                  </span>
                </>
              ) : null}
            </span>
          ) : null}
          <span className={item.date != null ? 'block' : undefined}>
            {item.text}
            {item.citation != null ? (
              <>
                {' '}
                <button
                  type="button"
                  className={`cursor-pointer ${ALT_LINK}`}
                  onClick={() =>
                    flashElement(`alt-src-${dimension}-${item.citation}`)
                  }
                >
                  [{item.citation}]
                </button>
              </>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
};
