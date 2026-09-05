import { Button } from '../components/Button';
import { CaptureFrame } from '../components/CaptureFrame';
import { CountdownDial } from '../components/CountdownDial';
import type { Ref } from 'react';
import { useT } from '../i18n/useT';

interface Props {
  language: string;
  total: number;
  remaining: number;
  onCancel: () => void;
  videoRef: Ref<HTMLVideoElement>;
  ready: boolean;
  errorMessage: string | null;
}

export function CountdownScreen({ language, total, remaining, onCancel, videoRef, ready, errorMessage }: Props) {
  const { t } = useT(language);
  return (
    <div className="screen">
      <p className="screen__eyebrow">{t('countdown.hold')}</p>
      <CaptureFrame videoRef={videoRef} ready={ready} errorMessage={errorMessage} aspect="portrait" />
      <CountdownDial total={total} remaining={remaining} />
      <Button variant="ghost" onClick={onCancel}>{t('countdown.cancel')}</Button>
    </div>
  );
}