import type { TieredSummaryStructure } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { LinkedClaimV7 } from './AltDebateTree';

// The deep-analysis report as its fixed outline (owner decision
// 2026-07-24): the group set and order never change run to run —
// summary first, then the four dimensions in report order. The backend
// enforces the shape (StructuredSummaryModel); groups a run left empty
// are skipped, never reordered. Bullets carry the evidence-list link
// contract, so cited values render as jumps to their report row.
const GROUPS: { key: keyof TieredSummaryStructure; labelKey: UiTextKey }[] = [
  { key: 'summary', labelKey: 'tiered.alt.summaryGroup' },
  { key: 'technicals', labelKey: 'tiered.dimension.technicals' },
  { key: 'fundamentals', labelKey: 'tiered.dimension.fundamentals' },
  { key: 'positioning', labelKey: 'tiered.dimension.positioning' },
  { key: 'macro_econ', labelKey: 'tiered.dimension.macro_econ' },
  { key: 'opinion', labelKey: 'tiered.dimension.opinion' },
  { key: 'company_events', labelKey: 'tiered.dimension.company_events' },
  { key: 'world_events', labelKey: 'tiered.dimension.world_events' },
];

interface AltSummaryOutlineProps {
  structure: TieredSummaryStructure;
}

export const AltSummaryOutline = ({ structure }: AltSummaryOutlineProps) => {
  const { t } = useUiLanguage();
  return (
    <ul
      data-testid="alt-summary-outline"
      className="flex list-disc flex-col gap-1 pl-4 text-sm leading-relaxed"
    >
      {GROUPS.map(({ key, labelKey }) => {
        const bullets = structure[key] ?? [];
        if (!bullets || bullets.length === 0) {
          return null;
        }
        return (
          <li key={key}>
            <span className="font-semibold text-gray-300">{t(labelKey)}</span>
            <ul className="list-[circle] pl-4">
              {bullets.map((bullet, index) => (
                <li key={index}>
                  <LinkedClaimV7
                    claim={bullet.text}
                    links={bullet.links ?? []}
                    struck={false}
                  />
                  {bullet.children && bullet.children.length > 0 ? (
                    <ul className="list-[square] pl-4 text-gray-400">
                      {bullet.children.map((child, childIndex) => (
                        <li key={childIndex}>
                          <LinkedClaimV7
                            claim={child.text}
                            links={child.links ?? []}
                            struck={false}
                          />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
};
