import { Button } from '../components/Button';
import { SUPPORTED_LANGUAGES } from '../i18n/catalog';
import { useT } from '../i18n/useT';

interface Props {
  onSelect: (code: string) => void;
}

export function LanguageScreen({ onSelect }: Props) {
  const { t } = useT('en');
  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('language.subtitle')}</p>
      <h1 className="screen__title">{t('language.title')}</h1>
      <div className="row" style={{ gap: 24 }}>
        {SUPPORTED_LANGUAGES.map((opt) => (
          <Button
            key={opt.code}
            size="lg"
            onClick={() => onSelect(opt.code)}
            aria-label={`language-${opt.code}`}
          >
            {t(opt.labelKey)}
          </Button>
        ))}
      </div>
    </div>
  );
}