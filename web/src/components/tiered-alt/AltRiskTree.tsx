import { useState } from 'react';
import type { TieredRiskDetail, TieredRiskItem } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { LinkedTextV8, MarkButton, type MarkModal } from './AltDebateTree';
import { AltFold, AltModal, AltModalTitle, AltSectionLabel, MODAL_BODY } from './AltUi';

// The tier-3 risk vote (risk_detail format 2), rendered like the tier-2
// vote transcript: a collapsed Transcript foldable holding a numbered
// how-it-works list, per-group risk bullets whose history is told by
// ✓/✗ marks (none = both AIs listed it), and the Size block with the
// code-owned count → multiplier mapping. Risks have no bullish/bearish
// word — every bullet IS a risk.

// "sentiment" stays for old stored runs that still carry the retired
// news-sentiment dimension.
const GROUP_ORDER = ['technicals', 'fundamentals', 'positioning', 'macro_econ', 'sentiment', 'plan'];

const GROUP_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  positioning: 'tiered.dimension.positioning',
  sentiment: 'tiered.dimension.sentiment',
  plan: 'tiered.dimension.plan',
};

const EXPLAIN_KEYS = [
  'tiered.tree.riskExplain1',
  'tiered.tree.riskExplain2',
  'tiered.tree.riskExplain3',
  'tiered.tree.riskExplain4',
  'tiered.tree.riskExplain5',
  'tiered.tree.riskExplain6',
  'tiered.tree.riskExplain7',
] as const;

// One risk bullet: id, then the marks (code ✗ for struck; one ✓/✗ per
// vote), then the claim in its own grid column so wraps hang indented.
const RiskItem = ({
  item,
  onShow,
}: {
  item: TieredRiskItem;
  onShow: (modal: MarkModal) => void;
}) => {
  const { t } = useUiLanguage();
  const dead = item.final_status === 'excluded';
  const votes = item.votes ?? [];
  return (
    <li
      data-testid={`alt-risk-item-${item.id}`}
      className="grid grid-cols-[auto_1fr] gap-x-2 text-xs"
    >
      <span className="flex items-baseline gap-1.5 whitespace-nowrap">
        <span className="font-mono text-gray-500">{item.id}</span>
        {item.struck ? (
          <MarkButton
            label="✗"
            onClick={() =>
              onShow({
                title: (
                  <AltModalTitle
                    subject={t('tiered.tree.codeCheck')}
                    kind={t('tiered.tree.invalid')}
                  />
                ),
                body: (
                  <ul className={`${MODAL_BODY} list-disc pl-4`}>
                    {(item.problems ?? []).map((problem, index) => (
                      <li key={index}>{problem}</li>
                    ))}
                  </ul>
                ),
              })
            }
          />
        ) : null}
        {votes.map((vote, index) => (
          <MarkButton
            key={index}
            label={vote.verdict === 'valid' ? '✓' : '✗'}
            onClick={() =>
              onShow({
                title: (
                  <AltModalTitle
                    subject={t(
                      index === 0 ? 'tiered.tree.firstCheck' : 'tiered.tree.secondCheck',
                    )}
                    kind={t(vote.verdict === 'valid' ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
                  />
                ),
                body: (
                  <p className={MODAL_BODY}>
                    {vote.reason ? (
                      <LinkedTextV8 text={vote.reason} links={vote.links ?? []} />
                    ) : (
                      '—'
                    )}
                  </p>
                ),
              })
            }
          />
        ))}
      </span>
      <span className="text-gray-200">
        <LinkedTextV8 text={item.claim} links={item.links ?? []} struck={dead} />
      </span>
    </li>
  );
};

interface AltRiskTreeProps {
  detail: TieredRiskDetail;
}

export const AltRiskTree = ({ detail }: AltRiskTreeProps) => {
  const { t } = useUiLanguage();
  const [modal, setModal] = useState<MarkModal | null>(null);
  const items = detail.items ?? [];
  const verdict = detail.verdict;
  const groups = GROUP_ORDER.map((group) => ({
    group,
    items: items.filter((item) => item.dimension === group),
  })).filter((group) => group.items.length > 0);
  const confirmed = verdict?.confirmed_risks ?? null;
  // Show the plugged-in arithmetic only when the fixed mapping actually
  // reproduces the stored multiplier.
  const mapped =
    confirmed == null ? null : confirmed === 0 ? 1.0 : confirmed <= 3 ? 0.5 : 0.0;
  const showFormula =
    mapped != null && verdict?.size_multiplier != null && mapped === verdict.size_multiplier;

  const riskCount = (count: number) =>
    count === 1 ? t('tiered.tree.riskOne') : t('tiered.tree.riskMany', { n: count });

  return (
    <>
      <AltFold title={t('tiered.tree.transcript')}>
        <div data-testid="alt-risk-tree" className="flex flex-col gap-3">
          <div data-testid="alt-risk-explain">
            <AltSectionLabel>{t('tiered.tree.howItWorks')}</AltSectionLabel>
            <ol className="flex list-decimal flex-col gap-1 pl-4 text-xs text-gray-400">
              {EXPLAIN_KEYS.map((key) => (
                <li key={key}>{t(key)}</li>
              ))}
            </ol>
          </div>

          {groups.map((group) => {
            const counted = group.items.filter(
              (item) => item.final_status === 'counted',
            ).length;
            return (
              <div key={group.group}>
                <AltSectionLabel>
                  {GROUP_LABEL_KEYS[group.group]
                    ? t(GROUP_LABEL_KEYS[group.group])
                    : group.group}
                  {': '}
                  <span className={counted > 0 ? 'text-red-300' : 'text-gray-500'}>
                    {riskCount(counted)}
                  </span>
                </AltSectionLabel>
                <ul className="flex flex-col gap-1.5">
                  {group.items.map((item) => (
                    <RiskItem key={item.id} item={item} onShow={setModal} />
                  ))}
                </ul>
              </div>
            );
          })}

          {verdict ? (
            <div
              data-testid="alt-risk-size"
              className="flex flex-col gap-1 border-t border-gray-700/60 pt-3"
            >
              <AltSectionLabel>{t('tiered.tree.size')}</AltSectionLabel>
              <div className="flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>{t('tiered.tree.sizeFormula')}</p>
                {showFormula && confirmed != null ? (
                  <p className={FORMULA_LINE} data-testid="alt-risk-size-formula">
                    {t('tiered.tree.sizeConfirmed', { n: confirmed })}
                  </p>
                ) : null}
                <p className={FORMULA_RESULT}>= ×{verdict.size_multiplier}</p>
              </div>
            </div>
          ) : null}
        </div>
      </AltFold>

      <AltModal
        isOpen={modal !== null}
        title={modal?.title ?? ''}
        onClose={() => setModal(null)}
      >
        {modal?.body}
      </AltModal>
    </>
  );
};
