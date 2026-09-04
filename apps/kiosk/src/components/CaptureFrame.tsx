import { RefObject } from 'react';

interface Props {
  videoRef: RefObject<HTMLVideoElement>;
  ready: boolean;
  errorMessage: string | null;
  hintText?: string;
  aspect?: 'portrait' | 'landscape';
}

export function CaptureFrame({ videoRef, ready, errorMessage, hintText, aspect = 'portrait' }: Props) {
  const cls = `capture-frame ${aspect === 'landscape' ? 'capture-frame--landscape' : ''}`;
  if (!ready) {
    return (
      <div className={`${cls} capture-frame--no-camera`}>
        <span>{errorMessage ?? 'Camera warming up…'}</span>
      </div>
    );
  }
  return (
    <div className={cls}>
      <video ref={videoRef} className="capture-frame__video" autoPlay playsInline muted />
      <div className="capture-frame__overlay" />
      <div className="capture-frame__corners">
        <span />
        <span />
      </div>
      {hintText ? <div className="capture-frame__hint">{hintText}</div> : null}
    </div>
  );
}