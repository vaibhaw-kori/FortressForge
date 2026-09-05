import { useEffect, useRef, useState, useCallback } from 'react';
import type { ReelItem } from '@aura/reel';

interface Props {
  current: ReelItem | null;
  preloadSrc: string | null;
  onEnded: () => void;
  onError: (id: string) => void;
  muted?: boolean;
}

/**
 * Double-buffered video stage with crossfade.
 * Two <video> elements are stacked; the active one is visible while the next
 * preloads in the background. On switch, we crossfade via CSS opacity.
 *
 * Error handling: if a video fails to load/play, onError is called and the
 * manager skips to the next item.
 */
export function VideoStage({ current, preloadSrc, onEnded, onError, muted = true }: Props) {
  const aRef = useRef<HTMLVideoElement>(null);
  const bRef = useRef<HTMLVideoElement>(null);
  const [active, setActive] = useState<'a' | 'b'>('a');
  const [aSrc, setASrc] = useState<string | null>(null);
  const [bSrc, setBSrc] = useState<string | null>(null);
  const currentIdRef = useRef<string | null>(null);

  // Keep currentIdRef in sync
  useEffect(() => {
    currentIdRef.current = current?.id ?? null;
  }, [current]);

  // When current changes, load it into the inactive element, then swap.
  useEffect(() => {
    if (!current) return;
    const target = active === 'a' ? bRef : aRef;
    const setTargetSrc = active === 'a' ? setBSrc : setASrc;

    // If the active element already shows this src, nothing to do.
    // (Without this guard the two buffers ping-pong forever once both
    // hold the same src.)
    const activeSrc = active === 'a' ? aSrc : bSrc;
    if (activeSrc === current.src) return;

    // If same src already preloaded in the inactive element, just flip.
    const existingSrc = active === 'a' ? bSrc : aSrc;
    if (existingSrc === current.src) {
      // Already preloaded - just flip
      setActive((prev) => (prev === 'a' ? 'b' : 'a'));
      return;
    }

    setTargetSrc(current.src);
    const el = target.current;
    if (!el) return;

    const onCanPlay = () => {
      // Start playback then crossfade
      el.play().catch(() => {
        // Autoplay may be blocked if not muted; try muted
        el.muted = true;
        el.play().catch(() => onError(current.id));
      });
      // slight delay to ensure frame is ready, then swap
      requestAnimationFrame(() => setActive((prev) => (prev === 'a' ? 'b' : 'a')));
    };

    const onErr = () => {
      onError(current.id);
    };

    el.addEventListener('canplay', onCanPlay, { once: true });
    el.addEventListener('error', onErr, { once: true });
    try {
      el.load();
    } catch {}

    return () => {
      el.removeEventListener('canplay', onCanPlay);
      el.removeEventListener('error', onErr);
    };
  }, [current, active, aSrc, bSrc, onError]);

  // Preload next video in hidden element without displaying
  useEffect(() => {
    if (!preloadSrc) return;
    // Create a hidden preload <video> or use the inactive element's preload
    const link = document.createElement('link');
    link.rel = 'preload';
    link.as = 'video';
    link.href = preloadSrc;
    document.head.appendChild(link);
    return () => {
      try { document.head.removeChild(link); } catch {}
    };
  }, [preloadSrc]);

  const handleEnded = useCallback(() => {
    onEnded();
  }, [onEnded]);

  const handleError = useCallback(
    (which: 'a' | 'b') => {
      const id = currentIdRef.current;
      if (!id) return;
      // Only handle error for the active video
      const isActive = (which === active);
      if (!isActive) return;
      onError(id);
    },
    [active, onError],
  );

  if (!current) {
    return (
      <div className="video-stage video-stage--empty" aria-label="Preparing presentation">
        <div className="video-stage__ambient" aria-hidden>
          <div className="video-stage__mark">A</div>
        </div>
      </div>
    );
  }

  return (
    <div className="video-stage">
      <video
        ref={aRef}
        src={aSrc ?? undefined}
        muted={muted}
        autoPlay
        playsInline
        preload="auto"
        className={`video-stage__video ${active === 'a' ? 'video-stage__video--active' : ''}`}
        onEnded={active === 'a' ? handleEnded : undefined}
        onError={() => handleError('a')}
      />
      <video
        ref={bRef}
        src={bSrc ?? undefined}
        muted={muted}
        autoPlay
        playsInline
        preload="auto"
        className={`video-stage__video ${active === 'b' ? 'video-stage__video--active' : ''}`}
        onEnded={active === 'b' ? handleEnded : undefined}
        onError={() => handleError('b')}
      />
      {/* Subtle vignette */}
      <div className="video-stage__vignette" aria-hidden />
    </div>
  );
}
