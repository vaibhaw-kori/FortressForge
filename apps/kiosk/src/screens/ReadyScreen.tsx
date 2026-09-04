import { ExperienceDTO } from '@aura/contracts';
import { Button } from '../components/Button';
import { CaptureFrame } from '../components/CaptureFrame';
import { RefObject } from 'react';
import { useCamera } from '../hooks/useCamera';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  experience: ExperienceDTO;
  onCapture: () => void;
  onChangeExperience: () => void;
}

export function ReadyScreen({ language, experience, onCapture, onChangeExperience }: Props) {
  const { t } = useT(language);
  const { videoRef, ready, errorMessage } = useCamera();
  const hint = ready ? t('ready.preview') : t('ready.noCamera');

  return (
    <div className="screen">
      <p className="screen__eyebrow">{experience.display_name}</p>
      <h1 className="screen__title">{t('ready.title')}</h1>
      <p className="screen__sub">{t('ready.subtitle')}</p>
      <CaptureFrame videoRef={videoRef as RefObject<HTMLVideoElement>} ready={ready} errorMessage={errorMessage} hintText={hint} aspect="portrait" />
      <div className="row" style={{ gap: 18 }}>
        <Button variant="ghost" onClick={onChangeExperience}>{t('ready.changeTheme')}</Button>
        <Button size="lg" onClick={onCapture} disabled={!ready}>{t('ready.capture')}</Button>
      </div>
    </div>
  );
}