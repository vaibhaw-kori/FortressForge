import { ExperienceDTO } from '@aura/contracts';
import { Button } from '../components/Button';
import { ExperienceCard } from '../components/ExperienceCard';
import { useExperiences } from '../hooks/useExperiences';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  selectedId: string | null;
  onSelect: (e: ExperienceDTO) => void;
  onBack: () => void;
}

export function ExperienceScreen({ language, selectedId, onSelect, onBack }: Props) {
  const { t } = useT(language);
  const { experiences, loading, error } = useExperiences(language);

  if (error) {
    return (
      <div className="screen">
        <p className="screen__eyebrow">{t('error.title')}</p>
        <h2 className="screen__title">{t('error.network')}</h2>
        <p className="screen__sub muted">{error.message}</p>
      </div>
    );
  }

  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('experience.subtitle')}</p>
      <h1 className="screen__title">{t('experience.title')}</h1>
      {loading ? (
        <p className="screen__sub muted">Loading…</p>
      ) : (
        <div className="grid" style={{ maxWidth: 1280, width: '100%' }}>
          {experiences.map((e) => (
            <ExperienceCard
              key={e.id}
              experience={e}
              active={e.id === selectedId}
              onSelect={onSelect}
              durationKey={'experience.duration'}
              chooseKey={'experience.choose'}
            />
          ))}
        </div>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <Button variant="ghost" onClick={onBack}>{t('experience.back')}</Button>
      </div>
    </div>
  );
}