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
const DEFAULT_POLICY: ReelPolicyConfig = {
  defaultInsert: 'queued',
  maxGeneratedInQueue: 20,
};

const FALLBACK_CURATED: ReelItem[] = [
  {
    id: 'curated-bbb',
    kind: 'curated',
    src: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
    duration_sec: 10,
    title: 'Big Buck Bunny',
  },
  {
    id: 'curated-sintel',
    kind: 'curated',
    src: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4',
    duration_sec: 10,
    title: 'Sintel',
  },
  {
    id: 'curated-bbb-w3',
    kind: 'curated',
    src: 'https://www.w3schools.com/html/mov_bbb.mp4',
    duration_sec: 10,
    title: 'W3Schools BBB',
  },
];

export default function App() {
  const [policy, setPolicy] = useState<ReelPolicyConfig>(DEFAULT_POLICY);
  const [initialPlaylist, setInitialPlaylist] = useState<ReelItem[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { isFullscreen, toggle } = useFullscreen(containerRef);

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
      <div className="stage-root stage-root--loading">
        <div className="stage-loader">Loading reel…</div>
      </div>
    );
  }

  return (
    <StageReady
      initialPlaylist={initialPlaylist}
      policy={policy}
      onPolicyChange={setPolicy}
      containerRef={containerRef}
      isFullscreen={isFullscreen}
      onToggleFullscreen={toggle}
    />
  );
}

function StageReady({
  initialPlaylist,
  policy,
  onPolicyChange,
  containerRef,
  isFullscreen,
  onToggleFullscreen,
}: {
  initialPlaylist: ReelItem[];
  policy: ReelPolicyConfig;
  onPolicyChange: (p: ReelPolicyConfig) => void;
  containerRef: React.RefObject<HTMLDivElement>;
  isFullscreen: boolean;
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

  const onEnded = useCallback(() => {
    advance();
  }, [advance]);

  const onError = useCallback(
    (id: string) => {
      handleError(id);
    },
    [handleError],
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
    <div ref={containerRef} className="stage-root">
      <VideoStage current={current} preloadSrc={preloadSrc} onEnded={onEnded} onError={onError} />
      <StageOverlay
        current={current}
        playlist={playlist}
        policy={policy}
        onPolicyChange={onPolicyChange}
        wsStatus={wsStatus}
        isFullscreen={isFullscreen}
        onToggleFullscreen={onToggleFullscreen}
      />
    </div>
  );
}
