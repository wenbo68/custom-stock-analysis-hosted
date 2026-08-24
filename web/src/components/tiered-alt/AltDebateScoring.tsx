import type { TieredAxisGrade, TieredDebateDetail, TieredDebaterScore } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { AltFold, AltSectionLabel, FVar } from './AltUi';

// The "Scoring and calculation" foldable of a scored tier-2 run: the
// judge's validity grades per debater, then the fixed formulas — each in
// the same three-line words/plugged/result shape as the levels and shares
// formulas. Two stored generations: v3 grades are bare numbers with one
// notes sentence; v4 grades are objects where every score below 5 carries
// the offending sentence verbatim plus why it is wrong (N/A at 5/5).

const SIDES = ['bull', 'bear'] as const;
type Side = (typeof SIDES)[number];

const SIDE_LABEL_KEY: Record<Side, UiTextKey> = {
  bull: 'tiered.debate.bull',
  bear: 'tiered.debate.bear',
};

const SIDE_COLOR: Record<Side, string> = {
  bull: 'text-emerald-300',
  bear: 'text-red-300',
};

const AXES = [
  { key: 'citation_validity', labelKey: 'tiered.debate.citationValidity' },
  { key: 'knowledge_validity', labelKey: 'tiered.debate.knowledgeValidity' },
  { key: 'logical_validity', labelKey: 'tiered.debate.logicValidity' },
] as const;

const axisScore = (axis: number | TieredAxisGrade): number =>
  typeof axis === 'number' ? axis : axis.score;

const positionScoreOf = (score: TieredDebaterScore): number =>
  score.position_score ?? score.bullishness ?? 0;

const weightText = (score: TieredDebaterScore) => score.weight.toFixed(2);

// One judge grade with its comment: N/A when nothing was wrong (5/5),
// otherwise the quoted sentence plus the judge's reason.
const AxisLine = ({ labelKey, axis }: { labelKey: UiTextKey; axis: TieredAxisGrade }) => {
  const { t } = useUiLanguage();
  const hasComment = Boolean(axis.quote || axis.why);
  return (
    <p className="text-xs text-gray-400">
      {t(labelKey)}: <span className="tabular-nums">{axis.score}/5</span>
      {' · '}
      {t('tiered.debate.comment')}:{' '}
      {hasComment ? (
        <span className="text-gray-500">
          {axis.quote ? <i>“{axis.quote}”</i> : null}
          {axis.quote && axis.why ? ' — ' : null}
          {axis.why}
        </span>
      ) : (
        <span className="text-gray-500">N/A</span>
      )}
    </p>
  );
};

const DebaterBlock = ({ side, score }: { side: Side; score: TieredDebaterScore }) => {
  const { t } = useUiLanguage();
  // v4 stores each axis as an object with the judge's comment; v3 stored
  // bare numbers plus one free-text notes sentence.
  const hasComments = AXES.some(({ key }) => typeof score[key] === 'object');
  return (
    <div data-testid={`alt-scoring-${side}`}>
      <div className={`mb-1 text-xs font-semibold ${SIDE_COLOR[side]}`}>
        {t(SIDE_LABEL_KEY[side])}
      </div>
      {hasComments ? (
        <div className="flex flex-col gap-0.5">
          <p className="text-xs text-gray-400">
            {t('tiered.debate.positionScore')}:{' '}
            <span className="tabular-nums">{positionScoreOf(score)}/10</span>
          </p>
          {AXES.map(({ key, labelKey }) => (
            <AxisLine
              key={key}
              labelKey={labelKey}
              axis={
                typeof score[key] === 'number'
                  ? { score: score[key] as number }
                  : (score[key] as TieredAxisGrade)
              }
            />
          ))}
        </div>
      ) : (
        <>
          <p className="text-xs text-gray-400">
            {t('tiered.debate.positionScore')}:{' '}
            <span className="tabular-nums">{positionScoreOf(score)}/10</span>
            {AXES.map(({ key, labelKey }) => (
              <span key={key}>
                {' · '}
                {t(labelKey)}: <span className="tabular-nums">{axisScore(score[key])}/5</span>
              </span>
            ))}
          </p>
          {score.notes ? <p className="mt-0.5 text-xs text-gray-500">{score.notes}</p> : null}
        </>
      )}
      <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
        <p className={FORMULA_LINE}>
          (<FVar>{t('tiered.debate.citationValidity')}</FVar> +{' '}
          <FVar>{t('tiered.debate.knowledgeValidity')}</FVar> +{' '}
          <FVar>{t('tiered.debate.logicValidity')}</FVar>) / 15
        </p>
        <p className={FORMULA_LINE}>
          = ({axisScore(score.citation_validity)} + {axisScore(score.knowledge_validity)} +{' '}
          {axisScore(score.logical_validity)}) / 15
        </p>
        <p className={FORMULA_RESULT}>
          = {weightText(score)} ({t('tiered.debate.weight')})
        </p>
      </div>
    </div>
  );
};

interface AltDebateScoringProps {
  verdict: NonNullable<TieredDebateDetail['verdict']>;
}

export const AltDebateScoring = ({ verdict }: AltDebateScoringProps) => {
  const { t } = useUiLanguage();
  const scoring = verdict.scoring;
  const finalScore = verdict.final_score;
  const rounded = verdict.final_score_rounded;
  if (!scoring || finalScore == null || rounded == null) {
    return null;
  }
  const { bull, bear } = scoring;

  return (
    <AltFold title={t('tiered.debate.scoringTitle')}>
      {SIDES.map((side) => (
        <DebaterBlock key={side} side={side} score={scoring[side]} />
      ))}

      <div>
        <AltSectionLabel>{t('tiered.debate.finalScore')}</AltSectionLabel>
        <div className="flex flex-col gap-1 overflow-x-auto text-sm">
          <p className={FORMULA_LINE}>
            (<FVar>{t('tiered.alt.f.bullWeight')}</FVar> ×{' '}
            <FVar>{t('tiered.alt.f.bullScore')}</FVar> +{' '}
            <FVar>{t('tiered.alt.f.bearWeight')}</FVar> ×{' '}
            <FVar>{t('tiered.alt.f.bearScore')}</FVar>) / (
            <FVar>{t('tiered.alt.f.bullWeight')}</FVar> +{' '}
            <FVar>{t('tiered.alt.f.bearWeight')}</FVar>)
          </p>
          <p className={FORMULA_LINE} data-testid="alt-scoring-final-formula">
            = ({weightText(bull)} × {positionScoreOf(bull)} + {weightText(bear)} ×{' '}
            {positionScoreOf(bear)}) / ({weightText(bull)} + {weightText(bear)})
          </p>
          <p className={FORMULA_RESULT}>= {finalScore.toFixed(1)}</p>
        </div>
      </div>

      <div>
        <AltSectionLabel>{t('tiered.alt.verdict')}</AltSectionLabel>
        <div className="flex flex-col gap-1 overflow-x-auto text-sm">
          <p className={FORMULA_LINE}>
            {t('tiered.debate.roundsTo', { raw: finalScore.toFixed(1), rounded })}
          </p>
          <p className={FORMULA_LINE}>{t('tiered.debate.ranges')}</p>
          <p className={FORMULA_RESULT} data-testid="alt-scoring-verdict">
            = {t(`tiered.direction.${verdict.direction}` as UiTextKey)}
          </p>
        </div>
      </div>
    </AltFold>
  );
};
