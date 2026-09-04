import { useCallback, useEffect, useState } from 'react';

export function useFullscreen(targetRef?: React.RefObject<HTMLElement>) {
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const enter = useCallback(async () => {
    const el = targetRef?.current ?? document.documentElement;
    try {
      await el.requestFullscreen();
    } catch {}
  }, [targetRef]);

  const exit = useCallback(async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
    } catch {}
  }, []);

  const toggle = useCallback(async () => {
    if (document.fullscreenElement) await exit();
    else await enter();
  }, [enter, exit]);

  return { isFullscreen, enter, exit, toggle, supported: typeof document !== 'undefined' && !!document.documentElement.requestFullscreen };
}
