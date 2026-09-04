/**
 * Fullscreen helpers. Browsers require a user gesture, so this hook
 * exposes `request()` that the caller must invoke from an onClick handler.
 */
import { useCallback, useEffect, useState } from 'react';

interface FSResult {
  isFullscreen: boolean;
  supported: boolean;
  request: () => Promise<void>;
  exit: () => Promise<void>;
}

export function useFullscreen(): FSResult {
  const supported = typeof document !== 'undefined' && !!document.fullscreenEnabled;
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    if (!supported) return;
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, [supported]);

  const request = useCallback(async () => {
    if (!supported) return;
    try {
      await document.documentElement.requestFullscreen();
    } catch {
      // user gesture missing — ignore
    }
  }, [supported]);

  const exit = useCallback(async () => {
    if (!supported) return;
    try {
      await document.exitFullscreen();
    } catch {
      // ignore
    }
  }, [supported]);

  return { isFullscreen, supported, request, exit };
}