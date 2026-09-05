import { useCallback, useEffect, useRef, useState } from 'react';
import { ReelItem, ReelPolicyConfig } from '@aura/reel';
import { VideoStage } from './components/VideoStage';
import { StageOverlay } from './components/StageOverlay';
import { useReelManager } from './hooks/useReelManager';
import { useDisplay2Socket } from './hooks/useDisplay2Socket';
import { useFullscreen } from './hooks/useFullscreen';
import { fetchPlaylist } from './services/api';
import './styles/globals.css';

const STAGE_ID = 'stage-1';
// Demo: play each new visitor video immediately after the current one
// finishes its frame (interrupt + advance), so the client sees it in seconds.
const DEFAULT_POLICY: ReelPolicyConfig = {
  defaultInsert: 'immediate',
  maxGeneratedInQueue: 20,
};

/** Local installation films. No remote URLs: the wall must play offline. */
const FALLBACK_CURATED: ReelItem[] = [
  { id: 'curated-a', kind: 'curated', src: '/videos/curated-a.mp4', duration_sec: 10, title: 'AURA Reel' },
  { id: 'curated-b', kind: 'curated', src: '/videos/curated-b.mp4', duration_sec: 10, title: 'AURA Reel' },
  { id: 'curated-c', kind: 'curated', src: '/videos/curated-c.mp4', duration_sec: 10, title: 'AURA Reel' },
];

/** Chrome auto-hide delay while a film plays (operator affordance). */
const OVERLAY_IDLE_MS = 3000;

export default function App() {
  const [policy] = useState<ReelPolicyConfig>(DEFAULT_POLICY);
  const [initialPlaylist, setInitialPlaylist] = useState<ReelItem[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { toggle } = useFullscreen(containerRef);

  useEffect(() => {
    let cancelled = false;
    fetchPlaylist()
      .then((items) => {
        if (cancelled) return;
        setInitialPlaylist(items.length > 0 ? items : FALLBACK_CURATED);
      })
      .catch(() => {
        if (!cancelled) setInitialPlaylist(FALLBACK_CURATED);
      });
    return () => { cancelled = true; };
  }, []);

  if (initialPlaylist === null) {
    return (
      <div className="stage-root stage-root--loading" aria-label="Preparing presentation">
        <div className="stage-loader" aria-hidden>
          <div className="stage-loader__mark">A</div>
        </div>
      </div>
    );
  }

  return (
    <StageReady
      initialPlaylist={initialPlaylist}
      policy={policy}
      containerRef={containerRef}
      onToggleFullscreen={toggle}
    />
  );
}

function StageReady({
  initialPlaylist,
  policy,
  containerRef,
  onToggleFullscreen,
}: {
  initialPlaylist: ReelItem[];
  policy: ReelPolicyConfig;
  containerRef: React.RefObject<HTMLDivElement>;
  onToggleFullscreen: () => void;
}) {
  const { current, playlist, preloadSrc, enqueue, advance, jumpTo, handleError, setPolicy, setPlaylist } =
    useReelManager({
      policy,
      initialPlaylist,
    });

  useEffect(() => {
    setPolicy(policy);
  }, [policy, setPolicy]);

  const handleWsEvent = useCallback(
    (ev: any) => {
      switch (ev.type) {
        case 'NEW_VIDEO_AVAILABLE': {
          const item: ReelItem = {
            id: ev.video_id ?? ev.job_id ?? `gen-${Date.now()}`,
            kind: 'generated',
            src: ev.src,
            duration_sec: ev.duration_sec ?? 4,
            title: ev.theme_id ? `Generated — ${ev.theme_id}` : 'Generated',
            theme_id: ev.theme_id,
          };
          const res = enqueue(item);
          if (res.shouldInterrupt && res.accepted) {
            // Defer to next tick to avoid interrupting the current frame
            setTimeout(() => advance(), 80);
          }
          break;
        }
        case 'REEL_UPDATED': {
          if (Array.isArray(ev.items) && ev.items.length > 0) {
            const items: ReelItem[] = ev.items.map((d: any) => ({
              id: d.id,
              kind: d.kind ?? 'curated',
              src: d.src,
              duration_sec: d.duration_sec ?? 4,
              title: d.title ?? null,
            }));
            setPlaylist(items);
          }
          break;
        }
        case 'PLAY_NEXT': {
          advance();
          break;
        }
        case 'PLAY_VIDEO': {
          if (ev.video_id) {
            const found = playlist.find((p) => p.id === ev.video_id);
            if (found) jumpTo(ev.video_id);
            else {
              // If not in playlist, treat as new generated item and play immediately
              const item: ReelItem = {
                id: ev.video_id,
                kind: 'generated',
                src: ev.src ?? ev.video_id,
                duration_sec: 4,
              };
              enqueue(item, 'immediate');
              setTimeout(() => advance(), 80);
            }
          }
          break;
        }
        case 'REFRESH_PLAYLIST': {
          fetchPlaylist().then((items) => {
            if (items.length > 0) setPlaylist(items);
          });
          break;
        }
        default:
          break;
      }
    },
    [enqueue, advance, jumpTo, setPlaylist, playlist],
  );

  const wsStatus = useDisplay2Socket(STAGE_ID, handleWsEvent);
  void wsStatus;

  const onEnded = useCallback(() => {
    advance();
  }, [advance]);

  const onError = useCallback(
    (id: string) => {
      handleError(id);
    },
    [handleError],
  );

  // Presentation chrome: reveal briefly on film change or pointer
  // activity, then fade so films play edge-to-edge.
  const [chromeHidden, setChromeHidden] = useState(false);
  const hideTimer = useRef<number | null>(null);
  const pokeChrome = useCallback(() => {
    setChromeHidden(false);
    if (hideTimer.current) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => setChromeHidden(true), OVERLAY_IDLE_MS);
  }, []);
  useEffect(() => {
    pokeChrome();
  }, [current?.id, pokeChrome]);
  useEffect(
    () => () => {
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
    },
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        e.preventDefault();
        advance();
      } else if (e.code === 'KeyF') {
        onToggleFullscreen();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [advance, onToggleFullscreen]);

  return (
    <div ref={containerRef} className="stage-root" onMouseMove={pokeChrome} onDoubleClick={() => onToggleFullscreen()}>
      <VideoStage current={current} preloadSrc={preloadSrc} onEnded={onEnded} onError={onError} />
      <StageOverlay current={current} playlist={playlist} hidden={chromeHidden} />
    </div>
  );
}
