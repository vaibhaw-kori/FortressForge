/**
 * Camera hook. Acquires a MediaStream once, exposes a video ref, and
 * provides a `capture` callback that grabs a still JPEG frame.
 */
import { RefObject, useCallback, useEffect, useRef, useState } from 'react';

export interface UseCameraResult {
  videoRef: RefObject<HTMLVideoElement>;
  ready: boolean;
  errorMessage: string | null;
  capture: () => Promise<{ blob: Blob; dataUrl: string } | null>;
}

export function useCamera(): UseCameraResult {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
        setErrorMessage('Camera API not available');
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: 'user' },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
        setReady(true);
      } catch (err: unknown) {
        const e = err as Error;
        setErrorMessage(e.message || 'Camera access denied');
      }
    }
    void start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setReady(false);
    };
  }, []);

  const capture = useCallback(async () => {
    const video = videoRef.current;
    if (!video || !ready) return null;
    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 720;
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    // Mirror so the preview matches the on-screen mirrored preview.
    ctx.save();
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(video, 0, 0, w, h);
    ctx.restore();
    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.92),
    );
    if (!blob) return null;
    const dataUrl: string = canvas.toDataURL('image/jpeg', 0.92);
    return { blob, dataUrl };
  }, [ready]);

  return { videoRef, ready, errorMessage, capture };
}