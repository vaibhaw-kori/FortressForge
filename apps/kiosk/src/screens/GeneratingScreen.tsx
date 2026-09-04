import { ProgressOrb } from '../components/ProgressOrb';
import { useT } from '../i18n/useT';
import type { JobState } from '@aura/contracts';

interface Props {
  language: string;
  progress: number;
  state: JobState | null;
}

function phaseKey(state: JobState | null): 'preparing' | 'queued' | 'processing' | 'animating' | 'encoding' | 'completed' {
  switch (state) {
    case 'CREATED':
    case 'QUEUED':
      return 'queued';
    case 'PROCESSING':
      return 'processing';
    case 'GENERATING':
      return 'animating';
    case 'POST_PROCESSING':
      return 'preparing';
    case 'ENCODING':
      return 'encoding';
    case 'COMPLETED':
    case 'FAILED':
    case 'CANCELLED':
    case 'TIMEOUT':
      return 'completed';
    default:
      return 'preparing';
  }
}

export function GeneratingScreen({ language, progress, state }: Props) {
  const { t } = useT(language);
  const phase = phaseKey(state);
  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('generating.title')}</p>
      <h2 className="screen__title">{t('generating.subtitle')}</h2>
      <ProgressOrb progress={progress} />
      <p className="screen__sub">{t(`generating.${phase}` as const)}</p>
    </div>
  );
}