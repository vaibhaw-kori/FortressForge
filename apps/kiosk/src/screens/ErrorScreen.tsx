import { Button } from '../components/Button';
import { ErrorPanel } from '../components/ErrorPanel';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  code?: string;
  message: string;
  onRetry: () => void;
  onReset: () => void;
}

export function ErrorScreen({ language, code, message, onRetry, onReset }: Props) {
  const { t } = useT(language);
  return (
    <div className="screen">
      <ErrorPanel
        code={code}
        message={message}
        retry={<Button onClick={onRetry}>{t('error.retry')}</Button>}
        reset={<Button variant="ghost" onClick={onReset}>{t('error.reset')}</Button>}
      />
    </div>
  );
}