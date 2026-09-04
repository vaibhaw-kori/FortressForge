import { LinearProgress } from '../components/LinearProgress';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  progress: number;
}

export function UploadingScreen({ language, progress }: Props) {
  const { t } = useT(language);
  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('uploading.title')}</p>
      <h2 className="screen__title">{t('uploading.subtitle')}</h2>
      <LinearProgress progress={progress} />
    </div>
  );
}