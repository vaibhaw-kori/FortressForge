import { Button } from '../components/Button';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  onNewVisitor: () => void;
}

export function CompletedScreen({ language, onNewVisitor }: Props) {
  const { t } = useT(language);
  return (
    <div className="screen">
      <div className="completed-check" aria-hidden>✓</div>
      <h1 className="screen__title">{t('completed.title')}</h1>
      <p className="screen__sub">{t('completed.subtitle')}</p>
      <p className="muted">{t('completed.outputSoon')}</p>
      <Button onClick={onNewVisitor}>{t('completed.newSession')}</Button>
    </div>
  );
}