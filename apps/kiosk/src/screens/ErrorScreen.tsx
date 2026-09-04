import { Button } from '../components/Button';
import { ErrorPanel } from '../components/ErrorPanel';
import { errorMessageKey } from '../i18n/errors';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  code?: string;
  message?: string;
  onRetry: () => void;
  onReset: () => void;
}

export function ErrorScreen({ language, code, message, onRetry, onReset }: Props) {
  const { t } = useT(language);
  return (
    <div className="screen">
      <ErrorPanel
        title={t('error.title')}
        message={
          <>
            <p className="screen__sub">{t('error.subtitle')}</p>
            <p className="screen__sub muted">{t(errorMessageKey(code, message))}</p>
          </>
        }
        retry={<Button onClick={onRetry}>{t('error.retry')}</Button>}
        reset={<Button variant="ghost" onClick={onReset}>{t('error.reset')}</Button>}
      />
    </div>
  );
}
