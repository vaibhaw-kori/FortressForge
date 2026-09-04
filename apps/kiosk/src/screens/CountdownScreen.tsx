import { Button } from '../components/Button';
import { CaptureFrame } from '../components/CaptureFrame';
import { CountdownDial } from '../components/CountdownDial';
import { RefObject } from 'react';
import { useCamera } from '../hooks/useCamera';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  total: number;
  remaining: number;
  onCancel: () => void;
}

export function CountdownScreen({ language, total, remaining, onCancel }: Props) {
  const { t } = useT(language);
  const { videoRef, ready, errorMessage } = useCamera();
  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('countdown.hold')}</p>
      <CaptureFrame videoRef={videoRef as RefObject<HTMLVideoElement>} ready={ready} errorMessage={errorMessage} aspect="portrait" />
      <CountdownDial total={total} remaining={remaining} />
      <Button variant="ghost" onClick={onCancel}>{t('countdown.cancel')}</Button>
    </div>
  );
}