import { ExperienceDTO } from '@aura/contracts';
import { Button } from '../components/Button';
import { CaptureFrame } from '../components/CaptureFrame';
import { RefObject } from 'react';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  experience: ExperienceDTO;
  onCapture: () => void;
  onChangeExperience: () => void;
  videoRef: RefObject<HTMLVideoElement>;
  ready: boolean;
  errorMessage: string | null;
}

export function ReadyScreen({ language, experience, onCapture, onChangeExperience, videoRef, ready, errorMessage }: Props) {
  const { t } = useT(language);
  const hint = ready ? t('ready.preview') : errorMessage ?? t('ready.noCamera');
  const showDemoBypass = !ready;

  return (
    <div className="screen">
      <p className="screen__eyebrow">{experience.display_name}</p>
      <h1 className="screen__title">{t('ready.title')}</h1>
      <p className="screen__sub">{t('ready.subtitle')}</p>
      <CaptureFrame videoRef={videoRef} ready={ready} errorMessage={errorMessage} hintText={hint} aspect="portrait" />
      <div className="row" style={{ gap: 18 }}>
        <Button variant="ghost" onClick={onChangeExperience}>{t('ready.changeTheme')}</Button>
        <Button size="lg" onClick={onCapture}>{t('ready.capture')}</Button>
      </div>
      {showDemoBypass && (
        <>
          <p className="screen__sub muted" style={{ fontSize: 12, marginTop: 4 }}>
            Camera blocked — tap <strong>Demo capture</strong> to record without camera.
          </p>
          <Button variant="ghost" onClick={onCapture} style={{ marginTop: 4, fontSize: 13, padding: '10px 18px' }}>Demo capture</Button>
        </>
      )}
    </div>
  );
}