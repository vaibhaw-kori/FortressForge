import { Button } from '../components/Button';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  dataUrl: string | null;
  onRetake: () => void;
  onContinue: () => void;
}

export function CapturedScreen({ language, dataUrl, onRetake, onContinue }: Props) {
  const { t } = useT(language);
  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('captured.review')}</p>
      <h2 className="screen__title" style={{ fontSize: 'clamp(28px, 4vw, 44px)' }}>
        {t('captured.title')}
      </h2>
      <div className="capture-frame" aria-label="captured preview">
        {dataUrl ? <img className="capture-frame__still" src={dataUrl} alt="captured" /> : null}
        <div className="capture-frame__overlay" />
        <div className="capture-frame__corners">
          <span />
          <span />
        </div>
      </div>
      <div className="row" style={{ gap: 18 }}>
        <Button variant="ghost" onClick={onRetake}>{t('captured.retake')}</Button>
        <Button size="lg" onClick={onContinue}>{t('captured.continue')}</Button>
      </div>
    </div>
  );
}