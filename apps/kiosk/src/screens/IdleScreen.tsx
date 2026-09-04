import { useT } from '../i18n/useT';

interface Props {
  onBegin: () => void;
}

export function IdleScreen({ onBegin }: Props) {
  const { t } = useT('en');
  return (
    <div className="screen" role="button" tabIndex={0} onClick={onBegin} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onBegin()}>
      <p className="screen__eyebrow">{t('idle.invite')}</p>
      <h1 className="screen__title">{t('brand.tagline')}</h1>
      <p className="idle-hint">{t('idle.touch')}</p>
    </div>
  );
}